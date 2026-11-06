from __future__ import annotations

import numpy as np
import pytest

from knowledgeos.embeddings import HashEmbedder, validate_embeddings
from knowledgeos.exceptions import EmbeddingError, IndexError_
from knowledgeos.hybrid_retrieval import reciprocal_rank_fusion
from knowledgeos.keyword_search import BM25Index, tokenize
from knowledgeos.schemas import RetrievalFilters
from knowledgeos.vector_store import NumpyVectorStore

from .conftest import doc_id_of


def test_embedding_dimension_consistency():
    emb = HashEmbedder(128)
    docs = emb.embed_documents(["alpha beta", "gamma delta", ""])
    q = emb.embed_query("alpha")
    assert docs.shape == (3, 128) and q.shape == (128,) and docs.dtype == np.float32
    assert np.allclose(np.linalg.norm(docs[:2], axis=1), 1.0)
    with pytest.raises(EmbeddingError):
        validate_embeddings(np.zeros((2, 64), np.float32), 2, 128)
    with pytest.raises(EmbeddingError):
        validate_embeddings(np.full((1, 4), np.nan, np.float32), 1, 4)


def test_vector_insert_search_delete_persist(tmp_path):
    store = NumpyVectorStore(tmp_path / "idx")
    vecs = np.eye(4, dtype=np.float32)
    store.add(["a", "b", "c", "d"], vecs, "m")
    assert store.search(vecs[2], 1)[0][0] == "c"
    assert {c for c, _ in store.search(vecs[2], 4, allowed_ids={"a", "b"})} == {"a", "b"}
    store.add(["c"], np.array([[0, 1, 0, 0]], np.float32), "m")  # replace, not duplicate
    assert len(store) == 4
    assert store.delete(["a", "zz"]) == 1 and "a" not in store.ids()
    store.save()
    reloaded = NumpyVectorStore(tmp_path / "idx")
    assert reloaded.ids() == {"b", "c", "d"}
    with pytest.raises(IndexError_):
        store.add(["e"], np.ones((1, 8), np.float32), "m")     # wrong dimension
    with pytest.raises(IndexError_):
        store.add(["e"], np.ones((1, 4), np.float32), "other")  # different model


def test_corrupt_index_recovers_empty(tmp_path):
    store = NumpyVectorStore(tmp_path / "idx")
    store.add(["a"], np.ones((1, 4), np.float32), "m")
    store.save()
    (tmp_path / "idx" / "vectors.npy").write_bytes(b"garbage")
    broken = NumpyVectorStore(tmp_path / "idx")
    assert len(broken) == 0 and broken.load_error


def test_bm25_only_scores_matching_chunks():
    bm = BM25Index()
    bm.build([("1", "random forest accuracy"), ("2", "neural networks"), ("3", "forest fires")])
    hits = bm.search("random forest", 10)
    assert hits[0][0] == "1" and {c for c, _ in hits} == {"1", "3"}
    assert bm.search("quantum", 10) == []
    assert [c for c, _ in bm.search("forest", 10, allowed_ids={"3"})] == ["3"]
    assert tokenize("The Models are running") == ["model", "running"]


def test_reciprocal_rank_fusion():
    fused = reciprocal_rank_fusion([["a", "b", "c"], ["b", "c", "a"]], k=60)
    assert fused[0][0] == "b"
    assert fused[0][1] == pytest.approx(1 / 62 + 1 / 61)


@pytest.mark.parametrize("strategy", ["dense", "keyword", "hybrid", "hybrid_rerank"])
def test_each_strategy_finds_the_right_page(indexed, strategy):
    out = indexed.search("What is supervised learning?", strategy, 3)
    top = out.results[0].chunk
    assert top.filename == "ml_basics.pdf" and top.page == 1
    if strategy == "hybrid_rerank" and out.strategy_used == "hybrid":
        assert any("Reranker unavailable" in w for w in out.warnings)  # honest fallback


def test_strategies_really_differ(indexed):
    kw = indexed.search("supervised learning", "keyword", 6)
    hy = indexed.search("supervised learning", "hybrid", 6)
    assert all("keyword" in r.component_scores and "dense" not in r.component_scores for r in kw.results)
    assert any("dense" in r.component_scores for r in hy.results)


def test_document_filter(indexed):
    xl = doc_id_of(indexed, "models.xlsx")
    out = indexed.search("learning accuracy model", "hybrid", 5, doc_ids=[xl])
    assert out.results and all(r.chunk.doc_id == xl for r in out.results)
    flt = indexed.store.chunk_ids_matching(RetrievalFilters(file_types=[".csv"]))
    assert flt and all(c.startswith(doc_id_of(indexed, "students.csv")) for c in flt)


def test_deletion_removes_searchable_chunks(indexed):
    pdf = doc_id_of(indexed, "ml_basics.pdf")
    with pytest.raises(Exception):
        indexed.delete_document(pdf)                       # confirmation required
    indexed.delete_document(pdf, confirm=True)
    for strategy in ("keyword", "dense", "hybrid"):
        assert not any(r.chunk.doc_id == pdf for r in indexed.search("supervised labeled", strategy, 10).results)
    assert indexed.index_health()["healthy"]


def test_repair_and_reindex(indexed):
    some = list(indexed.vectors.ids())[:2]
    indexed.vectors.delete(some)
    assert not indexed.index_health()["healthy"]
    assert "embedded 2" in indexed.repair_index()
    assert indexed.index_health()["healthy"]
    reports = indexed.reindex_all()
    assert all(r.status == "indexed" for r in reports) and indexed.index_health()["healthy"]

