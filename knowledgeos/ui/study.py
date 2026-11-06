"""Interactive study widgets (flip flashcards, click-to-answer quiz) and the Home page's
quick actions. Pure HTML/CSS: works inside gr.HTML without JavaScript. Gradio-free logic."""
from __future__ import annotations

import html
import uuid
from typing import TYPE_CHECKING, Any, Optional

from ..exceptions import KnowledgeOSError, safe_user_message
from .components import empty_state, notice

if TYPE_CHECKING:
    from ..services import KnowledgeService

E = html.escape
LETTERS = "ABCDEFGH"

QUICK_ACTIONS = [
    ("summary", "📄  Summarize\nkey points in a minute"),
    ("flashcards", "🃏  Flashcards\nflip to reveal answers"),
    ("quiz", "❓  Quiz me\nclick an option to check"),
    ("notes", "📝  Study notes\nheadings & bullets"),
    ("terms", "🔑  Key terms\nno AI needed"),
]


def flashcards_html(items: list[dict[str, Any]]) -> str:
    if not items:
        return empty_state("No flashcards", "The model did not return usable cards. Try again.")
    cells = []
    for i, it in enumerate(items, start=1):
        ok = "✅" if it.get("verified_source") else "⚠️"
        cells.append(
            f'<label class="kos-flip"><input type="checkbox"><div class="kos-flip-inner">'
            f'<div class="kos-face kos-front"><div class="h">Card {i} · tap to flip</div>'
            f'<div class="t">{E(str(it.get("front", "")))}</div></div>'
            f'<div class="kos-face kos-back"><div class="h">Answer</div><div class="t">{E(str(it.get("back", "")))}</div>'
            f'<div class="s">{ok} {E(str(it.get("source_label", "")))}</div></div>'
            f'</div></label>')
    return '<div class="kos-grid">' + "".join(cells) + "</div>"


def quiz_html(items: list[dict[str, Any]]) -> str:
    if not items:
        return empty_state("No quiz", "The model did not return usable questions. Try again.")
    uid = uuid.uuid4().hex[:6]
    blocks = []
    for i, it in enumerate(items, start=1):
        opts = []
        for j, o in enumerate(it.get("options", [])):
            cls = "correct" if j == it.get("answer_index") else "wrong"
            opts.append(f'<label class="kos-opt {cls}"><input type="radio" name="q{uid}_{i}">'
                        f'<span><b>{LETTERS[j % 8]}.</b> {E(str(o))}</span></label>')
        ok = "✅" if it.get("verified_source") else "⚠️"
        blocks.append(
            f'<div class="kos-q"><div class="qt">{i}. {E(str(it.get("question", "")))}</div>{"".join(opts)}'
            f'<details><summary>Explanation</summary>{E(str(it.get("explanation", "")))}</details>'
            f'<div class="src">{ok} Source: {E(str(it.get("source_label", "")))}</div></div>')
    return '<div class="kos-quiz">' + "".join(blocks) + "</div>"


def render_structured(task: str, structured: Any) -> Optional[str]:
    """HTML for interactive outputs, or None when the result is plain markdown."""
    if task == "flashcards" and isinstance(structured, list):
        return flashcards_html(structured)
    if task == "quiz" and isinstance(structured, list):
        return quiz_html(structured)
    return None


def run_quick_action(svc: "KnowledgeService", action: str, doc_id: Optional[str]) -> tuple[str, str, str]:
    """Home page quick action. Returns (interactive HTML, markdown, status HTML)."""
    if not doc_id:
        return "", "", notice("info", "Pick a document above first (upload one in 📚 Library if the list is empty).")
    R = svc.research
    try:
        res = {"summary": lambda: R.summarize_document(doc_id, "medium"),
               "flashcards": lambda: R.flashcards(doc_id, 8),
               "quiz": lambda: R.quiz(doc_id, 5),
               "notes": lambda: R.study_notes(doc_id, "medium"),
               "terms": lambda: R.key_terms(doc_id)}[action]()
    except KeyError:
        return "", "", notice("err", "Unknown action.")
    except KnowledgeOSError as e:
        return "", "", notice("err", safe_user_message(e))
    status = "".join(notice("warn", w) for w in res.warnings) or notice("ok", res.title)
    html_out = render_structured(res.task, res.structured)
    return (html_out or ""), ("" if html_out else res.markdown), status


def stats_html(svc: "KnowledgeService") -> str:
    s = svc.stats()
    p = s["provider"]
    items = [("Documents", s["documents"]), ("Ready", s["ready_documents"]), ("Chunks indexed", s["chunks"]),
             ("AI answers", "On" if p["available"] else "Off")]
    cells = "".join(f'<div class="kos-stat"><div class="v">{E(str(v))}</div><div class="l">{E(l)}</div></div>'
                    for l, v in items)
    return f'<div class="kos-stats">{cells}</div>'


def hero_html(svc: "KnowledgeService") -> str:
    s = svc.stats()
    if s["ready_documents"]:
        title, sub = "What do you want to learn today?", \
            "Ask a question, or turn a document into flashcards, a quiz or notes in one click."
    else:
        title, sub = "Turn your documents into answers.", \
            "Upload a PDF in 📚 Library — then ask questions with page-level sources, or study with flashcards."
    steps = "".join(f"<span>{x}</span>" for x in ["① Upload", "② Ask or 🎤 speak", "③ See the highlighted page",
                                                    "④ Study with cards"])
    return (f'<div class="kos-hero"><h1>{E(title)}</h1><p>{E(sub)}</p>{stats_html(svc)}'
            f'<div class="kos-steps2">{steps}</div></div>')


def topbar_html(svc: "KnowledgeService") -> str:
    from ..config import PROJECT_NAME, TAGLINE
    p = svc.provider_status()
    ready = svc.stats()["ready_documents"]
    pills = [(f"{ready} ready doc(s)", "ok" if ready else "warn"),
             (f"AI: {p['provider']}" + ("" if p["available"] else " (off)"), "ok" if p["available"] else "warn")]
    ph = "".join(f'<span class="kos-pill {k}">{E(t)}</span>' for t, k in pills)
    return (f'<div class="kos-topbar"><div class="kos-brand"><div class="kos-mark">✦</div><div>'
            f'<div class="kos-name">{E(PROJECT_NAME)}</div><div class="kos-sub">{E(TAGLINE)}</div></div></div>'
            f'<div class="kos-pills">{ph}</div></div>')
