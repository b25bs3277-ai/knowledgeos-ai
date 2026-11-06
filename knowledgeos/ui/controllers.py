"""Page logic, kept free of Gradio so it can be unit-tested and reused.

Each function takes the KnowledgeService plus plain inputs and returns plain
values (strings, lists, dicts). The Gradio page modules only wire these to widgets.
"""
from __future__ import annotations

import json
from typing import TYPE_CHECKING, Any, Callable, Iterator, Optional

from ..chunking import describe_chunking
from ..exceptions import KnowledgeOSError, safe_user_message
from ..logging_config import get_logger
from ..schemas import AnswerResult, Citation
from .components import (activity_md, citations_html, doc_choices, documents_table, empty_state, notice,
                         notices, passages_html, stat_cards)

if TYPE_CHECKING:
    from ..services import KnowledgeService

log = get_logger("ui")

STRATEGY_CHOICES = [
    ("Hybrid — BM25 + semantic, fused with RRF (recommended)", "hybrid"),
    ("Hybrid + cross-encoder reranking (slower, optional model)", "hybrid_rerank"),
    ("Semantic only (dense embeddings)", "dense"),
    ("Keyword only (BM25)", "keyword"),
]


# ======================= system status =======================
def system_status(svc: "KnowledgeService") -> list[tuple[str, str]]:
    """Real application state as (kind, message) notices, most important first."""
    docs = svc.list_documents()
    out: list[tuple[str, str]] = []
    if not docs:
        out.append(("info", "No documents yet. Open Document Library and upload PDF, DOCX, TXT, MD, CSV or XLSX files."))
    else:
        busy = [d for d in docs if d.status in ("uploaded", "extracting", "indexing")]
        failed = [d for d in docs if d.status == "failed"]
        ready = [d for d in docs if d.status == "ready"]
        if busy:
            out.append(("warn", f"{len(busy)} document(s) are still being processed."))
        if failed:
            out.append(("err", f"{len(failed)} document(s) failed to index. See Document Library for the reason."))
        if ready:
            out.append(("ok", f"{len(ready)} document(s) ready for search."))
        elif not busy:
            out.append(("warn", "No document is ready for search yet."))
    p = svc.provider_status()
    if not p["available"]:
        out.append(("warn", f"Answer generation is off: {p['detail']}"))
    health = svc.index_health()
    if not health["healthy"] and docs:
        out.append(("warn", "Index needs attention (vectors and database differ). "
                            "Use Document Library → Repair index."))
    return out


# ======================= overview page =======================
def overview(svc: "KnowledgeService") -> tuple[str, str, str]:
    """Returns (stat cards HTML, status notices HTML, recent activity markdown)."""
    s = svc.stats()
    p = s["provider"]
    cards = stat_cards([
        ("Documents", s["documents"]), ("Ready", s["ready_documents"]), ("Indexed chunks", s["chunks"]),
        ("Vectors", s["vectors"]), ("Failed", s["failed_documents"]),
        ("Generation", f"{p['provider']}" + ("" if p["available"] else " (off)")),
    ])
    return cards, notices(system_status(svc)), activity_md(svc.recent_activity(12))


def quick_search(svc: "KnowledgeService", query: str, strategy: Optional[str] = None) -> str:
    query = (query or "").strip()
    if not query:
        return notice("info", "Type something to search your documents.")
    if svc.store.counts()["chunks"] == 0:
        return empty_state("Nothing to search yet", "Upload and process documents first.")
    try:
        out = svc.search(query, strategy, 5)
    except KnowledgeOSError as e:
        return notice("err", safe_user_message(e))
    head = "".join(notice("warn", w) for w in out.warnings)
    if not out.results:
        return head + empty_state("No relevant passages", "Try different words or another strategy.")
    return head + notice("info", f"{len(out.results)} passage(s) · strategy {out.strategy_used} · "
                                 f"{out.timings_ms.get('retrieval_total_ms', 0)} ms") + passages_html(out.results)


# ======================= chat page =======================
def conversation_choices(svc: "KnowledgeService", owner: Optional[str]) -> list[tuple[str, str]]:
    if not owner:
        return []
    return [(f"{c['title']} · {c['n']} msg", c["conv_id"]) for c in svc.conversations.list(owner)]


