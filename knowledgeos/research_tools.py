"""Research workspace: summaries, comparison, study tools, reports and evidence tools.

Two tools are fully deterministic and work without any LLM:
  * key_terms         — TF-IDF over the document vs. the whole library
  * extract_evidence  — retrieval + best-matching sentences
All others need a generation provider. Without one they show the passages they
would have used and say so; they never fabricate output.
"""
from __future__ import annotations

import json
import math
import re
from collections import Counter
from dataclasses import dataclass, field
from typing import Any, Callable, Optional

from .answer_generation import SYSTEM_PROMPT, build_context
from .citations import format_sources_markdown, lexical_support, validate_citations
from .config import Settings
from .exceptions import KnowledgeOSError, NotFoundError, safe_user_message
from .hybrid_retrieval import Retriever
from .keyword_search import tokenize
from .llm_providers import LLMProvider
from .logging_config import get_logger, log_event
from .schemas import Citation, RetrievalFilters, RetrievedChunk
from .storage import MetadataStore
from .text_processing import split_sentences

log = get_logger("research")

LENGTHS = {"short": 120, "medium": 300, "long": 700}  # target words

TASKS: dict[str, dict[str, Any]] = {
    "summarize_document": {"label": "Summarize a document", "needs_llm": True},
    "summarize_section": {"label": "Summarize a section / topic within a document", "needs_llm": True},
    "compare_documents": {"label": "Compare documents on a topic", "needs_llm": True},
    "explain_concept": {"label": "Explain a concept from the documents", "needs_llm": True},
    "study_notes": {"label": "Generate study notes", "needs_llm": True},
    "flashcards": {"label": "Generate flashcards", "needs_llm": True},
    "quiz": {"label": "Generate a multiple-choice quiz", "needs_llm": True},
    "report": {"label": "Structured research report", "needs_llm": True},
    "pros_cons": {"label": "Pros and cons (from sources only)", "needs_llm": True},
    "key_terms": {"label": "Key-term extraction (statistical, no LLM)", "needs_llm": False},
    "extract_evidence": {"label": "Evidence extraction (retrieval only, no LLM)", "needs_llm": False},
}

RESEARCH_SYSTEM = SYSTEM_PROMPT + """

You are now producing a research output (not a chat reply). Follow the task format exactly.
Every factual statement must carry an evidence citation like [1]. If the evidence is too thin
for the task, say which parts could not be supported instead of filling gaps."""


@dataclass
class ResearchResult:
    task: str
    title: str
    markdown: str
    citations: list[Citation] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    structured: Any = None
    sources: list[RetrievedChunk] = field(default_factory=list)
    used_llm: bool = False


def parse_json_array(text: str) -> list[dict]:
    """Extract the first JSON array of objects from model output (tolerates code fences)."""
    start, end = text.find("["), text.rfind("]")
    if start < 0 or end <= start:
        raise ValueError("no JSON array found")
    data = json.loads(text[start:end + 1])
    if not isinstance(data, list) or not all(isinstance(x, dict) for x in data):
        raise ValueError("JSON is not a list of objects")
    return data


