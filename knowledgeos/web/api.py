"""Framework-free logic behind the KnowledgeOS web app: plain dicts in, plain dicts out.

The HTTP layer (server.py) only translates requests to these calls, so everything here
is unit-testable without a browser or a web framework.
"""
from __future__ import annotations

import io
import re
import tempfile
import threading
import time
import uuid
from collections import OrderedDict
from pathlib import Path
from typing import TYPE_CHECKING, Any, Optional

from ..exceptions import KnowledgeOSError, ValidationError, safe_user_message
from ..logging_config import get_logger
from ..pdf_preview import preview
from ..ui.viewer import sources_from_result

if TYPE_CHECKING:
    from ..services import KnowledgeService

log = get_logger("web")

PROVIDERS = [("none", "Off — show matching passages only"),
             ("gemini", "Google Gemini (free key from aistudio.google.com)"),
             ("openai_compatible", "OpenAI-compatible (OpenAI, Groq, …)")]


def _err(e: BaseException) -> dict[str, Any]:
    if not isinstance(e, KnowledgeOSError):
        log.exception("web api error")
    return {"error": safe_user_message(e)}


def speakable(markdown: str, limit: int = 1500) -> str:
    """Answer text suitable for text-to-speech: no citations, markdown symbols or source lists."""
    t = re.split(r"\n\s*\*\*Sources\*\*", markdown or "")[0]
    t = re.sub(r"\[\d+(?:\s*,\s*\d+)*\??\]", "", t)
    t = re.sub(r"[#*_`>|]+", " ", t)
    t = re.sub(r"\s*\n\s*[-•]\s*", ". ", t)
    t = re.sub(r"\s+", " ", t).strip()
    t = re.sub(r"\s+([.,;:!?।])", r"\1", t)          # no space before punctuation
    t = re.sub(r"([.!?।])(?:\s*[.!?।])+", r"\1", t)  # collapse repeated sentence ends
    return t[:limit]


class _LRU(OrderedDict):
    def __init__(self, cap: int) -> None:
        super().__init__()
        self.cap = cap

    def put(self, key: str, value: Any) -> None:
        self[key] = value
        self.move_to_end(key)
        while len(self) > self.cap:
            self.popitem(last=False)


