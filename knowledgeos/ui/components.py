"""Reusable presentation helpers. All user/document text is HTML-escaped here."""
from __future__ import annotations

import html
import time
from typing import Any, Iterable, Optional

from ..config import PROJECT_NAME, TAGLINE, VERSION

CSS = """
:root { --kos-accent: #4f46e5; --kos-ok: #15803d; --kos-warn: #b45309; --kos-err: #b91c1c;
        --kos-muted: #6b7280; --kos-card: rgba(127,127,127,0.06); --kos-border: rgba(127,127,127,0.22); }
.kos-header { display:flex; align-items:center; gap:14px; padding:6px 2px 10px; }
.kos-logo { width:42px; height:42px; border-radius:10px; background:var(--kos-accent); color:#fff;
            display:flex; align-items:center; justify-content:center; font-weight:700; font-size:18px; }
.kos-title { font-size:22px; font-weight:700; line-height:1.1; }
.kos-tag { color:var(--kos-muted); font-size:13px; }
.kos-cards { display:grid; grid-template-columns:repeat(auto-fit,minmax(150px,1fr)); gap:10px; margin:6px 0 12px; }
.kos-card { border:1px solid var(--kos-border); background:var(--kos-card); border-radius:10px; padding:12px 14px; }
.kos-card .v { font-size:24px; font-weight:700; }
.kos-card .l { color:var(--kos-muted); font-size:12px; text-transform:uppercase; letter-spacing:.04em; }
.kos-note { border-radius:8px; padding:10px 12px; margin:6px 0; border:1px solid var(--kos-border); font-size:14px; }
.kos-note.ok { border-left:4px solid var(--kos-ok); } .kos-note.warn { border-left:4px solid var(--kos-warn); }
.kos-note.err { border-left:4px solid var(--kos-err); } .kos-note.info { border-left:4px solid var(--kos-accent); }
.kos-badge { display:inline-block; padding:1px 8px; border-radius:999px; font-size:12px; font-weight:600;
             border:1px solid var(--kos-border); }
.kos-badge.ready { color:var(--kos-ok); } .kos-badge.failed { color:var(--kos-err); }
.kos-badge.indexing, .kos-badge.extracting, .kos-badge.uploaded { color:var(--kos-warn); }
.kos-empty { text-align:center; padding:28px 12px; color:var(--kos-muted); border:1px dashed var(--kos-border);
             border-radius:10px; }
.kos-empty b { display:block; font-size:16px; color:inherit; margin-bottom:4px; }
.kos-passage { border:1px solid var(--kos-border); border-radius:8px; padding:10px 12px; margin:8px 0; }
.kos-passage .meta { font-size:12px; color:var(--kos-muted); margin-bottom:4px; }
.kos-steps { display:flex; flex-wrap:wrap; gap:6px; font-size:13px; color:var(--kos-muted); }
.kos-steps span { border:1px solid var(--kos-border); border-radius:999px; padding:2px 10px; }
@media (max-width: 640px) { .kos-title { font-size:18px; } .kos-card .v { font-size:20px; } }
"""

E = html.escape


def header_html() -> str:
    return (f'<div class="kos-header"><div class="kos-logo">K</div><div>'
            f'<div class="kos-title">{E(PROJECT_NAME)} <span class="kos-tag">v{E(VERSION)}</span></div>'
            f'<div class="kos-tag">{E(TAGLINE)}</div></div></div>')


def workflow_html() -> str:
    steps = ["1 · Upload documents", "2 · Process", "3 · Ask questions", "4 · Inspect sources", "5 · Export"]
    return '<div class="kos-steps">' + "".join(f"<span>{E(s)}</span>" for s in steps) + "</div>"


def stat_cards(items: Iterable[tuple[str, Any]]) -> str:
    cells = "".join(f'<div class="kos-card"><div class="v">{E(str(v))}</div><div class="l">{E(l)}</div></div>'
                    for l, v in items)
    return f'<div class="kos-cards">{cells}</div>'


