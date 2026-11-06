"""Settings page. Components are created in SETTINGS_FIELDS order so values map 1:1 on save."""
from __future__ import annotations

from typing import TYPE_CHECKING, Any

import gradio as gr

from ..config import LLM_PROVIDERS, RETRIEVAL_STRATEGIES
from . import controllers as C
from . import workspace_controllers as W

if TYPE_CHECKING:
    from ..services import KnowledgeService


def build(svc: "KnowledgeService") -> dict[str, Any]:
    s = svc.settings
    f: dict[str, Any] = {}
    gr.Markdown("### Settings")
    gr.Markdown("Changes are saved to the data folder (never including API keys) and apply immediately.")

    with gr.Accordion("Retrieval", open=True):
        with gr.Row():
            f["retrieval_strategy"] = gr.Dropdown(C.STRATEGY_CHOICES, value=s.retrieval_strategy, label="Default strategy")
            f["top_k"] = gr.Slider(1, 20, value=s.top_k, step=1, label="Passages per answer (top-k)")
            f["candidate_k"] = gr.Slider(5, 100, value=s.candidate_k, step=1, label="Candidates before fusion/reranking")
            f["rrf_k"] = gr.Number(value=s.rrf_k, label="RRF constant k", precision=0)
        with gr.Row():
            f["min_dense_score"] = gr.Slider(0.0, 0.9, value=s.min_dense_score, step=0.01,
                                             label="Minimum semantic similarity (cosine)")
            f["min_rerank_score"] = gr.Number(value=s.min_rerank_score, label="Minimum reranker score (logit)")
            f["enable_multi_query"] = gr.Checkbox(value=s.enable_multi_query,
                                                  label="Multi-query retrieval (extra LLM call per question)")
            f["reranker_model"] = gr.Textbox(value=s.reranker_model, label="Reranker model", max_lines=1)

    with gr.Accordion("Ingestion & chunking", open=False):
        gr.Markdown(C.chunking_help(svc))
        with gr.Row():
            f["chunk_size_tokens"] = gr.Slider(64, 1024, value=s.chunk_size_tokens, step=16, label="Chunk size (tokens)")
            f["chunk_overlap_tokens"] = gr.Slider(0, 256, value=s.chunk_overlap_tokens, step=8, label="Overlap (tokens)")
            f["max_file_size_mb"] = gr.Number(value=s.max_file_size_mb, label="Max file size (MB)")
            f["max_files_per_upload"] = gr.Number(value=s.max_files_per_upload, label="Max files per upload", precision=0)
        f["enable_ocr"] = gr.Checkbox(value=s.enable_ocr, label="OCR for scanned PDF pages (needs: pip install "
                                      "pytesseract pypdfium2 and apt-get install tesseract-ocr)")

    with gr.Accordion("Embeddings", open=False):
        gr.Markdown(W.EMBEDDING_HELP)
        with gr.Row():
            f["embedding_model"] = gr.Dropdown(W.EMBEDDING_CHOICES, value=s.embedding_model, allow_custom_value=True,
                                               label="Embedding model (changing it requires Re-index all)")
            f["embedding_batch_size"] = gr.Slider(1, 128, value=s.embedding_batch_size, step=1, label="Batch size")
            f["device"] = gr.Radio(["auto", "cpu", "cuda"], value=s.device, label="Device")

    with gr.Accordion("Generation", open=True):
        provider_md = gr.Markdown(W.provider_summary(svc))
        with gr.Row():
            f["llm_provider"] = gr.Dropdown(list(LLM_PROVIDERS), value=s.llm_provider, label="Provider")
            f["llm_model"] = gr.Textbox(value=s.llm_model, label="Model (OpenAI-compatible)", max_lines=1)
            f["llm_base_url"] = gr.Textbox(value=s.llm_base_url, label="Base URL (OpenAI-compatible)", max_lines=1)
        with gr.Row():
            f["gemini_model"] = gr.Textbox(value=s.gemini_model, label="Gemini model", max_lines=1)
            f["local_model"] = gr.Textbox(value=s.local_model, label="Local model (Hugging Face id)", max_lines=1)
        with gr.Row():
            f["temperature"] = gr.Slider(0.0, 1.5, value=s.temperature, step=0.05, label="Temperature")
            f["max_output_tokens"] = gr.Slider(64, 4096, value=s.max_output_tokens, step=32, label="Max answer tokens")
            f["request_timeout_s"] = gr.Slider(10, 600, value=s.request_timeout_s, step=5, label="Timeout (s)")
            f["max_context_chars"] = gr.Slider(2000, 60000, value=s.max_context_chars, step=1000,
                                               label="Evidence budget (characters sent to the model)")
            f["history_turns"] = gr.Slider(0, 20, value=s.history_turns, step=1, label="Conversation turns sent")
        with gr.Group():
            gr.Markdown("**API keys** — held in memory for this runtime only; never saved, logged or exported.")
            with gr.Row():
                key_provider = gr.Dropdown(["openai_compatible", "gemini"], value="openai_compatible", label="For")
                key_box = gr.Textbox(type="password", label="API key", max_lines=1)
                key_save = gr.Button("Set key", size="sm")
                key_clear = gr.Button("Remove key", size="sm")
            key_msg = gr.HTML()
        test_btn = gr.Button("Test provider (sends one tiny request)", size="sm")
        test_msg = gr.HTML()

    with gr.Accordion("Logging & persistence", open=False):
        f["log_level"] = gr.Dropdown(["DEBUG", "INFO", "WARNING", "ERROR"], value=s.log_level, label="Log level")
        gr.Markdown("**Google Drive backup** — run the optional Drive cell in the notebook to authorise Drive "
                    "first. Backups contain documents, indexes, conversations and settings, never API keys.")
        with gr.Row():
            drive_btn = gr.Button("Check Drive", size="sm")
            backup_btn = gr.Button("Back up now", size="sm")
        drive_msg = gr.HTML()

    save = gr.Button("Save settings", variant="primary")
    save_msg = gr.HTML()

    assert list(f) == W.SETTINGS_FIELDS, "settings form order out of sync with SETTINGS_FIELDS"
    inputs = [f[name] for name in W.SETTINGS_FIELDS]

    def _save(*vals):
        return W.save_settings(svc, *vals), W.provider_summary(svc)

    save.click(_save, inputs, [save_msg, provider_md])
    key_save.click(lambda p, k: (W.save_api_key(svc, p, k), "", W.provider_summary(svc)),
                   [key_provider, key_box], [key_msg, key_box, provider_md])
    key_clear.click(lambda p: (W.clear_api_key(svc, p), W.provider_summary(svc)), key_provider, [key_msg, provider_md])
    test_btn.click(lambda: W.test_provider(svc), None, test_msg)
    drive_btn.click(lambda: W.drive_status(svc), None, drive_msg)
    backup_btn.click(lambda: W.backup_drive(svc), None, drive_msg)
    return {}

