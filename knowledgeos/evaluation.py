"""Evaluation laboratory.

Deterministic retrieval metrics (Recall@K, Precision@K, MRR, latency) are kept
strictly separate from answer metrics. Answer metrics are of two kinds:
  * deterministic: token-F1 vs reference, citation validity, evidence coverage, latency
  * model-based (optional "LLM-as-judge"): a 1–5 score from the configured LLM.
    LLM judges are biased (verbosity, self-preference, position), non-deterministic and
    not ground truth; results are labelled as such everywhere.

Relevance labels for a case, in order of precedence:
  relevant_chunk_ids > relevant_doc_ids > relevant_keywords (a chunk is relevant if it
  contains ANY keyword, case-insensitive). Recall is computed against the same label type.
"""
from __future__ import annotations

import csv
import io
import json
import re
import statistics
import time
import uuid
from collections import Counter
from dataclasses import asdict
from typing import TYPE_CHECKING, Any, Optional

from .answer_generation import AnswerGenerator
from .citations import citation_validity, evidence_coverage
from .exceptions import KnowledgeOSError, ValidationError, safe_user_message
from .hybrid_retrieval import RetrievalOutcome
from .keyword_search import tokenize
from .llm_providers import estimate_cost, estimate_tokens
from .query_understanding import plan_query
from .schemas import EvalCase, RetrievedChunk

if TYPE_CHECKING:  # avoid a runtime import cycle with services.py
    from .services import KnowledgeService

LIMITATIONS = """**How to read these numbers**
- Retrieval metrics are deterministic and depend entirely on your relevance labels. Bad labels → misleading scores.
- With a handful of questions, differences between strategies are usually within noise. Don't declare a winner from < ~30 labelled questions.
- Token-F1 rewards word overlap with your reference answer, not correctness; a correct paraphrase can score low.
- "Citation validity" checks that cited passages were really retrieved, not that they logically support the claim.
- The optional LLM-judge score is model-based: biased, non-deterministic and not ground truth."""


# ---------------- case management ----------------
def make_case(question: str, expected_answer: str = "", doc_ids: Optional[list[str]] = None,
              chunk_ids: Optional[list[str]] = None, keywords: Optional[list[str]] = None) -> EvalCase:
    question = (question or "").strip()
    if not question:
        raise ValidationError("empty question", user_message="Each evaluation case needs a question.")
    return EvalCase(case_id="e_" + uuid.uuid4().hex[:8], question=question,
                    expected_answer=(expected_answer or "").strip(),
                    relevant_doc_ids=[d for d in (doc_ids or []) if d],
                    relevant_chunk_ids=[c for c in (chunk_ids or []) if c],
                    relevant_keywords=[k.strip() for k in (keywords or []) if k and k.strip()])


def _split_list(v: Any) -> list[str]:
    if isinstance(v, list):
        return [str(x).strip() for x in v if str(x).strip()]
    return [x.strip() for x in re.split(r"[;|]", str(v or "")) if x.strip()]


def cases_from_rows(rows: list[dict[str, Any]]) -> list[EvalCase]:
    """Rows with keys: question, expected_answer, relevant_doc_ids, relevant_chunk_ids,
    relevant_keywords (lists may be ';'-separated strings). Blank questions are skipped."""
    out = []
    for r in rows:
        if not str(r.get("question", "")).strip():
            continue
        out.append(make_case(str(r["question"]), str(r.get("expected_answer", "") or ""),
                             _split_list(r.get("relevant_doc_ids")), _split_list(r.get("relevant_chunk_ids")),
                             _split_list(r.get("relevant_keywords"))))
    return out


def cases_from_json(text: str) -> list[EvalCase]:
    try:
        data = json.loads(text)
    except json.JSONDecodeError as e:
        raise ValidationError(str(e), user_message="The evaluation file is not valid JSON.") from e
    if not isinstance(data, list):
        raise ValidationError("not a list", user_message="Evaluation JSON must be a list of cases.")
    return cases_from_rows([d for d in data if isinstance(d, dict)])


def cases_from_csv(text: str) -> list[EvalCase]:
    return cases_from_rows(list(csv.DictReader(io.StringIO(text))))


def cases_to_json(cases: list[EvalCase]) -> str:
    return json.dumps([asdict(c) for c in cases], indent=2)


# ---------------- deterministic retrieval metrics ----------------
def label_type(case: EvalCase) -> str:
    if case.relevant_chunk_ids:
        return "chunk"
    if case.relevant_doc_ids:
        return "document"
    if case.relevant_keywords:
        return "keyword"
    return "none"


def is_relevant(rc: RetrievedChunk, case: EvalCase) -> bool:
    lt = label_type(case)
    if lt == "chunk":
        return rc.chunk.chunk_id in case.relevant_chunk_ids
    if lt == "document":
        return rc.chunk.doc_id in case.relevant_doc_ids
    if lt == "keyword":
        text = rc.chunk.text.lower()
        return any(k.lower() in text for k in case.relevant_keywords)
    return False