def details_markdown(result: AnswerResult) -> str:
    """Plain-language 'how this answer was produced' panel."""
    if result.insufficient_evidence:
        status = "⚠️ Not enough evidence in your documents."
    elif result.question_type in ("greeting", "meta", "ambiguous"):
        status = "ℹ️ Answered without searching documents."
    elif result.question_type == "general":
        status = "ℹ️ General-knowledge answer, not based on your documents."
    elif not result.generation_available:
        status = "ℹ️ Evidence only — no generation provider configured."
    elif result.grounded:
        status = "✅ Answer with verified citations."
    else:
        status = "⚠️ Answer without verifiable citations."
    method = result.retrieved[0].method if result.retrieved else "none"
    lines = [f"**Status:** {status}",
             f"- Question type: `{result.question_type}`",
             f"- Search query used: {result.standalone_query!r}" +
             (" _(rewritten from your follow-up)_" if result.standalone_query != result.question else ""),
             f"- Retrieval method: `{method}` · passages: {len(result.retrieved)}",
             f"- Provider: `{result.provider}`" + (f" · model `{result.model}`" if result.model else ""),
             "- Timings: " + (", ".join(f"{k} {v} ms" for k, v in result.timings_ms.items()) or "—"),
             f"- Request id: `{result.request_id}`"]
    if result.warnings:
        lines.append("\n**Warnings**")
        lines += [f"- {w}" for w in result.warnings]
    return "\n".join(lines)


def answer_panels(result: AnswerResult) -> tuple[str, str, str]:
    """(citations HTML, retrieved passages HTML, details markdown) for the evidence panel."""
    return citations_html(result.citations), passages_html(result.retrieved), details_markdown(result)


def load_conversation(svc: "KnowledgeService", owner: str, conv_id: Optional[str]
                      ) -> tuple[list[dict[str, str]], list[str], str]:
    """(chat messages, saved document filter, evidence HTML for the last answer)."""
    if not owner or not conv_id:
        return [], [], empty_state("No answer selected", "Ask a question to see its sources here.")
    try:
        conv = svc.conversations.get(owner, conv_id)
    except KnowledgeOSError as e:
        return [], [], notice("warn", safe_user_message(e))
    messages = [{"role": t.role, "content": t.content} for t in conv.turns if t.role in ("user", "assistant")]
    last = next((t for t in reversed(conv.turns) if t.role == "assistant"), None)
    cits = []
    if last:
        for d in last.meta.get("citations", []):
            try:
                cits.append(Citation(**d))
            except TypeError:
                continue
    evidence = citations_html(cits) if last else empty_state("No answer yet", "Ask a question to see its sources.")
    valid_docs = {d.doc_id for d in svc.list_documents()}
    return messages, [d for d in conv.doc_filter if d in valid_docs], evidence


def chat_turn(svc: "KnowledgeService", owner: str, conv_id: Optional[str], message: str,
              history: list[dict[str, str]], doc_ids: Optional[list[str]], strategy: Optional[str]
              ) -> Iterator[dict[str, Any]]:
    """Run one chat turn. Yields dicts: {history, conv_id, final, panels?}.

    Errors become a visible assistant message; they are logged, never swallowed.
    """
    history = list(history or []) + [{"role": "user", "content": message},
                                     {"role": "assistant", "content": "…"}]
    try:
        for text, result, cid in svc.ask_stream(owner, conv_id, message, doc_ids or None, strategy or None):
            history[-1] = {"role": "assistant", "content": text or "…"}
            conv_id = cid
            if result is None:
                yield {"history": history, "conv_id": conv_id, "final": False}
            else:
                yield {"history": history, "conv_id": conv_id, "final": True, "panels": answer_panels(result)}
        return
    except KnowledgeOSError as e:
        msg = safe_user_message(e)
    except Exception as e:  # unexpected: keep the UI alive, record full traceback in logs
        log.exception("chat turn failed")
        msg = safe_user_message(e)
    history[-1] = {"role": "assistant", "content": f"⛔ {msg}"}
    yield {"history": history, "conv_id": conv_id, "final": True,
           "panels": (notice("err", msg), "", f"**Error:** {msg}")}


def export_conversation(svc: "KnowledgeService", owner: str, conv_id: Optional[str], fmt: str) -> tuple[Optional[str], str]:
    """(file path or None, status HTML)."""
    if not conv_id:
        return None, notice("warn", "Select or start a conversation first.")
    try:
        if fmt == "json":
            path = svc.export_text("conversation", svc.conversations.export_json(owner, conv_id), "json")
        else:
            path = svc.export_text("conversation", svc.conversations.export_markdown(owner, conv_id), "md")
    except KnowledgeOSError as e:
        return None, notice("err", safe_user_message(e))
    return str(path), notice("ok", f"Exported {path.name}.")


