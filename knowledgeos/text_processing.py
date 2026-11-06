"""Text normalisation, paragraph/sentence splitting and extraction-quality checks."""
from __future__ import annotations

import re
import unicodedata
from typing import Any

_CTRL = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")
_HYPHEN_BREAK = re.compile(r"(\w)-\n(\w)")
_SPACES = re.compile(r"[ \t\u00a0\u2000-\u200b]+")
_MANY_NL = re.compile(r"\n{3,}")
_SENT_SPLIT = re.compile(r"(?<=[.!?])\s+(?=[A-Z0-9\"'(\[])")
_WORD = re.compile(r"\b\w+\b", re.UNICODE)


def normalize_text(text: str) -> str:
    """Unicode-normalise, drop control chars, re-join hyphenated line breaks, tidy whitespace."""
    if not text:
        return ""
    text = unicodedata.normalize("NFKC", text).replace("\r\n", "\n").replace("\r", "\n")
    text = _CTRL.sub("", text)
    text = _HYPHEN_BREAK.sub(r"\1\2", text)
    text = "\n".join(_SPACES.sub(" ", line).strip() for line in text.split("\n"))
    return _MANY_NL.sub("\n\n", text).strip()


def split_paragraphs(text: str) -> list[str]:
    return [p.strip() for p in re.split(r"\n\s*\n", text or "") if p.strip()]


def split_sentences(text: str) -> list[str]:
    flat = re.sub(r"\s*\n\s*", " ", text or "").strip()
    return [s.strip() for s in _SENT_SPLIT.split(flat) if s.strip()]


def word_count(text: str) -> int:
    return len(_WORD.findall(text or ""))


def quality_report(text: str) -> dict[str, Any]:
    """Cheap heuristics that flag garbled or near-empty extractions."""
    chars = len(text)
    words = _WORD.findall(text)
    n_words = len(words)
    alpha = sum(ch.isalpha() for ch in text)
    replacement = text.count("\ufffd")
    avg_len = (sum(len(w) for w in words) / n_words) if n_words else 0.0
    unique_ratio = (len(set(w.lower() for w in words)) / n_words) if n_words else 0.0
    flags: list[str] = []
    if chars and alpha / chars < 0.4:
        flags.append("low alphabetic ratio (possible garbled extraction, tables or numbers)")
    if chars and replacement / chars > 0.01:
        flags.append("many unreadable characters (encoding problem)")
    if n_words and avg_len > 15:
        flags.append("very long average word length (words may be merged)")
    if n_words > 200 and unique_ratio < 0.05:
        flags.append("highly repetitive text")
    return {
        "chars": chars,
        "words": n_words,
        "alpha_ratio": round(alpha / chars, 3) if chars else 0.0,
        "avg_word_len": round(avg_len, 2),
        "unique_word_ratio": round(unique_ratio, 3),
        "flags": flags,
    }

