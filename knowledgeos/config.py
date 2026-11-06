"""Central configuration for KnowledgeOS AI.

All tunable behaviour lives in :class:`Settings`. Secrets (API keys) are NEVER
stored in Settings or written to disk; they live only in :class:`SecretStore`
(process memory) or in environment variables.
"""
from __future__ import annotations

import json
import os
import threading
from dataclasses import asdict, dataclass, field, fields
from pathlib import Path
from typing import Any, Optional

PROJECT_NAME = "KnowledgeOS AI"
TAGLINE = "Your Intelligent, Evidence-Grounded Knowledge Workspace."
VERSION = "0.1.0"

SUPPORTED_EXTENSIONS: frozenset[str] = frozenset(
    {".pdf", ".txt", ".md", ".markdown", ".docx", ".csv", ".xlsx"}
)
RETRIEVAL_STRATEGIES: tuple[str, ...] = ("dense", "keyword", "hybrid", "hybrid_rerank")
LLM_PROVIDERS: tuple[str, ...] = ("none", "openai_compatible", "gemini", "local_hf")

# Environment variables that may hold secrets. Values are read lazily, never logged.
SECRET_ENV_VARS: dict[str, str] = {
    "openai_compatible": "KOS_OPENAI_API_KEY",
    "gemini": "KOS_GEMINI_API_KEY",
}


