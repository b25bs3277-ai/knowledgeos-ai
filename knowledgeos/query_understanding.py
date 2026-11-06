"""Question classification, conversation-aware rewriting and multi-query expansion.

Rewriting never invents context: with no history the question is used unchanged;
with history but no LLM, the heuristic only appends terms that literally appeared
in earlier user turns, and the UI shows the rewritten query.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Optional

from .exceptions import KnowledgeOSError
from .keyword_search import STOPWORDS, tokenize
from .llm_providers import LLMProvider
from .logging_config import get_logger, log_event
from .schemas import ChatTurn, QuestionType

log = get_logger("query")

_GREETING = re.compile(r"^\s*(hi|hello|hey|hiya|good (morning|afternoon|evening)|namaste|thanks?|thank you|"
                       r"thx|ok(ay)?|cool|great|bye|goodbye|see you)\b[\s!.,?]*(there|claude|bot)?[\s!.?]*$", re.I)
_META = re.compile(r"\b(what can you do|how (do|can) i (upload|use|add|delete|export)|who are you|"
                   r"what are you|help me get started|how does this (app|tool) work)\b", re.I)
_FOLLOWUP = re.compile(r"\b(it|its|they|them|their|this|that|these|those|he|she|the other( one)?|"
                       r"the former|the latter|same|above|previous|earlier)\b", re.I)
_FOLLOWUP_START = re.compile(r"^\s*(and|also|what about|how about|why|compare|so)\b", re.I)
_GENERAL = re.compile(r"\b(in general|generally speaking|without (the|my) documents|general knowledge)\b", re.I)
# Words that only point back at earlier context; they carry no topic on their own.
_REFERENCE_WORDS = frozenset({"other", "one", "ones", "same", "former", "latter", "different", "difference",
                              "previous", "earlier", "above", "mentioned", "thing", "compare", "similar"})


@dataclass
class QueryPlan:
    original: str
    question_type: QuestionType
    standalone: str
    rewrite_method: str = "none"          # none | heuristic | llm
    extra_queries: list[str] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)


def classify(question: str, has_documents: bool, has_history: bool) -> QuestionType:
    q = (question or "").strip()
    if not q:
        return QuestionType.AMBIGUOUS
    if _GREETING.match(q):
        return QuestionType.GREETING
    if _META.search(q):
        return QuestionType.META
    if _GENERAL.search(q):
        return QuestionType.GENERAL
    content_terms = [t for t in tokenize(q) if t not in STOPWORDS]
    if not content_terms and not has_history:
        return QuestionType.AMBIGUOUS
    topic_terms = [t for t in content_terms if t not in _REFERENCE_WORDS]
    if is_followup(q) and not has_history and len(topic_terms) <= 1:
        return QuestionType.AMBIGUOUS
    return QuestionType.DOCUMENT if has_documents else QuestionType.GENERAL


def is_followup(question: str) -> bool:
    return bool(_FOLLOWUP.search(question) or _FOLLOWUP_START.match(question))


def _recent_user_turns(history: list[ChatTurn], n: int = 2) -> list[str]:
    return [t.content for t in history if t.role == "user"][-n:]


def heuristic_rewrite(question: str, history: list[ChatTurn]) -> str:
    """Append content terms from the previous user question(s) that the follow-up lacks."""
    prev = _recent_user_turns(history)
    if not prev:
        return question
    have = set(tokenize(question))
    extra: list[str] = []
    for text in reversed(prev):
        for tok in re.findall(r"[A-Za-z0-9][A-Za-z0-9\-]+", text):
            low = tok.lower()
            if low not in STOPWORDS and tokenize(low) and tokenize(low)[0] not in have and low not in extra:
                extra.append(low)
    return f"{question} ({' '.join(extra[:12])})" if extra else question


_REWRITE_PROMPT = """Rewrite the user's latest question as ONE standalone search query, resolving pronouns
and references using ONLY the conversation below. Do not add facts, answers or assumptions that are not in
the conversation. If the question is already standalone, return it unchanged.
Output only the query text, no quotes, no explanation.

Conversation:
{history}

Latest question: {question}
Standalone query:"""

_MULTI_PROMPT = """Write {n} different short search queries that would help find passages answering the
question below. Use different wording and synonyms. Do not answer the question.
Output one query per line, no numbering.

Question: {question}"""


def llm_rewrite(question: str, history: list[ChatTurn], provider: LLMProvider, timeout: int) -> Optional[str]:
    lines = [f"{t.role.upper()}: {t.content[:600]}" for t in history[-6:]]
    msg = [{"role": "user", "content": _REWRITE_PROMPT.format(history="\n".join(lines), question=question)}]
    out = provider.generate(msg, temperature=0.0, max_tokens=80, timeout=min(timeout, 30)).strip()
    out = out.splitlines()[0].strip().strip('"').strip() if out else ""
    if not out or len(out) > 400 or out.upper().startswith(("I ", "SORRY", "AS AN")):
        return None
    return out


def plan_query(question: str, history: list[ChatTurn], has_documents: bool,
               provider: Optional[LLMProvider] = None, multi_query: bool = False,
               timeout: int = 30, n_extra: int = 2) -> QueryPlan:
    question = (question or "").strip()
    qtype = classify(question, has_documents, bool(history))
    plan = QueryPlan(original=question, question_type=qtype, standalone=question)
    if qtype != QuestionType.DOCUMENT:
        return plan
    usable = provider is not None and provider.available()[0]
    if history and is_followup(question):
        rewritten = None
        if usable:
            try:
                rewritten = llm_rewrite(question, history, provider, timeout)
                if rewritten:
                    plan.rewrite_method = "llm"
            except KnowledgeOSError as e:
                plan.notes.append(f"LLM rewrite failed ({e.user_message}); used keyword rewrite.")
        if not rewritten:
            rewritten = heuristic_rewrite(question, history)
            plan.rewrite_method = "heuristic" if rewritten != question else "none"
        plan.standalone = rewritten
    if multi_query:
        extras: list[str] = []
        if usable:
            try:
                msg = [{"role": "user", "content": _MULTI_PROMPT.format(n=n_extra, question=plan.standalone)}]
                raw = provider.generate(msg, temperature=0.3, max_tokens=120, timeout=min(timeout, 30))
                extras = [re.sub(r"^[\-\d.)\s]+", "", l).strip() for l in raw.splitlines()]
                extras = [e for e in extras if 3 < len(e) < 300][:n_extra]
            except KnowledgeOSError as e:
                plan.notes.append(f"Multi-query generation failed ({e.user_message}).")
        if not extras:  # deterministic fallback: keyword-only variant
            kw = " ".join(t for t in tokenize(plan.standalone))
            if kw and kw != plan.standalone.lower():
                extras = [kw]
        plan.extra_queries = extras
    log_event(log, "query planned", qtype=qtype.value, rewrite=plan.rewrite_method,
              extra_queries=len(plan.extra_queries))
    return plan


CANNED = {
    QuestionType.GREETING: ("Hello! I answer questions using the documents you upload, with citations to "
                            "the exact passages. Upload files in the Document Library, then ask away."),
    QuestionType.META: ("Here's the workflow: 1) Upload documents in **Document Library**, 2) wait until they "
                        "show **ready**, 3) ask questions here — every answer cites its sources, which you can "
                        "inspect in the **Evidence** panel, 4) use **Research Workspace** for summaries, "
                        "comparisons, notes, flashcards and quizzes, 5) export results from any page."),
    QuestionType.AMBIGUOUS: ("Could you say a bit more? For example, name the topic or document you mean — "
                             "I don't have earlier context to resolve that reference."),
}

