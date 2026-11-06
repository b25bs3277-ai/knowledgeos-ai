from __future__ import annotations

from pathlib import Path

import pytest

from knowledgeos.chunking import TokenCounter, chunk_units, split_text
from knowledgeos.document_loader import extract, make_doc_id
from knowledgeos.exceptions import (EmptyDocumentError, ExtractionError, FileTooLargeError, SecurityError,
                                    UnsupportedFileTypeError)
from knowledgeos.schemas import PageText
from knowledgeos.security import ensure_within, sanitize_filename, sha256_bytes, validate_upload


@pytest.mark.parametrize("ext,needle", [(".pdf", "labeled examples"), (".txt", "Gradient descent"),
                                        (".md", "chain rule"), (".docx", "actual positives"),
                                        (".csv", "Asha"), (".xlsx", "Random Forest")])
def test_extraction_per_format(settings, fixture_files, ext, needle):
    res = extract(fixture_files[ext], ext, settings)
    assert any(needle in u.text for u in res.units)


def test_location_metadata_preserved(settings, fixture_files):
    assert [u.page for u in extract(fixture_files[".pdf"], ".pdf", settings).units] == [1, 2, 3]
    xl = extract(fixture_files[".xlsx"], ".xlsx", settings)
    assert {u.sheet for u in xl.units} == {"Models", "Datasets"}
    assert any("Model: Random Forest; Type: Ensemble; Accuracy: 0.91" in u.text for u in xl.units)
    md = extract(fixture_files[".md"], ".md", settings)
    assert "Neural Networks > Backpropagation" in {u.section for u in md.units}


def test_chunk_metadata_and_stable_ids(settings, fixture_files):
    data = fixture_files[".pdf"].read_bytes()
    did = make_doc_id(sha256_bytes(data))
    assert did == make_doc_id(sha256_bytes(data)) and did.startswith("doc_")
    units = extract(fixture_files[".pdf"], ".pdf", settings).units
    a = chunk_units(did, "ml.pdf", units, settings, TokenCounter(None))
    b = chunk_units(did, "ml.pdf", units, settings, TokenCounter(None))
    assert [c.chunk_id for c in a] == [c.chunk_id for c in b]
    assert all(c.doc_id == did and c.filename == "ml.pdf" and c.page for c in a)
    assert all(c.chunk_id.startswith(did + ":") for c in a)


def test_chunk_size_and_overlap():
    counter = TokenCounter(None)
    text = "\n\n".join(f"Paragraph {i}. " + " ".join(f"Sentence {i}.{j} about topic {j}." for j in range(6))
                       for i in range(30))
    pieces = split_text(text, 64, 16, counter)
    assert len(pieces) > 5
    assert max(counter.count(p) for p in pieces) <= 64 + 16 + 8
    assert all(b.split("\n")[0] in a for a, b in zip(pieces, pieces[1:]))


def test_no_overlap_when_zero():
    counter = TokenCounter(None)
    text = "\n\n".join(f"Block {i} " + "word " * 40 for i in range(6))
    pieces = split_text(text, 64, 0, counter)
    assert not any(b.split("\n")[0] in a for a, b in zip(pieces, pieces[1:]))


def test_duplicate_and_empty_chunks_removed(settings):
    units = [PageText("This identical paragraph is repeated twice in the document."),
             PageText("This identical paragraph is repeated twice in the document."), PageText("   ")]
    assert len(chunk_units("doc_d", "d.txt", units, settings, TokenCounter(None))) == 1


def test_empty_document_rejected(settings, tmp_path):
    p = tmp_path / "empty.txt"
    p.write_text("  \n\n ", encoding="utf-8")
    with pytest.raises(EmptyDocumentError):
        extract(p, ".txt", settings)


def test_malformed_files(settings, tmp_path):
    bad_pdf = tmp_path / "bad.pdf"
    bad_pdf.write_bytes(b"%PDF-1.4\n garbage without objects")
    with pytest.raises((ExtractionError, EmptyDocumentError)):
        extract(bad_pdf, ".pdf", settings)
    bad_xlsx = tmp_path / "bad.xlsx"
    bad_xlsx.write_bytes(b"PK\x03\x04 not really a zip")
    with pytest.raises(ExtractionError):
        extract(bad_xlsx, ".xlsx", settings)


def test_upload_validation():
    with pytest.raises(UnsupportedFileTypeError):
        validate_upload("script.sh", b"echo hi", 10)
    with pytest.raises(UnsupportedFileTypeError):
        validate_upload("fake.pdf", b"not a pdf", 10)
    with pytest.raises(UnsupportedFileTypeError):
        validate_upload("bin.txt", b"abc\x00def", 10)
    with pytest.raises(FileTooLargeError):
        validate_upload("big.txt", b"a" * (2 * 1024 * 1024), 1)
    assert validate_upload("ok.md", b"# Title\ntext", 10) == ".md"


def test_path_traversal_protection(tmp_path):
    assert sanitize_filename("../../etc/passwd") == "passwd"
    assert sanitize_filename("..\\..\\win.ini") == "win.ini"
    with pytest.raises(SecurityError):
        ensure_within(tmp_path, tmp_path / ".." / "outside.txt")
    assert ensure_within(tmp_path, tmp_path / "a" / "b.txt") == (tmp_path / "a" / "b.txt").resolve()


def test_service_ingestion_rejects_and_dedupes(service, fixture_files):
    r1 = service.ingest_bytes("../../evil.txt", b"Some legitimate text content for indexing here.")
    assert r1.status == "indexed" and r1.filename == "evil.txt"
    stored = Path(service.store.get_document(r1.doc_id).stored_path)
    assert service.settings.uploads_dir.resolve() in stored.parents
    assert service.ingest_bytes("again.txt", b"Some legitimate text content for indexing here.").status == "duplicate"
    assert service.ingest_bytes("x.exe", b"MZ").status == "rejected"
    assert service.ingest_bytes("empty.txt", b"   ").status == "failed"   # stored, but marked failed with a reason
    failed = [d for d in service.list_documents() if d.status == "failed"]
    assert failed and "No usable text" in failed[0].error

