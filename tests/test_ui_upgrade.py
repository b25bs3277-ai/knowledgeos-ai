from __future__ import annotations

import pytest

from knowledgeos.llm_providers import MockProvider
from knowledgeos.pdf_preview import available, preview, render_page
from knowledgeos.ui import study as S
from knowledgeos.ui import viewer as V
from knowledgeos.conversations import new_session_id

from .conftest import doc_id_of


@pytest.mark.skipif(not available(), reason="pypdfium2/Pillow not installed")
def test_pdf_page_rendered_with_highlight(fixture_files):
    pv = render_page(str(fixture_files[".pdf"]), 1, [("trains models on labeled examples", (255, 214, 0, 95))])
    assert pv.image is not None and pv.n_pages == 3 and pv.matched >= 1
    plain = render_page(str(fixture_files[".pdf"]), 1)
    assert pv.image.tobytes() != plain.image.tobytes()          # highlight actually drawn
    assert render_page(str(fixture_files[".pdf"]), 99).page == 3  # clamped to last page


def test_non_pdf_preview_marks_focus(fixture_files):
    pv = preview(str(fixture_files[".txt"]), ".txt", None, "Gradient descent minimises a loss.", "minimises a loss")
    assert pv.image is None and '<mark class="kos-focus">' in pv.html


def test_answer_sources_open_the_cited_page(indexed):
    indexed.set_provider_override(MockProvider(lambda m: "Supervised learning uses labeled examples [1]."))
    res, _ = indexed.ask(new_session_id(), None, "What is supervised learning?")
    srcs = V.sources_from_result(indexed, res)
    assert srcs[0]["label"].startswith("[1] ml_basics.pdf") and srcs[0]["page"] == 1
    img, cap, html_view, page = V.open_source(indexed, srcs[0])
    assert page == 1 and "ml_basics.pdf" in cap
    if available():
        assert img is not None and "highlighted" in cap
        img2, cap2, _, page2 = V.open_source(indexed, srcs[0], 2)
        assert page2 == 2 and "no highlight" in cap2
    assert V.open_source(indexed, None)[0] is None


def test_interactive_cards_escape_and_structure():
    fc = S.flashcards_html([{"front": "<b>Q</b>", "back": "A", "source_label": "x.pdf — p. 1", "verified_source": True}])
    assert 'type="checkbox"' in fc and "&lt;b&gt;Q&lt;/b&gt;" in fc
    qz = S.quiz_html([{"question": "Q?", "options": ["a", "b"], "answer_index": 1, "explanation": "e",
                       "source_label": "s", "verified_source": False}])
    assert qz.count('type="radio"') == 2 and 'kos-opt correct' in qz and 'kos-opt wrong' in qz
    assert S.render_structured("summarize_document", None) is None


def test_home_quick_actions(indexed):
    pdf = doc_id_of(indexed, "ml_basics.pdf")
    html_out, md, status = S.run_quick_action(indexed, "terms", pdf)
    assert md and "Key terms" in md and not html_out
    indexed.set_provider_override(MockProvider(lambda m: '[{"front": "What is RL?", "back": "Learning from rewards", "source": 3}]'))
    html_out, md, status = S.run_quick_action(indexed, "flashcards", pdf)
    assert "kos-flip" in html_out and not md
    assert "Pick a document" in S.run_quick_action(indexed, "quiz", None)[2]
    assert "kos-hero" in S.hero_html(indexed) and "kos-topbar" in S.topbar_html(indexed)