class ResearchTools:
    def __init__(self, settings: Settings, store: MetadataStore, retriever_fn: Callable[[], Retriever],
                 provider_fn: Callable[[], LLMProvider]) -> None:
        self.settings = settings
        self.store = store
        self._retriever_fn = retriever_fn
        self._provider_fn = provider_fn

    # ---------------- evidence selection ----------------
    def _doc_passages(self, doc_id: str, topic: Optional[str] = None, max_chunks: int = 12) -> list[RetrievedChunk]:
        chunks = self.store.get_doc_chunks(doc_id)
        if not chunks:
            raise NotFoundError(f"No chunks for {doc_id}", user_message="That document has no indexed content.")
        if topic:
            out = self._retriever_fn().retrieve(topic, "hybrid", max_chunks, RetrievalFilters(doc_ids=[doc_id]))
            if out.results:
                return out.results
        if len(chunks) > max_chunks:  # evenly spaced sample keeps beginning, middle and end
            step = (len(chunks) - 1) / (max_chunks - 1)
            chunks = [chunks[round(i * step)] for i in range(max_chunks)]
        return [RetrievedChunk(chunk=c, score=0.0, rank=i + 1, method="document_order")
                for i, c in enumerate(chunks)]

    def _topic_passages(self, topic: str, doc_ids: Optional[list[str]], k: int = 10) -> list[RetrievedChunk]:
        filters = RetrievalFilters(doc_ids=doc_ids) if doc_ids else None
        return self._retriever_fn().retrieve(topic, None, k, filters).results

    # ---------------- LLM execution ----------------
    def _fallback(self, task: str, title: str, passages: list[RetrievedChunk], reason: str) -> ResearchResult:
        lines = [f"### {title}", "", f"**Generation unavailable:** {reason}", "",
                 "These are the passages this task would use:", ""]
        for i, rc in enumerate(passages[:8], start=1):
            t = rc.chunk.text[:400].replace("\n", " ")
            lines.append(f"**[{i}] {rc.chunk.filename} — {rc.chunk.location_label()}**\n> {t}…\n")
        return ResearchResult(task, title, "\n".join(lines), warnings=[reason], sources=passages)

    def _run_llm(self, task: str, title: str, instructions: str, passages: list[RetrievedChunk],
                 json_mode: bool = False, max_tokens: Optional[int] = None) -> ResearchResult:
        if not passages:
            return ResearchResult(task, title, f"### {title}\n\nNo relevant evidence was found in your documents.",
                                  warnings=["No evidence found."])
        provider = self._provider_fn()
        ok, why = provider.available()
        if not ok:
            return self._fallback(task, title, passages, why)
        context, mm, warn = build_context(passages, self.settings.max_context_chars)
        msgs = [{"role": "system", "content": RESEARCH_SYSTEM},
                {"role": "user", "content": f"Evidence:\n{context}\n\nTask:\n{instructions}"}]
        try:
            text = provider.generate(msgs, self.settings.temperature,
                                     max_tokens or self.settings.max_output_tokens * 2,
                                     self.settings.request_timeout_s * 2).strip()
        except KnowledgeOSError as e:
            r = self._fallback(task, title, passages, safe_user_message(e))
            r.warnings.insert(0, "Generation failed.")
            return r
        log_event(log, "research task done", task=task, passages=len(passages))
        if json_mode:
            return self._finish_json(task, title, text, mm, warn, passages)
        cits, cw, display = validate_citations(text, mm)
        if not any(c.verified for c in cits):
            cw.append("Output has no verifiable citations; treat it with caution.")
        md = f"### {title}\n\n{display}\n\n{format_sources_markdown(cits)}"
        return ResearchResult(task, title, md, cits, warn + cw, sources=passages, used_llm=True)

    def _finish_json(self, task: str, title: str, text: str, mm: dict, warn: list[str],
                     passages: list[RetrievedChunk]) -> ResearchResult:
        try:
            items = parse_json_array(text)
        except (ValueError, json.JSONDecodeError) as e:
            return ResearchResult(task, title, f"### {title}\n\nThe model's output could not be parsed "
                                  f"({e}). Try again or lower the temperature.\n\n```\n{text[:1500]}\n```",
                                  warnings=["Unparseable model output."] + warn, sources=passages, used_llm=True)
        valid: list[dict] = []
        dropped = 0
        for it in items:
            src = it.get("source")
            src = int(src) if isinstance(src, (int, float)) or (isinstance(src, str) and src.isdigit()) else None
            if task == "flashcards" and isinstance(it.get("front"), str) and isinstance(it.get("back"), str):
                valid.append({"front": it["front"].strip(), "back": it["back"].strip(), "source": src})
            elif (task == "quiz" and isinstance(it.get("question"), str) and isinstance(it.get("options"), list)
                  and len(it["options"]) >= 2 and isinstance(it.get("answer_index"), int)
                  and 0 <= it["answer_index"] < len(it["options"])):
                valid.append({"question": it["question"].strip(), "options": [str(o) for o in it["options"]],
                              "answer_index": it["answer_index"], "explanation": str(it.get("explanation", "")),
                              "source": src})
            else:
                dropped += 1
        if dropped:
            warn.append(f"{dropped} malformed item(s) were dropped.")
        cite_text = " ".join(f"item [{v['source']}]." for v in valid if v["source"] is not None)
        cits, cw, _ = validate_citations(cite_text, mm)
        good = {c.marker for c in cits if c.verified}
        for v in valid:
            v["verified_source"] = v["source"] in good
            rc = mm.get(v["source"]) if v["source"] is not None else None
            v["source_label"] = f"{rc.chunk.filename} — {rc.chunk.location_label()}" if rc else "unverified"
        lines = [f"### {title}", ""]
        for i, v in enumerate(valid, start=1):
            mark = "✅" if v["verified_source"] else "⚠️"
            if task == "flashcards":
                lines.append(f"**{i}. Q:** {v['front']}\n\n**A:** {v['back']}  \n_{mark} {v['source_label']}_\n")
            else:
                opts = "\n".join(f"   {'ABCDEFGH'[j]}. {o}" for j, o in enumerate(v["options"]))
                lines.append(f"**{i}. {v['question']}**\n{opts}\n\n<details><summary>Answer</summary>"
                             f"{'ABCDEFGH'[v['answer_index']]} — {v['explanation']} "
                             f"_({mark} {v['source_label']})_</details>\n")
        if not valid:
            lines.append("No valid items were produced.")
        return ResearchResult(task, title, "\n".join(lines), cits, warn + cw, valid, passages, True)

    # ---------------- LLM tasks ----------------
    def summarize_document(self, doc_id: str, length: str = "medium") -> ResearchResult:
        doc = self.store.get_document(doc_id)
        words = LENGTHS.get(length, 300)
        return self._run_llm("summarize_document", f"Summary — {doc.filename}",
                             f"Write a ~{words}-word summary of this document: main purpose, key points, "
                             "and conclusions. Use short paragraphs or bullets. Cite every point.",
                             self._doc_passages(doc_id, max_chunks=14))

    def summarize_section(self, doc_id: str, section_query: str, length: str = "short") -> ResearchResult:
        doc = self.store.get_document(doc_id)
        return self._run_llm("summarize_section", f"Section summary — {doc.filename}: {section_query}",
                             f"Summarize what the document says about '{section_query}' in about "
                             f"{LENGTHS.get(length, 120)} words. Cite every point.",
                             self._doc_passages(doc_id, topic=section_query, max_chunks=8))

    def compare_documents(self, doc_ids: list[str], topic: str) -> ResearchResult:
        if len(doc_ids) < 2:
            raise KnowledgeOSError("need 2 docs", user_message="Select at least two documents to compare.")
        passages: list[RetrievedChunk] = []
        names = []
        for d in doc_ids:
            names.append(self.store.get_document(d).filename)
            passages.extend(self._doc_passages(d, topic=topic or None, max_chunks=5))
        return self._run_llm("compare_documents", f"Comparison: {', '.join(names)}" + (f" — {topic}" if topic else ""),
                             "Compare the documents" + (f" on '{topic}'" if topic else "") + ". Output:\n"
                             "1. A markdown table: rows = aspects, one column per document, each cell cited.\n"
                             "2. 'Agreements' and 'Differences' bullet lists, each bullet cited.\n"
                             "3. Aspects one document covers that another does not.\n"
                             "Never attribute a finding to a document unless a passage from that document is cited.",
                             passages)

    def explain_concept(self, concept: str, doc_ids: Optional[list[str]] = None, level: str = "beginner") -> ResearchResult:
        return self._run_llm("explain_concept", f"Concept: {concept}",
                             f"Explain '{concept}' for a {level} reader using only the evidence: definition, "
                             "how it works, an example from the sources if present, and related terms. Cite each point.",
                             self._topic_passages(concept, doc_ids, 8))

    def study_notes(self, doc_id: str, length: str = "medium") -> ResearchResult:
        doc = self.store.get_document(doc_id)
        return self._run_llm("study_notes", f"Study notes — {doc.filename}",
                             f"Create structured study notes (~{LENGTHS.get(length, 300)} words): headings, "
                             "bullet points, key definitions in bold, and a 'Remember' section. Cite every bullet.",
                             self._doc_passages(doc_id, max_chunks=14))

    def flashcards(self, doc_id: str, count: int = 8) -> ResearchResult:
        doc = self.store.get_document(doc_id)
        count = max(1, min(count, 25))
        return self._run_llm("flashcards", f"Flashcards — {doc.filename}",
                             f"Create {count} flashcards. Output ONLY a JSON array of objects with keys "
                             '"front" (question), "back" (answer from the evidence) and "source" (the evidence '
                             "id number supporting it). No text outside the JSON.",
                             self._doc_passages(doc_id, max_chunks=14), json_mode=True)

    def quiz(self, doc_id: str, count: int = 5) -> ResearchResult:
        doc = self.store.get_document(doc_id)
        count = max(1, min(count, 20))
        return self._run_llm("quiz", f"Quiz — {doc.filename}",
                             f"Create {count} multiple-choice questions. Output ONLY a JSON array of objects "
                             'with keys "question", "options" (4 strings), "answer_index" (0-3), '
                             '"explanation" and "source" (evidence id). Distractors must be plausible but '
                             "clearly wrong according to the evidence. No text outside the JSON.",
                             self._doc_passages(doc_id, max_chunks=14), json_mode=True)

    def report(self, topic: str, doc_ids: Optional[list[str]] = None, length: str = "long") -> ResearchResult:
        return self._run_llm("report", f"Research report: {topic}",
                             f"Write a structured report on '{topic}' (~{LENGTHS.get(length, 700)} words) with "
                             "sections: Executive summary, Background, Key findings, Evidence gaps, Conclusion. "
                             "Cite every finding; list in 'Evidence gaps' what the sources do not cover.",
                             self._topic_passages(topic, doc_ids, 12))

    def pros_cons(self, topic: str, doc_ids: Optional[list[str]] = None) -> ResearchResult:
        return self._run_llm("pros_cons", f"Pros and cons: {topic}",
                             f"List the advantages and disadvantages of '{topic}' that the evidence states. "
                             "Use two headed bullet lists, each bullet cited. If the sources state no pros or no "
                             "cons, say so explicitly instead of inventing any.",
                             self._topic_passages(topic, doc_ids, 10))

    # ---------------- deterministic tasks ----------------
    def key_terms(self, doc_id: str, top_n: int = 20) -> ResearchResult:
        doc = self.store.get_document(doc_id)
        chunks = self.store.get_doc_chunks(doc_id)
        if not chunks:
            raise NotFoundError("no chunks", user_message="That document has no indexed content.")

        def terms(text: str) -> list[str]:
            toks = [t for t in tokenize(text) if len(t) > 2 and not t.isdigit()]
            return toks + [f"{a} {b}" for a, b in zip(toks, toks[1:])]

        tf = Counter(t for c in chunks for t in terms(c.text))
        docs = self.store.list_documents()
        df: Counter = Counter()
        for d in docs:
            df.update(set(t for c in self.store.get_doc_chunks(d.doc_id) for t in terms(c.text)))
        n = max(1, len(docs))
        scored = []
        for term, f in tf.items():
            if f < 2 and len(tf) > 50:
                continue
            idf = math.log((n + 1) / (df[term] + 1)) + 1
            weight = (1 + math.log(f)) * idf * (1.15 if " " in term else 1.0)
            scored.append((term, round(weight, 3), f))
        scored.sort(key=lambda x: -x[1])
        top = scored[:top_n]
        rows = ["| Term | Score | Occurrences | First seen |", "|---|---|---|---|"]
        for term, w, f in top:
            where = next((c.location_label() for c in chunks if term in " ".join(tokenize(c.text))), "")
            rows.append(f"| {term} | {w} | {f} | {where} |")
        md = (f"### Key terms — {doc.filename}\n\n_Statistical TF-IDF ranking against your whole library "
              f"({n} document(s)); no LLM involved._\n\n" + "\n".join(rows))
        return ResearchResult("key_terms", f"Key terms — {doc.filename}", md,
                              structured=[{"term": t, "score": w, "count": f} for t, w, f in top])

    def extract_evidence(self, query: str, doc_ids: Optional[list[str]] = None, k: int = 8) -> ResearchResult:
        results = self._topic_passages(query, doc_ids, k)
        if not results:
            return ResearchResult("extract_evidence", f"Evidence: {query}",
                                  f"### Evidence: {query}\n\nNo matching passages were found.",
                                  warnings=["No evidence found."])
        lines = [f"### Evidence: {query}", "", "_Retrieved passages with the best-matching sentences "
                 "(retrieval only; no LLM)._", ""]
        cits, items = [], []
        for i, rc in enumerate(results, start=1):
            sents = split_sentences(rc.chunk.text) or [rc.chunk.text]
            best = sorted(sents, key=lambda s: -lexical_support(query, s))[:2]
            quote = " … ".join(b[:300] for b in best)
            lines.append(f"**[{i}] {rc.chunk.filename} — {rc.chunk.location_label()}** "
                         f"(rank score {rc.score:.4f})\n> {quote}\n")
            cits.append(Citation(marker=i, chunk_id=rc.chunk.chunk_id, doc_id=rc.chunk.doc_id,
                                 filename=rc.chunk.filename, location=rc.chunk.location_label(),
                                 passage=quote, verified=True, note="Retrieved passage."))
            items.append({"marker": i, "filename": rc.chunk.filename, "location": rc.chunk.location_label(),
                          "chunk_id": rc.chunk.chunk_id, "text": quote})
        return ResearchResult("extract_evidence", f"Evidence: {query}", "\n".join(lines), cits,
                              structured=items, sources=results)

