"""System Diagnostics page: health report, logs and a shareable, secret-free export."""
from __future__ import annotations

from typing import TYPE_CHECKING, Any

import gradio as gr

from . import workspace_controllers as W

if TYPE_CHECKING:
    from ..services import KnowledgeService


def build(svc: "KnowledgeService") -> dict[str, Any]:
    gr.Markdown("### System diagnostics")
    gr.Markdown("The report covers dependencies, memory/GPU/disk, configuration, index consistency and recent "
                "warnings. It never includes API keys, document text or conversation content.")
    with gr.Row():
        gen = gr.Button("Generate report", variant="primary")
        exp = gr.Button("Export report .json")
    status = gr.HTML()
    exp_file = gr.File(label="Download", interactive=False)
    report = gr.JSON(label="Report")
    gr.Markdown("#### Application logs")
    with gr.Row():
        level = gr.Dropdown(["DEBUG", "INFO", "WARNING", "ERROR"], value="INFO", label="Minimum level")
        limit = gr.Slider(20, 500, value=200, step=20, label="Rows")
        show = gr.Button("Show logs")
    logs = gr.Dataframe(interactive=False, wrap=True)

    def _gen():
        rep, msg = W.diagnostics(svc)
        return rep, msg

    gen.click(_gen, None, [report, status])
    exp.click(lambda: W.export_diagnostics(svc), None, [exp_file, status])
    show.click(W.log_table, [level, limit], logs)
    return {}

