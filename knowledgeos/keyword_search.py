"""BM25 keyword retrieval with an inverted index.

Implemented directly (Okapi BM25, Lucene-style non-negative IDF) so only chunks
that actually contain a query term are scored. That makes "no keyword match"
detectable, which matters for honest "insufficient evidence" handling.
"""
from __future__ import annotations

import math
import re
import threading
from collections import Counter, defaultdict
from typing import Iterable, Optional

_TOKEN = re.compile(r"[a-z0-9]+(?:[._-][a-z0-9]+)*")
STOPWORDS = frozenset("""a an and are as at be been but by can could did do does for from had has have how
i if in into is it its me my of on or our so than that the their them then there these they this to
was we were what when where which who whom why will with would you your about also just not no""".split())


def tokenize(text: str) -> list[str]:
    toks = _TOKEN.findall((text or "").lower())
    out = []
    for t in toks:
        if t in STOPWORDS or len(t) < 2 and not t.isdigit():
            continue
        if len(t) > 4 and t.endswith("s") and not t.endswith("ss"):
            t = t[:-1]  # very light plural folding: "models" → "model"
        out.append(t)
    return out


class BM25Index:
    def __init__(self, k1: float = 1.5, b: float = 0.75) -> None:
        self.k1, self.b = k1, b
        self._lock = threading.RLock()
        self._ids: list[str] = []
        self._lens: list[int] = []
        self._postings: dict[str, dict[int, int]] = {}
        self._avgdl = 0.0

    def build(self, docs: Iterable[tuple[str, str]]) -> None:
        """(Re)build from (chunk_id, text) pairs. Full rebuild is fast at Colab scale."""
        ids, lens = [], []
        postings: dict[str, dict[int, int]] = defaultdict(dict)
        for i, (cid, text) in enumerate(docs):
            toks = tokenize(text)
            ids.append(cid)
            lens.append(len(toks))
            for term, tf in Counter(toks).items():
                postings[term][i] = tf
        with self._lock:
            self._ids, self._lens, self._postings = ids, lens, dict(postings)
            self._avgdl = (sum(lens) / len(lens)) if lens else 0.0

    def __len__(self) -> int:
        return len(self._ids)

    def idf(self, term: str) -> float:
        n = len(self._ids)
        df = len(self._postings.get(term, ()))
        return math.log(1 + (n - df + 0.5) / (df + 0.5)) if df else 0.0

    def search(self, query: str, k: int, allowed_ids: Optional[set[str]] = None) -> list[tuple[str, float]]:
        terms = list(dict.fromkeys(tokenize(query)))
        with self._lock:
            if not terms or not self._ids:
                return []
            scores: dict[int, float] = defaultdict(float)
            for term in terms:
                post = self._postings.get(term)
                if not post:
                    continue
                idf = self.idf(term)
                for i, tf in post.items():
                    dl = self._lens[i]
                    denom = tf + self.k1 * (1 - self.b + self.b * dl / (self._avgdl or 1))
                    scores[i] += idf * tf * (self.k1 + 1) / denom
            ranked = sorted(scores.items(), key=lambda x: -x[1])
            out = []
            for i, s in ranked:
                cid = self._ids[i]
                if allowed_ids is not None and cid not in allowed_ids:
                    continue
                out.append((cid, float(s)))
                if len(out) >= k:
                    break
            return out

