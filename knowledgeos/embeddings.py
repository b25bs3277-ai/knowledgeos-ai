"""Embedding abstraction.

* SentenceTransformerEmbedder — the real semantic model (default bge-small-en-v1.5).
* HashEmbedder — deterministic feature-hashing vectors ("hash://256"). It needs no
  download and is used by tests and as an explicit low-resource option. It is a
  LEXICAL approximation, not semantic; the UI labels it as such. It is never
  substituted silently for the real model.

Models are loaded once per process and cached; queries never trigger re-downloads.
"""
from __future__ import annotations

import hashlib
import re
import threading
from typing import Callable, Optional, Protocol

import numpy as np

from .exceptions import EmbeddingError
from .logging_config import get_logger, log_event

log = get_logger("embeddings")
ProgressCB = Optional[Callable[[int, int], None]]  # (done, total)


class Embedder(Protocol):
    model_name: str

    @property
    def dim(self) -> int: ...

    def embed_documents(self, texts: list[str], progress: ProgressCB = None) -> np.ndarray: ...

    def embed_query(self, text: str) -> np.ndarray: ...


def validate_embeddings(arr: np.ndarray, expected_rows: int, expected_dim: int) -> np.ndarray:
    if arr.ndim != 2 or arr.shape != (expected_rows, expected_dim):
        raise EmbeddingError(f"Bad embedding shape {arr.shape}, expected ({expected_rows}, {expected_dim})",
                             user_message="Embedding model returned vectors of an unexpected shape.")
    if not np.all(np.isfinite(arr)):
        raise EmbeddingError("Non-finite values in embeddings",
                             user_message="Embedding model produced invalid (NaN/inf) values.")
    return arr.astype(np.float32, copy=False)


def _l2_normalize(arr: np.ndarray) -> np.ndarray:
    norms = np.linalg.norm(arr, axis=1, keepdims=True)
    norms[norms == 0] = 1.0
    return (arr / norms).astype(np.float32)


def resolve_device(device: str) -> str:
    if device in ("cpu", "cuda"):
        if device == "cuda":
            try:
                import torch
                if not torch.cuda.is_available():
                    return "cpu"
            except ImportError:
                return "cpu"
        return device
    try:
        import torch
        return "cuda" if torch.cuda.is_available() else "cpu"
    except ImportError:
        return "cpu"


class HashEmbedder:
    _TOKEN = re.compile(r"[a-z0-9]+")

    def __init__(self, dim: int = 256) -> None:
        self.model_name = f"hash://{dim}"
        self._dim = dim

    @property
    def dim(self) -> int:
        return self._dim

    def _vec(self, text: str) -> np.ndarray:
        v = np.zeros(self._dim, dtype=np.float32)
        toks = self._TOKEN.findall(text.lower())
        feats = toks + [f"{a}_{b}" for a, b in zip(toks, toks[1:])]
        for f in feats:
            h = int.from_bytes(hashlib.blake2b(f.encode(), digest_size=8).digest(), "little")
            v[h % self._dim] += 1.0 if (h >> 63) & 1 else -1.0
        return v

    def embed_documents(self, texts: list[str], progress: ProgressCB = None) -> np.ndarray:
        if not texts:
            return np.zeros((0, self._dim), dtype=np.float32)
        out = _l2_normalize(np.stack([self._vec(t) for t in texts]))
        if progress:
            progress(len(texts), len(texts))
        return validate_embeddings(out, len(texts), self._dim)

    def embed_query(self, text: str) -> np.ndarray:
        return self.embed_documents([text])[0]


