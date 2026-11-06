"""Pluggable LLM providers behind one small interface.

Providers: none (no generation), openai_compatible (OpenAI, Groq, Together, local
OpenAI-style servers…), gemini (Google AI Studio), local_hf (small HF model on
this machine) and mock (tests only). API keys are read from SecretStore at call
time and are never logged or persisted.
"""
from __future__ import annotations

import json
import threading
import time
from abc import ABC, abstractmethod
from typing import Callable, Iterator, Optional

import requests

from .config import SecretStore, Settings
from .exceptions import GenerationError, GenerationTimeoutError, ProviderUnavailableError
from .logging_config import get_logger, log_event

log = get_logger("llm")
Messages = list[dict[str, str]]  # [{"role": "system"|"user"|"assistant", "content": str}]


def estimate_tokens(text: str) -> int:
    """Rough estimate (≈4 chars/token). Used for budgeting and cost display only."""
    return max(1, len(text or "") // 4)


def estimate_cost(tokens_in: int, tokens_out: int, usd_per_m_in: float, usd_per_m_out: float) -> float:
    """Cost from user-supplied prices (USD per million tokens). We ship no price table,
    because provider prices change; the Evaluation Lab asks the user for them."""
    return round(tokens_in / 1e6 * usd_per_m_in + tokens_out / 1e6 * usd_per_m_out, 6)


class LLMProvider(ABC):
    name = "base"

    def __init__(self, model: str = "") -> None:
        self.model = model

    @abstractmethod
    def available(self) -> tuple[bool, str]:
        """(usable?, human-readable reason). Must be cheap: no network calls."""

    @abstractmethod
    def generate(self, messages: Messages, temperature: float, max_tokens: int, timeout: int) -> str: ...

    def stream(self, messages: Messages, temperature: float, max_tokens: int, timeout: int) -> Iterator[str]:
        yield self.generate(messages, temperature, max_tokens, timeout)

    def label(self) -> str:
        return f"{self.name}:{self.model}" if self.model else self.name


class NoneProvider(LLMProvider):
    name = "none"

    def available(self) -> tuple[bool, str]:
        return False, ("No answer-generation provider is configured. KnowledgeOS will show the most "
                       "relevant passages instead. Configure a provider in Settings → Generation.")

    def generate(self, messages: Messages, temperature: float, max_tokens: int, timeout: int) -> str:
        raise ProviderUnavailableError("No provider", user_message=self.available()[1])


class MockProvider(LLMProvider):
    """Deterministic provider for tests. `responder(messages) -> str`."""

    name = "mock"

    def __init__(self, responder: Callable[[Messages], str], model: str = "mock-1") -> None:
        super().__init__(model)
        self.responder = responder
        self.calls: list[Messages] = []

    def available(self) -> tuple[bool, str]:
        return True, "mock provider (tests only)"

    def generate(self, messages: Messages, temperature: float, max_tokens: int, timeout: int) -> str:
        self.calls.append(messages)
        return self.responder(messages)

    def stream(self, messages: Messages, temperature: float, max_tokens: int, timeout: int) -> Iterator[str]:
        text = self.generate(messages, temperature, max_tokens, timeout)
        for i in range(0, len(text), 24):
            yield text[i:i + 24]


def _http_error(provider: str, resp: requests.Response) -> GenerationError:
    code = resp.status_code
    if code in (401, 403):
        return ProviderUnavailableError(f"{provider} auth failed ({code})",
                                        user_message=f"{provider}: the API key was rejected. Check it in Settings.")
    if code == 404:
        return GenerationError(f"{provider} 404", user_message=f"{provider}: model or endpoint not found. Check the model name/base URL.")
    if code == 429:
        return GenerationError(f"{provider} 429", user_message=f"{provider}: rate limit or quota exceeded. Wait and retry.")
    return GenerationError(f"{provider} HTTP {code}", user_message=f"{provider}: request failed (HTTP {code}).")


class OpenAICompatibleProvider(LLMProvider):
    name = "openai_compatible"

    def __init__(self, model: str, base_url: str, key_fn: Callable[[], Optional[str]]) -> None:
        super().__init__(model)
        self.base_url = base_url.rstrip("/")
        self._key_fn = key_fn

    def available(self) -> tuple[bool, str]:
        if not self.base_url.startswith(("https://", "http://localhost", "http://127.0.0.1")):
            return False, "Base URL must use https:// (or http://localhost for a local server)."
        if not self._key_fn():
            return False, "No API key set for the OpenAI-compatible provider (Settings → Generation)."
        return True, f"{self.model} via {self.base_url}"

    def _post(self, payload: dict, timeout: int, stream: bool) -> requests.Response:
        ok, why = self.available()
        if not ok:
            raise ProviderUnavailableError(why, user_message=why)
        try:
            r = requests.post(f"{self.base_url}/chat/completions", json=payload, stream=stream,
                              timeout=(10, timeout),
                              headers={"Authorization": f"Bearer {self._key_fn()}", "Content-Type": "application/json"})
        except requests.Timeout as e:
            raise GenerationTimeoutError("timeout", user_message=f"The provider did not respond within {timeout}s.") from e
        except requests.RequestException as e:
            raise GenerationError(type(e).__name__, user_message="Could not reach the generation provider (network error).") from e
        if r.status_code != 200:
            err = _http_error("OpenAI-compatible provider", r)
            r.close()
            raise err
        return r

    def generate(self, messages: Messages, temperature: float, max_tokens: int, timeout: int) -> str:
        r = self._post({"model": self.model, "messages": messages, "temperature": temperature,
                        "max_tokens": max_tokens}, timeout, stream=False)
        try:
            return r.json()["choices"][0]["message"]["content"] or ""
        except (ValueError, KeyError, IndexError) as e:
            raise GenerationError("bad response shape", user_message="Provider returned an unexpected response.") from e

    def stream(self, messages: Messages, temperature: float, max_tokens: int, timeout: int) -> Iterator[str]:
        deadline = time.time() + timeout
        r = self._post({"model": self.model, "messages": messages, "temperature": temperature,
                        "max_tokens": max_tokens, "stream": True}, timeout, stream=True)
        with r:
            for line in r.iter_lines(decode_unicode=True):
                if time.time() > deadline:
                    raise GenerationTimeoutError("stream timeout", user_message=f"Generation exceeded {timeout}s and was stopped.")
                if not line or not line.startswith("data:"):
                    continue
                data = line[5:].strip()
                if data == "[DONE]":
                    break
                try:
                    delta = json.loads(data)["choices"][0].get("delta", {}).get("content")
                except (ValueError, KeyError, IndexError):
                    continue
                if delta:
                    yield delta



class GeminiProvider(LLMProvider):
    name = "gemini"
    BASE = "https://generativelanguage.googleapis.com/v1beta/models"

    def __init__(self, model: str, key_fn: Callable[[], Optional[str]]) -> None:
        super().__init__(model)
        self._key_fn = key_fn

    def available(self) -> tuple[bool, str]:
        return (True, f"Gemini {self.model}") if self._key_fn() else \
            (False, "No Gemini API key set (Settings → Generation).")

    def _payload(self, messages: Messages, temperature: float, max_tokens: int) -> dict:
        system = "\n\n".join(m["content"] for m in messages if m["role"] == "system")
        contents = [{"role": "model" if m["role"] == "assistant" else "user", "parts": [{"text": m["content"]}]}
                    for m in messages if m["role"] != "system"]
        body: dict = {"contents": contents,
                      "generationConfig": {"temperature": temperature, "maxOutputTokens": max_tokens}}
        if system:
            body["systemInstruction"] = {"parts": [{"text": system}]}
        return body

    def _request(self, method: str, payload: dict, timeout: int, stream: bool) -> requests.Response:
        ok, why = self.available()
        if not ok:
            raise ProviderUnavailableError(why, user_message=why)
        url = f"{self.BASE}/{self.model}:{method}" + ("?alt=sse" if stream else "")
        try:
            r = requests.post(url, json=payload, stream=stream, timeout=(10, timeout),
                              headers={"x-goog-api-key": self._key_fn(), "Content-Type": "application/json"})
        except requests.Timeout as e:
            raise GenerationTimeoutError("timeout", user_message=f"Gemini did not respond within {timeout}s.") from e
        except requests.RequestException as e:
            raise GenerationError(type(e).__name__, user_message="Could not reach Gemini (network error).") from e
        if r.status_code != 200:
            err = _http_error("Gemini", r)
            r.close()
            raise err
        return r

    @staticmethod
    def _text(obj: dict) -> str:
        try:
            parts = obj["candidates"][0]["content"]["parts"]
            return "".join(p.get("text", "") for p in parts)
        except (KeyError, IndexError):
            return ""

    def generate(self, messages: Messages, temperature: float, max_tokens: int, timeout: int) -> str:
        r = self._request("generateContent", self._payload(messages, temperature, max_tokens), timeout, False)
        try:
            return self._text(r.json())
        except ValueError as e:
            raise GenerationError("bad json", user_message="Gemini returned an unexpected response.") from e

    def stream(self, messages: Messages, temperature: float, max_tokens: int, timeout: int) -> Iterator[str]:
        deadline = time.time() + timeout
        r = self._request("streamGenerateContent", self._payload(messages, temperature, max_tokens), timeout, True)
        with r:
            for line in r.iter_lines(decode_unicode=True):
                if time.time() > deadline:
                    raise GenerationTimeoutError("stream timeout", user_message=f"Generation exceeded {timeout}s.")
                if line and line.startswith("data:"):
                    try:
                        piece = self._text(json.loads(line[5:].strip()))
                    except ValueError:
                        continue
                    if piece:
                        yield piece


class LocalHFProvider(LLMProvider):
    """Small instruction model run with transformers. Slow on CPU (tens of seconds)."""

    name = "local_hf"
    _shared: dict[str, tuple] = {}
    _lock = threading.Lock()

    def __init__(self, model: str, device: str = "auto") -> None:
        super().__init__(model)
        from .embeddings import resolve_device
        self.device = resolve_device(device)

    def available(self) -> tuple[bool, str]:
        try:
            import torch  # noqa: F401
            import transformers  # noqa: F401
        except ImportError:
            return False, "transformers/torch not installed."
        note = "" if self.device == "cuda" else " (CPU: expect slow answers)"
        return True, f"local {self.model} on {self.device}{note}"

    def _load(self):
        with self._lock:
            if self.model not in self._shared:
                self._shared.clear()  # one local LLM in memory at a time
                from transformers import AutoModelForCausalLM, AutoTokenizer
                log_event(log, "loading local LLM", model=self.model, device=self.device)
                try:
                    tok = AutoTokenizer.from_pretrained(self.model)
                    mdl = AutoModelForCausalLM.from_pretrained(self.model).to(self.device)
                    mdl.eval()
                except Exception as e:
                    raise ProviderUnavailableError(
                        f"local load failed: {type(e).__name__}",
                        user_message=f"Could not load local model '{self.model}' (download or memory problem).") from e
                self._shared[self.model] = (tok, mdl)
            return self._shared[self.model]

    def _inputs(self, messages: Messages):
        tok, mdl = self._load()
        prompt = tok.apply_chat_template(messages, tokenize=False, add_generation_prompt=True)
        return tok, mdl, tok(prompt, return_tensors="pt").to(self.device)

    def _gen_kwargs(self, temperature: float, max_tokens: int, tok) -> dict:
        kw = {"max_new_tokens": max_tokens, "pad_token_id": tok.pad_token_id or tok.eos_token_id}
        if temperature > 0:
            kw.update(do_sample=True, temperature=temperature, top_p=0.9)
        else:
            kw.update(do_sample=False)
        return kw

    def generate(self, messages: Messages, temperature: float, max_tokens: int, timeout: int) -> str:
        return "".join(self.stream(messages, temperature, max_tokens, timeout))

    def stream(self, messages: Messages, temperature: float, max_tokens: int, timeout: int) -> Iterator[str]:
        from transformers import TextIteratorStreamer

        tok, mdl, inputs = self._inputs(messages)
        streamer = TextIteratorStreamer(tok, skip_prompt=True, skip_special_tokens=True, timeout=timeout)
        errors: list[BaseException] = []

        def run() -> None:
            try:
                mdl.generate(**inputs, streamer=streamer, **self._gen_kwargs(temperature, max_tokens, tok))
            except BaseException as e:  # surfaced below, never swallowed
                errors.append(e)
                streamer.end()

        threading.Thread(target=run, daemon=True).start()
        try:
            for piece in streamer:
                yield piece
        except Exception as e:  # queue.Empty on timeout
            raise GenerationTimeoutError("local timeout", user_message=f"Local model exceeded {timeout}s per step.") from e
        if errors:
            e = errors[0]
            msg = "Local model ran out of memory." if "out of memory" in str(e).lower() else "Local generation failed."
            raise GenerationError(type(e).__name__, user_message=msg) from e


def build_provider(settings: Settings, secrets: SecretStore) -> LLMProvider:
    p = settings.llm_provider
    if p == "openai_compatible":
        return OpenAICompatibleProvider(settings.llm_model, settings.llm_base_url,
                                        lambda: secrets.get("openai_compatible"))
    if p == "gemini":
        return GeminiProvider(settings.gemini_model, lambda: secrets.get("gemini"))
    if p == "local_hf":
        return LocalHFProvider(settings.local_model, settings.device)
    return NoneProvider()

