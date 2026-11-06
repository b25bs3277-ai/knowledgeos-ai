"""Chat page: streaming answers, conversations, document filter and evidence inspection."""
from __future__ import annotations

from typing import TYPE_CHECKING, Any

import gradio as gr

from . import controllers as C
from .components import empty_state, notice

if TYPE_CHECKING:
    from ..services import KnowledgeService

EXAMPLES = ["Summarize the main points of my documents.",
            "What does the document say about evaluation metrics?",
            "Compare the approaches described in the sources."]


def build(svc: "KnowledgeService", session: gr.State) -> dict[str, Any]:
    conv_id = gr.State(None)
    gr.Markdown("### Chat with documents")
    banner = gr.HTML()
    with gr.Row():
        # ---------- left: conversations & scope ----------
        with gr.Column(scale=1, min_width=240):
            conv_dd = gr.Dropdown(label="Conversations", choices=[], value=None, interactive=True)
            new_btn = gr.Button("＋ New conversation", size="sm")
            with gr.Accordion("Rename / delete / export", open=False):
                title_box = gr.Textbox(label="New title", max_lines=1)
                rename_btn = gr.Button("Rename", size="sm")
                del_confirm = gr.Checkbox(label="Yes, delete this conversation", value=False)
                del_btn = gr.Button("Delete conversation", size="sm", variant="stop")
                with gr.Row():
                    exp_md = gr.Button("Export .md", size="sm")
                    exp_json = gr.Button("Export .json", size="sm")
                exp_file = gr.File(label="Download", interactive=False)
                conv_msg = gr.HTML()
            doc_filter = gr.Dropdown(label="Search only these documents (empty = all)", multiselect=True,
                                     choices=C.doc_filter_choices(svc), value=[])
            strat = gr.Dropdown(C.STRATEGY_CHOICES, value=svc.settings.retrieval_strategy, label="Retrieval strategy")
        # ---------- centre: chat ----------
        with gr.Column(scale=3):
            chatbot = gr.Chatbot(type="messages", height=480, show_copy_button=True, label="KnowledgeOS")
            with gr.Row():
                box = gr.Textbox(placeholder="Ask a question about your documents…", show_label=False,
                                 scale=6, max_lines=6)
                send = gr.Button("Send", variant="primary", scale=1)
            gr.Examples(EXAMPLES, inputs=box)
    # ---------- evidence panel ----------
    with gr.Accordion("Evidence for the latest answer", open=True):
        with gr.Tabs():
            with gr.Tab("Cited sources"):
                cits = gr.HTML(empty_state("No answer yet", "Ask a question to see its sources here."))
            with gr.Tab("Retrieved passages & ranking"):
                passages = gr.HTML()
            with gr.Tab("How this answer was produced"):
                details = gr.Markdown()

    # ---------------- handlers ----------------
    def _banner():
        msgs = [(k, m) for k, m in C.system_status(svc) if k != "ok"]
        return "".join(notice(k, m) for k, m in msgs)

    def _conv_update(owner, selected=None):
        return gr.update(choices=C.conversation_choices(svc, owner), value=selected)

    def _send(message, history, owner, cid, docs, strategy):
        message = (message or "").strip()
        if not message:
            yield history, "", cid, gr.update(), gr.update(), gr.update(), gr.update()
            return
        for step in C.chat_turn(svc, owner, cid, message, history, docs, strategy):
            if not step["final"]:
                yield step["history"], "", step["conv_id"], gr.update(), gr.update(), gr.update(), gr.update()
            else:
                c_html, p_html, d_md = step["panels"]
                yield (step["history"], "", step["conv_id"], _conv_update(owner, step["conv_id"]),
                       c_html, p_html, d_md)

    send_outputs = [chatbot, box, conv_id, conv_dd, cits, passages, details]
    send.click(_send, [box, chatbot, session, conv_id, doc_filter, strat], send_outputs)
    box.submit(_send, [box, chatbot, session, conv_id, doc_filter, strat], send_outputs)

    def _select(owner, cid):
        msgs, flt, ev = C.load_conversation(svc, owner, cid)
        return msgs, cid, gr.update(value=flt), ev, "", ""

    conv_dd.input(_select, [session, conv_dd], [chatbot, conv_id, doc_filter, cits, passages, details])

    def _new(owner):
        return [], None, _conv_update(owner, None), empty_state("New conversation", "Ask your first question."), "", ""

    new_btn.click(_new, [session], [chatbot, conv_id, conv_dd, cits, passages, details])

    def _save_filter(owner, cid, docs):
        if owner and cid:
            try:
                svc.conversations.set_doc_filter(owner, cid, docs or [])
            except Exception:  # stale conversation id; the filter still applies to this view
                pass

    doc_filter.change(_save_filter, [session, conv_id, doc_filter], None)

    def _rename(owner, cid, title):
        if not cid:
            return gr.update(), notice("warn", "Select a conversation first.")
        try:
            svc.conversations.rename(owner, cid, title)
        except Exception as e:
            from ..exceptions import safe_user_message
            return gr.update(), notice("err", safe_user_message(e))
        return _conv_update(owner, cid), notice("ok", "Renamed.")

    rename_btn.click(_rename, [session, conv_id, title_box], [conv_dd, conv_msg])

    def _delete(owner, cid, ok):
        if not cid:
            return gr.update(), gr.update(), cid, notice("warn", "Select a conversation first."), False
        if not ok:
            return gr.update(), gr.update(), cid, notice("warn", "Tick the confirmation box to delete."), False
        svc.conversations.delete(owner, cid)
        return [], _conv_update(owner, None), None, notice("ok", "Conversation deleted."), False

    del_btn.click(_delete, [session, conv_id, del_confirm], [chatbot, conv_dd, conv_id, conv_msg, del_confirm])
    exp_md.click(lambda o, c: C.export_conversation(svc, o, c, "md"), [session, conv_id], [exp_file, conv_msg])
    exp_json.click(lambda o, c: C.export_conversation(svc, o, c, "json"), [session, conv_id], [exp_file, conv_msg])

    def _on_session(owner):
        return _conv_update(owner, None), gr.update(choices=C.doc_filter_choices(svc)), _banner()

    def _refresh_docs():
        return gr.update(choices=C.doc_filter_choices(svc)), _banner()

    return {"on_session_fn": _on_session, "on_session_outputs": [conv_dd, doc_filter, banner],
            "refresh_docs_fn": _refresh_docs, "refresh_docs_outputs": [doc_filter, banner]}

