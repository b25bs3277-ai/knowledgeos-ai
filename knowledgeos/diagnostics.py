"""Dependency, resource, configuration and index diagnostics.

The report never includes API keys (only 'set'/'not set'), document text, or
conversation content. Log messages are passed through the secret redactor.
"""
from __future__ import annotations

import importlib
import json
import platform
import shutil
import sys
import time
from typing import TYPE_CHECKING, Any

from .config import VERSION, Settings
from .logging_config import recent_logs, redact

if TYPE_CHECKING:
    from .services import KnowledgeService

REQUIRED = ["gradio", "sentence_transformers", "transformers", "torch", "numpy", "pandas",
            "pypdf", "docx", "openpyxl", "requests", "psutil"]
OPTIONAL = {"pytesseract": "OCR for scanned PDFs", "pypdfium2": "PDF page rendering for OCR",
            "pytest": "running the test suite"}


def _version(mod: str) -> str | None:
    try:
        return str(getattr(importlib.import_module(mod), "__version__", "installed"))
    except Exception:
        return None


def dependency_report() -> dict[str, Any]:
    req = {m: _version(m) for m in REQUIRED}
    opt = {m: {"version": _version(m), "purpose": p} for m, p in OPTIONAL.items()}
    return {"python": sys.version.split()[0], "platform": platform.platform(), "required": req,
            "missing_required": [m for m, v in req.items() if v is None], "optional": opt,
            "tesseract_binary": bool(shutil.which("tesseract"))}


def resource_report(settings: Settings) -> dict[str, Any]:
    out: dict[str, Any] = {"warnings": []}
    try:
        import psutil

        vm = psutil.virtual_memory()
        out["ram_total_gb"] = round(vm.total / 1e9, 2)
        out["ram_available_gb"] = round(vm.available / 1e9, 2)
        out["process_rss_gb"] = round(psutil.Process().memory_info().rss / 1e9, 2)
        if vm.available < 1.5e9:
            out["warnings"].append("Less than 1.5 GB RAM free: avoid the local LLM and lower the embedding batch size.")
    except Exception as e:
        out["ram_error"] = type(e).__name__
    try:
        du = shutil.disk_usage(settings.data_path)
        out["disk_free_gb"] = round(du.free / 1e9, 2)
        if du.free < 2e9:
            out["warnings"].append("Less than 2 GB disk free in the data directory.")
    except OSError as e:
        out["disk_error"] = type(e).__name__
    try:
        import torch

        out["cuda_available"] = torch.cuda.is_available()
        if torch.cuda.is_available():
            free, total = torch.cuda.mem_get_info()
            out["gpu"] = torch.cuda.get_device_name(0)
            out["gpu_free_gb"], out["gpu_total_gb"] = round(free / 1e9, 2), round(total / 1e9, 2)
    except Exception:
        out["cuda_available"] = False
    try:
        out["data_dir_size_mb"] = round(sum(p.stat().st_size for p in settings.data_path.rglob("*")
                                            if p.is_file()) / 1e6, 2)
    except OSError:
        pass
    return out


def config_report(service: "KnowledgeService") -> dict[str, Any]:
    s = service.settings
    return {"version": VERSION, "settings": s.to_dict(), "problems": s.validate(),
            "provider": service.provider_status(),
            "api_keys": {p: service.secrets.masked(p) for p in ("openai_compatible", "gemini")}}


def error_summary(limit: int = 50) -> list[dict[str, Any]]:
    return [{"ts": r.get("ts"), "request_id": r.get("request_id"), "logger": r.get("logger"),
             "msg": redact(str(r.get("msg", "")))[:300],
             "category": (r.get("data") or {}).get("category") or (r.get("data") or {}).get("error")}
            for r in recent_logs(limit * 4, "WARNING")][-limit:]


def full_report(service: "KnowledgeService") -> dict[str, Any]:
    return {"generated_at": time.strftime("%Y-%m-%d %H:%M:%S"), "config": config_report(service),
            "dependencies": dependency_report(), "resources": resource_report(service.settings),
            "index": service.index_health(), "counts": service.store.counts(),
            "recent_warnings_and_errors": error_summary(),
            "privacy": "No API keys, document text or conversation content are included."}


def report_json(service: "KnowledgeService") -> str:
    return redact(json.dumps(full_report(service), indent=2, default=str))

