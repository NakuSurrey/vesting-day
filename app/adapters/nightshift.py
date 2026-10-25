"""Model access: Meterless Nightshift (primary) with a deterministic SAMPLE_MODE stand-in.

Nightshift exposes one OpenAI-compatible endpoint on the builder's machine
(METERLESS_BASE_URL, Bearer METERLESS_RUNTIME_TOKEN). The NVIDIA key lives
inside Nightshift, never here. Every response carries a signed Meterless
compute receipt naming the model that did the work - we keep the model name
and receipt id so each generated sentence can show its badge.

Two rules learned the hard way with Nemotron thinking models:
  send reasoning_effort "none" and max_tokens >= 256, or you get empty text.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Optional

import httpx


class ModelError(Exception):
    def __init__(self, message: str, recoverable: bool = True) -> None:
        super().__init__(message)
        self.recoverable = recoverable


@dataclass
class Completion:
    text: str
    model: str            # the model that actually answered (from the response / receipt)
    receipt_id: Optional[str]
    provider: Optional[str]
    usage: dict[str, Any]


class ModelClient:
    """Interface the Writer (and the live match judge) use."""
    badge = "abstract"

    def complete(self, system: str, user: str, max_tokens: int = 768, temperature: float = 0.1) -> Completion:
        raise NotImplementedError


class NightshiftClient(ModelClient):
    def __init__(self, base_url: str, runtime_token: str, model: str, timeout: float = 90.0) -> None:
        self.base_url = base_url.rstrip("/")
        self.token = runtime_token
        self.model = model
        self.badge = model
        self._client = httpx.Client(timeout=timeout)

    def complete(self, system: str, user: str, max_tokens: int = 768, temperature: float = 0.1) -> Completion:
        body = {
            "model": self.model,
            "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}],
            "max_tokens": max(256, max_tokens),
            "temperature": temperature,
            "reasoning_effort": "none",
        }
        headers = {
            "Authorization": f"Bearer {self.token}",
            "meterless-app": "vesting-day",
            "meterless-scope": "user",
            "Content-Type": "application/json",
        }
        try:
            r = self._client.post(f"{self.base_url}/chat/completions", headers=headers, json=body)
        except httpx.HTTPError as e:
            raise ModelError(f"Nightshift unreachable at {self.base_url}: {e}") from e
        if r.status_code >= 400:
            raise ModelError(f"Nightshift returned {r.status_code}: {r.text[:300]}", recoverable=r.status_code >= 500)
        data = r.json()
        try:
            text = data["choices"][0]["message"]["content"] or ""
        except (KeyError, IndexError, TypeError) as e:
            raise ModelError(f"unexpected Nightshift response shape: {str(data)[:300]}") from e
        receipt = data.get("meterless") or {}
        route = receipt.get("winning_route") or {}
        return Completion(
            text=text.strip(),
            model=route.get("model") or data.get("model") or self.model,
            receipt_id=receipt.get("receipt_id"),
            provider=route.get("provider"),
            usage=data.get("usage") or {},
        )

    def list_models(self) -> list[str]:
        r = self._client.get(f"{self.base_url}/models", headers={"Authorization": f"Bearer {self.token}"})
        r.raise_for_status()
        return [m.get("id", "") for m in r.json().get("data", [])]


class TemplateModel(ModelClient):
    """SAMPLE_MODE stand-in. No model, no network. It never writes free prose:
    the Writer agent assembles drafts from computed evidence and this class only
    returns that assembled text, badged so nobody mistakes it for a model."""

    badge = "sample-mode/template"

    def complete(self, system: str, user: str, max_tokens: int = 768, temperature: float = 0.1) -> Completion:
        return Completion(text=user, model=self.badge, receipt_id=None, provider=None, usage={})
