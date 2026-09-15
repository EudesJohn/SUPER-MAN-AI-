"""LLM Gateway (sections 8, 26): provider abstraction, never a hard coupling.

The rest of the system only sees LLMGateway. Providers:
- MockProvider: deterministic offline stub, used in MVP and tests.
- OpenAIProvider / AnthropicProvider: real HTTP calls, only when an API key
  is configured via environment variable. They raise a clear error otherwise.
"""
from __future__ import annotations

import json
import os
from typing import Any

import httpx


class LLMNotConfiguredError(RuntimeError):
    pass


class LLMGateway:
    """Facade. Route requests through the ModelRouter."""

    def __init__(self) -> None:
        self._providers: dict[str, Any] = {}

    def register(self, name: str, provider: Any) -> None:
        self._providers[name] = provider

    def provider(self, name: str) -> Any:
        if name not in self._providers:
            raise LLMNotConfiguredError(f"LLM provider '{name}' is not registered")
        return self._providers[name]

    async def generate(self, provider: str, prompt: str, *, system: str | None = None) -> str:
        return await self.provider(provider).generate(prompt, system=system)

    async def structured_output(self, provider: str, prompt: str, schema_hint: str) -> dict[str, Any]:
        return await self.provider(provider).structured_output(prompt, schema_hint)


class MockProvider:
    """Offline deterministic provider. Never fabricates engineering data:

    it echoes the request structure so pipelines can be tested without a model.
    """

    name = "mock"

    async def generate(self, prompt: str, *, system: str | None = None) -> str:
        return f"[mock-llm] response to: {prompt[:120]}"

    async def structured_output(self, prompt: str, schema_hint: str) -> dict[str, Any]:
        return {"provider": "mock", "prompt": prompt[:200], "schema_hint": schema_hint, "note": "MOCK - not real analysis"}


class OpenAIProvider:
    name = "openai"

    def __init__(self, model: str, api_key_env: str = "OPENAI_API_KEY") -> None:
        self.model = model
        self.api_key = os.environ.get(api_key_env)
        self.api_key_env = api_key_env

    def _headers(self) -> dict[str, str]:
        if not self.api_key:
            raise LLMNotConfiguredError(
                f"environment variable {self.api_key_env} is not set - cannot use OpenAI"
            )
        return {"Authorization": f"Bearer {self.api_key}", "Content-Type": "application/json"}

    async def generate(self, prompt: str, *, system: str | None = None) -> str:
        payload = {
            "model": self.model,
            "messages": ([{"role": "system", "content": system}] if system else [])
            + [{"role": "user", "content": prompt}],
        }
        async with httpx.AsyncClient(timeout=60) as client:
            r = await client.post(
                "https://api.openai.com/v1/chat/completions", headers=self._headers(), json=payload
            )
            r.raise_for_status()
            return r.json()["choices"][0]["message"]["content"]

    async def structured_output(self, prompt: str, schema_hint: str) -> dict[str, Any]:
        raw = await self.generate(f"{prompt}\n\nAnswer ONLY with JSON matching: {schema_hint}")
        return json.loads(raw)


class NVIDIAProvider:
    """NVIDIA NIM / build.nvidia.com API (OpenAI-compatible chat endpoint).

    Key comes from the environment (NVIDIA_API_KEY), never from code.
    The HTTP transport is injectable so tests run offline deterministically.
    """

    name = "nvidia"
    BASE_URL = "https://integrate.api.nvidia.com/v1/chat/completions"

    def __init__(self, model: str, api_key_env: str = "NVIDIA_API_KEY", transport=None) -> None:
        self.model = model
        self.api_key_env = api_key_env
        self.api_key = os.environ.get(api_key_env)
        self._transport = transport  # optional httpx.AsyncBaseTransport (tests)

    def _headers(self) -> dict[str, str]:
        if not self.api_key:
            raise LLMNotConfiguredError(
                f"environment variable {self.api_key_env} is not set - cannot use NVIDIA API"
            )
        return {"Authorization": f"Bearer {self.api_key}", "Accept": "application/json",
                "Content-Type": "application/json"}

    async def generate(self, prompt: str, *, system: str | None = None) -> str:
        payload = {
            "model": self.model,
            "messages": ([{"role": "system", "content": system}] if system else [])
            + [{"role": "user", "content": prompt}],
            "temperature": 0.2,
            "max_tokens": 1024,
        }
        # Reasoning models may think for tens of seconds: generous read timeout.
        timeout = httpx.Timeout(240.0, connect=15.0)
        async with httpx.AsyncClient(timeout=timeout, transport=self._transport) as client:
            r = await client.post(self.BASE_URL, headers=self._headers(), json=payload)
            r.raise_for_status()
            return r.json()["choices"][0]["message"]["content"]

    async def structured_output(self, prompt: str, schema_hint: str) -> dict[str, Any]:
        raw = await self.generate(
            f"{prompt}\n\nReponds UNIQUEMENT avec du JSON valide respectant: {schema_hint}"
        )
        return _parse_json_loose(raw)


