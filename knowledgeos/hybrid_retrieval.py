"""Retrieval engine: dense, keyword (BM25), hybrid (RRF) and hybrid + rerank.

Score handling: cosine similarities and BM25 scores are NOT comparable, so hybrid
mode fuses by RANK using Reciprocal Rank Fusion: score(d) = Σ 1 / (k + rank_i(d)).
Relevance floors are applied per component BEFORE fusion (dense: cosine ≥
min_dense_score; keyword: must contain a query term), so fusion never promotes a
chunk that no component considered relevant.
"""
from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Callable, Optional

from .config import RETRIEVAL_STRATEGIES, Settings
from .embeddings import Embedder
from .exceptions import RetrievalError
from .keyword_search import BM25Index
from .logging_config import get_logger, log_event
from .reranking import CrossEncoderReranker
from .schemas import Chunk, RetrievalFilters, RetrievedChunk
from .storage import MetadataStore
from .vector_store import NumpyVectorStore

log = get_logger("retrieval")


def reciprocal_rank_fusion(ranked_lists: list[list[str]], k: int = 60) -> list[tuple[str, float]]:
    scores: dict[str, float] = {}
    for lst in ranked_lists:
        for rank, cid in enumerate(lst, start=1):
            scores[cid] = scores.get(cid, 0.0) + 1.0 / (k + rank)
    return sorted(scores.items(), key=lambda x: (-x[1], x[0]))


@dataclass
class RetrievalOutcome:
    results: list[RetrievedChunk]
    strategy_requested: str
    strategy_used: str
    queries: list[str]
    timings_ms: dict[str, float] = field(default_factory=dict)
    warnings: list[str] = field(default_factory=list)
    candidates_considered: int = 0