def retrieval_metrics(results: list[RetrievedChunk], case: EvalCase, k: int) -> dict[str, Optional[float]]:
    lt = label_type(case)
    if lt == "none":
        return {"precision_at_k": None, "recall_at_k": None, "mrr": None, "hit_at_k": None}
    top = results[:k]
    flags = [is_relevant(r, case) for r in top]
    precision = sum(flags) / k
    first = next((i for i, f in enumerate(flags, start=1) if f), None)
    if lt == "chunk":
        recall = len({r.chunk.chunk_id for r in top} & set(case.relevant_chunk_ids)) / len(case.relevant_chunk_ids)
    elif lt == "document":
        recall = len({r.chunk.doc_id for r in top} & set(case.relevant_doc_ids)) / len(case.relevant_doc_ids)
    else:
        joined = " ".join(r.chunk.text.lower() for r in top)
        recall = sum(k_.lower() in joined for k_ in case.relevant_keywords) / len(case.relevant_keywords)
    return {"precision_at_k": round(precision, 4), "recall_at_k": round(recall, 4),
            "mrr": round(1.0 / first, 4) if first else 0.0, "hit_at_k": 1.0 if first else 0.0}


def _mean(vals: list[Optional[float]]) -> Optional[float]:
    v = [x for x in vals if x is not None]
    return round(statistics.fmean(v), 4) if v else None


def run_retrieval_experiment(service: "KnowledgeService", cases: list[EvalCase], strategies: list[str],
                             k: int = 5, progress=None) -> dict[str, Any]:
    """Run every case through every strategy. Returns per-case rows and a per-strategy summary."""
    if not cases:
        raise ValidationError("no cases", user_message="Add at least one evaluation question first.")
    rows: list[dict[str, Any]] = []
    total = len(cases) * len(strategies)
    done = 0
    for strat in strategies:
        for case in cases:
            t = time.perf_counter()
            try:
                out: RetrievalOutcome = service.retriever.retrieve(case.question, strat, k)
                err, used, results, warn = "", out.strategy_used, out.results, "; ".join(out.warnings)
            except KnowledgeOSError as e:
                err, used, results, warn = safe_user_message(e), strat, [], ""
            latency = round((time.perf_counter() - t) * 1000, 1)
            m = retrieval_metrics(results, case, k)
            rows.append({"case_id": case.case_id, "question": case.question, "strategy": strat,
                         "strategy_used": used, "label_type": label_type(case), **m,
                         "latency_ms": latency, "top_sources": " | ".join(
                             f"{r.chunk.filename} ({r.chunk.location_label()})" for r in results[:3]),
                         "warnings": warn, "error": err})
            done += 1
            if progress:
                progress(done / total, f"{strat}: {done}/{total}")
    summary = []
    for strat in strategies:
        sr = [r for r in rows if r["strategy"] == strat]
        lat = [r["latency_ms"] for r in sr]
        summary.append({"strategy": strat, "cases": len(sr),
                        "labelled_cases": sum(r["label_type"] != "none" for r in sr),
                        f"precision@{k}": _mean([r["precision_at_k"] for r in sr]),
                        f"recall@{k}": _mean([r["recall_at_k"] for r in sr]),
                        "MRR": _mean([r["mrr"] for r in sr]),
                        f"hit@{k}": _mean([r["hit_at_k"] for r in sr]),
                        "mean_latency_ms": round(statistics.fmean(lat), 1) if lat else None,
                        "p95_latency_ms": round(sorted(lat)[max(0, int(len(lat) * 0.95) - 1)], 1) if lat else None,
                        "fell_back": sum(r["strategy_used"] != strat for r in sr)})
    return {"rows": rows, "summary": summary, "k": k, "n_cases": len(cases),
            "note": "Small evaluation sets cannot establish that one strategy is better."}


# ---------------- answer metrics ----------------
def token_f1(prediction: str, reference: str) -> Optional[float]:
    if not reference.strip():
        return None
    p = tokenize(re.sub(r"\[\d+[^\]]*\]", " ", prediction))
    r = tokenize(reference)
    if not p or not r:
        return 0.0
    common = sum((Counter(p) & Counter(r)).values())
    if common == 0:
        return 0.0
    prec, rec = common / len(p), common / len(r)
    return round(2 * prec * rec / (prec + rec), 4)


_JUDGE_PROMPT = """You are grading an answer against a reference answer.
Question: {q}
Reference answer: {ref}
Candidate answer: {ans}

Score 1-5 for factual agreement with the reference (5 = fully consistent and complete,
1 = contradicts or misses it). Reply ONLY with JSON: {{"score": <int>, "reason": "<short reason>"}}"""


def llm_judge(service: "KnowledgeService", question: str, reference: str, answer: str) -> tuple[Optional[int], str]:
    provider = service.provider
    if not provider.available()[0] or not reference.strip():
        return None, "not run"
    try:
        raw = provider.generate([{"role": "user", "content": _JUDGE_PROMPT.format(q=question, ref=reference, ans=answer[:3000])}],
                                0.0, 120, service.settings.request_timeout_s)
        m = re.search(r"\{.*\}", raw, re.S)
        data = json.loads(m.group(0)) if m else {}
        score = int(data.get("score"))
        return (score if 1 <= score <= 5 else None), str(data.get("reason", ""))[:200]
    except (KnowledgeOSError, ValueError, TypeError, json.JSONDecodeError) as e:
        return None, f"judge failed: {type(e).__name__}"


