"""Document Library: upload & process, browse, inspect, delete, re-index and index health."""
from __future__ import annotations

from typing import TYPE_CHECKING, Any

import gradio as gr

from ..config import SUPPORTED_EXTENSIONS
from . import controllers as C
from .components import DOC_COLUMNS, notice

if TYPE_CHECKING:
    from ..services import KnowledgeService


def build(svc: "KnowledgeService") -> dict[str, Any]:
    gr.Markdown("### Document library")
    with gr.Row():
        # ---------- upload ----------
        with gr.Column(scale=2):
            gr.Markdown("#### 1 · Upload & process")
            files = gr.File(label=f"Files (max {svc.settings.max_file_size_mb:g} MB each)", file_count="multiple",
                            file_types=sorted(SUPPORTED_EXTENSIONS), type="filepath")
            collection = gr.Textbox(label="Collection name", value="default", max_lines=1)
            process = gr.Button("Process documents", variant="primary")
            upload_msg = gr.HTML()
            report = gr.Dataframe(headers=C.UPLOAD_REPORT_COLUMNS, interactive=False, wrap=True,
                                  label="Processing report")
        with gr.Column(scale=1):
            with gr.Accordion("How documents are processed", open=False):
                gr.Markdown(
                    "Text is extracted per format (pages for PDF, sheets and rows for spreadsheets, headings for "
                    "Markdown/Word), cleaned, split into overlapping chunks, embedded, and indexed for both "
                    "semantic and keyword search.\n\n" + C.chunking_help(svc) +
                    "\n\nScanned PDFs need OCR (Settings). Uploaded files are treated as untrusted: nothing in "
                    "them is executed.")
            health = gr.JSON(label="Index health")
            with gr.Row():
                health_btn = gr.Button("Check health", size="sm")
                repair_btn = gr.Button("Repair index", size="sm")
            maint_msg = gr.HTML()

    # ---------- library ----------
    gr.Markdown("#### 2 · Library")
    with gr.Row():
        search = gr.Textbox(placeholder="Filter by filename…", show_label=False, scale=4)
        refresh = gr.Button("↻ Refresh", size="sm", scale=1)
    table = gr.Dataframe(headers=DOC_COLUMNS, interactive=False, wrap=True)

    gr.Markdown("#### 3 · Inspect & manage")
    with gr.Row():
        with gr.Column(scale=2):
            pick = gr.Dropdown(label="Document", choices=C.all_doc_choices(svc), value=None)
            detail_md = gr.Markdown("_Select a document to see its details._")
            with gr.Accordion("Raw metadata", open=False):
                detail_json = gr.JSON()
        with gr.Column(scale=1):
            reindex_btn = gr.Button("Re-index selected")
            del_confirm = gr.Checkbox(label="Yes, permanently delete the selected document", value=False)
            del_btn = gr.Button("Delete selected", variant="stop")
            all_confirm = gr.Checkbox(label="Yes, re-index ALL documents", value=False)
            all_btn = gr.Button("Re-index all")
            manage_msg = gr.HTML()

    # ---------------- handlers ----------------
    def _lists(query=""):
        return C.library_rows(svc, query or ""), gr.update(choices=C.all_doc_choices(svc))

    def _process(paths, coll, progress=gr.Progress()):
        rows, msg = C.upload(svc, paths, coll, lambda f, m: progress(f, desc=m))
        t, dd = _lists()
        return rows, msg, t, dd, None

    def _reindex(doc_id, progress=gr.Progress()):
        msg = C.reindex_document(svc, doc_id, lambda f, m: progress(f, desc=m))
        t, dd = _lists()
        return msg, t, dd

    def _delete(doc_id, ok):
        msg = C.delete_document(svc, doc_id, ok)
        t, dd = _lists()
        deleted = "kos-note ok" in msg
        dd = gr.update(choices=C.all_doc_choices(svc), value=None) if deleted else gr.update(choices=C.all_doc_choices(svc))
        return msg, t, dd, False, "_Select a document._" if deleted else gr.update(), {} if deleted else gr.update()

    def _reindex_all(ok, progress=gr.Progress()):
        msg = C.reindex_all(svc, ok, lambda f, m: progress(f, desc=m))
        t, dd = _lists()
        return msg, t, dd, False

    def _detail(doc_id):
        data, md = C.document_detail(svc, doc_id)
        return md, data

    ev_process = process.click(_process, [files, collection], [report, upload_msg, table, pick, files])
    refresh.click(_lists, [search], [table, pick])
    search.submit(_lists, [search], [table, pick])
    pick.change(_detail, [pick], [detail_md, detail_json])
    ev_reindex = reindex_btn.click(_reindex, [pick], [manage_msg, table, pick])
    ev_delete = del_btn.click(_delete, [pick, del_confirm],
                              [manage_msg, table, pick, del_confirm, detail_md, detail_json])
    ev_all = all_btn.click(_reindex_all, [all_confirm], [manage_msg, table, pick, all_confirm])
    health_btn.click(lambda: C.health_json(svc), None, health)
    ev_repair = repair_btn.click(lambda: (C.repair(svc), C.health_json(svc)), None, [maint_msg, health])

    return {"refresh_fn": lambda: _lists(), "refresh_outputs": [table, pick],
            "changed_events": [ev_process, ev_reindex, ev_delete, ev_all, ev_repair],
            "health_fn": lambda: C.health_json(svc), "health_output": health}

