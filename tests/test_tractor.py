"""Tests: mesh kernel, tractor builder, electrical design engine, schematic,
and the independent electrical verification (including a deliberate FAIL)."""
from __future__ import annotations

import math

import pytest

from core.calculation import CalculationEngine
from core.electrical_design import CircuitSpec, ElectricalDesignEngine
from core.schematic import render_schematic_svg
from providers.cad import mesh as M
from providers.cad.tractor import GROUP_SPECS, build_tractor


# --------------------------------------------------------------------------- #
# Mesh kernel: primitives verified against analytic volumes
# --------------------------------------------------------------------------- #
def test_box_volume_exact():
    m = M.box(2.0, 3.0, 4.0)
    assert m.volume() == pytest.approx(24.0, rel=1e-9)


def test_cylinder_volume_exact():
    m = M.cylinder(0.5, 0.5, 2.0, 64)
    assert m.volume() == pytest.approx(math.pi * 0.25 * 2.0, rel=2e-3)


def test_sphere_volume_exact():
    m = M.sphere(1.0, 64, 32)
    assert m.volume() == pytest.approx(4.0 / 3.0 * math.pi, rel=5e-3)


def test_torus_volume_exact():
    R, r = 2.0, 0.3
    m = M.torus(R, r, 48, 24)
    assert m.volume() == pytest.approx(2 * math.pi**2 * R * r**2, rel=2e-2)


def test_transforms_and_merge():
    a = M.box(1, 1, 1)
    placed = M.place(a, x=5, y=0, z=0)
    assert placed.centroid()[0] == pytest.approx(5.0)
    b = placed.merged_with(a)
    assert b.n_triangles == a.n_triangles * 2
    # volume of merged non-overlapping boxes = 2
    assert b.volume() == pytest.approx(2.0, rel=1e-9)


def test_stl_roundtrip(tmp_path):
    m = M.box(1.0, 1.0, 1.0)
    path = tmp_path / "test.stl"
    M.export_binary_stl(m, path)
    re = M.read_binary_stl(path)
    assert re.volume() == pytest.approx(1.0, rel=1e-6)
    assert re.n_triangles == 12


def test_tube_along_wire():
    m = M.tube_along([[0, 0, 0], [1, 0, 0]], 0.1, 8)
    assert m.volume() > 0
    assert m.volume() < math.pi * 0.1**2 * 1.0 * 2  # sanity: less than huge overestimate


# --------------------------------------------------------------------------- #
# Tractor builder
# --------------------------------------------------------------------------- #
def test_tractor_build_all_groups():
    b = build_tractor()
    assert set(b.groups.keys()) == set(GROUP_SPECS.keys())
    for g, m in b.groups.items():
        assert m.volume() > 0, f"group {g} is empty or invalid"
    names = [p["name"] for p in b.parts]
    for expected in ("chassis_frame", "engine_block_4cyl", "battery_12V_80Ah",
                     "starter_motor", "fuse_box", "feed_main_bat_fusebox"):
        assert expected in names


def test_tractor_harness_present():
    b = build_tractor()
    wires = [p for p in b.parts if p["group"] == "harness"]
    # feed + alt + starter + 2 headlights + 2 tails + dash + horn + ecu + grounds
    assert len(wires) >= 12


# --------------------------------------------------------------------------- #
# Electrical design engine
# --------------------------------------------------------------------------- #
@pytest.fixture()
def engine():
    return ElectricalDesignEngine(CalculationEngine.default_engine())


def test_electrical_design_headlight(engine):
    design = engine.design([CircuitSpec("headlight_left", "Phare G", 55.0, 2.6)])
    c = design["circuits"][0]
    assert c["current_a"] == pytest.approx(55.0 / 12.0, abs=0.01)  # 4.58 A
    assert c["fuse_a"] is not None and c["fuse_a"] >= 1.35 * 55 / 12
    assert c["drop_pct"] <= 3.0
    assert c["capacity_a"] >= 1.25 * c["current_a"]


def test_electrical_design_starter_no_fuse(engine):
    design = engine.design([CircuitSpec("starter_motor", "Démarreur", 1500.0, 1.2, kind="starter")])
    c = design["circuits"][0]
    assert c["current_a"] == pytest.approx(125.0, abs=0.1)
    assert c["fuse_a"] is None          # convention: solenoid-switched
    assert c["gauge_mm2"] >= 25         # thick cable required
    assert c["fuse_exception"] is not None


