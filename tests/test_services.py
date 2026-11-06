from __future__ import annotations

import json

import pytest

from knowledgeos.conversations import new_session_id
from knowledgeos.diagnostics import report_json
from knowledgeos.evaluation import retrieval_metrics, sample_cases, token_f1
from knowledgeos.exceptions import NotFoundError
from knowledgeos.llm_providers import MockProvider
from knowledgeos.schemas import Chunk, EvalCase, RetrievedChunk
from knowledgeos.ui import controllers as C
from knowledgeos.ui import workspace_controllers as W

from .conftest import doc_id_of


def test_end_to_end_answer_with_citation(indexed):
    indexed.set_provider_override(MockProvider(lambda m: "Supervised learning uses labeled examples [1]."))
    res, cid = indexed.ask(new_session_id(), None, "What is supervised learning?")
    assert res.grounded and res.citations[0].verified and res.citations[0].filename == "ml_basics.pdf"
    assert res.timings_ms["end_to_end_ms"] > 0


def test_no_documents_is_general_not_retrieval(service):
    res, _ = service.ask(new_session_id(), None, "What is supervised learning?")
    assert res.question_type == "general" and not res.retrieved


def test_conversation_isolation_and_management(indexed):
    alice, bob = new_session_id(), new_session_id()
    _, cid = indexed.ask(alice, None, "What is supervised learning?")
    assert indexed.conversations.list(bob) == []
    with pytest.raises(NotFoundError):
        indexed.conversations.get(bob, cid)
    indexed.conversations.rename(alice, cid, "Renamed")
    assert indexed.conversations.list(alice)[0]["title"] == "Renamed"
    assert json.loads(indexed.conversations.export_json(alice, cid))["title"] == "Renamed"
    assert indexed.conversations.history(alice, "c_missing") == []          # graceful
    indexed.conversations.delete(alice, cid)
    assert indexed.conversations.list(alice) == []


def test_research_tools(indexed):
    pdf = doc_id_of(indexed, "ml_basics.pdf")
    assert indexed.research.key_terms(pdf).structured
    assert indexed.research.extract_evidence("rewards environment").citations
    assert "Generation unavailable" in indexed.research.study_notes(pdf).markdown
    indexed.set_provider_override(MockProvider(lambda m: json.dumps(
        [{"question": "Q?", "options": ["a", "b", "c", "d"], "answer_index": 1, "explanation": "e", "source": 1},
         {"question": "bad", "options": ["a"], "answer_index": 5}])))
    quiz = indexed.research.quiz(pdf, 2)
    assert len(quiz.structured) == 1 and quiz.structured[0]["verified_source"]


def test_retrieval_metrics_arithmetic():
    mk = lambda cid, doc, text="t": RetrievedChunk(Chunk(cid, doc, "f", text, 0), 1.0, 1, "x")
    m = retrieval_metrics([mk("a", "d1"), mk("b", "d1"), mk("c", "d2")], EvalCase("c", "q", relevant_chunk_ids=["b", "z"]), 3)
    assert m == {"precision_at_k": 0.3333, "recall_at_k": 0.5, "mrr": 0.5, "hit_at_k": 1.0}
    m2 = retrieval_metrics([mk("a", "d1")], EvalCase("c", "q", relevant_doc_ids=["d2"]), 1)
    assert m2["mrr"] == 0.0 and m2["recall_at_k"] == 0.0
    assert retrieval_metrics([], EvalCase("c", "q"), 3)["mrr"] is None
    assert token_f1("labeled examples", "") is None and token_f1("cats", "dogs") == 0.0


def test_evaluation_lab_flow(indexed):
    state = [c.__dict__ for c in sample_cases()]
    summ, rows, comp, runs, res, _ = W.run_retrieval(indexed, state, ["keyword", "hybrid"], 3, [])
    assert len(summ) == 2 and len(rows) == 10 and set(comp["run"]) == {1}


def test_diagnostics_contains_no_secrets_or_text(indexed):
    indexed.set_api_key("gemini", "AIzaSyVERYSECRET1234567890abcdef")
    rep = report_json(indexed)
    assert "VERYSECRET" not in rep and "labeled examples" not in rep


def test_ui_controllers_reflect_real_state(service, fixture_files):
    assert "No documents yet" in C.overview(service)[1]
    rows, msg = C.upload(service, [str(fixture_files[".pdf"])], "default")
    assert rows[0][1] == "indexed" and "1 document(s) ready" in C.overview(service)[1]
    assert "confirmation" in C.delete_document(service, doc_id_of(service, "ml_basics.pdf"), False)


def test_app_builds_when_gradio_available(indexed):
    pytest.importorskip("gradio")
    from knowledgeos.app import create_app
    demo, svc = create_app(indexed)
    assert svc is indexed and demo is not None

