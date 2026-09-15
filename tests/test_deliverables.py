"""Tests: 3D DXF export (AutoCAD-native 3D) + deliverables packaging + design intent."""
from __future__ import annotations

import zipfile

import pytest

from providers.cad import mesh as M
from providers.cad.tractor import build_tractor


# --------------------------------------------------------------------------- #
# 3D DXF (3DFACE)
# --------------------------------------------------------------------------- #
def test_dxf3d_part_roundtrip(tmp_path):
    from providers.cad.dxf3d import part_dxf3d_content, read_dxf3d, save_dxf3d

    m = M.box(2.0, 1.0, 0.5)  # meters -> 2000 x 1000 x 500 mm in the DXF
    path = tmp_path / "piece.dxf"
    save_dxf3d(path, part_dxf3d_content(m, "plaque_test"))
    doc = read_dxf3d(path)
    assert doc["layers"], "part layer missing"
    assert len(doc["faces"]) == m.n_triangles
    # A box face: first corner of the first triangle must carry mm coordinates.
    coords = doc["faces"][0]["v"][0]
    assert len(coords) == 3
    assert max(abs(c) for c in coords) <= 2000.0 + 1e-6


def test_dxf3d_is_r12_and_ascii(tmp_path):
    from providers.cad.dxf3d import part_dxf3d_content, save_dxf3d

    path = tmp_path / "r.dxf"
    save_dxf3d(path, part_dxf3d_content(M.box(1, 1, 1), "b"))
    raw = path.read_text(encoding="ascii")  # must be pure ASCII
    assert "AC1009" in raw and "3DFACE" in raw


def test_dxf3d_assembly_layers_match_groups():
    from providers.cad.tractor import GROUP_SPECS
    from providers.cad.deliverables import GROUP_ACI
    from providers.cad.dxf3d import assembly_dxf3d_content, read_dxf3d
    from providers.cad.dxf import save_dxf
    from providers.cad.dxf3d import dxf_document  # noqa: F401 (import sanity)

    build = build_tractor()
    content = assembly_dxf3d_content(build.groups, GROUP_ACI)
    layers = dict()
    # Parse expected layers from the document text (avoid file IO here).
    tags = content.split("\n")
    for i in range(len(tags) - 1):
        if tags[i] == "2" and i > 0 and tags[i - 1] == "LAYER":
            layers[tags[i + 1]] = True
    for g in GROUP_SPECS:
        assert g in layers, f"group {g} missing as a DXF layer"
    assert "3DFACE" in content


# --------------------------------------------------------------------------- #
# Deliverables packaging
# --------------------------------------------------------------------------- #
@pytest.fixture()
def packaged(tmp_path):
    from core.electrical_design import CalculationEngine, ElectricalDesignEngine
    from core.electrical_design import DEFAULT_CIRCUITS
    from core.tools import ToolRegistry, make_file_tools
    from providers.cad.deliverables import package_deliverables
    from providers.cad.sheets import (
        build_arrangement_sheet,
        build_part_sheet,
        build_wire_schedule,
    )

    ws = tmp_path / "ws"
    ws.mkdir()
    registry = ToolRegistry(ws)
    make_file_tools(registry)

    def writer(rel: str, data: bytes):
        return registry.execute("write_file_bytes", agent="t", path=rel, content=data)

    design = ElectricalDesignEngine(CalculationEngine.default_engine()).design(
        list(DEFAULT_CIRCUITS))
    sched = build_wire_schedule(design)
    build = build_tractor()
    part_sheets = [build_arrangement_sheet(build)] + [
        build_part_sheet(n, m, "", "structure") for n, m in list(build.part_meshes.items())[:3]
    ]
    verifs = [{"id": "V1", "subject": "electrical_fusing", "outcome": "PASS",
               "detail": "test"}]
    # the extra 2D file must exist BEFORE packaging (the ZIP reads it)
    (ws / "PRJ-X/cad/tractor/deliverables/2D_PLANS").mkdir(parents=True)
    (ws / "PRJ-X/cad/tractor/deliverables/2D_PLANS/SCHEMA-01.dxf").write_bytes(b"0\nEOF\n")
    manifest = package_deliverables(
        build, sched, design, verifs, "PRJ-X/cad/tractor", "PRJ-X", writer, ws,
        part_sheets=part_sheets,
        extra_2d=[("PRJ-X/cad/tractor/deliverables/2D_PLANS/SCHEMA-01.dxf", "schema")],
    )
    return manifest, ws, sched


