"""LLM providers called with plain ``requests`` (no SDKs) and a fallback chain."""
from __future__ import annotations

import logging
import time
from typing import Any, Callable, Optional, Sequence

import requests

from ..redact import redact, register_secret

log = logging.getLogger(__name__)

TIMEOUT_S = 60
RETRY_429_BACKOFF_S = 3.0
MAX_RETRY_AFTER_S = 20.0


class ProviderError(RuntimeError):
    pass


class AllProvidersFailed(RuntimeError):
    def __init__(self, errors: list[tuple[str, BaseException]]):
        self.errors = errors
        detail = "; ".join(f"{name}: {redact(err)}" for name, err in errors) or "no providers configured"
        super().__init__(f"All LLM providers failed ({detail})")


class LLMProvider:
    """Base class. Subclasses implement :meth:`_request` and :meth:`_extract`."""

    name = "base"

    def __init__(self, api_key: str, model: str, model_strong: Optional[str] = None,
                 timeout: float = TIMEOUT_S, sleep: Callable[[float], None] = time.sleep):
        self.api_key = api_key
        register_secret(api_key)
        self.model = model
        self.model_strong = model_strong or model
        self.timeout = timeout
        self._sleep = sleep

    def complete(self, system: str, user: str, json_mode: bool = False, strong: bool = False) -> str:
        model = self.model_strong if strong else self.model
        resp = self._post_with_retry(model, system, user, json_mode)
        try:
            text = self._extract(resp.json())
        except (ValueError, KeyError, IndexError, TypeError) as exc:
            raise ProviderError(redact(f"{self.name}: unexpected response shape: {exc}")) from None
        if not text or not text.strip():
            raise ProviderError(f"{self.name}: empty completion")
        return text

    def _post_with_retry(self, model: str, system: str, user: str, json_mode: bool) -> requests.Response:
        resp = self._request(model, system, user, json_mode)
        if resp.status_code == 429:  # one retry with a short backoff
            wait = RETRY_429_BACKOFF_S
            try:
                wait = min(float(resp.headers.get("Retry-After", wait)), MAX_RETRY_AFTER_S)
            except (TypeError, ValueError):
                pass
            log.info("%s rate-limited (429); retrying in %.1fs", self.name, wait)
            self._sleep(wait)
            resp = self._request(model, system, user, json_mode)
        if resp.status_code >= 400:
            raise ProviderError(redact(f"{self.name}: HTTP {resp.status_code}: {resp.text[:200]}"))
        return resp

    def _request(self, model: str, system: str, user: str, json_mode: bool) -> requests.Response:
        raise NotImplementedError

    def _extract(self, data: dict[str, Any]) -> str:
        raise NotImplementedError


class OpenAICompatibleProvider(LLMProvider):
    """Any ``/chat/completions`` endpoint that speaks the OpenAI wire format."""

    base_url = ""

    def _request(self, model: str, system: str, user: str, json_mode: bool) -> requests.Response:
        body: dict[str, Any] = {
            "model": model,
            "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}],
            "temperature": 0.2,
        }
        if json_mode:
            body["response_format"] = {"type": "json_object"}
        return requests.post(
            f"{self.base_url}/chat/completions",
            headers={"Authorization": f"Bearer {self.api_key}", "Content-Type": "application/json"},
            json=body,
            timeout=self.timeout,
        )

    def _extract(self, data: dict[str, Any]) -> str:
        return data["choices"][0]["message"]["content"]


class GroqProvider(OpenAICompatibleProvider):
    name = "groq"
    base_url = "https://api.groq.com/openai/v1"


class XAIProvider(OpenAICompatibleProvider):
    """xAI Grok (optional; enable with AI_PROVIDERS=...,xai and XAI_API_KEY)."""

    name = "xai"
    base_url = "https://api.x.ai/v1"


class GeminiProvider(LLMProvider):
    name = "gemini"
    base_url = "https://generativelanguage.googleapis.com/v1beta"

    def _request(self, model: str, system: str, user: str, json_mode: bool) -> requests.Response:
        gen_cfg: dict[str, Any] = {"temperature": 0.2}
        if json_mode:
            gen_cfg["responseMimeType"] = "application/json"
        body = {
            "systemInstruction": {"parts": [{"text": system}]},
            "contents": [{"role": "user", "parts": [{"text": user}]}],
            "generationConfig": gen_cfg,
        }
        return requests.post(
            f"{self.base_url}/models/{model}:generateContent",
            headers={"x-goog-api-key": self.api_key, "Content-Type": "application/json"},
            json=body,
            timeout=self.timeout,
        )

    def _extract(self, data: dict[str, Any]) -> str:
        parts = data["candidates"][0]["content"]["parts"]
        return "".join(p.get("text", "") for p in parts)


class ProviderChain:
    """Tries providers in order; any exception (HTTP error, timeout, bad JSON) -> next one."""

    def __init__(self, providers: Sequence[LLMProvider]):
        self.providers = list(providers)
        self.last_provider: Optional[str] = None

    def __bool__(self) -> bool:
        return bool(self.providers)

    def complete(self, system: str, user: str, json_mode: bool = False, strong: bool = False) -> str:
        errors: list[tuple[str, BaseException]] = []
        for provider in self.providers:
            try:
                text = provider.complete(system, user, json_mode=json_mode, strong=strong)
                self.last_provider = provider.name
                return text
            except Exception as exc:  # noqa: BLE001 - any failure means "try the next provider"
                log.warning("LLM provider %s failed: %s", provider.name, redact(exc))
                errors.append((provider.name, exc))
        raise AllProvidersFailed(errors)


def build_chain(cfg: Any) -> ProviderChain:
    """Build the chain in ``cfg.ai_providers`` order, skipping providers without an API key."""
    factories: dict[str, Callable[[], Optional[LLMProvider]]] = {
        "groq": lambda: GroqProvider(cfg.groq_api_key, cfg.groq_model, cfg.groq_model_strong)
        if cfg.groq_api_key else None,
        "gemini": lambda: GeminiProvider(cfg.gemini_api_key, cfg.gemini_model, cfg.gemini_model_strong)
        if cfg.gemini_api_key else None,
        "xai": lambda: XAIProvider(cfg.xai_api_key, cfg.xai_model, cfg.xai_model_strong)
        if cfg.xai_api_key else None,
    }
    providers: list[LLMProvider] = []
    for key in cfg.ai_providers:
        factory = factories.get(key)
        if factory is None:
            log.warning("Unknown AI provider %r ignored (known: %s)", key, ", ".join(factories))
            continue
        provider = factory()
        if provider is None:
            log.info("AI provider %s skipped (no API key)", key)
            continue
        providers.append(provider)
    return ProviderChain(providers)
