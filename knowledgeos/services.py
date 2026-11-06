"""Application service layer: the single entry point the UI calls.

Owns the stores and indexes, serialises index mutations with a lock, and turns
lower-level exceptions into user-safe reports. The UI never touches storage directly.
"""
from __future__ import annotations

import shutil
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Iterator, Optional

from .chunking import chunk_units
from .config import LLM_PROVIDERS, SecretStore, Settings
from .conversations import ConversationStore
from .document_loader import extract, make_doc_id
from .embeddings import Embedder, get_embedder
from .exceptions import (ConfigurationError, KnowledgeOSError, NotFoundError, ValidationError,
                         error_category, safe_user_message)
from .hybrid_retrieval import RetrievalOutcome, Retriever
from .keyword_search import BM25Index
from .llm_providers import LLMProvider, build_provider
from .logging_config import get_logger, log_event, new_request_id, setup_logging
from .query_understanding import plan_query
from .reranking import CrossEncoderReranker, get_reranker
from .research_tools import ResearchTools
from .schemas import AnswerResult, ChatTurn, DocStatus, DocumentRecord, QuestionType, RetrievalFilters
from .security import ensure_within, sanitize_filename, sha256_bytes, validate_identifier, validate_upload
from .storage import MetadataStore
from .vector_store import NumpyVectorStore

log = get_logger("service")
Progress = Optional[Callable[[float, str], None]]  # (fraction 0–1, message)


@dataclass
class IngestReport:
    filename: str
    status: str                    # indexed | duplicate | rejected | failed
    message: str
    doc_id: Optional[str] = None
    chunks: int = 0
    warnings: list[str] = field(default_factory=list)
    duration_ms: float = 0.0