def test_deliverables_folder_structure(packaged):
    manifest, ws, _ = packaged
    base = ws / "PRJ-X/cad/tractor/deliverables"
    assert (base / "3D_MODELES" / "TRACTEUR_3D_ENSEMBLE.dxf").is_file()
    pieces = list((base / "3D_MODELES" / "PIECES").glob("PIECE_*.dxf"))
    assert len(pieces) == manifest["parts_count"]
    assert (base / "2D_PLANS" / "PLANS_ENSEMBLE_ET_PIECES.dxf").is_file()
    for f in ("NOMENCLATURE.csv", "CABLAGE_COMPLET.csv", "CIRCUITS_ELECTRIQUES.csv",
              "VERIFICATIONS.csv", "INDEX_LIVRABLES.csv"):
        assert (base / "1D_DONNEES" / f).is_file(), f
    assert (base / "LISEZ-MOI.txt").is_file()
    assert (base / "LIVRABLES_COMPLETS.zip").is_file()


def test_deliverables_zip_contains_tree(packaged):
    manifest, ws, _ = packaged
    zpath = ws / manifest["zip"]
    with zipfile.ZipFile(zpath) as z:
        names = z.namelist()
    assert any(n.endswith("3D_MODELES/TRACTEUR_3D_ENSEMBLE.dxf") for n in names)
    assert sum(1 for n in names if n.startswith("deliverables/3D_MODELES/PIECES/")) == \
        manifest["parts_count"]
    assert any(n.endswith("1D_DONNEES/NOMENCLATURE.csv") for n in names)


def test_deliverables_wiring_csv_rows(packaged):
    _, ws, sched = packaged
    csv_path = ws / "PRJ-X/cad/tractor/deliverables/1D_DONNEES/CABLAGE_COMPLET.csv"
    text = csv_path.read_text(encoding="utf-8-sig")
    for r in sched:
        assert r["id"] in text


def test_deliverables_bom_and_index(packaged):
    """BOM lists every part with mass; index lists every written file."""
    import csv as _csv

    manifest, ws, _ = packaged
    base = ws / "PRJ-X/cad/tractor/deliverables"
    with open(base / "1D_DONNEES" / "NOMENCLATURE.csv", encoding="utf-8-sig") as f:
        bom = list(_csv.DictReader(f, delimiter=";"))
    assert len(bom) == len(build_tractor().parts)
    assert all(row["masse_kg"] for row in bom)
    with open(base / "1D_DONNEES" / "INDEX_LIVRABLES.csv", encoding="utf-8-sig") as f:
        idx = list(_csv.DictReader(f, delimiter=";"))
    assert {row["dimension"] for row in idx} >= {"3D", "2D", "1D", "DOC"}


def test_schematic_sheet_dxf(tmp_path):
    """The 12 V schematic renders as a real DXF sheet with functional layers."""
    from core.electrical_design import CalculationEngine, ElectricalDesignEngine
    from core.electrical_design import DEFAULT_CIRCUITS
    from providers.cad.dxf import read_dxf
    from providers.cad.sheets import build_schematic_sheet

    design = ElectricalDesignEngine(CalculationEngine.default_engine()).design(
        list(DEFAULT_CIRCUITS))
    sheet = build_schematic_sheet(design, "PRJ-T")
    assert sheet.name == "SCHEMA-01"
    assert any(e.layer == "PUISSANCE" for e in sheet.edges)
    assert any(e.layer == "MASSE" for e in sheet.edges)
    assert len(sheet.view_labels) >= 6

    from providers.cad.drawings import DXF_LAYERS, dxf_document, sheet_to_dxf
    path = tmp_path / "SCHEMA-01.dxf"
    path.write_text(dxf_document(DXF_LAYERS, sheet_to_dxf(sheet, "PRJ-T")),
                    encoding="ascii", errors="replace")
    doc = read_dxf(path)
    assert "PUISSANCE" in doc["layers"] and "MASSE" in doc["layers"]
    assert len(doc["lines"]) >= 10


def test_writer_confines_deliverables(packaged):
    """Paths stay inside the workspace - sandbox enforcement still applies."""
    from core.tools import ToolDeniedError, ToolRegistry, make_file_tools

    registry = ToolRegistry(__import__("pathlib").Path(".") )
    make_file_tools(registry)
    with pytest.raises(ToolDeniedError):
        registry.execute("write_file_bytes", agent="t", path="../evil.dxf", content=b"x")


# --------------------------------------------------------------------------- #
# /ask design intent
# --------------------------------------------------------------------------- #
def test_design_intent_regex():
    from apps.api.main import DESIGN_INTENT_RE

    assert DESIGN_INTENT_RE.search("dessine un tracteur avec ses pieces")
    assert DESIGN_INTENT_RE.search("conçois la machine et génère les plans")
    assert DESIGN_INTENT_RE.search("fais le circuit electrique complet")
    assert DESIGN_INTENT_RE.search("un dossier que je peux ouvrir sur autocad")
    assert not DESIGN_INTENT_RE.search("quelle est la masse du tracteur ?")
    assert not DESIGN_INTENT_RE.search("combien de fusibles ?")
