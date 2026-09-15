"""Tests: hyper-aerodynamic EV car (scenario, HV network, shell masses, 3D,
deliverables, /car endpoint). Offline and deterministic."""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from core.calculation import CalculationEngine
from core.ev_design import design_hv_network
from core.ev_scenario import design_ev_scenario, parametric_spec
from providers.cad.aero_car import AERO_DEFAULTS, build_aero_car
from providers.cad.mesh import box
from providers.cad.solver import shell_mass

from apps.api.main import STATE, app
from core.components import ComponentResearcher
from core.config import AppConfig
from core.events import EventBus
from core.memory import ProjectMemory
from core.tools import ToolRegistry, make_file_tools
from core.verification import VerificationEngine


# --------------------------------------------------------------------------- #
# Scenario (aero + powertrain + battery)
# --------------------------------------------------------------------------- #
def test_scenario_is_coherent(calc):
    sc = design_ev_scenario(calc)
    co = sc["consistency"]
    assert co["motor_ok"], f"required {co['required_motor_kw']} kW > chosen"
    assert co["range_ok"], f"range {co['range_km']} km < target"
    assert 650 <= co["range_km"] <= 950        # 95 kWh / 118 Wh/km ~ 805 km
    assert 500 <= co["pack_mass_kg"] <= 700    # 95 kWh / 0.16 kWh/kg ~ 594 kg


def test_scenario_detects_underpowered_motor(calc):
    sc = design_ev_scenario(calc, motor_kw=100.0)
    assert not sc["consistency"]["motor_ok"]


# --------------------------------------------------------------------------- #
# HV network (800 V class)
# --------------------------------------------------------------------------- #
def test_hv_network_800v(calc):
    hv = design_hv_network(calc, system_voltage=800.0, motor_kw=480.0)
    assert hv["system_voltage"] == 800.0
    big = next(c for c in hv["circuits"] if c["name"] == "hv_battery_to_inverter")
    # 480 kW at 800 V / 0.97 eff ~ 618 A: parallel conductors mandatory
    assert big["parallel_per_pole"] >= 2
    assert big["drop_pct"] <= 2.0 + 1e-9
    assert big["fuse_a"] <= big["capacity_a"]


def test_hv_network_refuses_impossible_request(calc):
    with pytest.raises(ValueError):
        design_hv_network(calc, system_voltage=800.0, motor_kw=20000.0)


# --------------------------------------------------------------------------- #
# Shell mass model
# --------------------------------------------------------------------------- #
def test_shell_mass_is_area_times_thickness():
    b = box(2.0, 1.0, 0.5)   # surface 2*(2*1 + 2*0.5 + 1*0.5) = 7 m2
    mp = shell_mass(b, 1600.0, 0.003)
    assert mp.surface_area_m2 == pytest.approx(7.0, rel=1e-6)
    assert mp.mass_kg == pytest.approx(7.0 * 0.003 * 1600.0, rel=1e-6)
    assert mp.shell


# --------------------------------------------------------------------------- #
# 3D build plausibility (the 6-tonne-body regression guard)
# --------------------------------------------------------------------------- #
@pytest.fixture(scope="module")
def car_build():
    calc = CalculationEngine.default_engine(EventBus())
    sc = design_ev_scenario(calc)
    return sc, build_aero_car(parametric_spec(sc))


def test_total_mass_is_physically_plausible(car_build):
    sc, b = car_build
    total = sum(p["mass_kg"] for p in b.parts)
    # target mass 1780 kg +-30%: catches both absurd modes (solid body ~6 t,
    # missing pack ~1.0 t)
    assert 1250 <= total <= 2320, f"total mass {total} kg implausible"


def test_battery_pack_present_and_heavy(car_build):
    _, b = car_build
    pack = next(p for p in b.parts if p["name"] == "hv_battery_pack")
    assert 500 <= pack["mass_kg"] <= 700     # from the scenario's kWh
    assert pack["group"] == "structure"