# ======================= document library =======================
def library_rows(svc: "KnowledgeService", search: str = "") -> list[list[Any]]:
    return documents_table(svc.list_documents(search))


def upload(svc: "KnowledgeService", paths: Optional[list[str]], collection: str,
           progress: Optional[Callable[[float, str], None]] = None) -> tuple[list[list[Any]], str]:
    """Ingest uploaded files. Returns (report table rows, summary HTML)."""
    paths = [p for p in (paths or []) if p]
    if not paths:
        return [], notice("info", "Choose one or more files first.")
    reports = svc.ingest_paths(paths, (collection or "default").strip() or "default", progress)
    rows = [[r.filename, r.status, r.chunks, r.message, "; ".join(r.warnings)[:300], r.duration_ms]
            for r in reports]
    counts: dict[str, int] = {}
    for r in reports:
        counts[r.status] = counts.get(r.status, 0) + 1
    kind = "err" if counts.get("failed") or counts.get("rejected") else "ok"
    if counts.get("indexed") and kind == "err":
        kind = "warn"
    summary = ", ".join(f"{n} {s}" for s, n in counts.items())
    return rows, notice(kind, f"Processed {len(reports)} file(s): {summary}.")


UPLOAD_REPORT_COLUMNS = ["File", "Result", "Chunks", "Message", "Warnings", "ms"]


def document_detail(svc: "KnowledgeService", doc_id: Optional[str]) -> tuple[dict[str, Any], str]:
    if not doc_id:
        return {}, "_Select a document to see its details._"
    try:
        d = svc.document_details(doc_id)
    except KnowledgeOSError as e:
        return {}, notice("err", safe_user_message(e))
    rec = d["record"]
    md = [f"### {rec['filename']}",
          f"Status **{rec['status']}** · {d['chunks_in_db']} chunks · {d['chunks_with_vectors']} with vectors"]
    if rec.get("error"):
        md.append(f"\n⛔ **Error:** {rec['error']}")
    if rec.get("warnings"):
        md.append("\n**Extraction warnings**\n" + "\n".join(f"- {w}" for w in rec["warnings"]))
    md.append("\n**First chunks**")
    for p in d["preview"]:
        md.append(f"- `{p['location']}` — {p['text'][:200].replace(chr(10), ' ')}…")
    return d, "\n".join(md)


def delete_document(svc: "KnowledgeService", doc_id: Optional[str], confirm: bool) -> str:
    if not doc_id:
        return notice("warn", "Select a document first.")
    try:
        return notice("ok", svc.delete_document(doc_id, confirm=bool(confirm)))
    except KnowledgeOSError as e:
        return notice("warn" if e.category == "validation" else "err", safe_user_message(e))


def reindex_document(svc: "KnowledgeService", doc_id: Optional[str],
                     progress: Optional[Callable[[float, str], None]] = None) -> str:
    if not doc_id:
        return notice("warn", "Select a document first.")
    try:
        r = svc.reindex_document(doc_id, progress)
    except KnowledgeOSError as e:
        return notice("err", safe_user_message(e))
    return notice("ok" if r.status == "indexed" else "err", f"{r.filename}: {r.message}")


def reindex_all(svc: "KnowledgeService", confirm: bool,
                progress: Optional[Callable[[float, str], None]] = None) -> str:
    if not confirm:
        return notice("warn", "Tick the confirmation box: this re-embeds every document and can take a while.")
    reports = svc.reindex_all(progress)
    ok = sum(r.status == "indexed" for r in reports)
    return notice("ok" if ok == len(reports) else "warn", f"Re-indexed {ok}/{len(reports)} document(s).")


def repair(svc: "KnowledgeService") -> str:
    try:
        return notice("ok", svc.repair_index())
    except KnowledgeOSError as e:
        return notice("err", safe_user_message(e))


def doc_filter_choices(svc: "KnowledgeService") -> list[tuple[str, str]]:
    return doc_choices(svc.list_documents(), ready_only=True)


def all_doc_choices(svc: "KnowledgeService") -> list[tuple[str, str]]:
    return [(f"{d.filename} [{d.status}]", d.doc_id) for d in svc.list_documents()]


def chunking_help(svc: "KnowledgeService") -> str:
    return describe_chunking(svc.settings)


def health_json(svc: "KnowledgeService") -> dict[str, Any]:
    return json.loads(json.dumps(svc.index_health(), default=str))

