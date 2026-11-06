"""Overview page: real metrics, system status, recent activity and quick search."""
from __future__ import annotations

from typing import TYPE_CHECKING, Any

import gradio as gr

from . import controllers as C
from .components import workflow_html

if TYPE_CHECKING:
    from ..services import KnowledgeService


def build(svc: "KnowledgeService") -> dict[str, Any]:
    gr.Markdown("### Overview")
    gr.HTML(workflow_html())
    cards = gr.HTML()
    status = gr.HTML()
    with gr.Row():
        with gr.Column(scale=3):
            gr.Markdown("#### Quick search")
            with gr.Row():
                q = gr.Textbox(placeholder="Search your documents…", show_label=False, scale=5)
                strat = gr.Dropdown(C.STRATEGY_CHOICES, value=svc.settings.retrieval_strategy,
                                    show_label=False, scale=3)
                go = gr.Button("Search", variant="primary", scale=1)
            results = gr.HTML()
        with gr.Column(scale=2):
            gr.Markdown("#### Recent activity")
            activity = gr.Markdown()
            refresh = gr.Button("↻ Refresh overview", size="sm")

    def _refresh():
        return C.overview(svc)

    refresh.click(_refresh, outputs=[cards, status, activity])
    go.click(lambda text, s: C.quick_search(svc, text, s), [q, strat], results)
    q.submit(lambda text, s: C.quick_search(svc, text, s), [q, strat], results)
    return {"refresh_fn": _refresh, "refresh_outputs": [cards, status, activity]}

