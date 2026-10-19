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


class ModelUnavailable(ProviderError):
    """The requested model does not exist / was retired / is not enabled for this key."""


_MODEL_ERROR_HINTS = ("model_not_found", "does not exist", "decommissioned", "model_decommissioned",
                      "not supported", "no access to model", "invalid model")
# Models that cannot do chat completions (speech, moderation, embeddings ...).
_NON_CHAT_HINTS = ("whisper", "tts", "guard", "embed", "distil-whisper", "playai", "orpheus", "safeguard")


def _split_models(value: Optional[str]) -> list[str]:
    return [m.strip() for m in (value or "").split(",") if m.strip()]


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
        # ``model`` / ``model_strong`` may be comma-separated lists tried in order.
        self.models = _split_models(model)
        self.models_strong = _split_models(model_strong) or self.models
        self.model = self.models[0] if self.models else model
        self.model_strong = self.models_strong[0] if self.models_strong else self.model
        self.timeout = timeout
        self._sleep = sleep
        self._discovered: Optional[list[str]] = None

    def complete(self, system: str, user: str, json_mode: bool = False, strong: bool = False) -> str:
        candidates = list(self.models_strong if strong else self.models) or [self.model]
        tried: list[str] = []
        while candidates:
            model = candidates.pop(0)
            if model in tried:
                continue
            tried.append(model)
            try:
                text = self._complete_with(model, system, user, json_mode)
            except ModelUnavailable as exc:
                log.warning("%s: model %s unavailable (%s); trying another model", self.name, model, exc)
                if not candidates:
                    candidates = [m for m in self.list_models() if m not in tried][:5]
                continue
            self._remember(model, strong)
            return text
        raise ProviderError(f"{self.name}: no usable model (tried: {', '.join(tried)})")

    def _remember(self, model: str, strong: bool) -> None:
        """Put the model that worked first, so later calls in this run go straight to it."""
        lst = self.models_strong if strong else self.models
        if model in lst:
            lst.remove(model)
        lst.insert(0, model)
        if strong:
            self.model_strong = model
        else:
            self.model = model

    def list_models(self) -> list[str]:
        """Chat models available to this key (empty if the provider cannot list them)."""
        return []

    def _complete_with(self, model: str, system: str, user: str, json_mode: bool) -> str:
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
            msg = redact(f"{self.name}: HTTP {resp.status_code}: {resp.text[:200]}")
            if resp.status_code in (400, 404) and any(h in resp.text.lower() for h in _MODEL_ERROR_HINTS):
                raise ModelUnavailable(msg)
            raise ProviderError(msg)
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

    def list_models(self) -> list[str]:
        if self._discovered is None:
            self._discovered = []
            try:
                resp = requests.get(f"{self.base_url}/models", timeout=self.timeout,
                                    headers={"Authorization": f"Bearer {self.api_key}"})
                if resp.status_code == 200:
                    ids = [m.get("id", "") for m in resp.json().get("data", []) if m.get("active", True)]
                    self._discovered = [i for i in ids if i and not any(h in i.lower() for h in _NON_CHAT_HINTS)]
                    log.info("%s: available chat models: %s", self.name, ", ".join(self._discovered) or "none")
                else:
                    log.warning("%s: listing models failed: HTTP %s", self.name, resp.status_code)
            except (requests.RequestException, ValueError) as exc:
                log.warning("%s: listing models failed: %s", self.name, redact(exc))
        return list(self._discovered)


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
    if cfg.groq_api_key.startswith("xai-") and not cfg.xai_api_key:
        # An xAI Grok key was put into GROQ_API_KEY; use it as xAI instead of failing.
        log.warning("GROQ_API_KEY looks like an xAI key (xai-...); using it for xAI Grok")
        cfg.xai_api_key, cfg.groq_api_key = cfg.groq_api_key, ""
        if "xai" not in cfg.ai_providers:
            cfg.ai_providers = ["xai", *cfg.ai_providers]
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
