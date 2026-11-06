"""Format-specific text extraction. Every loader returns PageText units with
location metadata (page / sheet / section) so citations stay traceable."""
from __future__ import annotations

import io
import re
import shutil
from pathlib import Path
from typing import Callable

from .config import Settings
from .exceptions import DependencyError, EmptyDocumentError, ExtractionError
from .logging_config import get_logger, log_event
from .schemas import ExtractionResult, PageText
from .text_processing import normalize_text, quality_report

log = get_logger("loader")

ROWS_PER_UNIT = 25  # tabular rows grouped per extraction unit


def make_doc_id(file_hash: str) -> str:
    """Stable document id derived from the content hash (same file → same id)."""
    return "doc_" + file_hash[:16]


def ocr_available() -> tuple[bool, str]:
    """OCR needs pytesseract, pypdfium2 and the tesseract binary. All optional."""
    try:
        import pypdfium2  # noqa: F401
        import pytesseract  # noqa: F401
    except ImportError:
        return False, "pip install pytesseract pypdfium2 (and apt-get install tesseract-ocr)"
    if not shutil.which("tesseract"):
        return False, "tesseract binary missing: !apt-get -qq install tesseract-ocr"
    return True, "available"


def _ocr_pdf_page(path: Path, page_index: int) -> str:
    import pypdfium2 as pdfium
    import pytesseract

    pdf = pdfium.PdfDocument(str(path))
    try:
        image = pdf[page_index].render(scale=2.0).to_pil()
        return pytesseract.image_to_string(image, timeout=60)
    finally:
        pdf.close()


def _decode_text(data: bytes, warnings: list[str]) -> str:
    for enc in ("utf-8-sig", "utf-16"):
        try:
            if enc == "utf-16" and not data.startswith((b"\xff\xfe", b"\xfe\xff")):
                continue
            return data.decode(enc)
        except UnicodeDecodeError:
            continue
    try:
        text = data.decode("cp1252")
        warnings.append("Decoded as Windows-1252 (file was not valid UTF-8).")
        return text
    except UnicodeDecodeError:
        warnings.append("Decoded as Latin-1 with possible character errors.")
        return data.decode("latin-1", errors="replace")


# ---------------- PDF ----------------
def load_pdf(path: Path, settings: Settings, warnings: list[str]) -> list[PageText]:
    try:
        from pypdf import PdfReader
        from pypdf.errors import PdfReadError
    except ImportError as e:
        raise DependencyError(str(e), user_message="pypdf is not installed (re-run CELL 01).") from e
    try:
        reader = PdfReader(str(path))
        if reader.is_encrypted:
            try:
                reader.decrypt("")
            except Exception as e:
                raise ExtractionError("Encrypted PDF", user_message="PDF is password-protected.") from e
        pages = reader.pages
        n = len(pages)
    except PdfReadError as e:
        raise ExtractionError(f"Unreadable PDF: {e}", user_message="The PDF is damaged or unreadable.") from e

    if n > settings.max_pages_per_pdf:
        warnings.append(f"PDF has {n} pages; only the first {settings.max_pages_per_pdf} were read.")
        n = settings.max_pages_per_pdf
    can_ocr, ocr_msg = ocr_available() if settings.enable_ocr else (False, "")
    units: list[PageText] = []
    empty_pages: list[int] = []
    for i in range(n):
        try:
            text = pages[i].extract_text() or ""
        except Exception as e:  # pypdf can fail on individual malformed pages
            warnings.append(f"Page {i+1}: extraction error ({type(e).__name__}).")
            text = ""
        used_ocr = False
        if len(text.strip()) < 10 and can_ocr:
            try:
                text = _ocr_pdf_page(path, i)
                used_ocr = True
            except Exception as e:
                warnings.append(f"Page {i+1}: OCR failed ({type(e).__name__}).")
        if len(text.strip()) < 10:
            empty_pages.append(i + 1)
            continue
        units.append(PageText(text=text, page=i + 1, ocr=used_ocr))
    if empty_pages:
        shown = ", ".join(map(str, empty_pages[:15])) + ("…" if len(empty_pages) > 15 else "")
        hint = "" if can_ocr else (" Enable OCR in Settings for scanned pages."
                                   if not settings.enable_ocr else f" OCR unavailable: {ocr_msg}")
        warnings.append(f"{len(empty_pages)} page(s) had no extractable text: {shown}.{hint}")
    return units


