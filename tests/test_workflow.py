"""Integration tests: orchestrator workflow end-to-end (offline, no LLM)."""
from __future__ import annotations

import pytest

from apps.orchestrator import Orchestrator
from core.calculation import CalculationEngine
from core.events import EventBus
from core.memory import ProjectMemory
from core.models import VerificationOutcome
from core.tools import ToolRegistry, make_file_tools
from core.verification import VerificationEngine

SPEC = (
    "Je veux concevoir une machine industrielle capable de transporter 500 kg "
    "a 20 m/min, fonctionnant sous 400 V triphase, avec arret d'urgence, "
    "capteurs de position, automate programmable et interface operateur."
)


@pytest.fixture()
def orch(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    memory = ProjectMemory("test.db")
    bus = EventBus()
    calc = CalculationEngine.default_engine(bus)
    ws = tmp_path / "workspace"
    ws.mkdir()
    registry = ToolRegistry(ws)
    make_file_tools(registry)
    verification = VerificationEngine(memory, bus)
    return Orchestrator(memory, bus, calc, registry, verification)


@pytest.mark.asyncio
async def test_full_workflow(orch):
    project = await orch.create_project("Machine 500 kg", SPEC)
    result = await orch.execute(project["id"], SPEC)

    # Requirements extracted
    assert len(result["requirements"]) >= 6  # mass, speed, voltage + 4 qualitative
    assert result["known_gaps"] == []

    # Power computed deterministically
    expected = 500 * 9.80665 * 0.15 * (20 / 60) / 0.8
    assert result["power_w"] == pytest.approx(expected, rel=1e-6)

    # All tasks succeeded
    assert all(t["status"] in ("SUCCESS",) for t in result["tasks"])

    # Verifications persisted, no FAIL
    assert all(v["outcome"] != "FAIL" for v in result["verifications"])

    # Version created
    assert result["version"]["number"] == 1

    # Report exists on disk
    report = orch.memory.list_artifacts  # not used; report path check below
    from core.report import generate_report

    path = generate_report(project["id"], orch.memory)
    content = open(path, encoding="utf-8").read()
    assert "306" in content or "306.5" in content  # computed power appears


@pytest.mark.asyncio
async def test_verification_fails_undersized_shaft(orch):
    """The spec's exact counter-example: claimed 20 mm shaft vs required."""
    project = await orch.create_project("Shaft check", SPEC)
    pid = project["id"]
    await orch.execute(pid, SPEC)

    from core.models import CalculationRecord

    force = next(c for c in orch.memory.list_calculations(pid) if c["name"] == "motor_sizing_from_specs")
    F = force["inputs"]["mass_si"] * 9.80665 * 0.15
    orch.memory.add_calculation(
        pid,
        CalculationRecord(
            name="claimed_shaft_diameter",
            formula="claim",
            inputs={},
            units={"result": "mm"},
            result=20.0,
            result_unit="mm",
        ),
    )
    results = await orch.verification.verify_project(pid)
    shaft = next(r for r in results if r.subject == "shaft_bending_check")
    assert shaft.outcome == VerificationOutcome.FAIL
    assert "INSUFFICIENT" in shaft.detail


@pytest.mark.asyncio
async def test_missing_values_are_inconnu_not_fabricated(orch):
    project = await orch.create_project("Sparse spec", "Une machine qui transporte des charges.")
    result = await orch.execute(project["id"], "Une machine qui transporte des charges.")
    assert set(result["known_gaps"]) == {"mass", "speed"}


@pytest.mark.asyncio
async def test_events_journal(orch):
    project = await orch.create_project("Events", SPEC)
    await orch.execute(project["id"], SPEC)
    events = orch.memory.list_events(project["id"])
    kinds = {e["kind"] for e in events}
    assert "PROJECT_CREATED" in kinds
    assert "CALCULATION_COMPLETED" in kinds
    assert "TASK_COMPLETED" in kinds
