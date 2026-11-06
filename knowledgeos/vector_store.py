"""Exact cosine-similarity vector index backed by NumPy, persisted atomically.

Why not FAISS/Chroma? At Colab scale (≤ ~100k chunks) an exact matrix product is
fast, has no version-compatibility risk, and is trivially recoverable: if files are
missing or corrupt, vectors are rebuilt from the chunks stored in SQLite.
"""
from __future__ import annotations

import json
import os
import threading
from pathlib import Path
from typing import Optional

import numpy as np

from .exceptions import IndexError_
from .logging_config import get_logger, log_event

log = get_logger("vector_store")


class NumpyVectorStore:
    VECTORS = "vectors.npy"
    IDS = "ids.json"
    MANIFEST = "manifest.json"

    def __init__(self, index_dir: Path) -> None:
        self.index_dir = Path(index_dir)
        self.index_dir.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()
        self.model_name: Optional[str] = None
        self.dim: Optional[int] = None
        self._ids: list[str] = []
        self._pos: dict[str, int] = {}
        self._mat = np.zeros((0, 0), dtype=np.float32)
        self.load_error: Optional[str] = None
        self.load()

    # ---------------- persistence ----------------
    def load(self) -> bool:
        """Load from disk. On corruption, start empty and record `load_error` (no crash)."""
        with self._lock:
            vp, ip, mp = (self.index_dir / n for n in (self.VECTORS, self.IDS, self.MANIFEST))
            if not vp.exists() and not ip.exists():
                self._reset_memory(None, None)
                return True
            try:
                manifest = json.loads(mp.read_text(encoding="utf-8"))
                ids = json.loads(ip.read_text(encoding="utf-8"))
                mat = np.load(vp, allow_pickle=False)
                if mat.ndim != 2 or mat.shape[0] != len(ids) or mat.shape[1] != manifest["dim"]:
                    raise ValueError(f"shape {mat.shape} vs {len(ids)} ids, dim {manifest['dim']}")
                if len(set(ids)) != len(ids):
                    raise ValueError("duplicate ids in index")
                self.model_name, self.dim = manifest["model"], int(manifest["dim"])
                self._ids = list(ids)
                self._pos = {cid: i for i, cid in enumerate(self._ids)}
                self._mat = mat.astype(np.float32, copy=False)
                self.load_error = None
                return True
            except Exception as e:
                self.load_error = f"{type(e).__name__}: {e}"
                log_event(log, "vector index unreadable; starting empty", 30, error=self.load_error)
                self._reset_memory(None, None)
                return False

    def save(self) -> None:
        with self._lock:
            tmp_v = self.index_dir / (self.VECTORS + ".tmp")
            with open(tmp_v, "wb") as f:
                np.save(f, self._mat if self._mat.size else np.zeros((0, self.dim or 0), np.float32))
            tmp_i = self.index_dir / (self.IDS + ".tmp")
            tmp_i.write_text(json.dumps(self._ids), encoding="utf-8")
            tmp_m = self.index_dir / (self.MANIFEST + ".tmp")
            tmp_m.write_text(json.dumps({"model": self.model_name, "dim": self.dim or 0,
                                         "count": len(self._ids), "format": 1}), encoding="utf-8")
            os.replace(tmp_v, self.index_dir / self.VECTORS)
            os.replace(tmp_i, self.index_dir / self.IDS)
            os.replace(tmp_m, self.index_dir / self.MANIFEST)

    def _reset_memory(self, model: Optional[str], dim: Optional[int]) -> None:
        self.model_name, self.dim = model, dim
        self._ids, self._pos = [], {}
        self._mat = np.zeros((0, dim or 0), dtype=np.float32)

    def clear(self, model_name: Optional[str] = None, dim: Optional[int] = None) -> None:
        with self._lock:
            self._reset_memory(model_name, dim)
            self.save()

    # ---------------- mutation ----------------
    def add(self, chunk_ids: list[str], vectors: np.ndarray, model_name: str) -> None:
        """Insert or replace vectors. Dimension/model must match the existing index."""
        if len(chunk_ids) != len(vectors):
            raise IndexError_("ids/vectors length mismatch")
        if len(set(chunk_ids)) != len(chunk_ids):
            raise IndexError_("duplicate chunk ids in batch")
        if not len(chunk_ids):
            return
        vectors = np.asarray(vectors, dtype=np.float32)
        with self._lock:
            if self.dim is None or not self._ids:
                if self.dim not in (None, vectors.shape[1]) or (self.model_name and self.model_name != model_name):
                    self._reset_memory(model_name, vectors.shape[1])
                self.model_name, self.dim = model_name, int(vectors.shape[1])
                if self._mat.shape[1] != self.dim:
                    self._mat = np.zeros((0, self.dim), dtype=np.float32)
            if vectors.shape[1] != self.dim or model_name != self.model_name:
                raise IndexError_(
                    f"Index built with {self.model_name} (dim {self.dim}); got {model_name} (dim {vectors.shape[1]})",
                    user_message="Embedding model changed since indexing. Re-index all documents.")
            existing = [i for i, c in enumerate(chunk_ids) if c in self._pos]
            for i in existing:
                self._mat[self._pos[chunk_ids[i]]] = vectors[i]
            new = [i for i, c in enumerate(chunk_ids) if c not in self._pos]
            if new:
                start = len(self._ids)
                self._mat = np.vstack([self._mat, vectors[new]])
                for j, i in enumerate(new):
                    self._ids.append(chunk_ids[i])
                    self._pos[chunk_ids[i]] = start + j

    def delete(self, chunk_ids: list[str]) -> int:
        with self._lock:
            drop = {c for c in chunk_ids if c in self._pos}
            if not drop:
                return 0
            keep = [i for i, c in enumerate(self._ids) if c not in drop]
            self._mat = self._mat[keep]
            self._ids = [self._ids[i] for i in keep]
            self._pos = {c: i for i, c in enumerate(self._ids)}
            return len(drop)

    # ---------------- query ----------------
    def search(self, query_vec: np.ndarray, k: int, allowed_ids: Optional[set[str]] = None,
               min_score: Optional[float] = None) -> list[tuple[str, float]]:
        with self._lock:
            if not self._ids:
                return []
            q = np.asarray(query_vec, dtype=np.float32).reshape(-1)
            if q.shape[0] != self.dim:
                raise IndexError_(f"Query dim {q.shape[0]} != index dim {self.dim}",
                                  user_message="Query embedding does not match the index. Re-index documents.")
            scores = self._mat @ q
            if allowed_ids is not None:
                mask = np.fromiter((c in allowed_ids for c in self._ids), dtype=bool, count=len(self._ids))
                scores = np.where(mask, scores, -np.inf)
            k = min(k, len(self._ids))
            idx = np.argpartition(-scores, k - 1)[:k]
            idx = idx[np.argsort(-scores[idx])]
            out = [(self._ids[i], float(scores[i])) for i in idx if np.isfinite(scores[i])]
            if min_score is not None:
                out = [(c, s) for c, s in out if s >= min_score]
            return out

    def get_vectors(self, chunk_ids: list[str]) -> dict[str, np.ndarray]:
        with self._lock:
            return {c: self._mat[self._pos[c]].copy() for c in chunk_ids if c in self._pos}

    def ids(self) -> set[str]:
        with self._lock:
            return set(self._ids)

    def __len__(self) -> int:
        return len(self._ids)

    def consistency(self, expected_ids: set[str]) -> dict:
        have = self.ids()
        return {"vectors": len(have), "expected": len(expected_ids),
                "missing": len(expected_ids - have), "orphaned": len(have - expected_ids),
                "model": self.model_name, "dim": self.dim, "load_error": self.load_error,
                "healthy": expected_ids == have and self.load_error is None}

