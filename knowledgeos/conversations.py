"""Conversation persistence in its own SQLite DB, isolated per browser session.

Every row carries an `owner` (a random per-session id held in Gradio state), and
every query filters by it, so one visitor's chats are never listed or loaded for
another. This is isolation between sessions, not authentication: anyone holding
a public share link gets their own fresh owner id but can still use the shared
document library.
"""
from __future__ import annotations

import json
import sqlite3
import threading
import time
import uuid
from dataclasses import asdict
from pathlib import Path
from typing import Any, Optional

from .exceptions import NotFoundError, ValidationError
from .schemas import ChatTurn, Conversation

_SCHEMA = """
CREATE TABLE IF NOT EXISTS conversations(
    conv_id TEXT PRIMARY KEY, owner TEXT NOT NULL, title TEXT NOT NULL,
    created_at REAL NOT NULL, updated_at REAL NOT NULL, doc_filter TEXT NOT NULL DEFAULT '[]');
CREATE INDEX IF NOT EXISTS idx_conv_owner ON conversations(owner, updated_at);
CREATE TABLE IF NOT EXISTS turns(
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    conv_id TEXT NOT NULL REFERENCES conversations(conv_id) ON DELETE CASCADE,
    role TEXT NOT NULL, content TEXT NOT NULL, ts REAL NOT NULL, meta TEXT NOT NULL DEFAULT '{}');
CREATE INDEX IF NOT EXISTS idx_turns_conv ON turns(conv_id, id);
"""


def new_session_id() -> str:
    return "s_" + uuid.uuid4().hex


class ConversationStore:
    def __init__(self, db_path: Path) -> None:
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()
        self._conn = sqlite3.connect(str(self.db_path), check_same_thread=False, timeout=30)
        self._conn.row_factory = sqlite3.Row
        self._conn.execute("PRAGMA foreign_keys=ON")
        self._conn.executescript(_SCHEMA)

    def close(self) -> None:
        with self._lock:
            self._conn.close()

    @staticmethod
    def _check_owner(owner: str) -> None:
        if not owner or not isinstance(owner, str) or len(owner) > 80:
            raise ValidationError("bad owner", user_message="Session expired; reload the page.")

    def _row(self, owner: str, conv_id: str) -> sqlite3.Row:
        self._check_owner(owner)
        row = self._conn.execute("SELECT * FROM conversations WHERE conv_id=? AND owner=?",
                                 (conv_id, owner)).fetchone()
        if row is None:
            raise NotFoundError("conversation not found", user_message="Conversation not found.")
        return row

    def create(self, owner: str, title: str = "New conversation") -> Conversation:
        self._check_owner(owner)
        now = time.time()
        conv = Conversation(conv_id="c_" + uuid.uuid4().hex[:16], title=title[:80] or "New conversation",
                            created_at=now, updated_at=now)
        with self._lock, self._conn:
            self._conn.execute("INSERT INTO conversations(conv_id,owner,title,created_at,updated_at) VALUES(?,?,?,?,?)",
                               (conv.conv_id, owner, conv.title, now, now))
        return conv

    def list(self, owner: str) -> list[dict[str, Any]]:
        self._check_owner(owner)
        with self._lock:
            rows = self._conn.execute(
                "SELECT c.conv_id,c.title,c.updated_at,(SELECT COUNT(*) FROM turns t WHERE t.conv_id=c.conv_id) n "
                "FROM conversations c WHERE owner=? ORDER BY updated_at DESC", (owner,)).fetchall()
        return [dict(r) for r in rows]

    def get(self, owner: str, conv_id: str) -> Conversation:
        with self._lock:
            row = self._row(owner, conv_id)
            turns = self._conn.execute("SELECT role,content,ts,meta FROM turns WHERE conv_id=? ORDER BY id",
                                       (conv_id,)).fetchall()
        return Conversation(conv_id=row["conv_id"], title=row["title"], created_at=row["created_at"],
                            updated_at=row["updated_at"], doc_filter=json.loads(row["doc_filter"]),
                            turns=[ChatTurn(t["role"], t["content"], t["ts"], json.loads(t["meta"])) for t in turns])

    def history(self, owner: str, conv_id: Optional[str], limit: int = 20) -> list[ChatTurn]:
        """Recent turns, or [] when the conversation is missing (graceful)."""
        if not conv_id:
            return []
        try:
            return self.get(owner, conv_id).turns[-limit:]
        except NotFoundError:
            return []

    def append(self, owner: str, conv_id: str, turn: ChatTurn) -> None:
        with self._lock, self._conn:
            row = self._row(owner, conv_id)
            self._conn.execute("INSERT INTO turns(conv_id,role,content,ts,meta) VALUES(?,?,?,?,?)",
                               (conv_id, turn.role, turn.content, turn.ts, json.dumps(turn.meta, default=str)))
            self._conn.execute("UPDATE conversations SET updated_at=? WHERE conv_id=?", (time.time(), conv_id))
            if turn.role == "user" and row["title"] == "New conversation":
                self._conn.execute("UPDATE conversations SET title=? WHERE conv_id=?",
                                   (turn.content.strip().replace("\n", " ")[:60] or "New conversation", conv_id))

    def rename(self, owner: str, conv_id: str, title: str) -> None:
        title = (title or "").strip()[:80]
        if not title:
            raise ValidationError("empty title", user_message="Title cannot be empty.")
        with self._lock, self._conn:
            self._row(owner, conv_id)
            self._conn.execute("UPDATE conversations SET title=? WHERE conv_id=?", (title, conv_id))

    def set_doc_filter(self, owner: str, conv_id: str, doc_ids: list[str]) -> None:
        with self._lock, self._conn:
            self._row(owner, conv_id)
            self._conn.execute("UPDATE conversations SET doc_filter=? WHERE conv_id=?", (json.dumps(doc_ids), conv_id))

    def delete(self, owner: str, conv_id: str) -> None:
        with self._lock, self._conn:
            self._row(owner, conv_id)
            self._conn.execute("DELETE FROM conversations WHERE conv_id=?", (conv_id,))

    def clear_turns(self, owner: str, conv_id: str) -> None:
        with self._lock, self._conn:
            self._row(owner, conv_id)
            self._conn.execute("DELETE FROM turns WHERE conv_id=?", (conv_id,))

    def export_markdown(self, owner: str, conv_id: str) -> str:
        c = self.get(owner, conv_id)
        out = [f"# {c.title}", f"_Exported from KnowledgeOS AI · {time.strftime('%Y-%m-%d %H:%M')}_", ""]
        for t in c.turns:
            who = "**You**" if t.role == "user" else "**KnowledgeOS**"
            out.append(f"{who} ({time.strftime('%H:%M', time.localtime(t.ts))}):\n\n{t.content}\n")
        return "\n".join(out)

    def export_json(self, owner: str, conv_id: str) -> str:
        c = self.get(owner, conv_id)
        return json.dumps(asdict(c), indent=2, default=str)

