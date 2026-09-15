"""LLM layer tests - fully offline (httpx MockTransport simulates the NVIDIA API).

No test ever hits the real network; the live call is proven separately in the
session by an explicit API request (kept out of the suite on purpose).
"""
from __future__ import annotations

import json
import os

import httpx
import pytest


def test_load_env(tmp_path, monkeypatch):
    from core.config import load_env

    env_file = tmp_path / ".env"
    env_file.write_text("# comment\nNVIDIA_API_KEY=test-key-123\nQUOTED=\"v a l\"\n", encoding="utf-8")
    monkeypatch.delenv("NVIDIA_API_KEY", raising=False)
    loaded = load_env(env_file)
    assert loaded["NVIDIA_API_KEY"] == "test-key-123"
    assert os.environ["NVIDIA_API_KEY"] == "test-key-123"
    assert loaded["QUOTED"] == "v a l"


def test_parse_json_loose():
    from providers.llm.gateway import _parse_json_loose

    assert _parse_json_loose('```json\n{"a": 1}\n```') == {"a": 1}
    assert _parse_json_loose('blabla {"a": {"b": 2}} tralala') == {"a": {"b": 2}}
    with pytest.raises(ValueError, match="no JSON"):
        _parse_json_loose("pas de json ici")


def _mock_nvidia(handler_payload: dict) -> httpx.MockTransport:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.host == "integrate.api.nvidia.com"
        assert request.headers["Authorization"].startswith("Bearer ")
        body = json.loads(request.content)
        content = handler_payload.get("content", "ok")
        return httpx.Response(200, json={"choices": [{"message": {"role": "assistant", "content": content}}]})

    return httpx.MockTransport(handler)


async def test_nvidia_provider_generate_offline():
    from providers.llm.gateway import NVIDIAProvider

    transport = _mock_nvidia({"content": "reponse simulée"})
    provider = NVIDIAProvider("meta/llama-3.1-70b-instruct", transport=transport)
    provider.api_key = "test-key"
    answer = await provider.generate("question", system="system")
    assert answer == "reponse simulée"


async def test_nvidia_provider_missing_key_raises():
    from providers.llm.gateway import LLMNotConfiguredError, NVIDIAProvider

    provider = NVIDIAProvider("m", api_key_env="DEFINITELY_NOT_SET_ENV_123")
    with pytest.raises(LLMNotConfiguredError):
        await provider.generate("x")


async def test_nvidia_structured_output_with_fences():
    from providers.llm.gateway import NVIDIAProvider

    transport = _mock_nvidia({"content": '```json\n{"sum": 2}\n```'})
    provider = NVIDIAProvider("m", transport=transport)
    provider.api_key = "k"
    assert (await provider.structured_output("1+1", '{"sum": int}')) == {"sum": 2}


def test_make_gateway_mock_and_nvidia(monkeypatch):
    from core.config import AppConfig, LLMConfig
    from providers.llm.gateway import make_gateway_from_config

    # mock -> disabled
    gw, router, notes = make_gateway_from_config(AppConfig(llm=LLMConfig(provider="mock")))
    assert gw is None and router is None

    # nvidia without key -> honest degradation
    monkeypatch.delenv("NVIDIA_API_KEY", raising=False)
    gw, router, notes = make_gateway_from_config(AppConfig(llm=LLMConfig(provider="nvidia")))
    assert gw is None and any("absente" in n for n in notes)

    # nvidia with key -> active
    monkeypatch.setenv("NVIDIA_API_KEY", "k")
    gw, router, notes = make_gateway_from_config(AppConfig(llm=LLMConfig(provider="nvidia")))
    assert gw is not None and router.default == "nvidia"


def test_router_refuses_calculations():
    from providers.llm.gateway import LLMGateway, ModelRouter

    router = ModelRouter(LLMGateway(), default="nvidia")
    with pytest.raises(ValueError, match="CalculationEngine"):
        router.route("calculation")


# --------------------------------------------------------------------------- #
# /ask endpoint (grounded answer)
# --------------------------------------------------------------------------- #
async def test_ask_endpoint_grounded(tmp_path, monkeypatch):
    from apps.api.main import app
    from fastapi.testclient import TestClient

    from core.memory import ProjectMemory
    from core.models import Requirement
    from core.tools import ToolRegistry, make_file_tools
    from providers.llm.gateway import LLMGateway, ModelRouter, NVIDIAProvider

    mem = ProjectMemory(str(tmp_path / "ask.db"))
    pid = mem.create_project("Projet question", "test") ["id"]
    mem.add_requirement(pid, Requirement(description="Charge maximale", quantity="mass",
                                         value=500.0, raw_value="500 kg", unit="kg"))
    ws = tmp_path / "ws"
    ws.mkdir()
    registry = ToolRegistry(ws)
    make_file_tools(registry)

    provider = NVIDIAProvider("m", transport=_mock_nvidia({"content": "La charge maximale est 500 kg."}))
    provider.api_key = "test-key"
    gateway = LLMGateway()
    gateway.register("nvidia", provider)
    monkeypatch.setattr("apps.api.main.STATE", {
        "memory": mem, "llm_gateway": gateway, "llm_router": ModelRouter(gateway, "nvidia"),
        "registry": registry, "bus": None, "calc": None, "config": None,
    })
    # No context manager: the lifespan would overwrite the injected STATE.
    client = TestClient(app)
    r = client.post(f"/projects/{pid}/ask", json={"question": "Quelle est la charge maximale ?"})
    mem.close()
    assert r.status_code == 200
    data = r.json()
    assert "500 kg" in data["answer"]
    assert "grounding" in data


async def test_ask_endpoint_without_llm_returns_400(tmp_path, monkeypatch):
    from apps.api.main import app
    from fastapi.testclient import TestClient

    from core.memory import ProjectMemory
    from core.tools import ToolRegistry, make_file_tools

    mem = ProjectMemory(str(tmp_path / "ask2.db"))
    pid = mem.create_project("Sans LLM", "test")["id"]
    ws = tmp_path / "ws2"
    ws.mkdir()
    registry = ToolRegistry(ws)
    make_file_tools(registry)
    monkeypatch.setattr("apps.api.main.STATE", {
        "memory": mem, "llm_gateway": None, "llm_router": None,
        "registry": registry, "bus": None, "calc": None, "config": None,
    })
    client = TestClient(app)
    # Existing project + design question would run the pipeline without the LLM;
    # a plain question with no LLM configured must honestly return 400.
    r = client.post(f"/projects/{pid}/ask", json={"question": "quelle est la masse ?"})
    mem.close()
    assert r.status_code == 400