def test_electrical_design_feed_aggregates(engine):
    circuits = [
        CircuitSpec("l1", "L1", 55.0, 2.0),
        CircuitSpec("l2", "L2", 55.0, 2.0),
        CircuitSpec("feed_main", "Feed", 0.0, 1.5, kind="feed"),
    ]
    design = engine.design(circuits)
    feed = next(c for c in design["circuits"] if c["name"] == "feed_main")
    assert feed["current_a"] == pytest.approx(110.0 / 12.0, abs=0.1)


def test_electrical_design_unsolvable_raises(engine):
    with pytest.raises(ValueError, match="INCONNU"):
        engine.design([CircuitSpec("x", "X", 20000.0, 50.0, kind="load")])


# --------------------------------------------------------------------------- #
# Schematic renderer
# --------------------------------------------------------------------------- #
@pytest.fixture()
def memory_demo_design(engine):
    """Full default design used by sheet/verification tests."""
    from core.electrical_design import DEFAULT_CIRCUITS

    return engine.design(list(DEFAULT_CIRCUITS))


def test_schematic_svg_valid(engine):
    design = engine.design(
        [
            CircuitSpec("starter_motor", "Démarreur", 1500.0, 1.2, kind="starter"),
            CircuitSpec("headlight_left", "Phare G", 55.0, 2.6),
            CircuitSpec("feed_main", "Feed", 0.0, 1.5, kind="feed"),
        ]
    )
    svg = render_schematic_svg(design)
    assert svg.startswith("<svg") and svg.rstrip().endswith("</svg>")
    assert "BATTERIE" in svg and "DÉMARREUR" in svg and "MASSE CHÂSSIS" in svg
    assert "À VÉRIFIER" in svg                      # honesty marker
    assert 'stroke-width="-' not in svg             # no negative widths
    assert svg.count("polyline") >= 3


# --------------------------------------------------------------------------- #
# Independent verification: PASS on good design, FAIL on a broken one
# --------------------------------------------------------------------------- #
async def test_verification_passes_good_design(engine, memory, bus):
    from core.verification import VerificationEngine

    design = engine.design(
        [
            CircuitSpec("headlight_left", "Phare G", 55.0, 2.6),
            CircuitSpec("horn", "Klaxon", 72.0, 2.8),
            CircuitSpec("ecu_engine", "Calculateur", 20.0, 1.2),
        ]
    )
    results = await VerificationEngine(memory, bus).verify_electrical_design("p-ok", design)
    assert len(results) == 6  # fusing, capacity, drop, ground, balance, cranking
    failed = [r for r in results if r.outcome.value == "FAIL"]
    assert not failed, [r.detail for r in failed]
    # no starter in this design -> cranking check is honestly UNKNOWN
    cranking = next(r for r in results if r.subject == "battery_cranking_capacity")
    assert cranking.outcome.value == "UNKNOWN"


async def test_verification_fails_unfused_design(engine, memory, bus):
    """Deliberate counter-example: an unfused consumer circuit must FAIL."""
    from core.verification import VerificationEngine

    design = engine.design(
        [
            CircuitSpec("headlight_left", "Phare G", 55.0, 2.6),
            CircuitSpec("rogue_load", "Charge sans fusible", 36.0, 1.5),
        ]
    )
    # Simulate a design bug: remove the fuse from one consumer circuit.
    for c in design["circuits"]:
        if c["name"] == "rogue_load":
            c["fuse_a"] = None
            c["fuse_exception"] = None
    results = await VerificationEngine(memory, bus).verify_electrical_design("p-bad", design)
    fusing = next(r for r in results if r.subject == "electrical_fusing")
    assert fusing.outcome.value == "FAIL"
    assert "rogue_load" in fusing.detail


async def test_verification_fails_power_balance(engine, memory, bus):
    """Counter-example: loads beyond the alternator's continuous output must FAIL.
    (Loads kept wire-sizeable: the sizer honestly refuses impossible ones.)"""
    from core.verification import VerificationEngine

    design = engine.design(
        [CircuitSpec("work_lights", "Gyrophare + projecteurs", 500.0, 2.0),
         CircuitSpec("cab_heater", "Chauffage cabine", 500.0, 2.0)],
        alternator_max_a=90.0,  # continuous ~810 W < 1000 W of loads
    )
    assert design["power_balance"]["margin_w"] < 0
    results = await VerificationEngine(memory, bus).verify_electrical_design("p-bal", design)
    bal = next(r for r in results if r.subject == "electrical_power_balance")
    assert bal.outcome.value == "FAIL"