class WebAPI:
    def __init__(self, svc: "KnowledgeService") -> None:
        self.svc = svc
        self._answers = _LRU(300)   # answer id -> sources (for the page viewer)
        self._images = _LRU(60)     # image key -> PNG bytes
        self._jobs: dict[str, dict[str, Any]] = {}
        self._lock = threading.Lock()

    # ------------------------------------------------------------------ state
    def state(self) -> dict[str, Any]:
        s = self.svc.stats()
        docs = [{"doc_id": d.doc_id, "filename": d.filename, "status": d.status, "type": d.file_type,
                 "chunks": d.chunk_count, "size": d.size_bytes, "error": d.error or "",
                 "warnings": d.warnings[:5], "uploaded_at": d.uploaded_at}
                for d in self.svc.list_documents()]
        return {"stats": {k: s[k] for k in ("documents", "ready_documents", "chunks")},
                "provider": s["provider"], "docs": docs,
                "limits": {"max_file_mb": self.svc.settings.max_file_size_mb,
                           "max_files": self.svc.settings.max_files_per_upload}}

    # ------------------------------------------------------------------ ask
    def ask(self, owner: str, conv_id: Optional[str], question: str,
            doc_ids: Optional[list[str]] = None) -> dict[str, Any]:
        try:
            res, cid = self.svc.ask(owner, conv_id or None, question, doc_ids or None)
        except Exception as e:
            return _err(e)
        srcs = sources_from_result(self.svc, res)
        aid = uuid.uuid4().hex[:12]
        with self._lock:
            self._answers.put(aid, srcs)
        markers: dict[str, int] = {}
        for i, s in enumerate(srcs):
            m = re.match(r"\[(\d+)\]", s["label"])
            if m:
                markers[m.group(1)] = i
        display = re.split(r"\n\n\*\*Sources\*\*\n", res.answer)[0]
        if not res.generation_available and res.citations:  # evidence-only answers number their passages
            markers = {str(c.marker): i for i, c in enumerate(res.citations) if i < len(srcs)}
        if res.insufficient_evidence:
            kind = "insufficient"
        elif res.question_type in ("greeting", "meta", "ambiguous"):
            kind = "info"
        elif res.question_type == "general":
            kind = "general"
        elif not res.generation_available:
            kind = "evidence"
        else:
            kind = "grounded" if res.grounded else "unverified"
        return {"aid": aid, "conv_id": cid, "answer": display, "speak": speakable(display), "kind": kind,
                "markers": markers, "warnings": res.warnings[:6], "query": res.standalone_query,
                "timings": res.timings_ms,
                "sources": [{"i": i, "label": s["label"], "filename": s["filename"], "page": s["page"],
                             "cited": s["label"].startswith("[")} for i, s in enumerate(srcs)]}

    # ------------------------------------------------------------------ page viewer
    def source(self, aid: str, i: int, page: Optional[int] = None) -> dict[str, Any]:
        with self._lock:
            srcs = self._answers.get(aid)
        if not srcs or not 0 <= i < len(srcs):
            return {"error": "This answer's sources have expired. Ask the question again."}
        src = srcs[i]
        try:
            rec = self.svc.store.get_document(src["doc_id"])
        except KnowledgeOSError as e:
            return _err(e)
        target = page or src["page"]
        same = target == src["page"]
        pv = preview(rec.stored_path, rec.file_type, target, src["passage"] if same else "",
                     src.get("focus", "") if same else "", rec.filename)
        out: dict[str, Any] = {"filename": rec.filename, "page": pv.page, "n_pages": pv.n_pages,
                               "matched": pv.matched if same else 0, "home_page": src["page"],
                               "html": pv.html, "notes": pv.notes, "image": None}
        if pv.image is not None:
            buf = io.BytesIO()
            pv.image.save(buf, format="PNG", optimize=True)
            key = uuid.uuid4().hex
            with self._lock:
                self._images.put(key, buf.getvalue())
            out["image"] = f"/api/img/{key}"
        return out

    def image(self, key: str) -> Optional[bytes]:
        with self._lock:
            return self._images.get(key)

    # ------------------------------------------------------------------ study
    def study(self, action: str, doc_id: str, count: int = 8) -> dict[str, Any]:
        R = self.svc.research
        tasks = {"summary": lambda: R.summarize_document(doc_id, "medium"),
                 "flashcards": lambda: R.flashcards(doc_id, count),
                 "quiz": lambda: R.quiz(doc_id, min(count, 10)),
                 "notes": lambda: R.study_notes(doc_id, "medium"),
                 "terms": lambda: R.key_terms(doc_id)}
        if action not in tasks:
            return {"error": "Unknown study action."}
        if not doc_id:
            return {"error": "Choose a document first."}
        try:
            r = tasks[action]()
        except Exception as e:
            return _err(e)
        structured = r.structured if r.task in ("flashcards", "quiz") else None
        return {"task": r.task, "title": r.title, "markdown": r.markdown, "items": structured,
                "warnings": r.warnings[:6], "used_llm": r.used_llm}

    # ------------------------------------------------------------------ settings
    def settings(self) -> dict[str, Any]:
        s = self.svc.settings
        return {"provider": s.llm_provider, "providers": PROVIDERS, "gemini_model": s.gemini_model,
                "llm_model": s.llm_model, "llm_base_url": s.llm_base_url,
                "keys": {p: self.svc.secrets.masked(p) for p in ("gemini", "openai_compatible")},
                "status": self.svc.provider_status(), "timeout": s.request_timeout_s}

    def save_settings(self, provider: str, model: str = "", key: str = "", base_url: str = "") -> dict[str, Any]:
        provider = provider if provider in {p for p, _ in PROVIDERS} else "none"
        changes: dict[str, Any] = {"llm_provider": provider}
        model = (model or "").strip()
        if provider == "gemini" and model:
            changes["gemini_model"] = model
        if provider == "openai_compatible":
            if model:
                changes["llm_model"] = model
            if (base_url or "").strip():
                changes["llm_base_url"] = base_url.strip()
        try:
            self.svc.update_settings(**changes)
            if (key or "").strip() and provider in ("gemini", "openai_compatible"):
                self.svc.set_api_key(provider, key)
        except ValueError as e:
            return {"error": f"Not saved: {e}"}
        except Exception as e:
            return _err(e)
        return {"ok": True, **self.settings()}

    def test_provider(self) -> dict[str, Any]:
        prov = self.svc.provider
        ok, why = prov.available()
        if not ok:
            return {"ok": False, "message": why}
        t0 = time.perf_counter()
        try:
            out = prov.generate([{"role": "user", "content": "Reply with the single word OK."}], 0.0, 8,
                                min(self.svc.settings.request_timeout_s, 120))
        except KnowledgeOSError as e:
            return {"ok": False, "message": safe_user_message(e)}
        return {"ok": True, "message": f"Connected · replied in {(time.perf_counter() - t0) * 1000:.0f} ms "
                                       f"({out.strip()[:30]!r})"}

    # ------------------------------------------------------------------ library
    def start_upload(self, files: list[tuple[str, bytes]]) -> dict[str, Any]:
        if not files:
            return {"error": "Choose at least one file."}
        if len(files) > self.svc.settings.max_files_per_upload:
            return {"error": f"Too many files; the limit is {self.svc.settings.max_files_per_upload} at a time."}
        jid = uuid.uuid4().hex[:10]
        job = {"id": jid, "progress": 0.0, "message": "Starting…", "done": False, "reports": []}
        self._jobs[jid] = job

        def run() -> None:
            n = len(files)
            for k, (name, data) in enumerate(files):
                def prog(f: float, msg: str, k: int = k, name: str = name) -> None:
                    job["progress"] = round((k + max(0.0, min(f, 1.0))) / n, 3)
                    job["message"] = f"{name}: {msg}"
                job["message"] = f"{name}: uploading"
                try:
                    r = self.svc.ingest_bytes(name, data, progress=prog)
                    job["reports"].append({"filename": r.filename, "status": r.status, "message": r.message,
                                           "chunks": r.chunks, "warnings": r.warnings[:3]})
                except Exception as e:  # never leave a job hanging
                    log.exception("upload job failed")
                    job["reports"].append({"filename": name, "status": "failed", "message": safe_user_message(e),
                                           "chunks": 0, "warnings": []})
            job.update(progress=1.0, message="Done", done=True)

        threading.Thread(target=run, daemon=True).start()
        return {"job": jid}

    def job(self, jid: str) -> dict[str, Any]:
        j = self._jobs.get(jid)
        return dict(j) if j else {"error": "Unknown upload job."}

    def delete_doc(self, doc_id: str) -> dict[str, Any]:
        try:
            return {"ok": True, "message": self.svc.delete_document(doc_id, confirm=True)}
        except Exception as e:
            return _err(e)

    # ------------------------------------------------------------------ voice (server-side fallback)
    def transcribe(self, data: bytes, suffix: str = ".webm", mode: str = "transcribe") -> dict[str, Any]:
        from ..voice import transcribe
        if not data:
            return _err(ValidationError("empty", user_message="No audio received."))
        suffix = suffix if re.fullmatch(r"\.[a-z0-9]{2,5}", suffix or "") else ".webm"
        with tempfile.NamedTemporaryFile(suffix=suffix, delete=False) as f:
            f.write(data)
            path = f.name
        try:
            return {"text": transcribe(path, mode, self.svc.settings.device)}
        except Exception as e:
            return _err(e)
        finally:
            Path(path).unlink(missing_ok=True)
