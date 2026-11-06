"""Render a PDF page as an image and highlight where an answer's evidence appears on it.

Uses pypdfium2 (text search gives exact character boxes) and Pillow for the overlay.
Non-PDF documents get an HTML preview of the passage instead.
"""
from __future__ import annotations

import html
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional, Sequence

EVIDENCE = (255, 214, 0, 95)     # yellow: the retrieved passage
FOCUS = (255, 140, 0, 125)       # orange: the sentence the citation points to


@dataclass
class PagePreview:
    image: Optional[object]          # PIL.Image or None
    page: Optional[int]              # 1-based
    n_pages: int = 0
    matched: int = 0                 # phrases found and highlighted
    html: str = ""                   # fallback / non-PDF preview
    notes: list[str] = field(default_factory=list)


def _phrases(text: str, size: int = 5, limit: int = 40) -> list[str]:
    """Short overlapping word windows: robust to line breaks and hyphenation in the PDF text layer."""
    words = re.findall(r"[^\s]+", text or "")
    if len(words) <= size:
        return [" ".join(words)] if words else []
    step = max(2, size - 1)
    out = [" ".join(words[i:i + size]) for i in range(0, len(words) - size + 1, step)]
    tail = " ".join(words[-size:])
    if tail not in out:
        out.append(tail)  # make sure the passage's last words are covered
    return out[:limit]


def available() -> bool:
    try:
        import pypdfium2  # noqa: F401
        from PIL import Image  # noqa: F401
        return True
    except ImportError:
        return False


def page_count(path: str) -> int:
    import pypdfium2 as pdfium
    pdf = pdfium.PdfDocument(path)
    try:
        return len(pdf)
    finally:
        pdf.close()


def render_page(path: str, page: int, highlights: Sequence[tuple[str, tuple]] = (),
                scale: float = 1.6) -> PagePreview:
    """Render 1-based `page`; each highlight is (text, rgba). Returns a PagePreview."""
    import pypdfium2 as pdfium
    from PIL import Image, ImageDraw

    pdf = pdfium.PdfDocument(path)
    try:
        n = len(pdf)
        page = max(1, min(int(page or 1), n))
        pg = pdf[page - 1]
        _, height = pg.get_size()
        img = pg.render(scale=scale).to_pil().convert("RGBA")
        overlay = Image.new("RGBA", img.size, (0, 0, 0, 0))
        draw = ImageDraw.Draw(overlay)
        matched = 0
        tp = pg.get_textpage()
        for text, color in highlights:
            for phrase in _phrases(text):
                searcher = tp.search(phrase, match_case=False, match_whole_word=False)
                occ = searcher.get_next()
                if not occ:
                    continue
                matched += 1
                for i in range(tp.count_rects(*occ)):
                    left, bottom, right, top = tp.get_rect(i)
                    box = [left * scale - 2, (height - top) * scale - 2, right * scale + 2, (height - bottom) * scale + 2]
                    draw.rounded_rectangle(box, radius=3, fill=color)
        img = Image.alpha_composite(img, overlay).convert("RGB")
        return PagePreview(image=img, page=page, n_pages=n, matched=matched)
    finally:
        pdf.close()


def text_preview(text: str, focus: str = "", title: str = "") -> str:
    """HTML preview for non-PDF sources, with the focus sentence marked."""
    body = html.escape(text or "")
    f = html.escape((focus or "").strip())
    if f and f in body:
        body = body.replace(f, f'<mark class="kos-focus">{f}</mark>', 1)
    head = f'<div class="kos-doc-title">{html.escape(title)}</div>' if title else ""
    return f'<div class="kos-textdoc">{head}<div class="kos-textbody">{body}</div></div>'


def preview(stored_path: str, file_type: str, page: Optional[int], passage: str = "", focus: str = "",
            title: str = "") -> PagePreview:
    """Best available preview for a source location."""
    if file_type == ".pdf" and page and Path(stored_path).exists() and available():
        try:
            hl = [(passage, EVIDENCE)] if passage else []
            if focus:
                hl.append((focus, FOCUS))
            pv = render_page(stored_path, page, hl)
            if (passage or focus) and pv.matched == 0:
                pv.notes.append("Exact text could not be located on the page image (PDF text layer differs); "
                                "the passage is shown below.")
                pv.html = text_preview(passage, focus)
            return pv
        except Exception as e:  # damaged PDF etc. → text fallback, reason shown
            return PagePreview(None, page, 0, 0, text_preview(passage, focus, title),
                               [f"Page image unavailable ({type(e).__name__})."])
    note = [] if file_type != ".pdf" else ["Page images need pypdfium2; showing the passage text."]
    return PagePreview(None, page, 0, 0, text_preview(passage, focus, title), note)