def run_answer_eval(service: "KnowledgeService", cases: list[EvalCase], strategy: Optional[str] = None,
                    use_judge: bool = False, usd_per_m_in: float = 0.0, usd_per_m_out: float = 0.0,
                    progress=None) -> dict[str, Any]:
    """End-to-end answers without touching any user conversation."""
    if not cases:
        raise ValidationError("no cases", user_message="Add at least one evaluation question first.")
    from .answer_generation import build_context  # noqa: F401  (documents the dependency)
    gen = AnswerGenerator(service.settings, service.provider)
    has_docs = service.store.counts()["chunks"] > 0
    rows = []
    for i, case in enumerate(cases, start=1):
        t0 = time.perf_counter()
        plan = plan_query(case.question, [], has_docs, service.provider, False, service.settings.request_timeout_s)
        outcome = service.retriever.retrieve(plan.standalone, strategy) if plan.question_type.value == "document" else None
        res = gen.answer(plan, outcome, [])
        e2e = round((time.perf_counter() - t0) * 1000, 1)
        marker_map = {c.marker: rc for c in res.citations if c.verified
                      for rc in res.retrieved if rc.chunk.chunk_id == c.chunk_id}
        tokens_in = estimate_tokens(case.question) + sum(estimate_tokens(r.chunk.text) for r in res.retrieved)
        tokens_out = estimate_tokens(res.answer)
        judge_score, judge_reason = (llm_judge(service, case.question, case.expected_answer, res.answer)
                                     if use_judge and res.generation_available else (None, "not run"))
        rows.append({
            "case_id": case.case_id, "question": case.question, "provider": res.provider,
            "generation_available": res.generation_available, "insufficient_evidence": res.insufficient_evidence,
            "token_f1": token_f1(res.answer, case.expected_answer) if res.generation_available else None,
            "citation_count": len(res.citations), "citation_validity": citation_validity(res.citations),
            "evidence_coverage": evidence_coverage(res.answer, marker_map) if res.generation_available else None,
            "retrieval_ms": res.timings_ms.get("retrieval_total_ms"), "generation_ms": res.timings_ms.get("generation_ms"),
            "end_to_end_ms": e2e, "est_tokens_in": tokens_in, "est_tokens_out": tokens_out,
            "est_cost_usd": estimate_cost(tokens_in, tokens_out, usd_per_m_in, usd_per_m_out)
            if (usd_per_m_in or usd_per_m_out) else None,
            "llm_judge_score (model-based)": judge_score, "llm_judge_reason": judge_reason,
            "answer": res.answer[:2000]})
        if progress:
            progress(i / len(cases), f"answered {i}/{len(cases)}")
    summary = {
        "cases": len(rows),
        "mean_token_f1": _mean([r["token_f1"] for r in rows]),
        "mean_citation_validity": _mean([r["citation_validity"] for r in rows if r["citation_count"]]),
        "mean_evidence_coverage": _mean([r["evidence_coverage"] for r in rows]),
        "mean_end_to_end_ms": _mean([r["end_to_end_ms"] for r in rows]),
        "insufficient_evidence_rate": _mean([1.0 if r["insufficient_evidence"] else 0.0 for r in rows]),
        "total_est_cost_usd": round(sum(r["est_cost_usd"] or 0 for r in rows), 6)
        if any(r["est_cost_usd"] is not None for r in rows) else None,
        "mean_llm_judge (model-based)": _mean([r["llm_judge_score (model-based)"] for r in rows]),
        "token_estimates": "≈4 characters per token; actual billing may differ."}
    return {"rows": rows, "summary": summary}


# ---------------- export ----------------
def rows_to_csv(rows: list[dict[str, Any]]) -> str:
    if not rows:
        return ""
    buf = io.StringIO()
    fields = list(dict.fromkeys(k for r in rows for k in r))
    w = csv.DictWriter(buf, fieldnames=fields)
    w.writeheader()
    for r in rows:
        w.writerow({k: ("" if v is None else v) for k, v in r.items()})
    return buf.getvalue()


def results_to_json(result: dict[str, Any]) -> str:
    return json.dumps(result, indent=2, default=str)


def sample_cases() -> list[EvalCase]:
    """Demo cases that match the synthetic fixture documents (tests/fixture_factory.py)."""
    return [
        make_case("What is supervised learning?", "Supervised learning trains models on labeled examples.",
                  keywords=["labeled examples"]),
        make_case("How do reinforcement learning agents learn?", "By trial and error using rewards.",
                  keywords=["rewards"]),
        make_case("What does recall measure?", "How many actual positives the model found.",
                  keywords=["actual positives"]),
        make_case("Which model had 0.91 accuracy?", "Random Forest.", keywords=["Random Forest"]),
        make_case("What does backpropagation compute?", "Gradients using the chain rule.", keywords=["chain rule"]),
    ]