class KnowledgeService:
    def __init__(self, settings: Optional[Settings] = None, secrets: Optional[SecretStore] = None) -> None:
        self.settings = settings or Settings.load()
        self.settings.ensure_dirs()
        setup_logging(self.settings.logs_dir, self.settings.log_level)
        self.secrets = secrets or SecretStore()
        self.store = MetadataStore(self.settings.db_path)
        self.vectors = NumpyVectorStore(self.settings.index_dir)
        self.conversations = ConversationStore(self.settings.data_path / "conversations.sqlite3")
        self.bm25 = BM25Index()
        self._index_lock = threading.RLock()
        self._provider_override: Optional[LLMProvider] = None
        self._provider: LLMProvider = build_provider(self.settings, self.secrets)
        self.started_at = time.time()
        self._rebuild_bm25()
        self.research = ResearchTools(self.settings, self.store, lambda: self.retriever, lambda: self.provider)
        self._recover_interrupted()
        log_event(log, "service started", **self.store.counts(), vectors=len(self.vectors))

    # ---------------- component accessors ----------------
    @property
    def provider(self) -> LLMProvider:
        return self._provider_override or self._provider

    def set_provider_override(self, provider: Optional[LLMProvider]) -> None:
        """Testing / advanced use: force a specific provider instance."""
        self._provider_override = provider

    def embedder(self) -> Embedder:
        s = self.settings
        return get_embedder(s.embedding_model, s.device, s.embedding_query_prefix, s.embedding_batch_size)

    def reranker(self) -> CrossEncoderReranker:
        return get_reranker(self.settings.reranker_model, self.settings.device)

    @property
    def retriever(self) -> Retriever:
        return Retriever(self.settings, self.store, self.vectors, self.bm25, self.embedder, self.reranker)

    def _rebuild_bm25(self) -> None:
        self.bm25.build((c.chunk_id, c.text) for c in self.store.iter_all_chunks())

    def _recover_interrupted(self) -> None:
        """Documents stuck mid-ingestion (runtime crashed) are marked failed, never 'ready'."""
        for d in self.store.list_documents():
            if d.status in (DocStatus.EXTRACTING.value, DocStatus.INDEXING.value):
                d.status, d.error = DocStatus.FAILED.value, "Interrupted during processing; use Re-index."
                self.store.upsert_document(d)

    # ---------------- ingestion ----------------
    def ingest_bytes(self, filename: str, data: bytes, collection: str = "default",
                     progress: Progress = None) -> IngestReport:
        t0 = time.perf_counter()
        new_request_id()
        try:
            safe_name = sanitize_filename(filename)
            ext = validate_upload(safe_name, data, self.settings.max_file_size_mb)
        except KnowledgeOSError as e:
            return IngestReport(filename, "rejected", safe_user_message(e))
        file_hash = sha256_bytes(data)
        existing = self.store.find_by_hash(file_hash)
        if existing is not None:
            return IngestReport(safe_name, "duplicate",
                                f"Already in library as '{existing.filename}' ({existing.status}).",
                                doc_id=existing.doc_id, chunks=existing.chunk_count)
        doc_id = make_doc_id(file_hash)
        doc_dir = ensure_within(self.settings.uploads_dir, self.settings.uploads_dir / doc_id)
        doc_dir.mkdir(parents=True, exist_ok=True)
        stored = ensure_within(doc_dir, doc_dir / safe_name)
        stored.write_bytes(data)
        rec = DocumentRecord(doc_id=doc_id, filename=safe_name, file_hash=file_hash, file_type=ext,
                             size_bytes=len(data), stored_path=str(stored), collection=collection or "default")
        self.store.upsert_document(rec)
        report = self._process(rec, progress)
        report.duration_ms = round((time.perf_counter() - t0) * 1000, 1)
        return report

    def ingest_paths(self, paths: list[str], collection: str = "default",
                     progress: Progress = None) -> list[IngestReport]:
        """Ingest files from local paths (what Gradio's upload component provides)."""
        if len(paths) > self.settings.max_files_per_upload:
            return [IngestReport("(batch)", "rejected",
                                 f"Too many files ({len(paths)}); the limit is {self.settings.max_files_per_upload}.")]
        reports = []
        limit = self.settings.max_file_size_mb * 1024 * 1024
        for i, p in enumerate(paths):
            path = Path(p)
            name = path.name
            sub = (lambda f, m, i=i: progress((i + f) / len(paths), f"{name}: {m}")) if progress else None
            try:
                if path.stat().st_size > limit:
                    reports.append(IngestReport(name, "rejected",
                                                f"'{name}' exceeds the {self.settings.max_file_size_mb:g} MB limit."))
                    continue
                reports.append(self.ingest_bytes(name, path.read_bytes(), collection, sub))
            except OSError as e:
                reports.append(IngestReport(name, "failed", f"Could not read file ({type(e).__name__})."))
        if progress:
            progress(1.0, "Done")
        return reports

    def _process(self, rec: DocumentRecord, progress: Progress = None) -> IngestReport:
        """Extract → chunk → embed → index for one registered document."""
        def step(f: float, msg: str) -> None:
            if progress:
                progress(f, msg)

        with self._index_lock:
            try:
                emb = self.embedder()
                if len(self.vectors) and self.vectors.model_name not in (None, emb.model_name):
                    raise ConfigurationError(
                        "model mismatch",
                        user_message=(f"The index uses '{self.vectors.model_name}' but Settings select "
                                      f"'{emb.model_name}'. Run 'Re-index all' in Document Library first."))
                rec.status, rec.error = DocStatus.EXTRACTING.value, None
                self.store.upsert_document(rec)
                step(0.1, "extracting text")
                result = extract(Path(rec.stored_path), rec.file_type, self.settings)
                step(0.35, "chunking")
                chunks = chunk_units(rec.doc_id, rec.filename, result.units, self.settings,
                                     collection=rec.collection)
                if not chunks:
                    raise ValidationError("no chunks", user_message="No usable chunks were produced.")
                rec.status = DocStatus.INDEXING.value
                self.store.upsert_document(rec)
                ids = [c.chunk_id for c in chunks]
                cached = self.vectors.get_vectors(ids) if self.vectors.model_name == emb.model_name else {}
                todo = [c for c in chunks if c.chunk_id not in cached]
                step(0.45, f"embedding {len(todo)} chunk(s)" + (f", reusing {len(cached)}" if cached else ""))
                vecs = emb.embed_documents([c.text for c in todo],
                                           progress=lambda d, n: step(0.45 + 0.45 * d / max(n, 1), f"embedded {d}/{n}"))
                old_ids = set(self.store.chunk_ids_for_doc(rec.doc_id)) - set(ids)
                self.store.replace_chunks(rec.doc_id, chunks)
                self.vectors.delete(list(old_ids))
                if todo:
                    self.vectors.add([c.chunk_id for c in todo], vecs, emb.model_name)
                self.vectors.save()
                self._rebuild_bm25()
                rec.status, rec.indexed_at = DocStatus.READY.value, time.time()
                rec.chunk_count, rec.unit_count = len(chunks), len(result.units)
                rec.warnings, rec.quality = result.warnings, result.quality
                self.store.upsert_document(rec)
                self.store.add_activity("indexed", f"Indexed {rec.filename} ({len(chunks)} chunks)")
                step(1.0, "ready")
                log_event(log, "document indexed", doc_id=rec.doc_id, chunks=len(chunks))
                return IngestReport(rec.filename, "indexed", f"Indexed {len(chunks)} chunk(s).",
                                    rec.doc_id, len(chunks), result.warnings)
            except KnowledgeOSError as e:
                return self._fail(rec, safe_user_message(e), error_category(e))
            except MemoryError:
                return self._fail(rec, "Ran out of memory. Try a smaller file or a lower batch size.", "memory")
            except Exception as e:  # unexpected: log with traceback, show safe message
                log.exception("unexpected ingestion error")
                return self._fail(rec, safe_user_message(e), "unexpected")

    def _fail(self, rec: DocumentRecord, message: str, category: str) -> IngestReport:
        rec.status, rec.error = DocStatus.FAILED.value, message
        self.store.upsert_document(rec)
        self.store.add_activity("failed", f"{rec.filename}: {message}")
        log_event(log, "document failed", 40, doc_id=rec.doc_id, category=category)
        return IngestReport(rec.filename, "failed", message, rec.doc_id)

    # ---------------- document management ----------------
    def list_documents(self, search: str = "") -> list[DocumentRecord]:
        docs = self.store.list_documents()
        s = search.strip().lower()
        return [d for d in docs if s in d.filename.lower()] if s else docs

    def document_details(self, doc_id: str, preview_chunks: int = 5) -> dict[str, Any]:
        validate_identifier(doc_id, "document id")
        rec = self.store.get_document(doc_id)
        chunks = self.store.get_doc_chunks(doc_id)
        vec_ids = self.vectors.ids()
        return {"record": rec.to_dict(),
                "chunks_in_db": len(chunks),
                "chunks_with_vectors": sum(c.chunk_id in vec_ids for c in chunks),
                "preview": [{"chunk_id": c.chunk_id, "location": c.location_label(),
                             "text": c.text[:300]} for c in chunks[:preview_chunks]]}

    def get_chunk(self, chunk_id: str) -> dict[str, Any]:
        found = self.store.get_chunks([chunk_id])
        if chunk_id not in found:
            raise NotFoundError("chunk missing", user_message="That passage is no longer in the index.")
        return found[chunk_id].to_dict()

    def delete_document(self, doc_id: str, confirm: bool = False) -> str:
        if not confirm:
            raise ValidationError("not confirmed", user_message="Tick the confirmation box to delete.")
        validate_identifier(doc_id, "document id")
        with self._index_lock:
            rec = self.store.get_document(doc_id)
            ids = self.store.chunk_ids_for_doc(doc_id)
            self.vectors.delete(ids)
            self.vectors.save()
            self.store.delete_document(doc_id)
            self._rebuild_bm25()
            doc_dir = ensure_within(self.settings.uploads_dir, self.settings.uploads_dir / doc_id)
            if doc_dir.exists() and doc_dir != self.settings.uploads_dir.resolve():
                shutil.rmtree(doc_dir)
            self.store.add_activity("deleted", f"Deleted {rec.filename}")
        return f"Deleted '{rec.filename}' and its {len(ids)} searchable chunk(s)."

    def reindex_document(self, doc_id: str, progress: Progress = None) -> IngestReport:
        validate_identifier(doc_id, "document id")
        rec = self.store.get_document(doc_id)
        if not Path(rec.stored_path).exists():
            return self._fail(rec, "The original file is missing from storage; delete and re-upload it.", "missing_file")
        return self._process(rec, progress)

    def reindex_all(self, progress: Progress = None) -> list[IngestReport]:
        """Rebuild every vector with the currently selected embedding model."""
        docs = self.store.list_documents()
        with self._index_lock:
            emb = self.embedder()
            self.vectors.clear(emb.model_name, emb.dim)
            reports = []
            for i, d in enumerate(docs):
                sub = (lambda f, m, i=i, n=d.filename: progress((i + f) / len(docs), f"{n}: {m}")) if progress else None
                reports.append(self.reindex_document(d.doc_id, sub))
        self.store.add_activity("reindex", f"Re-indexed {len(docs)} document(s)")
        return reports


    # ---------------- index health ----------------
    def index_health(self) -> dict[str, Any]:
        db_ok, db_msg = self.store.integrity_ok()
        cons = self.vectors.consistency(self.store.all_chunk_ids())
        docs = self.store.list_documents()
        by_status: dict[str, int] = {}
        for d in docs:
            by_status[d.status] = by_status.get(d.status, 0) + 1
        model_ok = not cons["model"] or cons["model"] == self.settings.embedding_model
        return {"database_ok": db_ok, "database_check": db_msg, "vector_index": cons,
                "bm25_entries": len(self.bm25), "documents_by_status": by_status,
                "embedding_model_matches_settings": model_ok,
                "healthy": db_ok and cons["healthy"] and model_ok and len(self.bm25) == cons["expected"]}

    def repair_index(self, progress: Progress = None) -> str:
        """Remove orphan vectors and embed chunks that lack vectors (no re-extraction)."""
        with self._index_lock:
            emb = self.embedder()
            if len(self.vectors) and self.vectors.model_name != emb.model_name:
                return "Embedding model differs from the index; use 'Re-index all' instead of repair."
            expected = self.store.all_chunk_ids()
            have = self.vectors.ids()
            orphans = list(have - expected)
            removed = self.vectors.delete(orphans)
            missing = list(expected - have)
            chunks = self.store.get_chunks(missing)
            texts = [chunks[c].text for c in missing if c in chunks]
            ids = [c for c in missing if c in chunks]
            if ids:
                vecs = emb.embed_documents(texts, progress=(lambda d, n: progress(d / n, f"embedded {d}/{n}"))
                                           if progress else None)
                self.vectors.add(ids, vecs, emb.model_name)
            self.vectors.save()
            self._rebuild_bm25()
        msg = f"Repair complete: removed {removed} orphan vector(s), embedded {len(ids)} missing chunk(s)."
        self.store.add_activity("repair", msg)
        return msg

    # ---------------- questions & search ----------------
    def search(self, query: str, strategy: Optional[str] = None, top_k: Optional[int] = None,
               doc_ids: Optional[list[str]] = None) -> RetrievalOutcome:
        new_request_id()
        filters = RetrievalFilters(doc_ids=doc_ids) if doc_ids else None
        return self.retriever.retrieve(query, strategy, top_k, filters)

    def ask_stream(self, owner: str, conv_id: Optional[str], question: str,
                   doc_ids: Optional[list[str]] = None, strategy: Optional[str] = None
                   ) -> Iterator[tuple[str, Optional[AnswerResult], str]]:
        """Stream an answer. Yields (partial_text, final_result_or_None, conv_id)."""
        from .answer_generation import AnswerGenerator  # local import keeps module graph simple

        rid = new_request_id()
        question = (question or "").strip()
        if not question:
            raise ValidationError("empty", user_message="Please type a question.")
        if len(question) > 4000:
            raise ValidationError("too long", user_message="Questions are limited to 4,000 characters.")
        if not conv_id:
            conv_id = self.conversations.create(owner).conv_id
        history = self.conversations.history(owner, conv_id, self.settings.history_turns * 2)
        has_docs = self.store.counts()["chunks"] > 0
        t0 = time.perf_counter()
        plan = plan_query(question, history, has_docs, self.provider, self.settings.enable_multi_query,
                          self.settings.request_timeout_s)
        outcome = None
        if plan.question_type == QuestionType.DOCUMENT:
            filters = RetrievalFilters(doc_ids=doc_ids) if doc_ids else None
            outcome = self.retriever.retrieve(plan.standalone, strategy, None, filters, plan.extra_queries)
        gen = AnswerGenerator(self.settings, self.provider)
        final: Optional[AnswerResult] = None
        for text, res in gen.stream(plan, outcome, history):
            if res is not None:
                final = res
            yield text, None, conv_id
        assert final is not None
        final.timings_ms["end_to_end_ms"] = round((time.perf_counter() - t0) * 1000, 1)
        final.warnings = plan.notes + final.warnings
        final.request_id = rid
        self.conversations.append(owner, conv_id, ChatTurn("user", question))
        self.conversations.append(owner, conv_id, ChatTurn("assistant", final.answer, meta={
            "request_id": rid, "standalone_query": final.standalone_query, "rewrite": plan.rewrite_method,
            "provider": final.provider, "citations": [c.__dict__ for c in final.citations],
            "insufficient_evidence": final.insufficient_evidence, "timings_ms": final.timings_ms}))
        self.store.add_activity("question", f"Q: {question[:80]}")
        yield final.answer, final, conv_id

    def ask(self, owner: str, conv_id: Optional[str], question: str,
            doc_ids: Optional[list[str]] = None, strategy: Optional[str] = None) -> tuple[AnswerResult, str]:
        result, cid = None, conv_id
        for _, res, cid in self.ask_stream(owner, conv_id, question, doc_ids, strategy):
            if res is not None:
                result = res
        assert result is not None and cid is not None
        return result, cid

    # ---------------- settings & providers ----------------
    def update_settings(self, **changes: Any) -> list[str]:
        """Validate, apply and persist settings. Returns notices for the UI."""
        new = self.settings.updated(**changes)
        notices = []
        if new.embedding_model != self.settings.embedding_model and len(self.vectors):
            notices.append("Embedding model changed: run 'Re-index all' before dense search works again.")
        if (new.chunk_size_tokens, new.chunk_overlap_tokens) != (self.settings.chunk_size_tokens,
                                                                 self.settings.chunk_overlap_tokens):
            notices.append("Chunking changed: it applies to new uploads; re-index to apply it to existing documents.")
        for f in new.__dataclass_fields__:   # mutate in place so all components see the change
            setattr(self.settings, f, getattr(new, f))
        self.settings.save()
        self._provider = build_provider(self.settings, self.secrets)
        setup_logging(self.settings.logs_dir, self.settings.log_level)
        notices.append("Settings saved.")
        return notices

    def set_api_key(self, provider: str, key: str) -> str:
        if provider not in LLM_PROVIDERS or provider in ("none", "local_hf"):
            raise ValidationError("bad provider", user_message="That provider does not use an API key.")
        self.secrets.set(provider, key)
        self._provider = build_provider(self.settings, self.secrets)
        return f"API key for {provider}: {self.secrets.masked(provider)} (kept in memory only)."

    def provider_status(self) -> dict[str, Any]:
        ok, why = self.provider.available()
        return {"provider": self.provider.name, "model": self.provider.model, "available": ok, "detail": why}

    # ---------------- dashboard ----------------
    def stats(self) -> dict[str, Any]:
        c = self.store.counts()
        return {**c, "vectors": len(self.vectors), "provider": self.provider_status(),
                "retrieval_strategy": self.settings.retrieval_strategy,
                "embedding_model": self.settings.embedding_model,
                "failed_documents": sum(d.status == "failed" for d in self.store.list_documents()),
                "uptime_s": round(time.time() - self.started_at)}

    def recent_activity(self, limit: int = 15) -> list[dict[str, Any]]:
        return self.store.recent_activity(limit)

    # ---------------- exports ----------------
    def export_text(self, basename: str, content: str, ext: str = "md") -> Path:
        if ext not in ("md", "json", "csv", "txt"):
            raise ValidationError("bad ext", user_message="Unsupported export format.")
        name = sanitize_filename(f"{basename}_{time.strftime('%Y%m%d_%H%M%S')}.{ext}")
        path = ensure_within(self.settings.exports_dir, self.settings.exports_dir / name)
        path.write_text(content, encoding="utf-8")
        return path

    # ---------------- optional Google Drive backup ----------------
    DRIVE_DIR = Path("/content/drive/MyDrive/KnowledgeOS_backup")

    def drive_status(self) -> str:
        if not Path("/content/drive/MyDrive").exists():
            return "Google Drive is not mounted. Run the optional Drive cell in the notebook to authorise it."
        last = self.DRIVE_DIR / "knowledgeos.sqlite3"
        return f"Drive mounted. Last backup: {time.ctime(last.stat().st_mtime)}" if last.exists() else \
            "Drive mounted. No backup yet."

    def backup_to_drive(self) -> str:
        """Copy runtime data (no secrets are ever stored there) to Drive."""
        if not Path("/content/drive/MyDrive").exists():
            raise ConfigurationError("drive", user_message=self.drive_status())
        with self._index_lock:
            tmp = self.DRIVE_DIR.with_name(self.DRIVE_DIR.name + "_tmp")
            if tmp.exists():
                shutil.rmtree(tmp)
            shutil.copytree(self.settings.data_path, tmp, ignore=shutil.ignore_patterns("*.tmp", "logs", "*-wal", "*-shm"))
            if self.DRIVE_DIR.exists():
                shutil.rmtree(self.DRIVE_DIR)
            tmp.rename(self.DRIVE_DIR)
        self.store.add_activity("backup", "Backed up data to Google Drive")
        return f"Backed up to {self.DRIVE_DIR}."

    def close(self) -> None:
        self.store.close()
        self.conversations.close()


def restore_from_drive(data_dir: Path, drive_dir: Path = KnowledgeService.DRIVE_DIR) -> str:
    """Restore a Drive backup BEFORE starting the service (call from a notebook cell)."""
    if not drive_dir.exists():
        return f"No backup found at {drive_dir}."
    if data_dir.exists():
        shutil.rmtree(data_dir)
    shutil.copytree(drive_dir, data_dir)
    return f"Restored data from {drive_dir} to {data_dir}."