class Retriever:
    def __init__(self, settings: Settings, store: MetadataStore, vectors: NumpyVectorStore,
                 bm25: BM25Index, embedder_fn: Callable[[], Embedder],
                 reranker_fn: Callable[[], CrossEncoderReranker]) -> None:
        self.settings = settings
        self.store = store
        self.vectors = vectors
        self.bm25 = bm25
        self._embedder_fn = embedder_fn
        self._reranker_fn = reranker_fn

    # ---------------- component searches ----------------
    def _dense(self, query: str, k: int, allowed: Optional[set[str]], warnings: list[str]) -> list[tuple[str, float]]:
        if len(self.vectors) == 0:
            return []
        emb = self._embedder_fn()
        if self.vectors.model_name and self.vectors.model_name != emb.model_name:
            warnings.append(f"Index was built with '{self.vectors.model_name}' but the current model is "
                            f"'{emb.model_name}'. Dense search skipped — re-index documents.")
            return []
        qv = emb.embed_query(query)
        return self.vectors.search(qv, k, allowed, min_score=self.settings.min_dense_score)

    def _keyword(self, query: str, k: int, allowed: Optional[set[str]]) -> list[tuple[str, float]]:
        return self.bm25.search(query, k, allowed)

    # ---------------- main entry ----------------
    def retrieve(self, query: str, strategy: Optional[str] = None, top_k: Optional[int] = None,
                 filters: Optional[RetrievalFilters] = None,
                 extra_queries: Optional[list[str]] = None) -> RetrievalOutcome:
        s = self.settings
        strategy = strategy or s.retrieval_strategy
        if strategy not in RETRIEVAL_STRATEGIES:
            raise RetrievalError(f"Unknown strategy {strategy}", user_message=f"Unknown retrieval strategy '{strategy}'.")
        query = (query or "").strip()
        if not query:
            raise RetrievalError("Empty query", user_message="Please enter a question.")
        top_k = top_k or s.top_k
        cand_k = max(s.candidate_k, top_k)
        queries = [query] + [q for q in (extra_queries or []) if q and q.strip() and q.strip() != query]
        warnings: list[str] = []
        timings: dict[str, float] = {}

        allowed: Optional[set[str]] = None
        if filters and not filters.is_empty():
            allowed = self.store.chunk_ids_matching(filters)
            if not allowed:
                return RetrievalOutcome([], strategy, strategy, queries, timings,
                                        ["No indexed chunks match the selected filters."])

        dense_lists: list[list[tuple[str, float]]] = []
        kw_lists: list[list[tuple[str, float]]] = []
        if strategy in ("dense", "hybrid", "hybrid_rerank"):
            t = time.perf_counter()
            dense_lists = [self._dense(q, cand_k, allowed, warnings) for q in queries]
            timings["dense_ms"] = round((time.perf_counter() - t) * 1000, 1)
        if strategy in ("keyword", "hybrid", "hybrid_rerank"):
            t = time.perf_counter()
            kw_lists = [self._keyword(q, cand_k, allowed) for q in queries]
            timings["keyword_ms"] = round((time.perf_counter() - t) * 1000, 1)

        comp_scores: dict[str, dict[str, float]] = {}
        comp_ranks: dict[str, dict[str, int]] = {}

        def note(name: str, lists: list[list[tuple[str, float]]]) -> None:
            for lst in lists:
                for rank, (cid, sc) in enumerate(lst, start=1):
                    cs, cr = comp_scores.setdefault(cid, {}), comp_ranks.setdefault(cid, {})
                    if sc > cs.get(name, float("-inf")):
                        cs[name] = round(sc, 4)
                    cr[name] = min(rank, cr.get(name, rank))

        note("dense", dense_lists)
        note("keyword", kw_lists)

        used = strategy
        if strategy == "dense" or strategy == "keyword":
            lists = dense_lists if strategy == "dense" else kw_lists
            if len(lists) == 1:
                fused = lists[0]
            else:  # multi-query: fuse the per-query lists by rank
                fused = reciprocal_rank_fusion([[c for c, _ in l] for l in lists], s.rrf_k)
        else:
            fused = reciprocal_rank_fusion([[c for c, _ in l] for l in dense_lists + kw_lists], s.rrf_k)
        candidates = [c for c, _ in fused]
        score_of = dict(fused)

        if strategy == "hybrid_rerank" and candidates:
            reranker = self._reranker_fn()
            if reranker.available():
                t = time.perf_counter()
                pool = candidates[:cand_k]
                chunk_map = self.store.get_chunks(pool)
                reranked = reranker.rerank(query, [(c, chunk_map[c].text) for c in pool if c in chunk_map])
                timings["rerank_ms"] = round((time.perf_counter() - t) * 1000, 1)
                for cid, sc in reranked:
                    comp_scores.setdefault(cid, {})["rerank"] = round(sc, 4)
                reranked = [(c, sc) for c, sc in reranked if sc >= s.min_rerank_score]
                candidates = [c for c, _ in reranked]
                score_of = dict(reranked)
            else:
                used = "hybrid"
                warnings.append(f"Reranker unavailable ({reranker.error}); used hybrid RRF ranking instead.")

        chunk_map = self.store.get_chunks(candidates[: cand_k * 2])
        results: list[RetrievedChunk] = []
        seen_hash: set[str] = set()
        for cid in candidates:
            ch: Optional[Chunk] = chunk_map.get(cid)
            if ch is None:
                warnings.append("Index contained a chunk missing from the database; run Diagnostics → Repair.")
                continue
            if ch.content_hash in seen_hash:  # identical passage from another document/copy
                continue
            seen_hash.add(ch.content_hash)
            results.append(RetrievedChunk(chunk=ch, score=round(score_of[cid], 6), rank=len(results) + 1,
                                          method=used, component_scores=comp_scores.get(cid, {}),
                                          component_ranks=comp_ranks.get(cid, {})))
            if len(results) >= top_k:
                break
        timings["retrieval_total_ms"] = round(sum(timings.values()), 1)
        log_event(log, "retrieved", strategy=used, queries=len(queries), candidates=len(candidates),
                  returned=len(results), **timings)
        return RetrievalOutcome(results, strategy, used, queries, timings,
                                list(dict.fromkeys(warnings)), len(candidates))