async def test_verification_fails_battery_cca(engine, memory, bus):
    """Counter-example: an undersized battery cannot crank the starter."""
    from core.verification import VerificationEngine

    design = engine.design(
        [CircuitSpec("starter_motor", "Démarreur", 1500.0, 1.2, kind="starter")],
        battery_ah=10.0,  # CCA ~ 40 A << 1.2 x 125 A
    )
    results = await VerificationEngine(memory, bus).verify_electrical_design("p-cca", design)
    cca = next(r for r in results if r.subject == "battery_cranking_capacity")
    assert cca.outcome.value == "FAIL"


async def test_verification_full_design_passes(engine, memory, bus):
    from core.verification import VerificationEngine

    from core.electrical_design import DEFAULT_CIRCUITS

    design = engine.design(list(DEFAULT_CIRCUITS))
    results = await VerificationEngine(memory, bus).verify_electrical_design("p-full", design)
    assert len(results) == 6
    failed = [r for r in results if r.outcome.value == "FAIL"]
    assert not failed, [r.detail for r in failed]


# --------------------------------------------------------------------------- #
# DXF writer + technical drawings
# --------------------------------------------------------------------------- #
def test_dxf_roundtrip(tmp_path):
    from providers.cad.dxf import dxf_document, ent_line, ent_text, read_dxf, save_dxf

    layers = {"ARETES": 7, "COTE": 3}
    ents = [ent_line("ARETES", 0, 0, 10, 0), ent_text("COTE", 5, -2, 3, "100")]
    path = tmp_path / "part.dxf"
    save_dxf(path, layers, ents)
    doc = read_dxf(path)
    assert doc["layers"]["ARETES"] == 7
    assert len(doc["lines"]) == 1 and len(doc["texts"]) == 1
    assert doc["texts"][0]["text"] == "100"
    assert doc["lines"][0]["layer"] == "ARETES"


def test_dxf_starts_with_acadver(tmp_path):
    from providers.cad.dxf import dxf_document, ent_line, save_dxf, read_dxf

    path = tmp_path / "v.dxf"
    save_dxf(path, {"A": 7}, [ent_line("A", 0, 0, 1, 1)])
    raw = path.read_text()
    assert "AC1009" in raw and raw.startswith("0\nSECTION")
    assert len(read_dxf(path)["lines"]) == 1


def test_part_sheet_views_and_dims():
    from providers.cad.sheets import build_part_sheet

    mesh = M.box(2.0, 1.0, 0.5)  # 2000 x 1000 x 500 mm part
    sheet = build_part_sheet("plaque_test", mesh, "plaque d'essai", "structure",
                             density=7850.0)
    assert sheet.name == "PIECE-plaque_test"
    assert len(sheet.edges) >= 12          # 4 silhouette edges x 3 views
    assert len(sheet.dims) >= 3            # L, H, W dimensions
    labels = {d.label for d in sheet.dims}
    assert "2000" in labels and "1000" in labels and "500" in labels
    assert 0 < sheet.scale <= 1.0
    assert [lab[0] for lab in sheet.view_labels] == \
        ["VUE DE FACE", "VUE DE DESSUS", "VUE DE DROITE"]
    assert "Masse: " in sheet.meta["mass"]


def test_part_sheet_cylinder_outline():
    from providers.cad.sheets import build_part_sheet

    mesh = M.cylinder(0.15, 0.15, 0.6, 32, axis="x")  # arbre
    sheet = build_part_sheet("arbre", mesh, "arbre de transmission", "structure")
    # top view of an X-axis cylinder: faceted circular outline -> many edges
    assert len(sheet.edges) > 40


def test_arrangement_and_wiring_sheets(memory_demo_design):
    from providers.cad.sheets import build_arrangement_sheet, build_wire_schedule, build_wiring_sheet

    build = build_tractor()
    arr = build_arrangement_sheet(build)
    assert arr.name == "ENSEMBLE-00" and len(arr.edges) > 50

    design = memory_demo_design
    sched = build_wire_schedule(design)
    assert any(r["de"] == "BAT+" and r["vers"] == "BOITE FUSIBLES" for r in sched)
    assert any(r["vers"] == "MASSE CHASSIS" for r in sched)
    assert any(r["de"] == "BAT+" and "DEMARREUR" in r["vers"] for r in sched)
    ws = build_wiring_sheet(design, "p-x")
    assert ws.name == "CABLAGE-01"
    assert any("TABLEAU DE CABLAGE" in n for n in ws.notes)