def _parse_json_loose(raw: str) -> dict[str, Any]:
    """Parse the first JSON object in a model answer (handles ```json fences)."""
    text = raw.strip()
    if "```" in text:
        for chunk in text.split("```"):
            c = chunk.strip()
            if c.startswith("json"):
                c = c[4:].strip()
            if c.startswith("{"):
                text = c
                break
    start = text.find("{")
    end = text.rfind("}")
    if start == -1 or end == -1:
        raise ValueError(f"model answer contains no JSON object: {raw[:200]!r}")
    return json.loads(text[start : end + 1])


class AnthropicProvider:
    name = "anthropic"

    def __init__(self, model: str, api_key_env: str = "ANTHROPIC_API_KEY") -> None:
        self.model = model
        self.api_key = os.environ.get(api_key_env)
        self.api_key_env = api_key_env

    def _headers(self) -> dict[str, str]:
        if not self.api_key:
            raise LLMNotConfiguredError(
                f"environment variable {self.api_key_env} is not set - cannot use Anthropic"
            )
        return {"x-api-key": self.api_key, "anthropic-version": "2023-06-01"}

    async def generate(self, prompt: str, *, system: str | None = None) -> str:
        payload: dict[str, Any] = {
            "model": self.model,
            "max_tokens": 2048,
            "messages": [{"role": "user", "content": prompt}],
        }
        if system:
            payload["system"] = system
        async with httpx.AsyncClient(timeout=60) as client:
            r = await client.post(
                "https://api.anthropic.com/v1/messages", headers=self._headers(), json=payload
            )
            r.raise_for_status()
            return r.json()["content"][0]["text"]

    async def structured_output(self, prompt: str, schema_hint: str) -> dict[str, Any]:
        raw = await self.generate(f"{prompt}\n\nAnswer ONLY with JSON matching: {schema_hint}")
        return json.loads(raw)


class ModelRouter:
    """Chooses the provider per task kind (section 9).

    Rule enforced here: calculations NEVER go to an LLM - callers must use
    the CalculationEngine. The router only handles language tasks.
    """

    def __init__(self, gateway: LLMGateway, default: str = "mock") -> None:
        self.gateway = gateway
        self.default = default

    def route(self, task_kind: str) -> str:
        if task_kind in ("calculation", "unit_conversion"):
            raise ValueError("calculations must use CalculationEngine, never the LLM")
        return self.default


def make_gateway_from_config(config) -> tuple["LLMGateway | None", "ModelRouter | None", list[str]]:
    """Build the gateway + router from AppConfig.llm. Returns (gateway, router, notes).

    provider 'mock' -> gateway registered but disabled; 'nvidia'/'openai'/'anthropic'
    -> real provider; a missing key degrades honestly to notes, never a fake client.
    """
    notes: list[str] = []
    cfg = config.llm
    gateway = LLMGateway()
    if cfg.provider == "nvidia":
        provider = NVIDIAProvider(cfg.model or "z-ai/glm-5.3-flash")
        if provider.api_key:
            gateway.register("nvidia", provider)
            notes.append(f"LLM nvidia actif (modele {provider.model})")
            return gateway, ModelRouter(gateway, default="nvidia"), notes
        notes.append("NVIDIA_API_KEY absente: LLM desactive (pas de simulation)")
        return None, None, notes
    if cfg.provider in ("openai", "anthropic") and cfg.model:
        provider = (OpenAIProvider if cfg.provider == "openai" else AnthropicProvider)(cfg.model)
        if provider.api_key:  # type: ignore[attr-defined]
            gateway.register(cfg.provider, provider)
            notes.append(f"LLM {cfg.provider} actif (modele {cfg.model})")
            return gateway, ModelRouter(gateway, default=cfg.provider), notes
        notes.append(f"Cle {provider.api_key_env} absente: LLM desactive (pas de simulation)")
        return None, None, notes
    notes.append("LLM en mode mock: raisonnement par moteurs deterministes uniquement")
    return None, None, notes
