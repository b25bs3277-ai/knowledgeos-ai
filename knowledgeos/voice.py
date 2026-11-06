"""Speech-to-text for the microphone button, using OpenAI Whisper through transformers.

The model downloads on first use (whisper-base ~290 MB on CPU, whisper-small ~970 MB on GPU)
and stays loaded. Audio never leaves this machine.
"""
from __future__ import annotations

import threading
from typing import Optional

from .embeddings import resolve_device
from .exceptions import DependencyError, ValidationError
from .logging_config import get_logger, log_event

log = get_logger("voice")
_LOCK = threading.Lock()
_PIPE: dict[str, object] = {}

VOICE_MODES = [("Keep my language (Hindi stays Hindi)", "transcribe"),
               ("Translate my speech to English", "english")]


def default_model(device: str) -> str:
    return "openai/whisper-small" if device == "cuda" else "openai/whisper-base"


def _pipeline(name: str, device: str):
    with _LOCK:
        if name not in _PIPE:
            try:
                from transformers import pipeline
            except ImportError as e:
                raise DependencyError(str(e), user_message="Voice input needs the transformers package.") from e
            _PIPE.clear()  # keep one speech model in memory
            log_event(log, "loading speech model", model=name, device=device)
            try:
                _PIPE[name] = pipeline("automatic-speech-recognition", model=name,
                                       device=0 if device == "cuda" else -1, chunk_length_s=30)
            except Exception as e:
                raise DependencyError(f"{type(e).__name__}: {e}",
                                      user_message=f"Could not load the speech model '{name}' "
                                                   "(download or memory problem).") from e
        return _PIPE[name]


def transcribe(audio_path: Optional[str], mode: str = "transcribe", device: str = "auto",
               model: Optional[str] = None) -> str:
    """Return the spoken text. mode='english' translates any language to English."""
    if not audio_path:
        raise ValidationError("no audio", user_message="No recording received. Click the mic, speak, then stop.")
    dev = resolve_device(device)
    pipe = _pipeline(model or default_model(dev), dev)
    task = "translate" if mode == "english" else "transcribe"
    try:
        out = pipe(audio_path, generate_kwargs={"task": task})
    except Exception as e:
        raise ValidationError(f"{type(e).__name__}: {e}",
                              user_message="Could not process the recording. Please try again.") from e
    raw = out.get("text") if isinstance(out, dict) else out
    text = str(raw or "").strip()
    if len(text) < 2:
        raise ValidationError("empty", user_message="I couldn't hear anything. Try again, closer to the mic.")
    log_event(log, "transcribed", chars=len(text), task=task)
    return text
