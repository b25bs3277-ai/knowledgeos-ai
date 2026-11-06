"""Paragraph-aware, token-aware chunking with overlap and stable chunk IDs.

Strategy: paragraphs → (if too long) sentences → (if still too long) word windows.
Segments are packed greedily up to `chunk_size_tokens`; each new chunk starts with
a tail of the previous one (~`chunk_overlap_tokens`) so context isn't cut mid-idea.
Token counts come from the embedding model's tokenizer; if it can't be loaded we
fall back to an estimate of 1 token ≈ 4 characters.
"""
from __future__ import annotations

import math
from functools import lru_cache
from typing import Iterator, Optional

from .config import Settings
from .logging_config import get_logger, log_event
from .schemas import Chunk, PageText
from .security import sha256_text
from .text_processing import normalize_text, split_paragraphs, split_sentences

log = get_logger("chunking")


class TokenCounter:
    def __init__(self, model_name: Optional[str]) -> None:
        self.model_name = model_name
        self.tokenizer = None
        self.mode = "chars"
        self.error: Optional[str] = None
        if model_name:
            try:
                from transformers import AutoTokenizer

                tok = AutoTokenizer.from_pretrained(model_name)
                tok.model_max_length = 10**9  # we only count; silences length warnings
                self.tokenizer, self.mode = tok, "tokens"
            except Exception as e:  # offline, missing model, etc.
                self.error = f"{type(e).__name__}: {e}"[:300]

    def count(self, text: str) -> int:
        if self.tokenizer is not None:
            return len(self.tokenizer.encode(text, add_special_tokens=False))
        return max(1, math.ceil(len(text) / 4))


@lru_cache(maxsize=4)
def get_token_counter(model_name: Optional[str]) -> TokenCounter:
    counter = TokenCounter(model_name)
    log_event(log, "token counter ready", mode=counter.mode, model=model_name, error=counter.error)
    return counter


def _word_windows(text: str, max_tokens: int) -> Iterator[str]:
    words = text.split()
    step = max(8, int(max_tokens / 1.4))  # ~1.3 tokens per English word, with margin
    for i in range(0, len(words), step):
        yield " ".join(words[i:i + step])


def _segments(text: str, counter: TokenCounter, max_tokens: int) -> Iterator[tuple[str, int]]:
    for para in split_paragraphs(text):
        n = counter.count(para)
        if n <= max_tokens:
            yield para, n
            continue
        for sent in split_sentences(para):
            ns = counter.count(sent)
            if ns <= max_tokens:
                yield sent, ns
            else:
                for win in _word_windows(sent, max_tokens):
                    yield win, counter.count(win)


def _overlap_tail(segs: list[tuple[str, int]], overlap: int, counter: TokenCounter) -> list[tuple[str, int]]:
    if overlap <= 0 or not segs:
        return []
    tail: list[tuple[str, int]] = []
    total = 0
    for seg, n in reversed(segs):
        if total + n > overlap:
            if not tail:  # last segment alone is bigger than overlap → take its trailing words
                words = seg.split()
                part = " ".join(words[-max(1, int(overlap / 1.4)):])
                tail.append((part, counter.count(part)))
            break
        tail.insert(0, (seg, n))
        total += n
    return tail


def split_text(text: str, chunk_size: int, overlap: int, counter: TokenCounter) -> list[str]:
    """Split one text unit into overlapping chunks (pure function; easy to test)."""
    out: list[str] = []
    cur: list[tuple[str, int]] = []
    cur_t = 0
    new_since_emit = False
    for seg, n in _segments(text, counter, chunk_size):
        if cur and cur_t + n > chunk_size and new_since_emit:
            out.append("\n".join(s for s, _ in cur))
            cur = _overlap_tail(cur, overlap, counter)
            cur_t = sum(t for _, t in cur)
            new_since_emit = False
        cur.append((seg, n))
        cur_t += n
        new_since_emit = True
    if cur and new_since_emit:
        out.append("\n".join(s for s, _ in cur))
    return out


def make_chunk_id(doc_id: str, ordinal: int, content_hash: str) -> str:
    """Deterministic: same document content + settings → same chunk IDs."""
    return f"{doc_id}:{ordinal:05d}:{content_hash[:8]}"


def chunk_units(doc_id: str, filename: str, units: list[PageText], settings: Settings,
                counter: Optional[TokenCounter] = None, collection: str = "default") -> list[Chunk]:
    """Turn extracted units into traceable chunks, dropping empties and duplicates."""
    counter = counter or get_token_counter(settings.embedding_model)
    chunks: list[Chunk] = []
    seen: set[str] = set()
    skipped_dup = skipped_short = 0
    for unit in units:
        unit_text = normalize_text(unit.text)
        cursor = 0
        for piece in split_text(unit_text, settings.chunk_size_tokens,
                                settings.chunk_overlap_tokens, counter):
            piece = piece.strip()
            if not piece:
                continue
            h = sha256_text(" ".join(piece.lower().split()))
            if h in seen:
                skipped_dup += 1
                continue
            if len(piece) < settings.min_chunk_chars and len(units) > 1:
                skipped_short += 1
                continue
            seen.add(h)
            probe = piece[:40]
            start = unit_text.find(probe, max(0, cursor - len(piece)))
            start = start if start >= 0 else cursor
            cursor = start + len(piece)
            chunks.append(Chunk(
                chunk_id=make_chunk_id(doc_id, len(chunks), h), doc_id=doc_id, filename=filename,
                text=piece, ordinal=len(chunks), page=unit.page, sheet=unit.sheet,
                section=unit.section, char_start=start, char_end=start + len(piece),
                content_hash=h, collection=collection))
    log_event(log, "chunked", doc_id=doc_id, chunks=len(chunks), dup_skipped=skipped_dup,
              short_skipped=skipped_short, mode=counter.mode)
    return chunks


def describe_chunking(settings: Settings) -> str:
    """Plain-language explanation for the Settings UI."""
    mode = get_token_counter(settings.embedding_model).mode
    unit = "tokens" if mode == "tokens" else "estimated tokens (≈4 characters each)"
    return (f"Documents are split at paragraph, then sentence boundaries into chunks of up to "
            f"{settings.chunk_size_tokens} {unit}, each repeating the last ~"
            f"{settings.chunk_overlap_tokens} of the previous chunk. Smaller chunks give more "
            f"precise citations; larger chunks give the model more context per passage.")