def notice(kind: str, message: str) -> str:
    kind = kind if kind in ("ok", "warn", "err", "info") else "info"
    icon = {"ok": "✅", "warn": "⚠️", "err": "⛔", "info": "ℹ️"}[kind]
    return f'<div class="kos-note {kind}">{icon} {E(message)}</div>'


def notices(items: Iterable[tuple[str, str]]) -> str:
    return "".join(notice(k, m) for k, m in items)


def empty_state(title: str, hint: str) -> str:
    return f'<div class="kos-empty"><b>{E(title)}</b>{E(hint)}</div>'


def badge(status: str) -> str:
    return f'<span class="kos-badge {E(status)}">{E(status)}</span>'


def fmt_ts(ts: Optional[float]) -> str:
    return time.strftime("%Y-%m-%d %H:%M", time.localtime(ts)) if ts else "—"


def fmt_size(n: int) -> str:
    for unit in ("B", "KB", "MB", "GB"):
        if n < 1024 or unit == "GB":
            return f"{n:.0f} {unit}" if unit == "B" else f"{n:.1f} {unit}"
        n /= 1024
    return str(n)


def passages_html(results: list, max_chars: int = 700) -> str:
    """Retrieved passages with rank, scores and location, for the evidence panel."""
    if not results:
        return empty_state("No passages", "Nothing was retrieved for this question.")
    blocks = []
    for r in results:
        ch = r.chunk
        comps = ", ".join(f"{k} {v}" for k, v in r.component_scores.items())
        ranks = ", ".join(f"{k} #{v}" for k, v in r.component_ranks.items())
        text = ch.text if len(ch.text) <= max_chars else ch.text[:max_chars] + "…"
        blocks.append(
            f'<div class="kos-passage"><div class="meta">#{r.rank} · <b>{E(ch.filename)}</b> · '
            f'{E(ch.location_label())} · method {E(r.method)} · score {r.score:.4f}'
            f'{" · " + E(comps) if comps else ""}{" · ranks " + E(ranks) if ranks else ""}'
            f'<br>chunk <code>{E(ch.chunk_id)}</code></div>{E(text)}</div>')
    return "".join(blocks)


def citations_html(citations: list) -> str:
    if not citations:
        return empty_state("No citations", "This answer has no source citations.")
    rows = []
    for c in citations:
        status = notice("ok", "Verified: this passage was retrieved and given to the model.") if c.verified \
            else notice("warn", "Unverified: the model cited a source that was not provided.")
        rows.append(f'<div class="kos-passage"><div class="meta">[{c.marker}] <b>{E(c.filename)}</b> · '
                    f'{E(c.location)} · doc <code>{E(c.doc_id)}</code> · chunk <code>{E(c.chunk_id)}</code></div>'
                    f'{status}<div>{E(c.passage)}</div><div class="meta">{E(c.note)}</div></div>')
    return "".join(rows)


def documents_table(docs: list) -> list[list[Any]]:
    return [[d.filename, d.status, d.file_type, fmt_size(d.size_bytes), d.chunk_count,
             fmt_ts(d.uploaded_at), fmt_ts(d.indexed_at), (d.error or "")[:120],
             len(d.warnings), d.doc_id] for d in docs]


DOC_COLUMNS = ["File", "Status", "Type", "Size", "Chunks", "Uploaded", "Indexed", "Error", "Warnings", "Doc ID"]


def doc_choices(docs: list, ready_only: bool = True) -> list[tuple[str, str]]:
    return [(f"{d.filename} ({d.chunk_count} chunks)", d.doc_id) for d in docs
            if not ready_only or d.status == "ready"]


def activity_md(rows: list[dict[str, Any]]) -> str:
    if not rows:
        return "_No activity yet._"
    return "\n".join(f"- `{fmt_ts(r['ts'])}` **{E(r['kind'])}** — {E(r['message'])}" for r in rows)

