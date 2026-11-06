"""Plain dataclasses shared by every layer. No business logic, no heavy imports."""
from __future__ import annotations

import time
from dataclasses import asdict, dataclass, field
from enum import Enum
from typing import Any, Optional


def now_ts() -> float:
    return time.time()


class DocStatus(str, Enum):
    UPLOADED = "uploaded"
    EXTRACTING = "extracting"
    INDEXING = "indexing"
    READY = "ready"
    FAILED = "failed"


class QuestionType(str, Enum):
    GREETING = "greeting"
    META = "meta"              # questions about the app itself
    DOCUMENT = "document"      # needs retrieval
    GENERAL = "general"        # general chat, no retrieval
    AMBIGUOUS = "ambiguous"


@dataclass
class PageText:
    """Text extracted from one locatable unit (PDF page, sheet, section)."""

    text: str
    page: Optional[int] = None        # 1-based PDF page
    sheet: Optional[str] = None       # spreadsheet sheet name
    section: Optional[str] = None     # heading / row range / paragraph range
    ocr: bool = False


@dataclass
class ExtractionResult:
    units: list[PageText]
    warnings: list[str] = field(default_factory=list)
    quality: dict[str, Any] = field(default_factory=dict)

    @property
    def total_chars(self) -> int:
        return sum(len(u.text) for u in self.units)


@dataclass
class DocumentRecord:
    doc_id: str
    filename: str
    file_hash: str
    file_type: str
    size_bytes: int
    stored_path: str
    status: str = DocStatus.UPLOADED.value
    uploaded_at: float = field(default_factory=now_ts)
    indexed_at: Optional[float] = None
    chunk_count: int = 0
    unit_count: int = 0
    error: Optional[str] = None
    warnings: list[str] = field(default_factory=list)
    collection: str = "default"
    quality: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "DocumentRecord":
        known = {k: d[k] for k in cls.__dataclass_fields__ if k in d}
        return cls(**known)


@dataclass
class Chunk:
    chunk_id: str
    doc_id: str
    filename: str
    text: str
    ordinal: int
    page: Optional[int] = None
    sheet: Optional[str] = None
    section: Optional[str] = None
    char_start: int = 0
    char_end: int = 0
    content_hash: str = ""
    collection: str = "default"

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "Chunk":
        known = {k: d[k] for k in cls.__dataclass_fields__ if k in d}
        return cls(**known)

    def location_label(self) -> str:
        parts = []
        if self.page is not None:
            parts.append(f"p. {self.page}")
        if self.sheet:
            parts.append(f"sheet '{self.sheet}'")
        if self.section:
            parts.append(self.section)
        return ", ".join(parts) if parts else f"chunk {self.ordinal}"


@dataclass
class RetrievedChunk:
    chunk: Chunk
    score: float                       # final score used for ordering
    rank: int                          # 1-based final rank
    method: str                        # dense | keyword | hybrid | hybrid_rerank
    component_scores: dict[str, float] = field(default_factory=dict)
    component_ranks: dict[str, int] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        d["chunk"] = self.chunk.to_dict()
        return d


@dataclass
class RetrievalFilters:
    doc_ids: Optional[list[str]] = None
    collection: Optional[str] = None
    file_types: Optional[list[str]] = None

    def is_empty(self) -> bool:
        return not (self.doc_ids or self.collection or self.file_types)


@dataclass
class Citation:
    marker: int                         # [n] as used in the answer text
    chunk_id: str
    doc_id: str
    filename: str
    location: str
    passage: str
    verified: bool                      # True only if chunk_id was actually retrieved
    note: str = ""


@dataclass
class AnswerResult:
    question: str
    standalone_query: str
    answer: str
    question_type: str
    citations: list[Citation] = field(default_factory=list)
    retrieved: list[RetrievedChunk] = field(default_factory=list)
    provider: str = "none"
    model: str = ""
    grounded: bool = False
    insufficient_evidence: bool = False
    generation_available: bool = False
    timings_ms: dict[str, float] = field(default_factory=dict)
    warnings: list[str] = field(default_factory=list)
    request_id: str = ""


@dataclass
class ChatTurn:
    role: str                           # "user" | "assistant"
    content: str
    ts: float = field(default_factory=now_ts)
    meta: dict[str, Any] = field(default_factory=dict)


@dataclass
class Conversation:
    conv_id: str
    title: str
    created_at: float = field(default_factory=now_ts)
    updated_at: float = field(default_factory=now_ts)
    turns: list[ChatTurn] = field(default_factory=list)
    doc_filter: list[str] = field(default_factory=list)


@dataclass
class EvalCase:
    case_id: str
    question: str
    expected_answer: str = ""
    relevant_doc_ids: list[str] = field(default_factory=list)
    relevant_chunk_ids: list[str] = field(default_factory=list)
    relevant_keywords: list[str] = field(default_factory=list)

