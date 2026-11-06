"""Shared fixtures. Tests use the hash embedder and mock LLMs, so they need no downloads,
no GPU and no API keys. They check application logic, not embedding-model quality."""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from knowledgeos.config import SecretStore, Settings  # noqa: E402
from knowledgeos.services import KnowledgeService  # noqa: E402
from tests.fixture_factory import write_all  # noqa: E402


@pytest.fixture
def settings(tmp_path) -> Settings:
    return Settings(data_dir=str(tmp_path / "data"), embedding_model="hash://256", min_dense_score=0.05)


@pytest.fixture
def service(settings):
    svc = KnowledgeService(settings, SecretStore())
    yield svc
    svc.close()


@pytest.fixture
def fixture_files(tmp_path) -> dict:
    return write_all(tmp_path / "fixtures")


@pytest.fixture
def indexed(service, fixture_files):
    reports = service.ingest_paths([str(p) for p in fixture_files.values()])
    assert all(r.status == "indexed" for r in reports), [r.message for r in reports]
    return service


def doc_id_of(service, filename: str) -> str:
    return next(d.doc_id for d in service.list_documents() if d.filename == filename)

