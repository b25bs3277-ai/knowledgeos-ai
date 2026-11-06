"""Input validation, safe paths, upload checks and prompt-injection risk reduction.

Prompt-injection handling here REDUCES risk; it cannot guarantee that an LLM
will never follow instructions embedded in a document.
"""
from __future__ import annotations

import hashlib
import re
import unicodedata
from pathlib import Path
from typing import Iterable

from .config import SUPPORTED_EXTENSIONS
from .exceptions import FileTooLargeError, SecurityError, UnsupportedFileTypeError, ValidationError

_SAFE_CHARS = re.compile(r"[^A-Za-z0-9._\- ]+")
_ID_RE = re.compile(r"^[A-Za-z0-9_\-]{1,64}$")

# Magic-byte signatures used to catch renamed binaries.
_MAGIC = {
    ".pdf": [b"%PDF"],
    ".docx": [b"PK\x03\x04"],
    ".xlsx": [b"PK\x03\x04"],
}
_TEXT_EXTS = {".txt", ".md", ".markdown", ".csv"}

INJECTION_PATTERNS = [
    r"ignore (all|any|the)? ?(previous|prior|above) (instructions|prompts|rules)",
    r"disregard (all|any|the)? ?(previous|prior|above|system)",
    r"you are now (a|an|in) ",
    r"system prompt",
    r"reveal (your|the) (instructions|prompt|api key|secrets?)",
    r"act as (an? )?(unrestricted|jailbroken|dan)",
    r"<\s*/?\s*(system|assistant|instructions?)\s*>",
    r"begin (new )?instructions",
    r"do not (cite|mention) (the )?sources",
]
_INJECTION_RE = re.compile("|".join(INJECTION_PATTERNS), re.IGNORECASE)


def sanitize_filename(name: str, max_len: int = 120) -> str:
    """Strip directories, control chars and unsafe characters from a filename."""
    if not name:
        raise ValidationError("Empty filename", user_message="The file has no name.")
    name = unicodedata.normalize("NFKC", name).replace("\\", "/").split("/")[-1]
    name = "".join(ch for ch in name if unicodedata.category(ch)[0] != "C")
    name = _SAFE_CHARS.sub("_", name).strip(" .")
    if not name or name in {".", ".."}:
        raise ValidationError("Filename unusable after sanitising", user_message="Invalid filename.")
    stem, dot, ext = name.rpartition(".")
    if dot and len(name) > max_len:
        name = stem[: max_len - len(ext) - 1] + "." + ext
    return name[:max_len]


def ensure_within(base: Path, target: Path) -> Path:
    """Resolve `target` and guarantee it lies inside `base` (path-traversal guard)."""
    base_r = Path(base).resolve()
    target_r = Path(target).resolve()
    if target_r != base_r and base_r not in target_r.parents:
        raise SecurityError(f"Path escapes base dir: {target}", user_message="Unsafe file path rejected.")
    return target_r


def validate_identifier(value: str, kind: str = "id") -> str:
    if not isinstance(value, str) or not _ID_RE.match(value):
        raise ValidationError(f"Invalid {kind}: {value!r}", user_message=f"Invalid {kind}.")
    return value


def file_extension(filename: str) -> str:
    return Path(filename).suffix.lower()


def validate_upload(filename: str, data: bytes, max_size_mb: float) -> str:
    """Validate type, size and content signature. Returns the normalised extension."""
    ext = file_extension(filename)
    if ext not in SUPPORTED_EXTENSIONS:
        raise UnsupportedFileTypeError(
            f"Unsupported extension {ext!r}",
            user_message=f"'{filename}': unsupported type '{ext or 'none'}'. "
                         f"Supported: {', '.join(sorted(SUPPORTED_EXTENSIONS))}.")
    size = len(data)
    if size == 0:
        raise ValidationError("Zero-byte upload", user_message=f"'{filename}' is empty (0 bytes).")
    if size > max_size_mb * 1024 * 1024:
        raise FileTooLargeError(
            f"File {size} bytes exceeds {max_size_mb} MB",
            user_message=f"'{filename}' is {size/1048576:.1f} MB; the limit is {max_size_mb:g} MB.")
    sigs = _MAGIC.get(ext)
    if sigs and not any(data.startswith(s) for s in sigs):
        raise UnsupportedFileTypeError(
            "Content signature mismatch",
            user_message=f"'{filename}' does not look like a real {ext} file.")
    if ext in _TEXT_EXTS and b"\x00" in data[:8192]:
        raise UnsupportedFileTypeError(
            "Binary content in text file", user_message=f"'{filename}' appears to be binary, not text.")
    return ext


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8", errors="replace")).hexdigest()


def detect_injection(text: str) -> list[str]:
    """Return suspicious instruction-like phrases found in untrusted text."""
    return sorted({m.group(0).strip()[:80] for m in _INJECTION_RE.finditer(text or "")})


def neutralize_untrusted(text: str) -> str:
    """Defang delimiter-spoofing so document text cannot close our evidence tags."""
    text = re.sub(r"<\s*/?\s*(evidence|system|assistant|user|instructions?)\b[^>]*>",
                  "[tag removed]", text or "", flags=re.IGNORECASE)
    return text.replace("```", "'''")


def wrap_evidence(passages: Iterable[tuple[int, str, str]]) -> str:
    """Format (marker, source_label, text) triples as clearly delimited untrusted evidence."""
    blocks = []
    for marker, label, body in passages:
        blocks.append(f'<evidence id="{marker}" source="{neutralize_untrusted(label)}">\n'
                      f"{neutralize_untrusted(body)}\n</evidence>")
    return "\n\n".join(blocks)


def clamp_text(text: str, max_chars: int) -> str:
    text = text or ""
    return text if len(text) <= max_chars else text[:max_chars]


PUBLIC_URL_WARNING = (
    "SECURITY NOTICE: A Gradio share link is a public URL. Anyone with the link can use this "
    "app, see uploaded documents' search results, and consume your configured LLM quota. "
    "There is no login. Do not upload confidential documents while sharing, and stop the app "
    "when finished. Colab runtimes are temporary; data is lost when the runtime ends unless "
    "you enable Google Drive persistence."
)