# ---------------- TXT / Markdown ----------------
_MD_HEADING = re.compile(r"^(#{1,6})\s+(.+?)\s*#*\s*$")


def load_txt(path: Path, settings: Settings, warnings: list[str]) -> list[PageText]:
    return [PageText(text=_decode_text(path.read_bytes(), warnings))]


def load_markdown(path: Path, settings: Settings, warnings: list[str]) -> list[PageText]:
    text = _decode_text(path.read_bytes(), warnings)
    units: list[PageText] = []
    heading_stack: list[str] = []
    buf: list[str] = []
    in_code = False

    def flush() -> None:
        body = "\n".join(buf).strip()
        if body:
            units.append(PageText(text=body, section=" > ".join(heading_stack) or None))
        buf.clear()

    for line in text.splitlines():
        if line.strip().startswith("```"):
            in_code = not in_code
        m = None if in_code else _MD_HEADING.match(line)
        if m:
            flush()
            level = len(m.group(1))
            heading_stack[:] = heading_stack[: level - 1] + [m.group(2).strip()]
            buf.append(m.group(2).strip())  # keep heading text searchable
        else:
            buf.append(line)
    flush()
    return units



# ---------------- DOCX ----------------
def load_docx(path: Path, settings: Settings, warnings: list[str]) -> list[PageText]:
    try:
        import docx
        from docx.table import Table
        from docx.text.paragraph import Paragraph
    except ImportError as e:
        raise DependencyError(str(e), user_message="python-docx is not installed (re-run CELL 01).") from e
    try:
        document = docx.Document(str(path))
    except Exception as e:
        raise ExtractionError(f"Bad DOCX: {e}", user_message="The Word file is damaged or unreadable.") from e

    units: list[PageText] = []
    section = "Introduction"
    buf: list[str] = []
    table_no = 0

    def flush() -> None:
        body = "\n".join(buf).strip()
        if body:
            units.append(PageText(text=body, section=section))
        buf.clear()

    for el in document.element.body.iterchildren():
        tag = el.tag.rsplit("}", 1)[-1]
        if tag == "p":
            para = Paragraph(el, document)
            text = para.text.strip()
            if not text:
                continue
            style = (para.style.name if para.style is not None else "") or ""
            if style.lower().startswith(("heading", "title")):
                flush()
                section = text[:120]
            buf.append(text)
        elif tag == "tbl":
            table_no += 1
            table = Table(el, document)
            rows = [[c.text.strip() for c in r.cells] for r in table.rows]
            if not rows:
                continue
            header = [h or f"Column {i+1}" for i, h in enumerate(rows[0])]
            lines = [f"Table {table_no} (columns: {', '.join(header)})"]
            for r_i, row in enumerate(rows[1:], start=1):
                pairs = [f"{header[i] if i < len(header) else f'Column {i+1}'}: {v}"
                         for i, v in enumerate(row) if v]
                if pairs:
                    lines.append(f"Row {r_i} — " + "; ".join(pairs))
            buf.append("\n".join(lines))
    flush()
    return units


