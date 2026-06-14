from __future__ import annotations

import json
import os
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from typing import Any

from .config import LLMConfig


@dataclass
class LLMResponse:
    text: str
    raw: dict[str, Any] = field(default_factory=dict)


class LLMProvider:
    name = "none"

    @property
    def available(self) -> bool:
        return False

    def complete(self, system: str, user: str) -> LLMResponse:
        raise RuntimeError("No LLM provider is configured.")


class NoopLLMProvider(LLMProvider):
    name = "none"


class OpenAICompatibleChatProvider(LLMProvider):
    name = "openai-compatible-chat"

    def __init__(self, config: LLMConfig):
        self.config = config
        self.endpoint = os.environ.get(config.endpoint_env, "https://api.openai.com/v1/chat/completions")
        self.api_key = os.environ.get(config.api_key_env, "")
        self.model = os.environ.get(config.model_env, "")

    @property
    def available(self) -> bool:
        return bool(self.api_key and self.model)

    def complete(self, system: str, user: str) -> LLMResponse:
        if not self.available:
            raise RuntimeError(
                f"Provider {self.name} requires {self.config.api_key_env} and {self.config.model_env}."
            )
        payload = {
            "model": self.model,
            "temperature": self.config.temperature,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
        }
        request = urllib.request.Request(
            self.endpoint,
            data=json.dumps(payload).encode("utf-8"),
            headers={
                "Authorization": f"Bearer {self.api_key}",
                "Content-Type": "application/json",
            },
            method="POST",
        )
        try:
            with urllib.request.urlopen(request, timeout=self.config.timeout_seconds) as response:
                raw = json.loads(response.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace")
            raise RuntimeError(f"LLM provider HTTP {exc.code}: {detail}") from exc

        try:
            text = raw["choices"][0]["message"]["content"]
        except (KeyError, IndexError, TypeError) as exc:
            raise RuntimeError(f"Unexpected LLM provider response: {raw}") from exc
        return LLMResponse(text=text, raw=raw)


def build_llm_provider(config: LLMConfig) -> LLMProvider:
    provider_name = os.environ.get("AGENTOS_LLM_PROVIDER", config.provider).strip().lower()
    if provider_name in {"", "none", "off", "disabled"}:
        return NoopLLMProvider()
    if provider_name == OpenAICompatibleChatProvider.name:
        return OpenAICompatibleChatProvider(config)
    raise ValueError(f"Unsupported LLM provider: {provider_name}")

