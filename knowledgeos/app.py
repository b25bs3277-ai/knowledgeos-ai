"""Assemble the KnowledgeOS Gradio application.

Usage (notebook):
    from knowledgeos.app import launch
    demo, svc = launch(share=False)
    ...
    demo.close()   # stop the server
"""
from __future__ import annotations

from typing import Any, Optional

import gradio as gr

from .config import PROJECT_NAME, SecretStore, Settings
from .conversations import new_session_id
from .logging_config import get_logger, log_event
from .security import PUBLIC_URL_WARNING
from .services import KnowledgeService
from .ui import chat, dashboard, documents, evaluation, help as help_page, research
from .ui import settings as settings_page
from .ui import system
from .ui.components import CSS, header_html, notice

log = get_logger("app")


def create_app(service: Optional[KnowledgeService] = None, public: bool = False) -> tuple[gr.Blocks, KnowledgeService]:
    svc = service or KnowledgeService(Settings.load(), SecretStore())
    with gr.Blocks(css=CSS, title=PROJECT_NAME, theme=gr.themes.Soft()) as demo:
        session = gr.State(None)  # per-browser-session id, set on page load
        gr.HTML(header_html())
        if public:
            gr.HTML(notice("warn", PUBLIC_URL_WARNING))
        with gr.Tabs():
            with gr.Tab("Overview"):
                p_dash = dashboard.build(svc)
            with gr.Tab("Chat with documents"):
                p_chat = chat.build(svc, session)
            with gr.Tab("Document library"):
                p_docs = documents.build(svc)
            with gr.Tab("Research workspace"):
                p_res = research.build(svc)
            with gr.Tab("Evaluation lab"):
                p_eval = evaluation.build(svc)
            with gr.Tab("System diagnostics"):
                system.build(svc)
            with gr.Tab("Settings"):
                settings_page.build(svc)
            with gr.Tab("Help"):
                help_page.build()

        # ---- after any library change, refresh every widget that lists documents or shows stats ----
        refresh_outputs = (p_chat["refresh_docs_outputs"] + p_res["refresh_docs_outputs"] +
                           p_eval["refresh_docs_outputs"] + p_dash["refresh_outputs"])

        def _refresh_all():
            out = list(p_chat["refresh_docs_fn"]()) + list(p_res["refresh_docs_fn"]())
            out.append(p_eval["refresh_docs_fn"]())
            out += list(p_dash["refresh_fn"]())
            return out

        for ev in p_docs["changed_events"]:
            ev.then(_refresh_all, None, refresh_outputs)

        # ---- page load: give this browser its own session id and fill every page with real state ----
        load_outputs = [session] + p_chat["on_session_outputs"] + p_dash["refresh_outputs"] + p_docs["refresh_outputs"]

        def _on_load():
            owner = new_session_id()
            return [owner, *p_chat["on_session_fn"](owner), *p_dash["refresh_fn"](), *p_docs["refresh_fn"]()]

        demo.load(_on_load, None, load_outputs)
    return demo, svc


def launch(share: bool = False, server_port: int = 7860, service: Optional[KnowledgeService] = None,
           debug: bool = False) -> tuple[gr.Blocks, KnowledgeService]:
    """Start the app without blocking the notebook. Returns (demo, service); call demo.close() to stop."""
    demo, svc = create_app(service, public=share)
    demo.queue(default_concurrency_limit=2, max_size=32)
    log_event(log, "launching", share=share, port=server_port)
    demo.launch(share=share, server_port=server_port, prevent_thread_lock=True, debug=debug,
                show_error=True, inbrowser=False,
                max_file_size=f"{int(svc.settings.max_file_size_mb)}mb",
                allowed_paths=[str(svc.settings.exports_dir)])  # lets download buttons serve exported files
    return demo, svc