# ---------------- CSV / XLSX ----------------
def _frame_to_units(df, sheet: str | None, settings: Settings, warnings: list[str],
                    label: str) -> list[PageText]:
    """Render rows as 'column: value' records so row relationships survive chunking."""
    df = df.fillna("")
    df.columns = [str(c).strip() if str(c).strip() and not str(c).startswith("Unnamed")
                  else f"Column {i+1}" for i, c in enumerate(df.columns)]
    df = df.loc[:, [c for c in df.columns]]
    if len(df) > settings.max_rows_per_sheet:
        warnings.append(f"{label}: {len(df)} rows; only the first {settings.max_rows_per_sheet} were read.")
        df = df.head(settings.max_rows_per_sheet)
    cols = list(df.columns)
    units = [PageText(text=f"{label} — columns: {', '.join(cols)}. Total rows: {len(df)}.",
                      sheet=sheet, section="schema")]
    records = df.astype(str).to_dict(orient="records")
    for start in range(0, len(records), ROWS_PER_UNIT):
        block = records[start:start + ROWS_PER_UNIT]
        lines = []
        for offset, rec in enumerate(block):
            pairs = [f"{k}: {v.strip()}" for k, v in rec.items() if v.strip()]
            if pairs:
                lines.append(f"Row {start + offset + 1} — " + "; ".join(pairs))
        if lines:
            end = start + len(block)
            units.append(PageText(text="\n".join(lines), sheet=sheet, section=f"rows {start+1}–{end}"))
    return units


def load_csv(path: Path, settings: Settings, warnings: list[str]) -> list[PageText]:
    import pandas as pd

    text = _decode_text(path.read_bytes(), warnings)
    try:
        df = pd.read_csv(io.StringIO(text), dtype=str, keep_default_na=False,
                         sep=None, engine="python", on_bad_lines="skip")
    except Exception as e:
        raise ExtractionError(f"Bad CSV: {e}", user_message="The CSV file could not be parsed.") from e
    return _frame_to_units(df, None, settings, warnings, "CSV")


def load_xlsx(path: Path, settings: Settings, warnings: list[str]) -> list[PageText]:
    import pandas as pd

    try:
        sheets = pd.read_excel(str(path), sheet_name=None, dtype=str, engine="openpyxl")
    except Exception as e:
        raise ExtractionError(f"Bad XLSX: {e}", user_message="The Excel file is damaged or unreadable.") from e
    units: list[PageText] = []
    for name, df in sheets.items():
        if df.dropna(how="all").empty:
            warnings.append(f"Sheet '{name}' is empty and was skipped.")
            continue
        units.extend(_frame_to_units(df.dropna(how="all"), str(name), settings, warnings, f"Sheet '{name}'"))
    return units


LOADERS: dict[str, Callable[[Path, Settings, list[str]], list[PageText]]] = {
    ".pdf": load_pdf,
    ".txt": load_txt,
    ".md": load_markdown,
    ".markdown": load_markdown,
    ".docx": load_docx,
    ".csv": load_csv,
    ".xlsx": load_xlsx,
}


def extract(path: Path, ext: str, settings: Settings) -> ExtractionResult:
    """Extract, normalise and quality-check a stored document.

    Raises ExtractionError / EmptyDocumentError with user-safe messages; never
    returns silently empty results.
    """
    loader = LOADERS.get(ext)
    if loader is None:
        raise ExtractionError(f"No loader for {ext}", user_message=f"No extractor for '{ext}'.")
    warnings: list[str] = []
    try:
        raw_units = loader(Path(path), settings, warnings)
    except (ExtractionError, DependencyError):
        raise
    except Exception as e:
        log_event(log, "extraction crashed", 40, ext=ext, error=type(e).__name__)
        raise ExtractionError(f"{type(e).__name__}: {e}",
                              user_message=f"Extraction failed ({type(e).__name__}).") from e

    units = []
    for u in raw_units:
        u.text = normalize_text(u.text)
        if u.text:
            units.append(u)
    result = ExtractionResult(units=units, warnings=warnings)
    if result.total_chars < settings.min_text_chars:
        hint = " It may be a scanned PDF — enable OCR in Settings." if ext == ".pdf" else ""
        raise EmptyDocumentError("No usable text", user_message=f"No usable text was found.{hint}")
    result.quality = quality_report("\n".join(u.text for u in units))
    result.warnings.extend(f"Quality: {f}" for f in result.quality["flags"])
    log_event(log, "extracted", ext=ext, units=len(units), chars=result.total_chars,
              warnings=len(result.warnings))
    return result

