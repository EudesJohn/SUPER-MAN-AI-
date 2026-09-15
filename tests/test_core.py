"""Core unit tests: units, requirements extraction, calculation engine, tools."""
from __future__ import annotations

import pytest

from core import units
from core.calculation import CalculationEngine
from core.requirements import RequirementsEngine
from core.tools import RiskLevel, ToolDeniedError, ToolRegistry, ToolSpec, make_file_tools


# --------------------------------------------------------------------- #
# Unit engine
# --------------------------------------------------------------------- #
def test_unit_conversion_basic():
    assert units.convert(20, "m/min", "m/s") == pytest.approx(20 / 60)


def test_unit_conversion_kn_to_n():
    assert units.convert(2, "kN", "N") == pytest.approx(2000.0)


def test_unit_conversion_incompatible_raises():
    with pytest.raises(ValueError):
        units.convert(1, "kg", "m")


def test_unknown_unit_raises():
    with pytest.raises(Exception):
        units.parse(1, "not_a_unit")


# --------------------------------------------------------------------- #
# Requirements engine
# --------------------------------------------------------------------- #
SPEC = (
    "Je veux concevoir une machine industrielle capable de transporter 500 kg "
    "a 20 m/min, fonctionnant sous 400 V triphase, avec arret d'urgence, "
    "capteurs de position, automate programmable et interface operateur."
)


def test_extract_mass_and_speed():
    reqs = RequirementsEngine().extract(SPEC)
    by_dim = {}
    for r in reqs:
        if r.value is not None:
            by_dim.setdefault(r.quantity, []).append(r)
    assert any(abs(r.value - 500.0) < 1e-6 for r in by_dim["mass"])
    assert any(abs(r.value - 20 / 60) < 1e-6 for r in by_dim["speed"])
    assert any(abs(r.value - 400.0) < 1e-6 for r in by_dim["voltage"])


def test_extract_qualitative():
    reqs = RequirementsEngine().extract(SPEC)
    quants = {r.quantity for r in reqs}
    assert {"three_phase_supply", "emergency_stop", "position_sensors", "plc", "hmi"} <= quants


def test_extract_english():
    reqs = RequirementsEngine().extract("Design a conveyor with a load of 250 kg and speed 0.5 m/s")
    dims = {r.quantity: r.value for r in reqs if r.value is not None}
    assert dims["mass"] == 250.0
    assert dims["speed"] == pytest.approx(0.5)


def test_detect_gaps():
    reqs = RequirementsEngine().extract("transporter 500 kg")
    gaps = RequirementsEngine.detect_gaps(reqs, ["mass", "speed", "voltage"])
    assert "speed" in gaps and "voltage" in gaps and "mass" not in gaps


# --------------------------------------------------------------------- #
# Calculation engine
# --------------------------------------------------------------------- #
def test_motor_sizing_deterministic():
    eng = CalculationEngine.default_engine()
    rec = eng.run(
        "motor_sizing_from_specs",
        {"mass_si": 500.0, "speed_si": 20 / 60, "friction_coefficient": 0.15, "efficiency": 0.8},
    )
    # F = 500*9.80665*0.15 = 735.5 N ; P = F*v/eta = 735.5*(1/3)/0.8 = 306.5 W
    expected = 500 * 9.80665 * 0.15 * (20 / 60) / 0.8
    assert rec.result == pytest.approx(expected, rel=1e-6)
    assert rec.result_unit == "W"
    assert rec.formula == "P_shaft = (m*g*mu + m*a) * v / eta"


def test_speed_to_rpm():
    eng = CalculationEngine.default_engine()
    rec = eng.run("linear_speed_to_rotational", {"speed_si": 20 / 60, "diameter_si": 0.2})
    expected = (20 / 60) / (3.141592653589793 * 0.2) * 60
    assert rec.result == pytest.approx(expected, rel=1e-6)


def test_shaft_section_modulus_and_stress():
    eng = CalculationEngine.default_engine()
    wz = eng.run("round_solid_section_modulus", {"diameter_si": 0.02})
    expected_wz = 3.141592653589793 * 0.02**3 / 32
    assert wz.result == pytest.approx(expected_wz, rel=1e-9)
    sigma = eng.run(
        "cantilever_bending_stress",
        {"force_si": 735.5, "length_si": 0.1, "section_modulus_si": expected_wz},
    )
    assert sigma.result == pytest.approx(735.5 * 0.1 / expected_wz, rel=1e-9)


def test_unknown_calculator_raises():
    eng = CalculationEngine.default_engine()
    with pytest.raises(KeyError):
        eng.run("does_not_exist", {})


def test_power_with_efficiency_rejects_bad_eta():
    eng = CalculationEngine.default_engine()
    with pytest.raises(ValueError):
        eng.run("power_with_efficiency", {"power_si": 100.0, "efficiency": 0.0})


# --------------------------------------------------------------------- #
# Tool registry / sandbox
# --------------------------------------------------------------------- #
def test_tool_registry_workspace_confinement(tmp_path):
    registry = ToolRegistry(tmp_path / "ws")
    make_file_tools(registry)
    out = registry.execute("write_text", agent="test", path="reports/x.md", content="hello")
    assert (tmp_path / "ws" / "reports" / "x.md").exists()
    assert out["checksum"]

    with pytest.raises(ToolDeniedError):
        registry.execute("write_text", agent="test", path="../outside.md", content="no")


def test_tool_registry_rejects_unknown_tool(tmp_path):
    registry = ToolRegistry(tmp_path)
    with pytest.raises(ToolDeniedError):
        registry.execute("delete_system32", agent="rogue")


def test_critical_tool_disabled_by_default(tmp_path):
    registry = ToolRegistry(tmp_path)

    def dangerous():
        return "boom"

    registry.register(
        ToolSpec(name="run_external", description="external op", risk=RiskLevel.CRITICAL), dangerous
    )
    with pytest.raises(ToolDeniedError):
        registry.execute("run_external", agent="test")
