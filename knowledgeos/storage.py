"""SQLite repository for document records, chunks, index metadata and activity.

Vector data lives separately in vector_store.py. Conversations use their own
database (conversations.py), so chat history never mixes with document content.
"""
from __future__ import annotations

import json
import sqlite3
import threading
import time
from pathlib import Path
from typing import Any, Iterable, Optional

from .exceptions import IndexError_, NotFoundError
from .schemas import Chunk, DocumentRecord, RetrievalFilters

_SCHEMA = """
CREATE TABLE IF NOT EXISTS documents(
    doc_id TEXT PRIMARY KEY, file_hash TEXT UNIQUE NOT NULL, filename TEXT NOT NULL,
    status TEXT NOT NULL, uploaded_at REAL NOT NULL, data TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS chunks(
    chunk_id TEXT PRIMARY KEY,
    doc_id TEXT NOT NULL REFERENCES documents(doc_id) ON DELETE CASCADE,
    ordinal INTEGER NOT NULL, collection TEXT NOT NULL, data TEXT NOT NULL);
CREATE INDEX IF NOT EXISTS idx_chunks_doc ON chunks(doc_id);
CREATE TABLE IF NOT EXISTS meta(key TEXT PRIMARY KEY, value TEXT);
CREATE TABLE IF NOT EXISTS activity(
    id INTEGER PRIMARY KEY AUTOINCREMENT, ts REAL NOT NULL, kind TEXT NOT NULL, message TEXT NOT NULL);
"""


