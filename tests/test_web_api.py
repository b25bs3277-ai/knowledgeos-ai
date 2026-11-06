from __future__ import annotations

import json

from knowledgeos.llm_providers import MockProvider
from knowledgeos.web.api import WebAPI, speakable

from .conftest import doc_id_of


def test_state_lists_documents(indexed):
    st = WebAPI(indexed).state()
    assert st["stats"]["ready_documents"] == 6 and {d["filename"] for d in st["docs"]} >= {"ml_basics.pdf", "models.xlsx"}


def test_ask_returns_clickable_sources_and_page_image(indexed):
    indexed.set_provider_override(MockProvider(lambda m: "Supervised learning uses labeled examples [1]."))
    api = WebAPI(indexed)
    r = api.ask("w_test", None, "What is supervised learning?")
    assert r["kind"] == "grounded" and r["markers"] == {"1": 0} and "**Sources**" not in r["answer"]
    assert r["sources"][0]["filename"] == "ml_basics.pdf" and r["sources"][0]["page"] == 1 and r["sources"][0]["cited"]
    assert "[1]" not in r["speak"] and r["speak"].startswith("Supervised")
    src = api.source(r["aid"], 0)
    assert src["page"] == 1 and src["home_page"] == 1
    if src["image"]:
        assert src["matched"] >= 1 and api.image(src["image"].rsplit("/", 1)[-1]).startswith(b"\x89PNG")
        assert api.source(r["aid"], 0, 2)["matched"] == 0
    assert "error" in api.source("nope", 0)
    r2 = api.ask("w_test", r["conv_id"], "and the other one?")      # follow-up in the same conversation
    assert r2["conv_id"] == r["conv_id"]


def test_ask_without_provider_is_evidence_only(indexed):
    r = WebAPI(indexed).ask("w_x", None, "What is supervised learning?")
    assert r["kind"] == "evidence" and r["sources"] and r["markers"]


def test_study_flashcards_and_terms(indexed):
    api = WebAPI(indexed)
    pdf = doc_id_of(indexed, "ml_basics.pdf")
    assert api.study("terms", pdf)["markdown"]
    indexed.set_provider_override(MockProvider(lambda m: json.dumps([{"front": "Q", "back": "A", "source": 1}])))
    r = api.study("flashcards", pdf, 3)
    assert r["items"][0]["front"] == "Q" and r["items"][0]["verified_source"]
    assert "error" in api.study("bogus", pdf) and "error" in api.study("summary", "")


def test_settings_save_and_masking(indexed):
    api = WebAPI(indexed)
    s = api.save_settings("gemini", "gemini-test-model", "AIzaSyTESTKEY1234567890abcdefgh")
    assert s["provider"] == "gemini" and s["gemini_model"] == "gemini-test-model"
    assert "AIzaSyTEST" not in json.dumps(s) and s["keys"]["gemini"].startswith("set")
    assert api.save_settings("not-a-provider")["provider"] == "none"


def test_upload_job_and_delete(service, fixture_files):
    import time
    api = WebAPI(service)
    jid = api.start_upload([("notes.txt", fixture_files[".txt"].read_bytes()), ("bad.exe", b"MZ")])["job"]
    for _ in range(100):
        j = api.job(jid)
        if j["done"]:
            break
        time.sleep(0.05)
    assert j["done"] and [r["status"] for r in j["reports"]] == ["indexed", "rejected"]
    doc = service.list_documents()[0].doc_id
    assert api.delete_doc(doc)["ok"] and not service.list_documents()
    assert "error" in api.start_upload([])


def test_transcribe_errors_are_reported(service):
    assert "error" in WebAPI(service).transcribe(b"")


def test_speakable_strips_markdown():
    assert speakable("**Bold** answer [1, 2].\n- item one\n\n**Sources**\n- [1] x") == "Bold answer. item one"
