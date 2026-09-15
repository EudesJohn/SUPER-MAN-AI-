"""Shared pytest fixtures."""
from __future__ import annotations

import pytest

from core.calculation import CalculationEngine
from core.events import EventBus
from core.memory import ProjectMemory
from core.tools import ToolRegistry, make_file_tools


@pytest.fixture()
def memory(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    m = ProjectMemory("test.db")
    yield m
    m.close()


@pytest.fixture()
def bus():
    return EventBus()


@pytest.fixture()
def calc(bus):
    return CalculationEngine.default_engine(bus)


@pytest.fixture()
def registry(tmp_path):
    ws = tmp_path / "ws"
    ws.mkdir()
    r = ToolRegistry(ws)
    make_file_tools(r)
    return r
