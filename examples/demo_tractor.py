"""End-to-end demo: parametric 3D tractor + complete 12 V electrical circuit.

Runs the real engines/providers stack offline:
  3D build (all parts) -> electrical design (deterministic sizing) ->
  independent verification -> sandboxed STL/SVG/JSON export.

Run: .venv/Scripts/python examples/demo_tractor.py
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from core.calculation import CalculationEngine  # noqa: E402
from core.electrical_design import DEFAULT_CIRCUITS, ElectricalDesignEngine
from core.schematic import render_schematic_svg
from core.tools import ToolRegistry, make_file_tools
from core.verification import VerificationEngine
from providers.cad.provider import detect_provider
from providers.cad.tractor import build_tractor, export_tractor

OUT = Path("workspace/tractor-demo/cad/tractor")


def main() -> None:
    print("=" * 70)
    print("AI ENGINEER - Demo: tracteur 3D parametrique + circuit 12 V complet")
    print("=" * 70)

    # ---------------- 1) CAD: build the full 3D tractor ----------------
    provider, cad_notes = detect_provider(None)
    ok, reason = provider.availability()
    print(f"\n[1] CAD provider: {provider.name} - disponible: {ok} ({reason})")
    if not ok:
        raise SystemExit("CAD provider unavailable - aborting honestly")

    registry = ToolRegistry(str(OUT))
    make_file_tools(registry)
    build = build_tractor()
    cad = export_tractor(build, ".", lambda p, d: registry.execute("write_file_bytes", agent="demo", path=p, content=d))
    print(f"    Pieces conçues  : {len(cad['parts'])}")
    print(f"    Masse totale    : {cad['total_mass_kg']} kg (densites materio explicites)")
    print(f"    Triangles        : {cad['total_triangles']}")
    for f, info in sorted(cad["files"].items()):
        print(f"      - {f:11s} -> {info['path']:28s} {info['triangles']:>6} triangles")

    # ---------------- 2) Electrical: deterministic 12 V sizing ----------------
    print("\n[2] Conception electrique 12 V (dimensionnement deterministe)")
    design = ElectricalDesignEngine(CalculationEngine.default_engine()).design(list(DEFAULT_CIRCUITS))
    hdr = f"    {'Circuit':28s} {'A':>7s} {'mm2':>5s} {'Fusible':>8s} {'dU%':>6s}"
    print(hdr)
    for c in design["circuits"]:
        fuse = f"F{c['fuse_a']:g} A" if c["fuse_a"] else "sans fus.*"
        print(f"    {c['description'][:28]:28s} {c['current_a']:7.1f} {c['gauge_mm2']:5g} {fuse:>8s} {c['drop_pct']:6.2f}")

    # ---------------- 3) Independent verification ----------------
    print("\n[3] Verification independante (recalcul avec constantes propres)")
    import asyncio
    import tempfile

    from core.memory import ProjectMemory
    from core.verification import VerificationEngine as VE

    # VerificationEngine persists into memory; the demo uses a throwaway DB.
    with tempfile.TemporaryDirectory() as td:
        mem = ProjectMemory(f"{td}/demo.db")
        results = asyncio.run(VE(mem).verify_electrical_design("demo", design))
        mem.close()
    for r in results:
        print(f"    [{r.outcome.value:7s}] {r.subject}: {r.detail[:90]}")
    failed = [r for r in results if r.outcome.value == "FAIL"]
    if failed:
        raise SystemExit(f"verification FAILED: {failed}")

    # ---------------- 4) Schematic + drawings + manifest export -------
    print("\n[4] Export (via outils sandbox)")
    svg = render_schematic_svg(design, title="Tracteur demo - reseau 12 V")
    registry.execute("write_text", agent="demo", path="electrical_schematic.svg", content=svg)

    from providers.cad.sheets import (
        build_arrangement_sheet,
        build_part_sheet,
        build_wire_schedule,
        build_wiring_sheet,
    )
    from providers.cad.drawings import write_sheet

    def writer(rel_path: str, data: bytes) -> dict:
        return registry.execute("write_file_bytes", agent="demo", path=rel_path, content=data)

    sheets = [build_arrangement_sheet(build)]
    note_of = {p["name"]: (p["group"], p["note"]) for p in cad["parts"]}
    for name, m in build.part_meshes.items():
        group, note = note_of.get(name, ("?", ""))
        sheets.append(build_part_sheet(name, m, note, group))
    sheets.append(build_wiring_sheet(design, "tractor-demo"))
    for sh in sheets:
        write_sheet(sh, "tractor-demo", "drawings", writer)
    print(f"    Feuilles DXF+SVG : {len(sheets)} (ensemble, pieces, cablage)")

    manifest = {"cad": cad, "electrical_design": design, "cad_notes": cad_notes,
                "wire_schedule": build_wire_schedule(design),
                "drawings": [{"sheet": s.name, "title": s.title} for s in sheets],
                "verifications": [r.model_dump(mode="json") for r in results]}
    registry.execute("write_text", agent="demo", path="tractor_build.json",
                     content=json.dumps(manifest, ensure_ascii=False, indent=2))
    for p in sorted(OUT.rglob("*")):
        if p.is_file():
            print(f"    {p} ({p.stat().st_size:,} octets)")

    print("\nOK - tracteur 3D complet + circuit electrique 12 V routes, verifie, exporte.")
    print("    NB: geometrie de synthese parametrique - validation humaine requise avant fabrication.")


if __name__ == "__main__":
    main()