class SentenceTransformerEmbedder:
    def __init__(self, model_name: str, device: str = "auto", query_prefix: str = "",
                 batch_size: int = 32) -> None:
        self.model_name = model_name
        self.device = resolve_device(device)
        self.query_prefix = query_prefix
        self.batch_size = max(1, batch_size)
        self._model = None
        self._dim: Optional[int] = None
        self._lock = threading.Lock()

    def _load(self):
        if self._model is not None:
            return self._model
        with self._lock:
            if self._model is None:
                try:
                    from sentence_transformers import SentenceTransformer
                except ImportError as e:
                    raise EmbeddingError(str(e), user_message="sentence-transformers is not installed.") from e
                log_event(log, "loading embedding model", model=self.model_name, device=self.device)
                try:
                    model = SentenceTransformer(self.model_name, device=self.device)
                except Exception as e:
                    raise EmbeddingError(
                        f"Model load failed: {type(e).__name__}: {e}",
                        user_message=(f"Could not load embedding model '{self.model_name}'. Check the "
                                      "model name and internet access (first use downloads it).")) from e
                getter = getattr(model, "get_embedding_dimension", None) or model.get_sentence_embedding_dimension
                self._dim = int(getter())
                self._model = model
        return self._model

    @property
    def dim(self) -> int:
        self._load()
        assert self._dim is not None
        return self._dim

    def _encode(self, texts: list[str], batch_size: int) -> np.ndarray:
        return self._load().encode(texts, batch_size=batch_size, convert_to_numpy=True,
                                   normalize_embeddings=True, show_progress_bar=False)

    def embed_documents(self, texts: list[str], progress: ProgressCB = None) -> np.ndarray:
        if not texts:
            return np.zeros((0, self.dim), dtype=np.float32)
        model_dim = self.dim
        parts: list[np.ndarray] = []
        bs = self.batch_size
        i = 0
        while i < len(texts):
            batch = texts[i:i + bs]
            try:
                parts.append(self._encode(batch, bs))
            except RuntimeError as e:  # CUDA/CPU OOM → halve batch and retry
                if "out of memory" in str(e).lower() and bs > 1:
                    bs = max(1, bs // 2)
                    log_event(log, "OOM during embedding; reducing batch size", 30, new_batch_size=bs)
                    try:
                        import torch
                        torch.cuda.empty_cache()
                    except Exception:
                        pass
                    continue
                raise EmbeddingError(str(e), user_message="Embedding failed (see logs).") from e
            i += len(batch)
            if progress:
                progress(i, len(texts))
        return validate_embeddings(np.vstack(parts), len(texts), model_dim)

    def embed_query(self, text: str) -> np.ndarray:
        vec = self._encode([self.query_prefix + text], 1)
        return validate_embeddings(vec, 1, self.dim)[0]


_CACHE: dict[tuple, Embedder] = {}
_CACHE_LOCK = threading.Lock()


def get_embedder(model_name: str, device: str = "auto", query_prefix: str = "",
                 batch_size: int = 32) -> Embedder:
    """Return a cached embedder; only one real model is kept in memory at a time."""
    key = (model_name, resolve_device(device), query_prefix)
    with _CACHE_LOCK:
        if key in _CACHE:
            emb = _CACHE[key]
            if isinstance(emb, SentenceTransformerEmbedder):
                emb.batch_size = max(1, batch_size)
            return emb
        if model_name.startswith("hash://"):
            emb: Embedder = HashEmbedder(int(model_name.split("://", 1)[1] or 256))
        else:
            for k in [k for k, v in _CACHE.items() if isinstance(v, SentenceTransformerEmbedder)]:
                del _CACHE[k]  # free previous large model before loading another
            emb = SentenceTransformerEmbedder(model_name, device, query_prefix, batch_size)
        _CACHE[key] = emb
        return emb


EMBEDDING_TRADEOFFS = """\
| Model | Dim | Download | Notes |
|---|---|---|---|
| BAAI/bge-small-en-v1.5 (default) | 384 | ~130 MB | Strong English retrieval for its size; fast on CPU |
| sentence-transformers/all-MiniLM-L6-v2 | 384 | ~90 MB | Fastest; slightly weaker retrieval |
| BAAI/bge-base-en-v1.5 | 768 | ~440 MB | Better quality; ~3x slower, 2x index storage |
| hash://256 | 256 | none | Lexical approximation only; no semantic matching |

Index storage ≈ chunks × dim × 4 bytes (e.g. 10,000 chunks × 384 ≈ 15 MB).
Changing the model requires re-indexing all documents."""

