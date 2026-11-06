"""Citation extraction and validation.

"Verified" has one precise meaning here: the cited marker maps to a passage that the
retrieval system actually returned and handed to the model, and all metadata
(filename, page, sheet, chunk id) comes from our database, never from model text.
It does NOT prove that the passage logically supports the sentence; a lexical
support score is shown as an additional, imperfect signal.
"""
from __future__ import annotations

import re
from typing import Any

from .keyword_search import tokenize
from .schemas import Citation, RetrievedChunk
from .text_processing import split_sentences

CITE_RE = re.compile(r"\[(\d{1,3}(?:\s*,\s*\d{1,3})*)\]")
INSUFFICIENT_TAG = "INSUFFICIENT_EVIDENCE"


def extract_markers(text: str) -> list[int]:
    seen: list[int] = []
    for m in CITE_RE.finditer(text or ""):
        for n in m.group(1).split(","):
            v = int(n.strip())
            if v not in seen:
                seen.append(v)
    return seen


def lexical_support(sentence: str, passage: str) -> float:
    """Fraction of the sentence's content words that appear in the passage (0–1)."""
    s = set(tokenize(CITE_RE.sub("", sentence)))
    if not s:
        return 1.0
    return round(len(s & set(tokenize(passage))) / len(s), 3)


def _best_snippet(passage: str, sentence: str, max_chars: int = 320) -> str:
    sents = split_sentences(passage) or [passage]
    best = max(sents, key=lambda x: lexical_support(sentence, x) if sentence else 0)
    return best if len(best) <= max_chars else best[:max_chars].rsplit(" ", 1)[0] + "…"


def validate_citations(answer: str, marker_map: dict[int, RetrievedChunk]) -> tuple[list[Citation], list[str], str]:
    """Return (citations, warnings, display_answer). Unknown markers are flagged `[n?]`."""
    warnings: list[str] = []
    sentences = split_sentences(answer) or [answer]
    first_sentence_for: dict[int, str] = {}
    for s in sentences:
        for n in extract_markers(s):
            first_sentence_for.setdefault(n, s)

    citations: list[Citation] = []
    for n in extract_markers(answer):
        rc = marker_map.get(n)
        sent = first_sentence_for.get(n, "")
        if rc is None:
            citations.append(Citation(marker=n, chunk_id="", doc_id="", filename="(unknown)", location="",
                                      passage="", verified=False,
                                      note="The model cited a source number that was never provided to it."))
            continue
        ch = rc.chunk
        support = lexical_support(sent, ch.text) if sent else 0.0
        note = f"Retrieved passage (rank {rc.rank}). Lexical support {support:.0%}."
        if sent and support < 0.25:
            note += " Low overlap: check this claim manually."
        citations.append(Citation(marker=n, chunk_id=ch.chunk_id, doc_id=ch.doc_id, filename=ch.filename,
                                  location=ch.location_label(), passage=_best_snippet(ch.text, sent),
                                  verified=True, note=note))
    bad = sorted({c.marker for c in citations if not c.verified})
    display = answer
    if bad:
        warnings.append(f"Unverifiable citation marker(s) {bad} were flagged with '?'.")

        def fix(m: re.Match) -> str:
            nums = [x.strip() for x in m.group(1).split(",")]
            return "[" + ", ".join(f"{x}?" if int(x) in bad else x for x in nums) + "]"
        display = CITE_RE.sub(fix, answer)
    return citations, warnings, display


def sentence_report(answer: str, marker_map: dict[int, RetrievedChunk]) -> list[dict[str, Any]]:
    """Per-sentence citation status, used for evidence coverage and the evidence panel."""
    rows = []
    for s in split_sentences(answer):
        if len(tokenize(s)) < 3:  # skip fragments like "In summary:"
            continue
        markers = extract_markers(s)
        valid = [m for m in markers if m in marker_map]
        support = max((lexical_support(s, marker_map[m].chunk.text) for m in valid), default=0.0)
        rows.append({"sentence": s, "markers": markers, "valid_markers": valid, "support": support})
    return rows


def evidence_coverage(answer: str, marker_map: dict[int, RetrievedChunk]) -> float:
    """Share of substantive sentences carrying at least one verified citation (0–1)."""
    rows = sentence_report(answer, marker_map)
    return round(sum(1 for r in rows if r["valid_markers"]) / len(rows), 3) if rows else 0.0


def citation_validity(citations: list[Citation]) -> float:
    return round(sum(c.verified for c in citations) / len(citations), 3) if citations else 0.0


def format_sources_markdown(citations: list[Citation]) -> str:
    if not citations:
        return ""
    lines = ["**Sources**"]
    for c in citations:
        badge = "✅ verified" if c.verified else "⚠️ unverified"
        loc = f" — {c.location}" if c.location else ""
        lines.append(f"- [{c.marker}] {c.filename}{loc} · {badge}")
    return "\n".join(lines)