def test_body_is_a_shell_panel(car_build):
    _, b = car_build
    body = next(p for p in b.parts if p["name"] == "monovolume_teardrop_body")
    assert body["shell_thickness_mm"] == 3.0
    assert 30 <= body["mass_kg"] <= 120      # real CFRP monocoque panels


def test_all_parts_have_positive_mass_and_com(car_build):
    _, b = car_build
    assert len(b.parts) >= 25
    assert len({p["name"] for p in b.parts}) == len(b.parts), "duplicate part names"
    for p in b.parts:
        assert p["mass_kg"] > 0, p["name"]
        # CoM must sit within the car bounding box (nose ~ +2300 mm, tail ~ -950 mm).
        x_mm = p["center_of_mass_mm"][0]
        assert abs(x_mm) <= 2600, (p["name"], x_mm)


def test_aero_defaults_match_scenario(calc):
    sc = design_ev_scenario(calc)
    assert sc["scenario"]["cd"] == AERO_DEFAULTS["cd"]
    assert sc["scenario"]["frontal_area_m2"] == AERO_DEFAULTS["frontal_area_m2"]


# --------------------------------------------------------------------------- #
# Independent verification: HV rules + a deliberate FAIL
# --------------------------------------------------------------------------- #
def test_hv_verification_passes_real_design(memory, bus, calc):
    import asyncio

    mem = memory
    prj = mem.create_project("hv-test")
    hv = design_hv_network(calc, system_voltage=800.0, motor_kw=480.0)
    results = asyncio.run(
        VerificationEngine(mem, bus).verify_hv_design(prj["id"], hv))
    assert results, "no HV verification rules ran"
    assert all(r.outcome.value == "PASS" for r in results), \
        [f"{r.subject}: {r.detail}" for r in results]


def test_hv_verification_fails_broken_design(memory, bus, calc):
    import asyncio

    mem = memory
    prj = mem.create_project("hv-broken")
    hv = design_hv_network(calc, system_voltage=800.0, motor_kw=480.0)
    # Sabotage: claim an absurdly small conductor for the main link.
    hv["circuits"][0]["gauge_mm2"] = 1.5
    results = asyncio.run(
        VerificationEngine(mem, bus).verify_hv_design(prj["id"], hv))
    assert any(r.outcome.value == "FAIL" for r in results), \
        [f"{r.subject}: {r.outcome}" for r in results]


# --------------------------------------------------------------------------- #
# End-to-end through the API
# --------------------------------------------------------------------------- #
@pytest.fixture()
def client(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    STATE.clear()
    monkeypatch.setenv("AI_ENGINEER_TEST", "1")
    with TestClient(app) as c:
        STATE["config"] = AppConfig()
        STATE["component_researcher"] = None
        STATE["orchestrator"].component_researcher = None
        yield c


def test_car_endpoint_end_to_end(client):
    prj = client.post("/projects", json={"name": "Voiture", "description": "aero EV"}).json()
    pid = prj["id"]
    r = client.post(f"/projects/{pid}/car", json={})
    assert r.status_code == 200, r.text
    d = r.json()
    assert d["kind"] == "aero_car"
    assert d["scenario"]["consistency"]["motor_ok"]
    total = d["cad"]["total_mass_kg"]
    assert 1250 <= total <= 2320, f"total mass {total} implausible"
    assert d["deliverables"]["parts_count"] == len(d["cad"]["parts"])
    # ZIP + 3D assembly downloadable
    zip_path = d["deliverables"]["zip"]
    got = client.get(f"/artifacts/{pid}/{zip_path.split('/', 1)[1]}")
    assert got.status_code == 200
    assert got.headers["content-type"] == "application/zip"
    # HV + LV verifications all ran
    subjects = {v["subject"] for v in d["verifications"]}
    assert any(s.startswith("hv_") for s in subjects), subjects
    # version created
    assert d["version"]["number"] >= 1


def test_car_endpoint_requires_project(client):
    r = client.post("/projects/PRJ-inconnu/car", json={})
    assert r.status_code == 404
