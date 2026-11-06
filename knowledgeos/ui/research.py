"""Research Workspace page."""
from __future__ import annotations

from typing import TYPE_CHECKING, Any

import gradio as gr

from . import controllers as C
from . import workspace_controllers as W

if TYPE_CHECKING:
    from ..services import KnowledgeService


def build(svc: "KnowledgeService") -> dict[str, Any]:
    last = gr.State(None)
    gr.Markdown("### Research workspace")
    with gr.Row():
        with gr.Column(scale=1, min_width=280):
            task = gr.Dropdown(W.TASK_CHOICES, value="summarize_document", label="Task")
            hint = gr.Markdown(W.TASK_HINTS["summarize_document"])
            doc = gr.Dropdown(label="Document", choices=C.doc_filter_choices(svc), value=None)
            docs = gr.Dropdown(label="Documents (compare / limit search)", multiselect=True,
                               choices=C.doc_filter_choices(svc), value=[])
            topic = gr.Textbox(label="Topic, concept or question", max_lines=2)
            length = gr.Radio(["short", "medium", "long"], value="medium", label="Length")
            count = gr.Slider(1, 20, value=8, step=1, label="Number of flashcards / quiz questions")
            run = gr.Button("Run task", variant="primary")
            with gr.Row():
                exp_md = gr.Button("Export .md", size="sm")
                exp_json = gr.Button("Export .json", size="sm")
            exp_file = gr.File(label="Download", interactive=False)
        with gr.Column(scale=2):
            status = gr.HTML()
            output = gr.Markdown("_Results appear here._")
            with gr.Accordion("Sources used", open=False):
                cits = gr.HTML()

    task.change(lambda t: W.TASK_HINTS.get(t, ""), task, hint)

    def _run(t, d, ds, tp, ln, n):
        md, c_html, msg, payload = W.run_research(svc, t, d, ds, tp, ln, n)
        return (md or "_No output._"), c_html, msg, payload

    run.click(_run, [task, doc, docs, topic, length, count], [output, cits, status, last])
    exp_md.click(lambda p: W.export_research(svc, p, "md"), last, [exp_file, status])
    exp_json.click(lambda p: W.export_research(svc, p, "json"), last, [exp_file, status])

    def _refresh_docs():
        ch = C.doc_filter_choices(svc)
        return gr.update(choices=ch), gr.update(choices=ch)

    return {"refresh_docs_fn": _refresh_docs, "refresh_docs_outputs": [doc, docs]}

