"""Structured JSON logging with request IDs, timing and secret redaction."""
from __future__ import annotations

import contextvars
import json
import logging
import re
import time
import uuid
from collections import deque
from contextlib import contextmanager
from logging.handlers import RotatingFileHandler
from pathlib import Path
from typing import Any, Iterator, Optional

_request_id: contextvars.ContextVar[str] = contextvars.ContextVar("request_id", default="-")

# Patterns that look like credentials. Redaction is defence-in-depth, not a guarantee.
_SECRET_PATTERNS = [
    re.compile(r"sk-[A-Za-z0-9_\-]{16,}"),
    re.compile(r"gsk_[A-Za-z0-9]{16,}"),
    re.compile(r"AIza[0-9A-Za-z_\-]{20,}"),
    re.compile(r"hf_[A-Za-z0-9]{20,}"),
    re.compile(r"(?i)(api[_-]?key|authorization|bearer|token|password)\s*[:=]\s*\S+"),
]

LOGGER_NAME = "knowledgeos"
_RECENT: deque[dict[str, Any]] = deque(maxlen=500)   # in-memory tail for the diagnostics UI


def redact(text: str) -> str:
    for pat in _SECRET_PATTERNS:
        text = pat.sub("[REDACTED]", text)
    return text


def new_request_id() -> str:
    rid = uuid.uuid4().hex[:12]
    _request_id.set(rid)
    return rid


def current_request_id() -> str:
    return _request_id.get()


class _JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, Any] = {
            "ts": round(record.created, 3),
            "level": record.levelname,
            "logger": record.name,
            "request_id": getattr(record, "request_id", _request_id.get()),
            "msg": redact(record.getMessage()),
        }
        extra = getattr(record, "data", None)
        if isinstance(extra, dict):
            payload["data"] = json.loads(redact(json.dumps(extra, default=str)))
        if record.exc_info:
            payload["exc"] = redact(self.formatException(record.exc_info))[-2000:]
        return json.dumps(payload, ensure_ascii=False)


class _MemoryHandler(logging.Handler):
    def emit(self, record: logging.LogRecord) -> None:
        try:
            _RECENT.append(json.loads(self.format(record)))
        except Exception:  # never let logging crash the app
            pass


def setup_logging(log_dir: Optional[Path] = None, level: str = "INFO") -> logging.Logger:
    """Idempotently configure the 'knowledgeos' logger."""
    logger = logging.getLogger(LOGGER_NAME)
    logger.setLevel(getattr(logging, level.upper(), logging.INFO))
    logger.propagate = False
    for h in list(logger.handlers):
        logger.removeHandler(h)
        h.close()
    fmt = _JsonFormatter()
    mem = _MemoryHandler()
    mem.setFormatter(fmt)
    logger.addHandler(mem)
    if log_dir is not None:
        Path(log_dir).mkdir(parents=True, exist_ok=True)
        fh = RotatingFileHandler(Path(log_dir) / "knowledgeos.log", maxBytes=2_000_000,
                                 backupCount=3, encoding="utf-8")
        fh.setFormatter(fmt)
        logger.addHandler(fh)
    return logger


def get_logger(name: str = "") -> logging.Logger:
    return logging.getLogger(f"{LOGGER_NAME}.{name}" if name else LOGGER_NAME)


def log_event(logger: logging.Logger, msg: str, level: int = logging.INFO, **data: Any) -> None:
    logger.log(level, msg, extra={"data": data, "request_id": _request_id.get()})


def recent_logs(limit: int = 200, min_level: str = "DEBUG") -> list[dict[str, Any]]:
    order = {"DEBUG": 10, "INFO": 20, "WARNING": 30, "ERROR": 40, "CRITICAL": 50}
    floor = order.get(min_level.upper(), 10)
    rows = [r for r in _RECENT if order.get(r.get("level", "INFO"), 20) >= floor]
    return rows[-limit:]


@contextmanager
def timed(logger: logging.Logger, operation: str, sink: Optional[dict[str, float]] = None,
          **data: Any) -> Iterator[None]:
    """Time a block; logs duration and optionally stores ms in `sink[operation]`."""
    start = time.perf_counter()
    try:
        yield
    except Exception as exc:
        ms = (time.perf_counter() - start) * 1000
        log_event(logger, f"{operation} failed", logging.ERROR, duration_ms=round(ms, 1),
                  error=type(exc).__name__, **data)
        raise
    ms = (time.perf_counter() - start) * 1000
    if sink is not None:
        sink[operation] = round(ms, 1)
    log_event(logger, f"{operation} done", logging.DEBUG, duration_ms=round(ms, 1), **data)

