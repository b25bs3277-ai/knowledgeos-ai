"""Optional cross-encoder reranking. Lazy-loaded; failures are reported, never hidden."""
from __future__ import annotations

import threading
from typing import Optional

from .embeddings import resolve_device
from .logging_config import get_logger, log_event

log = get_logger("reranking")


class CrossEncoderReranker:
    def __init__(self, model_name: str, device: str = "auto") -> None:
        self.model_name = model_name
        self.device = resolve_device(device)
        self._model = None
        self.error: Optional[str] = None
        self._lock = threading.Lock()

    def available(self) -> bool:
        if self._model is not None:
            return True
        if self.error:
            return False
        with self._lock:
            if self._model is None and not self.error:
                try:
                    from sentence_transformers import CrossEncoder

                    log_event(log, "loading reranker", model=self.model_name, device=self.device)
                    self._model = CrossEncoder(self.model_name, device=self.device, max_length=512)
                except Exception as e:
                    self.error = f"{type(e).__name__}: {e}"[:300]
                    log_event(log, "reranker unavailable", 30, error=self.error)
        return self._model is not None

    def rerank(self, query: str, items: list[tuple[str, str]], batch_size: int = 16) -> list[tuple[str, float]]:
        """Score (chunk_id, text) pairs; returns ids sorted by descending relevance logit."""
        if not items:
            return []
        if not self.available():
            raise RuntimeError(f"Reranker unavailable: {self.error}")
        scores = self._model.predict([(query, t) for _, t in items], batch_size=batch_size,
                                     show_progress_bar=False)
        return sorted(((cid, float(s)) for (cid, _), s in zip(items, scores)), key=lambda x: -x[1])


_RERANKERS: dict[tuple[str, str], CrossEncoderReranker] = {}


def get_reranker(model_name: str, device: str = "auto") -> CrossEncoderReranker:
    key = (model_name, resolve_device(device))
    if key not in _RERANKERS:
        _RERANKERS.clear()  # keep at most one cross-encoder in memory
        _RERANKERS[key] = CrossEncoderReranker(model_name, device)
    return _RERANKERS[key]

