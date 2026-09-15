"""Technical drawing engine (mise en plan): real orthographic views with
dimensions, computed from the 3D meshes - like an engineer's part drawings.

Views are true projections: hidden-line removal per view direction, feature
edges (sharp mesh creases) plus silhouette edges, drawn to paper scale with
dimensions. Each sheet is emitted BOTH as DXF (AutoCAD-compatible) and as an
SVG preview (same geometry, for the console).
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Any

import numpy as np

from providers.cad.dxf import ACI, dxf_document, ent_arc, ent_circle, ent_line, ent_text
from providers.cad.mesh import Mesh

# --------------------------------------------------------------------------- #
# Edge extraction: feature (crease) + silhouette edges of a mesh
# --------------------------------------------------------------------------- #
@dataclass
class Edge2D:
    x1: float
    y1: float
    x2: float
    y2: float
    kind: str = "visible"  # visible | hidden
    layer: str = ""        # explicit DXF layer override (empty = default)


def _face_normal(mesh: Mesh, tri_idx: int) -> np.ndarray:
    a, b, c = mesh.triangles[tri_idx]
    n = np.cross(mesh.vertices[b] - mesh.vertices[a], mesh.vertices[c] - mesh.vertices[a])
    ln = np.linalg.norm(n)
    return n / ln if ln > 1e-12 else n


def project_edges(mesh: Mesh, view: str, tol_deg: float = 20.0) -> list[Edge2D]:
    """Orthographic projection of crease + silhouette edges for a view direction.

    view: 'front' (-Y), 'side' (+X), 'top' (+Z).
    Visible if at least one adjacent face points toward the viewer.
    """
    dirs = {"front": np.array([0.0, -1.0, 0.0]),
            "side": np.array([1.0, 0.0, 0.0]),
            "top": np.array([0.0, 0.0, 1.0])}
    vdir = dirs[view]
    n_faces = len(mesh.triangles)
    normals = np.array([_face_normal(mesh, i) for i in range(n_faces)])
    facing = normals @ vdir > 1e-9  # front-facing triangles

    edge_map: dict[tuple[int, int], list[int]] = {}
    for fi, tri in enumerate(mesh.triangles):
        for a, b in ((tri[0], tri[1]), (tri[1], tri[2]), (tri[2], tri[0])):
            key = (min(a, b), max(a, b))
            edge_map.setdefault(key, []).append(fi)

    # 2D projection basis per view
    if view == "front":
        proj = lambda p: (p[0], p[2])   # noqa: E731
    elif view == "side":
        proj = lambda p: (p[1], p[2])   # noqa: E731
    else:
        proj = lambda p: (p[0], p[1])   # noqa: E731

    edges: list[Edge2D] = []
    for (a, b), faces in edge_map.items():
        visible = any(facing[f] for f in faces)
        if not visible:
            continue
        if len(faces) == 2:
            cosang = float(np.clip(normals[faces[0]] @ normals[faces[1]], -1, 1))
            if math.degrees(math.acos(cosang)) < tol_deg:
                continue  # smooth continuation: not a drawing edge
        p1, p2 = mesh.vertices[a], mesh.vertices[b]
        x1, y1 = proj(p1)
        x2, y2 = proj(p2)
        if abs(x2 - x1) < 1e-9 and abs(y2 - y1) < 1e-9:
            continue
        edges.append(Edge2D(x1, y1, x2, y2))
    return edges


def project_bounds(mesh: Mesh, view: str) -> tuple[float, float, float, float]:
    """Axis-aligned bounds of the projected mesh: (xmin, ymin, xmax, ymax)."""
    if view == "front":
        pts = mesh.vertices[:, [0, 2]]
    elif view == "side":
        pts = mesh.vertices[:, [1, 2]]
    else:
        pts = mesh.vertices[:, [0, 1]]
    return float(pts[:, 0].min()), float(pts[:, 1].min()), float(pts[:, 0].max()), float(pts[:, 1].max())


# --------------------------------------------------------------------------- #
# Sheet model
# --------------------------------------------------------------------------- #
@dataclass
class Dim:
    x1: float
    y1: float
    x2: float
    y2: float
    label: str
    offset: float = 0.0  # perpendicular offset for the dim line


@dataclass
class Sheet:
    name: str
    title: str
    scale: float                      # paper mm per model mm (1 = 1:1)
    edges: list[Edge2D] = field(default_factory=list)
    circles: list[tuple[float, float, float]] = field(default_factory=list)
    dims: list[Dim] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)
    # view labels ("Vue de face"...) anchored under each view center
    view_labels: list[tuple[str, float, float]] = field(default_factory=list)
    # engineering meta for the title block (mass, material, sheet x/y, date...)
    meta: dict[str, str] = field(default_factory=dict)


def scale_edges(edges: list[Edge2D], s: float, dx: float, dy: float) -> list[Edge2D]:
    return [Edge2D(e.x1 * s + dx, e.y1 * s + dy, e.x2 * s + dx, e.y2 * s + dy, e.kind) for e in edges]


def scale_circles(cs: list[tuple[float, float, float]], s: float, dx: float, dy: float):
    return [(x * s + dx, y * s + dy, r * s) for x, y, r in cs]


def scale_dim_list(dims: list[Dim], s: float, dx: float, dy: float) -> list[Dim]:
    return [Dim(d.x1 * s + dx, d.y1 * s + dy, d.x2 * s + dx, d.y2 * s + dy, d.label, d.offset * s)
            for d in dims]


# --------------------------------------------------------------------------- #
# Sheet -> DXF entities
# --------------------------------------------------------------------------- #
PAPER_W, PAPER_H = 420.0, 297.0  # A3 landscape (mm)


def title_block(sheet: Sheet, project_id: str) -> list[list[str]]:
    """Title block, drafting style: designation, project, sheet x/y, scale,
    mass/material when known, date, validation stamp."""
    from datetime import date

    tb_x, tb_y, tb_w, tb_h = PAPER_W - 170, 10, 160, 46
    e: list[list[str]] = []
    e.append(ent_line("CADRE", tb_x, tb_y, tb_x + tb_w, tb_y))
    e.append(ent_line("CADRE", tb_x + tb_w, tb_y, tb_x + tb_w, tb_y + tb_h))
    e.append(ent_line("CADRE", tb_x + tb_w, tb_y + tb_h, tb_x, tb_y + tb_h))
    e.append(ent_line("CADRE", tb_x, tb_y + tb_h, tb_x, tb_y))
    e.append(ent_line("CADRE", tb_x, tb_y + 16, tb_x + tb_w, tb_y + 16))
    e.append(ent_line("CADRE", tb_x, tb_y + 30, tb_x + tb_w, tb_y + 30))
    e.append(ent_text("TEXTE", tb_x + 4, tb_y + 34, 5, sheet.title[:34]))
    e.append(ent_text("TEXTE", tb_x + 4, tb_y + 20, 4, f"AI ENGINEER - {project_id}"))
    e.append(ent_text("TEXTE", tb_x + 4, tb_y + 5, 3.5,
                      f"Ech. 1:{1/sheet.scale:g} - A VALIDER avant fabrication"))
    e.append(ent_text("TEXTE", tb_x + 90, tb_y + 20, 4, f"Feuille: {sheet.name}"))
    e.append(ent_text("TEXTE", tb_x + 90, tb_y + 5, 3.5, f"Date: {date.today().isoformat()}"))
    # meta line 2: mass / material / projection convention
    meta2 = sheet.meta.get("mass", "")
    mat = sheet.meta.get("material", "")
    if meta2 or mat:
        e.append(ent_text("TEXTE", tb_x + 90, tb_y + 34, 3,
                          f"{meta2}{' - ' if meta2 and mat else ''}{mat}"[:38]))
    return e


def view_label_entities(sheet: Sheet) -> list[list[str]]:
    """View captions under each projection (drafting practice)."""
    e: list[list[str]] = []
    for label, cx, cy in sheet.view_labels:
        e.append(ent_text("TEXTE", cx, cy, 3.2, label))
    return e


def sheet_to_dxf(sheet: Sheet, project_id: str) -> list[list[str]]:
    e: list[list[str]] = []
    # frame
    e.append(ent_line("CADRE", 5, 5, PAPER_W - 5, 5))
    e.append(ent_line("CADRE", PAPER_W - 5, 5, PAPER_W - 5, PAPER_H - 5))
    e.append(ent_line("CADRE", PAPER_W - 5, PAPER_H - 5, 5, PAPER_H - 5))
    e.append(ent_line("CADRE", 5, PAPER_H - 5, 5, 5))
    # geometry
    for ed in sheet.edges:
        layer = ed.layer or ("ARETES" if ed.kind == "visible" else "CACHE")
        e.append(ent_line(layer, ed.x1, ed.y1, ed.x2, ed.y2))
    for x, y, r in sheet.circles:
        e.append(ent_circle("ARETES", x, y, r))
    # dimensions
    for d in sheet.dims:
        nx, ny = -(d.y2 - d.y1), (d.x2 - d.x1)
        ln = math.hypot(nx, ny) or 1.0
        nx, ny = nx / ln * d.offset, ny / ln * d.offset
        e.append(ent_line("COTE", d.x1 + nx, d.y1 + ny, d.x2 + nx, d.y2 + ny))
        e.append(ent_line("COTE", d.x1, d.y1, d.x1 + nx * 1.15, d.y1 + ny * 1.15))
        e.append(ent_line("COTE", d.x2, d.y2, d.x2 + nx * 1.15, d.y2 + ny * 1.15))
        mx, my = (d.x1 + d.x2) / 2 + nx * 1.6, (d.y1 + d.y2) / 2 + ny * 1.6
        e.append(ent_text("COTE", mx, my, 3.5, d.label))
    e += view_label_entities(sheet)
    e += title_block(sheet, project_id)
    for i, note in enumerate(sheet.notes):
        e.append(ent_text("TEXTE", 15, PAPER_H - 20 - 6 * i, 3.5, note))
    return e


DXF_LAYERS = {"CADRE": ACI["white"], "ARETES": ACI["white"], "CACHE": ACI["gray"],
              "COTE": ACI["green"], "TEXTE": ACI["cyan"], "FAISCEAU": ACI["red"],
              "PUISSANCE": ACI["red"], "ECLAIRAGE": ACI["yellow"],
              "SIGNALISATION": ACI["green"], "COMMANDE": ACI["cyan"],
              "COMPOSANT": ACI["white"], "MASSE": ACI["gray"]}


# --------------------------------------------------------------------------- #
# Sheet -> SVG (same content, console preview)
# --------------------------------------------------------------------------- #
def sheet_to_svg(sheet: Sheet, project_id: str) -> str:
    def esc(s: str) -> str:
        return s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")

    p: list[str] = [f'<svg xmlns="http://www.w3.org/2000/svg" width="{PAPER_W}" height="{PAPER_H}" '
                    f'viewBox="0 0 {PAPER_W:.0f} {PAPER_H:.0f}" style="background:#fff">']
    p.append(f'<rect x="5" y="5" width="{PAPER_W - 10}" height="{PAPER_H - 10}" fill="none" stroke="#333" stroke-width="1"/>')
    layer_colors = {"PUISSANCE": "#d62828", "ECLAIRAGE": "#c9a227",
                    "SIGNALISATION": "#2a9d8f", "COMMANDE": "#457bd9",
                    "FAISCEAU": "#f77f00"}
    for ed in sheet.edges:
        if ed.layer in layer_colors:
            color, dash = layer_colors[ed.layer], ''
        else:
            color = "#111" if ed.kind == "visible" else "#aaa"
            dash = '' if ed.kind == "visible" else ' stroke-dasharray="4 3"'
        p.append(f'<line x1="{ed.x1:.2f}" y1="{PAPER_H - ed.y1:.2f}" x2="{ed.x2:.2f}" y2="{PAPER_H - ed.y2:.2f}" '
                 f'stroke="{color}" stroke-width="0.6"{dash}/>')
    for x, y, r in sheet.circles:
        p.append(f'<circle cx="{x:.2f}" cy="{PAPER_H - y:.2f}" r="{r:.2f}" fill="none" stroke="#111" stroke-width="0.6"/>')
    for d in sheet.dims:
        nx, ny = -(d.y2 - d.y1), (d.x2 - d.x1)
        ln = math.hypot(nx, ny) or 1.0
        nx, ny = nx / ln * d.offset, ny / ln * d.offset
        p.append(f'<line x1="{d.x1 + nx:.2f}" y1="{PAPER_H - d.y1 - ny:.2f}" x2="{d.x2 + nx:.2f}" y2="{PAPER_H - d.y2 - ny:.2f}" '
                 f'stroke="#2a9d8f" stroke-width="0.5"/>')
        for px, py in ((d.x1, d.y1), (d.x2, d.y2)):
            p.append(f'<line x1="{px:.2f}" y1="{PAPER_H - py:.2f}" x2="{px + nx * 1.3:.2f}" y2="{PAPER_H - py - ny * 1.3:.2f}" '
                     f'stroke="#2a9d8f" stroke-width="0.5"/>')
        mx, my = (d.x1 + d.x2) / 2 + nx * 1.8, (d.y1 + d.y2) / 2 + ny * 1.8
        p.append(f'<text x="{mx:.2f}" y="{PAPER_H - my:.2f}" font-size="4.5" text-anchor="middle" fill="#14776f">{esc(d.label)}</text>')
    # view labels
    for label, cx, cy in sheet.view_labels:
        p.append(f'<text x="{cx:.2f}" y="{PAPER_H - cy:.2f}" font-size="3.2" '
                 f'text-anchor="middle" fill="#555">{esc(label)}</text>')
    # title block
    tb_x, tb_y = PAPER_W - 170, 10
    tb_y_top = PAPER_H - tb_y - 46
    p.append(f'<rect x="{tb_x}" y="{tb_y_top}" width="160" height="46" fill="none" stroke="#333"/>')
    p.append(f'<line x1="{tb_x}" y1="{tb_y_top + 16}" x2="{tb_x + 160}" y2="{tb_y_top + 16}" stroke="#333"/>')
    p.append(f'<line x1="{tb_x}" y1="{tb_y_top + 30}" x2="{tb_x + 160}" y2="{tb_y_top + 30}" stroke="#333"/>')
    p.append(f'<text x="{tb_x + 4}" y="{tb_y_top + 12}" font-size="5" font-weight="bold">{esc(sheet.title)}</text>')
    p.append(f'<text x="{tb_x + 4}" y="{tb_y_top + 26}" font-size="4">AI ENGINEER - {esc(project_id)} - {esc(sheet.name)}</text>')
    p.append(f'<text x="{tb_x + 4}" y="{tb_y_top + 42}" font-size="3.5">Ech. 1:{1 / sheet.scale:g} - A VALIDER avant fabrication</text>')
    if sheet.meta.get("mass") or sheet.meta.get("material"):
        m2 = f'{sheet.meta.get("mass", "")}{" - " if sheet.meta.get("mass") and sheet.meta.get("material") else ""}{sheet.meta.get("material", "")}'[:38]
        p.append(f'<text x="{tb_x + 90}" y="{tb_y_top + 12}" font-size="3">{esc(m2)}</text>')
    for i, note in enumerate(sheet.notes):
        p.append(f'<text x="15" y="{20 + 6 * i}" font-size="3.5" fill="#555">{esc(note)}</text>')
    p.append("</svg>")
    return "\n".join(p)


def write_sheet(sheet: Sheet, project_id: str, out_dir: str, writer) -> dict[str, Any]:
    """Write one sheet as DXF + SVG through the sandboxed writer."""
    dxf_out = writer(f"{out_dir}/{sheet.name}.dxf",
                     dxf_document(DXF_LAYERS, sheet_to_dxf(sheet, project_id)).encode("ascii", errors="replace"))
    svg_out = writer(f"{out_dir}/{sheet.name}.svg", sheet_to_svg(sheet, project_id).encode("utf-8"))
    return {"sheet": sheet.name, "title": sheet.title, "dxf": dxf_out["path"],
            "svg": svg_out["path"], "edges": len(sheet.edges), "dims": len(sheet.dims)}