@dataclass
class Settings:
    """Non-secret application settings (safe to persist as JSON)."""

    # --- storage -------------------------------------------------------
    data_dir: str = field(default_factory=lambda: os.environ.get("KOS_DATA_DIR", "/content/knowledgeos_data"))

    # --- ingestion -----------------------------------------------------
    max_file_size_mb: float = 25.0
    max_files_per_upload: int = 20
    max_pages_per_pdf: int = 1500
    max_rows_per_sheet: int = 20000
    enable_ocr: bool = False             # optional; requires pytesseract + tesseract binary
    min_text_chars: int = 20             # below this a document is treated as "empty"

    # --- chunking (token units when a tokenizer exists; chars = tokens * 4 fallback) ---
    chunk_size_tokens: int = 256
    chunk_overlap_tokens: int = 40
    min_chunk_chars: int = 30

    # --- embeddings ----------------------------------------------------
    embedding_model: str = "BAAI/bge-small-en-v1.5"   # 384-dim, ~130 MB, CPU friendly
    embedding_query_prefix: str = "Represent this sentence for searching relevant passages: "
    embedding_batch_size: int = 32
    device: str = "auto"                              # auto | cpu | cuda

    # --- retrieval -----------------------------------------------------
    retrieval_strategy: str = "hybrid"
    top_k: int = 6
    candidate_k: int = 30
    rrf_k: int = 60
    min_dense_score: float = 0.25          # cosine similarity floor for dense hits
    min_rerank_score: float = -6.0         # cross-encoder logit floor
    enable_multi_query: bool = False
    reranker_model: str = "cross-encoder/ms-marco-MiniLM-L-6-v2"

    # --- generation ----------------------------------------------------
    llm_provider: str = "none"
    llm_model: str = "gpt-4o-mini"
    llm_base_url: str = "https://api.openai.com/v1"
    gemini_model: str = "gemini-1.5-flash"
    local_model: str = "Qwen/Qwen2.5-0.5B-Instruct"
    temperature: float = 0.2
    max_output_tokens: int = 800
    request_timeout_s: int = 60
    max_context_chars: int = 12000
    history_turns: int = 6

    # --- observability -------------------------------------------------
    log_level: str = "INFO"
    log_document_content: bool = False

    # ------------------------------------------------------------------
    @property
    def data_path(self) -> Path:
        return Path(self.data_dir)

    @property
    def uploads_dir(self) -> Path:
        return self.data_path / "uploads"

    @property
    def index_dir(self) -> Path:
        return self.data_path / "index"

    @property
    def db_path(self) -> Path:
        return self.data_path / "knowledgeos.sqlite3"

    @property
    def logs_dir(self) -> Path:
        return self.data_path / "logs"

    @property
    def exports_dir(self) -> Path:
        return self.data_path / "exports"

    @property
    def settings_file(self) -> Path:
        return self.data_path / "settings.json"

    def ensure_dirs(self) -> None:
        for d in (self.data_path, self.uploads_dir, self.index_dir, self.logs_dir, self.exports_dir):
            d.mkdir(parents=True, exist_ok=True)

    def validate(self) -> list[str]:
        """Return a list of human-readable problems (empty list = valid)."""
        p: list[str] = []
        if self.chunk_size_tokens < 32:
            p.append("chunk_size_tokens must be >= 32")
        if not 0 <= self.chunk_overlap_tokens < self.chunk_size_tokens:
            p.append("chunk_overlap_tokens must be >= 0 and smaller than chunk_size_tokens")
        if self.retrieval_strategy not in RETRIEVAL_STRATEGIES:
            p.append(f"retrieval_strategy must be one of {RETRIEVAL_STRATEGIES}")
        if self.llm_provider not in LLM_PROVIDERS:
            p.append(f"llm_provider must be one of {LLM_PROVIDERS}")
        if not 1 <= self.top_k <= 50:
            p.append("top_k must be between 1 and 50")
        if self.candidate_k < self.top_k:
            p.append("candidate_k must be >= top_k")
        if not 0 < self.max_file_size_mb <= 200:
            p.append("max_file_size_mb must be in (0, 200]")
        if not 0.0 <= self.temperature <= 2.0:
            p.append("temperature must be in [0, 2]")
        if self.device not in ("auto", "cpu", "cuda"):
            p.append("device must be auto, cpu or cuda")
        if self.embedding_batch_size < 1:
            p.append("embedding_batch_size must be >= 1")
        return p

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    def save(self) -> Path:
        """Persist settings atomically (no secrets exist in this object)."""
        self.ensure_dirs()
        tmp = self.settings_file.with_suffix(".tmp")
        tmp.write_text(json.dumps(self.to_dict(), indent=2), encoding="utf-8")
        tmp.replace(self.settings_file)
        return self.settings_file

    def updated(self, **changes: Any) -> "Settings":
        """Return a validated copy with changes applied (unknown keys rejected)."""
        valid = {f.name for f in fields(self)}
        unknown = set(changes) - valid
        if unknown:
            raise ValueError(f"Unknown setting(s): {sorted(unknown)}")
        data = self.to_dict()
        data.update(changes)
        new = Settings.from_dict(data)
        problems = new.validate()
        if problems:
            raise ValueError("; ".join(problems))
        return new

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "Settings":
        """Build Settings, ignoring unknown keys and coercing basic types."""
        kwargs: dict[str, Any] = {}
        for f in fields(cls):
            if f.name not in data:
                continue
            value = data[f.name]
            default = getattr(cls(), f.name)
            try:
                if isinstance(default, bool):
                    value = value if isinstance(value, bool) else str(value).lower() in ("1", "true", "yes")
                elif isinstance(default, int):
                    value = int(value)
                elif isinstance(default, float):
                    value = float(value)
                elif isinstance(default, str):
                    value = str(value)
            except (TypeError, ValueError):
                continue  # keep default for malformed values
            kwargs[f.name] = value
        return cls(**kwargs)

    @classmethod
    def load(cls, data_dir: Optional[str] = None) -> "Settings":
        """Load persisted settings, falling back to defaults if missing/corrupt."""
        base = cls() if data_dir is None else cls(data_dir=data_dir)
        if base.settings_file.exists():
            try:
                loaded = cls.from_dict(json.loads(base.settings_file.read_text(encoding="utf-8")))
                loaded.data_dir = base.data_dir
                if not loaded.validate():
                    return loaded
            except (json.JSONDecodeError, OSError):
                pass
        return base


class SecretStore:
    """In-memory, per-process secret holder. Never persisted, never logged."""

    def __init__(self) -> None:
        self._secrets: dict[str, str] = {}
        self._lock = threading.Lock()

    def set(self, provider: str, value: str) -> None:
        value = (value or "").strip()
        with self._lock:
            if value:
                self._secrets[provider] = value
            else:
                self._secrets.pop(provider, None)

    def get(self, provider: str) -> Optional[str]:
        with self._lock:
            if provider in self._secrets:
                return self._secrets[provider]
        env = SECRET_ENV_VARS.get(provider)
        return os.environ.get(env) if env else None

    def has(self, provider: str) -> bool:
        return bool(self.get(provider))

    def masked(self, provider: str) -> str:
        v = self.get(provider)
        return "not set" if not v else f"set (…{v[-4:]})" if len(v) > 8 else "set"

    def clear(self) -> None:
        with self._lock:
            self._secrets.clear()

