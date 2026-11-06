"""Source viewer logic (Gradio-free): which pages an answer used, and rendering them."""
from __future__ import annotations

from typing import TYPE_CHECKING, Any, Optional

from ..pdf_preview import PagePreview, preview
from ..schemas import AnswerResult
from .components import empty_state

if TYPE_CHECKING:
    from ..services import KnowledgeService


def sources_from_result(svc: "KnowledgeService", result: AnswerResult) -> list[dict[str, Any]]:
    """Verified citations first (in marker order), then other retrieved passages; one entry per chunk."""
    chunks = {rc.chunk.chunk_id: rc.chunk for rc in result.retrieved}
    out: list[dict[str, Any]] = []
    seen: set[str] = set()
    for c in sorted(result.citations, key=lambda c: c.marker):
        if not c.verified or c.chunk_id in seen:
            continue
        ch = chunks.get(c.chunk_id) or svc.store.get_chunks([c.chunk_id]).get(c.chunk_id)
        if ch is None:
            continue
        seen.add(c.chunk_id)
        out.append({"label": f"[{c.marker}] {ch.filename} · {ch.location_label()}", "doc_id": ch.doc_id,
                    "page": ch.page, "passage": ch.text, "focus": c.passage, "filename": ch.filename})
    for rc in result.retrieved:
        ch = rc.chunk
        if ch.chunk_id in seen or len(out) >= 8:
            continue
        seen.add(ch.chunk_id)
        out.append({"label": f"#{rc.rank} {ch.filename} · {ch.location_label()}", "doc_id": ch.doc_id,
                    "page": ch.page, "passage": ch.text, "focus": "", "filename": ch.filename})
    return out


def open_source(svc: "KnowledgeService", src: Optional[dict[str, Any]],
                page: Optional[int] = None) -> tuple[Optional[object], str, str, Optional[int]]:
    """Returns (page image or None, caption markdown, fallback HTML, page shown)."""
    if not src:
        return None, "", empty_state("No source selected", "Ask a question — its sources appear here."), None
    try:
        rec = svc.store.get_document(src["doc_id"])
    except Exception:
        return None, "", empty_state("Document removed", "This source is no longer in the library."), None
    target = page or src.get("page")
    same_page = target == src.get("page")
    pv: PagePreview = preview(rec.stored_path, rec.file_type, target,
                              src["passage"] if same_page else "", src.get("focus", "") if same_page else "",
                              rec.filename)
    if pv.image is not None:
        where = f"page **{pv.page}** of {pv.n_pages}"
        mark = (f" · 🟨 evidence highlighted ({pv.matched} match{'es' if pv.matched != 1 else ''})"
                if same_page and pv.matched else (" · (no highlight on this page)" if not same_page else ""))
        caption = f"**{rec.filename}** — {where}{mark}"
    else:
        caption = f"**{rec.filename}** — {src['label'].split(' ', 1)[-1]}"
    if pv.notes:
        caption += "\n\n_" + " ".join(pv.notes) + "_"
    return pv.image, caption, pv.html, pv.page