class MetadataStore:
    def __init__(self, db_path: Path) -> None:
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()
        try:
            self._conn = sqlite3.connect(str(self.db_path), check_same_thread=False, timeout=30)
            self._conn.row_factory = sqlite3.Row
            self._conn.execute("PRAGMA foreign_keys=ON")
            self._conn.execute("PRAGMA journal_mode=WAL")
            self._conn.executescript(_SCHEMA)
        except sqlite3.DatabaseError as e:
            raise IndexError_(f"Cannot open metadata DB: {e}",
                              user_message="The document database is damaged. Use Diagnostics → Reset index.") from e

    def close(self) -> None:
        with self._lock:
            self._conn.close()

    # ---------------- documents ----------------
    def upsert_document(self, doc: DocumentRecord) -> None:
        with self._lock, self._conn:
            self._conn.execute(
                "INSERT INTO documents(doc_id,file_hash,filename,status,uploaded_at,data) VALUES(?,?,?,?,?,?) "
                "ON CONFLICT(doc_id) DO UPDATE SET filename=excluded.filename,status=excluded.status,data=excluded.data",
                (doc.doc_id, doc.file_hash, doc.filename, doc.status, doc.uploaded_at, json.dumps(doc.to_dict())))

    def get_document(self, doc_id: str) -> DocumentRecord:
        with self._lock:
            row = self._conn.execute("SELECT data FROM documents WHERE doc_id=?", (doc_id,)).fetchone()
        if row is None:
            raise NotFoundError(f"Document {doc_id} not found", user_message="Document not found.")
        return DocumentRecord.from_dict(json.loads(row["data"]))

    def find_by_hash(self, file_hash: str) -> Optional[DocumentRecord]:
        with self._lock:
            row = self._conn.execute("SELECT data FROM documents WHERE file_hash=?", (file_hash,)).fetchone()
        return DocumentRecord.from_dict(json.loads(row["data"])) if row else None

    def list_documents(self) -> list[DocumentRecord]:
        with self._lock:
            rows = self._conn.execute("SELECT data FROM documents ORDER BY uploaded_at DESC").fetchall()
        return [DocumentRecord.from_dict(json.loads(r["data"])) for r in rows]

    def delete_document(self, doc_id: str) -> int:
        """Delete a document and (via cascade) its chunks. Returns chunk ids removed count."""
        with self._lock, self._conn:
            n = self._conn.execute("SELECT COUNT(*) FROM chunks WHERE doc_id=?", (doc_id,)).fetchone()[0]
            cur = self._conn.execute("DELETE FROM documents WHERE doc_id=?", (doc_id,))
            if cur.rowcount == 0:
                raise NotFoundError(f"Document {doc_id} not found", user_message="Document not found.")
        return int(n)

    # ---------------- chunks ----------------
    def replace_chunks(self, doc_id: str, chunks: Iterable[Chunk]) -> None:
        with self._lock, self._conn:
            self._conn.execute("DELETE FROM chunks WHERE doc_id=?", (doc_id,))
            self._conn.executemany(
                "INSERT INTO chunks(chunk_id,doc_id,ordinal,collection,data) VALUES(?,?,?,?,?)",
                [(c.chunk_id, c.doc_id, c.ordinal, c.collection, json.dumps(c.to_dict())) for c in chunks])

    def chunk_ids_for_doc(self, doc_id: str) -> list[str]:
        with self._lock:
            return [r[0] for r in self._conn.execute(
                "SELECT chunk_id FROM chunks WHERE doc_id=? ORDER BY ordinal", (doc_id,))]

    def get_chunks(self, chunk_ids: list[str]) -> dict[str, Chunk]:
        out: dict[str, Chunk] = {}
        with self._lock:
            for i in range(0, len(chunk_ids), 500):
                part = chunk_ids[i:i + 500]
                q = f"SELECT data FROM chunks WHERE chunk_id IN ({','.join('?' * len(part))})"
                for r in self._conn.execute(q, part):
                    c = Chunk.from_dict(json.loads(r["data"]))
                    out[c.chunk_id] = c
        return out

    def get_doc_chunks(self, doc_id: str) -> list[Chunk]:
        with self._lock:
            rows = self._conn.execute("SELECT data FROM chunks WHERE doc_id=? ORDER BY ordinal", (doc_id,)).fetchall()
        return [Chunk.from_dict(json.loads(r["data"])) for r in rows]

    def iter_all_chunks(self) -> list[Chunk]:
        with self._lock:
            rows = self._conn.execute("SELECT data FROM chunks ORDER BY doc_id, ordinal").fetchall()
        return [Chunk.from_dict(json.loads(r["data"])) for r in rows]

    def all_chunk_ids(self) -> set[str]:
        with self._lock:
            return {r[0] for r in self._conn.execute("SELECT chunk_id FROM chunks")}

    def chunk_ids_matching(self, filters: RetrievalFilters) -> set[str]:
        docs = self.list_documents()
        allowed_docs = {d.doc_id for d in docs
                        if (not filters.doc_ids or d.doc_id in filters.doc_ids)
                        and (not filters.collection or d.collection == filters.collection)
                        and (not filters.file_types or d.file_type in filters.file_types)}
        if not allowed_docs:
            return set()
        out: set[str] = set()
        with self._lock:
            ids = list(allowed_docs)
            for i in range(0, len(ids), 500):
                part = ids[i:i + 500]
                q = f"SELECT chunk_id FROM chunks WHERE doc_id IN ({','.join('?' * len(part))})"
                out.update(r[0] for r in self._conn.execute(q, part))
        return out

    # ---------------- stats / meta / activity ----------------
    def counts(self) -> dict[str, int]:
        with self._lock:
            docs = self._conn.execute("SELECT COUNT(*) FROM documents").fetchone()[0]
            ready = self._conn.execute("SELECT COUNT(*) FROM documents WHERE status='ready'").fetchone()[0]
            chunks = self._conn.execute("SELECT COUNT(*) FROM chunks").fetchone()[0]
        return {"documents": docs, "ready_documents": ready, "chunks": chunks}

    def set_meta(self, key: str, value: Any) -> None:
        with self._lock, self._conn:
            self._conn.execute("INSERT INTO meta(key,value) VALUES(?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value",
                               (key, json.dumps(value)))

    def get_meta(self, key: str, default: Any = None) -> Any:
        with self._lock:
            row = self._conn.execute("SELECT value FROM meta WHERE key=?", (key,)).fetchone()
        return json.loads(row[0]) if row else default

    def add_activity(self, kind: str, message: str) -> None:
        with self._lock, self._conn:
            self._conn.execute("INSERT INTO activity(ts,kind,message) VALUES(?,?,?)", (time.time(), kind, message[:500]))
            self._conn.execute("DELETE FROM activity WHERE id NOT IN (SELECT id FROM activity ORDER BY id DESC LIMIT 500)")

    def recent_activity(self, limit: int = 20) -> list[dict[str, Any]]:
        with self._lock:
            rows = self._conn.execute("SELECT ts,kind,message FROM activity ORDER BY id DESC LIMIT ?", (limit,)).fetchall()
        return [dict(r) for r in rows]

    def integrity_ok(self) -> tuple[bool, str]:
        with self._lock:
            res = self._conn.execute("PRAGMA quick_check").fetchone()[0]
        return res == "ok", res

