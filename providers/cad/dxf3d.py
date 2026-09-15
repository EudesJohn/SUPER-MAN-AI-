"""3D DXF (R12) export - real 3D geometry AutoCAD opens natively.

Each mesh triangle becomes a 3DFACE entity (4th corner = 3rd for triangles).
Units are MILLIMETERS: the model is stored in meters, so coordinates are
scaled by 1000. Layers carry the AutoCAD Color Index so groups/parts keep
distinct colors. A minimal reader allows round-trip verification in tests.

This is NOT a STEP/B-Rep solid: it is a faceted (tessellated) 3D model - the
honest, dependency-free way to hand real 3D geometry to AutoCAD.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any

from providers.cad.dxf import dxf_document
from providers.cad.mesh import Mesh

MM_PER_M = 1000.0


def ent_3dface(layer: str, v0, v1, v2) -> list[str]:
    """One triangle as a 3DFACE (4th corner repeats the 3rd)."""
    return ["0", "3DFACE", "8", layer,
            "10", f"{v0[0]:.3f}", "20", f"{v0[1]:.3f}", "30", f"{v0[2]:.3f}",
            "11", f"{v1[0]:.3f}", "21", f"{v1[1]:.3f}", "31", f"{v1[2]:.3f}",
            "12", f"{v2[0]:.3f}", "22", f"{v2[1]:.3f}", "32", f"{v2[2]:.3f}",
            "13", f"{v2[0]:.3f}", "23", f"{v2[1]:.3f}", "33", f"{v2[2]:.3f}"]


def mesh_to_3dfaces(m: Mesh, layer: str) -> list[list[str]]:
    """All triangles of a mesh -> 3DFACE entities, converted m -> mm."""
    v = m.vertices * MM_PER_M
    tris = m.triangles
    out: list[list[str]] = []
    for t in tris:
        a, b, c = v[t[0]], v[t[1]], v[t[2]]
        out.append(ent_3dface(layer, a, b, c))
    return out


def part_dxf3d_content(m: Mesh, part_name: str) -> str:
    """Full DXF document for ONE part, 3D, its own layer."""
    layer = f"P_{part_name[:28]}"  # layer names <= 31 chars in R12
    return dxf_document({layer: 7}, mesh_to_3dfaces(m, layer))


def assembly_dxf3d_content(groups: dict[str, Mesh], colors: dict[str, int]) -> str:
    """Full DXF document for the WHOLE assembly: one layer per group."""
    layers = {g: colors.get(g, 7) for g in groups}
    entities: list[list[str]] = []
    for g, m in groups.items():
        entities += mesh_to_3dfaces(m, g)
    return dxf_document(layers, entities)


def save_dxf3d(path: str | Path, content: str) -> dict[str, Any]:
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(content, encoding="ascii", errors="replace")
    return {"path": str(p), "bytes": p.stat().st_size}


# --------------------------------------------------------------------------- #
# Minimal reader (round-trip verification in tests)
# --------------------------------------------------------------------------- #
def read_dxf3d(path: str | Path) -> dict[str, Any]:
    raw = Path(path).read_text(encoding="utf-8", errors="replace").replace("\r\n", "\n")
    tags = raw.split("\n")
    pairs = [(tags[i].strip(), tags[i + 1]) for i in range(0, len(tags) - 1, 2)]
    result: dict[str, Any] = {"layers": {}, "faces": []}
    i = 0
    while i < len(pairs):
        code, val = pairs[i]
        if code == "0" and val == "LAYER":
            name, color = "", 7
            j = i + 1
            while j < len(pairs) and pairs[j][0] != "0":
                if pairs[j][0] == "2":
                    name = pairs[j][1]
                elif pairs[j][0] == "62":
                    color = int(pairs[j][1])
                j += 1
            if name:
                result["layers"][name] = color
            i = j
            continue
        if code == "0" and val == "3DFACE":
            face: dict[str, Any] = {"layer": "", "v": []}
            corners: dict[str, list[float]] = {}
            j = i + 1
            while j < len(pairs) and pairs[j][0] != "0":
                k, s = pairs[j]
                if k == "8":
                    face["layer"] = s
                elif k in ("10", "20", "30", "11", "21", "31", "12", "22", "32", "13", "23", "33"):
                    corners.setdefault(k[1], []).append(float(s))  # '0'..'3' = corner index
                j += 1
            face["v"] = [corners.get(str(n), []) for n in range(3)]
            result["faces"].append(face)
            i = j
            continue
        i += 1
    return result
