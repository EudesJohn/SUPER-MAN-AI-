"""Sheet builders: assembly drawing + individual part drawings + wiring sheet.

Each sheet follows drafting practice: A3 landscape, frame, title block,
3rd-angle orthographic views (top above front, side to the right) at a
STANDARD scale (1:1, 1:2, 1:5, 1:10, 1:20), overall dimensions in mm.
Wires are drawn on functional layers (power / lighting / signalling / control).
"""
from __future__ import annotations

import math
from typing import Any

from providers.cad.drawings import (
    Dim,
    Edge2D,
    Sheet,
    project_bounds,
    project_edges,
    scale_circles,
    scale_dim_list,
    scale_edges,
)
from providers.cad.mesh import Mesh
from providers.cad.tractor import TractorBuild

MM = 1000.0  # model (m) -> paper (mm)
STANDARD_SCALES = [1, 2, 5, 10, 20, 50]
VIEW_W, VIEW_H = 105.0, 100.0  # usable box per view on A3


def _pick_scale(extent_mm: float) -> int:
    for s in STANDARD_SCALES:
        if extent_mm / s <= max(VIEW_W, VIEW_H):
            return s
    return STANDARD_SCALES[-1]


def _fit_view(mesh: Mesh, view: str, scale_denom: int) -> tuple[list[Edge2D], list[tuple[float, float, float]], float, float]:
    """Project a view, scale 1:scale_denom, centered on (0,0). Returns edges, circles, w, h."""
    edges = project_edges(mesh, view)
    xmin, ymin, xmax, ymax = project_bounds(mesh, view)
    cx, cy = (xmin + xmax) / 2.0, (ymin + ymax) / 2.0
    s = MM / scale_denom
    placed = [Edge2D((e.x1 - cx) * s, (e.y1 - cy) * s, (e.x2 - cx) * s, (e.y2 - cy) * s, e.kind) for e in edges]
    return placed, [], (xmax - xmin) * s, (ymax - ymin) * s


def _add_dim(dims: list[Dim], x1: float, y1: float, x2: float, y2: float, value_mm: float, offset: float) -> None:
    label = f"{value_mm:.0f}"
    dims.append(Dim(x1, y1, x2, y2, label, offset=offset))


def build_part_sheet(name: str, mesh: Mesh, note: str, group: str,
                     density: float | None = None) -> Sheet:
    """One part drawing: front / top / side views + overall dims + view
    captions + mass/material in the title block (drafting practice)."""
    xmin, ymin, zmin = mesh.vertices.min(axis=0)
    xmax, ymax, zmax = mesh.vertices.max(axis=0)
    L, W, H = (xmax - xmin) * MM, (ymax - ymin) * MM, (zmax - zmin) * MM
    scale_denom = _pick_scale(max(L, W, H))
    s = MM / scale_denom

    dims: list[Dim] = []
    edges: list[Edge2D] = []
    labels: list[tuple[str, float, float]] = []

    # FRONT view (-Y): width x height - placed bottom-left
    fe, _, fw, fh = _fit_view(mesh, "front", scale_denom)
    fx, fy = 75.0, 95.0
    edges += scale_edges(fe, 1.0, fx, fy)
    _add_dim(dims, fx - fw / 2, fy - fh / 2, fx + fw / 2, fy - fh / 2, L, -8)
    _add_dim(dims, fx + fw / 2, fy - fh / 2, fx + fw / 2, fy + fh / 2, H, 8)
    labels.append(("VUE DE FACE", fx, fy - fh / 2 - 16))

    # TOP view (+Z): width x depth - above the front view (3rd angle)
    te, _, tw, td = _fit_view(mesh, "top", scale_denom)
    tx, ty = 75.0, 205.0
    edges += scale_edges(te, 1.0, tx, ty)
    _add_dim(dims, tx - tw / 2, ty + td / 2, tx + tw / 2, ty + td / 2, L, 8)
    labels.append(("VUE DE DESSUS", tx, ty - td / 2 - 8))

    # SIDE view (+X): depth x height - right of the front view
    se, _, sw, sh = _fit_view(mesh, "side", scale_denom)
    sx, sy = 225.0, 95.0
    edges += scale_edges(se, 1.0, sx, sy)
    _add_dim(dims, sx - sw / 2, sy - sh / 2, sx + sw / 2, sy - sh / 2, W, -8)
    labels.append(("VUE DE DROITE", sx, sy - sh / 2 - 16))

    meta: dict[str, str] = {}
    if density is not None:
        from providers.cad.solver import mass_properties

        mp = mass_properties(mesh, density)
        meta["mass"] = f"Masse: {mp.mass_kg:.2f} kg"
    meta["material"] = f"Groupe: {group}"

    return Sheet(
        name=f"PIECE-{name}",
        title=f"{name} - {note[:40] if note else group}",
        scale=1.0 / scale_denom,
        edges=edges,
        dims=dims,
        notes=[
            f"Piece: {name} (groupe {group})",
            f"Encombrement: {L:.0f} x {W:.0f} x {H:.0f} mm",
            "Vue de dessus au-dessus, vue de droite a droite (3e angle).",
            "Geometrie parametrique de synthese - cotes fonctionnelles a confirmer.",
        ],
        view_labels=labels,
        meta=meta,
    )


def build_arrangement_sheet(build: TractorBuild) -> Sheet:
    whole = build.groups["structure"].merged_with(build.groups["wheels"]).merged_with(
        build.groups["engine"]).merged_with(build.groups["body"]).merged_with(build.groups["cabin"])
    sheet = build_part_sheet("ENSEMBLE", whole, "Vue d'ensemble - tracteur", "assemblage")
    sheet.name = "ENSEMBLE-00"
    sheet.title = "Tracteur - vue d'ensemble (ensemble)"
    sheet.notes.append("Dessin d'ensemble: pieces individuelles sur feuilles PIECE-*.")
    return sheet


# --------------------------------------------------------------------------- #
# Wiring sheet + wire schedule
# --------------------------------------------------------------------------- #
def _wire_layers(group: str) -> str:
    return {"power": "PUISSANCE", "lighting": "ECLAIRAGE",
            "signalling": "SIGNALISATION", "control": "COMMANDE"}.get(group, "FAISCEAU")


def build_wire_schedule(design: dict[str, Any]) -> list[dict[str, str]]:
    """Terminal-to-terminal schedule derived from the design (source of truth)."""
    rows: list[dict[str, str]] = []
    n = 0
    for c in design["circuits"]:
        kind = c["kind"]
        fuse = f"F{c['fuse_a']:g}" if c["fuse_a"] else "-"
        if kind == "feed":
            n += 1
            rows.append({"id": f"W{n:02d}", "de": "BAT+", "vers": "BOITE FUSIBLES",
                         "circuit": c["description"], "a": f"{c['current_a']:.1f}",
                         "mm2": f"{c['gauge_mm2']:g}", "couleur": c["color"], "fusible": fuse,
                         "layer": _wire_layers("power")})
        elif kind == "alternator":
            n += 1
            rows.append({"id": f"W{n:02d}", "de": "ALT B+", "vers": "BAT+",
                         "circuit": c["description"], "a": f"{c['current_a']:.1f}",
                         "mm2": f"{c['gauge_mm2']:g}", "couleur": c["color"], "fusible": fuse,
                         "layer": _wire_layers("power")})
        elif kind == "starter":
            n += 1
            rows.append({"id": f"W{n:02d}", "de": "BAT+", "vers": "DEMARREUR",
                         "circuit": c["description"], "a": f"{c['current_a']:.1f}",
                         "mm2": f"{c['gauge_mm2']:g}", "couleur": c["color"], "fusible": "sans (solenoide)",
                         "layer": _wire_layers("power")})
        else:
            n += 1
            rows.append({"id": f"W{n:02d}", "de": "BOITE FUSIBLES", "vers": c["description"].upper()[:24],
                         "circuit": c["name"], "a": f"{c['current_a']:.1f}",
                         "mm2": f"{c['gauge_mm2']:g}", "couleur": c["color"], "fusible": fuse,
                         "layer": _wire_layers("signalling" if c["name"] in ("horn",) else
                                               "lighting" if "light" in c["name"] else "control")})
            n += 1
            rows.append({"id": f"W{n:02d}", "de": c["description"].upper()[:24], "vers": "MASSE CHASSIS",
                         "circuit": c["name"] + " (retour)", "a": f"{c['current_a']:.1f}",
                         "mm2": f"{c['gauge_mm2']:g}", "couleur": "noir", "fusible": "-",
                         "layer": "FAISCEAU"})
    return rows


def build_wiring_sheet(design: dict[str, Any], project_id: str) -> Sheet:
    rows = build_wire_schedule(design)
    edges: list[Edge2D] = []
    # Left column: sources; right: fuse box + consumers (simple orthogonal routing).
    src_x, fb_x = 60.0, 300.0
    y = 240.0
    step = 22.0
    # battery bus
    edges.append(Edge2D(src_x, 250, src_x, 60, "visible"))
    edges.append(Edge2D(fb_x, 250, fb_x, 60, "visible"))
    for r in rows:
        if r["de"] == "BAT+" and r["vers"] == "BOITE FUSIBLES":
            edges.append(Edge2D(src_x, 250, fb_x, 250, "visible"))
        elif r["de"] == "ALT B+":
            edges.append(Edge2D(src_x, 235, fb_x - 20, 235, "visible"))
            edges.append(Edge2D(fb_x - 20, 235, fb_x - 20, 250, "visible"))
        elif r["de"] == "BAT+":
            edges.append(Edge2D(src_x, 220, src_x - 20, 220, "visible"))
        elif r["vers"] == "MASSE CHASSIS":
            edges.append(Edge2D(fb_x, 60, 380, 60, "visible"))
        else:
            y -= step
            edges.append(Edge2D(fb_x, y, 380, y, "visible"))
    # connection table as text is added via notes (readable in DXF/SVG)
    notes = ["TABLEAU DE CABLAGE (DE -> VERS):"]
    for r in rows:
        notes.append(f"{r['id']}  {r['de']} -> {r['vers']}  {r['mm2']} mm2  {r['couleur']}  {r['fusible']}  {r['a']} A")
    notes += ["Sections dimensionnees: capacite >= 1.25*I et dU <= 3% (voir design JSON).",
              "Retours de masse: chssis (convention monofil).",
              "A VALIDER - schema unifilaire de principe, pas un schema de fabrication."]
    return Sheet(name="CABLAGE-01", title="Cablage complet - réseau 12 V",
                 scale=1.0, edges=edges, dims=[],
                 notes=notes[:40])


# --------------------------------------------------------------------------- #
# Electrical SCHEMATIC as a sheet (DXF + SVG): components as symbols,
# wires on functional layers, fuse labels, ground bus, legend.
# --------------------------------------------------------------------------- #
def build_schematic_sheet(design: dict[str, Any], project_id: str) -> Sheet:
    """Unifilar-style 12 V schematic rendered as drafting entities.

    Layers: COMPOSANT (symbols), PUISSANCE / ECLAIRAGE / SIGNALISATION /
    COMMANDE (wires), MASSE (ground bus), TEXTE (labels). Same netlist as
    the SVG schematic - single source of truth.
    """
    edges: list[Edge2D] = []
    labels: list[tuple[str, float, float]] = []

    def wire(layer: str, pts: list[tuple[float, float]]) -> None:
        for (x1, y1), (x2, y2) in zip(pts[:-1], pts[1:]):
            edges.append(Edge2D(x1, y1, x2, y2, layer=layer))

    def box(x: float, y: float, w: float, h: float) -> None:
        for p, q in (((x, y), (x + w, y)), ((x + w, y), (x + w, y + h)),
                     ((x + w, y + h), (x, y + h)), ((x, y + h), (x, y))):
            edges.append(Edge2D(p[0], p[1], q[0], q[1], layer="COMPOSANT"))

    loads = [c for c in design["circuits"] if c["kind"] in ("load", "starter")]
    feed = next((c for c in design["circuits"] if c["kind"] == "feed"), None)
    alt = next((c for c in design["circuits"] if c["kind"] == "alternator"), None)
    starter = next((c for c in loads if c["kind"] == "starter"), None)

    U = design["system_voltage"]
    # ---------------- sources column ----------------
    bx, by, bw, bh = 40.0, 160.0, 34.0, 52.0
    box(bx, by, bw, bh)
    labels.append((f"BATTERIE {U:.0f}V / {design['battery']['capacity_ah']:.0f}Ah (HYP.)",
                   bx + bw / 2, by - 4))
    ax, ay, aw, ah = 40.0, 250.0, 44.0, 22.0
    box(ax, ay, aw, ah)
    labels.append((f"ALTERNATEUR {design['alternator']['max_current_a']:.0f}A (HYP.)",
                   ax + aw / 2, ay + ah + 6))
    sx, sy, sw_, sh_ = 40.0, 60.0, 44.0, 22.0
    box(sx, sy, sw_, sh_)
    labels.append(("DÉMARREUR", sx + sw_ / 2, sy - 4))

    # ---------------- fuse box ----------------
    n = len(loads)
    fbx, fby, fbw, fbh = 150.0, 60.0, 30.0, 40.0 + 18.0 * n
    box(fbx, fby, fbw, fbh)
    labels.append(("BOÎTE À FUSIBLES", fbx + fbw / 2, fby + fbh + 6))

    # battery+ -> fuse box (via main fuse), alternator B+ -> battery+
    wire("PUISSANCE", [(bx + bw, by + bh - 6), (fbx, by + bh - 6)])
    labels.append((f"F principal - {feed['gauge_mm2'] if feed else '?'} mm²",
                   (bx + bw + fbx) / 2, by + bh - 2))
    wire("PUISSANCE", [(ax + aw, ay + ah / 2), (bx + bw / 2, ay + ah / 2),
                        (bx + bw / 2, by + bh)])
    # battery+ -> starter (unfused, solenoid)
    if starter:
        wire("PUISSANCE", [(bx + 6, by), (bx + 6, sy + sh_ / 2), (sx, sy + sh_ / 2)])

    # ---------------- consumers with fuse drops ----------------
    ground_y = 24.0
    for i, c in enumerate(loads):
        ry = fby + 30.0 + 18.0 * i
        layer = {"signalling": "SIGNALISATION", "lighting": "ECLAIRAGE",
                 "control": "COMMANDE"}.get(
            "lighting" if "light" in c["name"] else
            "signalling" if c["name"] == "horn" else "control", "COMMANDE")
        if c["kind"] == "starter":
            layer = "PUISSANCE"
        fuse_txt = f"F{c['fuse_a']:.4g}" if c["fuse_a"] else "sans F*"
        wire(layer, [(fbx + fbw, ry), (240.0, ry)])
        labels.append((f"{fuse_txt} - {c['gauge_mm2']} mm² - {c['current_a']:.1f}A",
                       (fbx + fbw + 240) / 2, ry + 3))
        lb_x, lb_w, lb_h = 240.0, 90.0, 12.0
        box(lb_x, ry - lb_h / 2, lb_w, lb_h)
        labels.append((c["description"][:28], lb_x + lb_w / 2, ry - lb_h / 2 - 2))
        # ground return to chassis bus
        wire("MASSE", [(lb_x + lb_w / 2, ry - lb_h / 2), (lb_x + lb_w / 2, ground_y)])

    # ---------------- ground bus + battery return ----------------
    wire("MASSE", [(30.0, ground_y), (370.0, ground_y)])
    wire("MASSE", [(bx + 6, by), (bx + 6, ground_y)])
    labels.append(("MASSE CHÂSSIS", 370.0, ground_y + 4))

    notes = [
        "SCHEMA ELECTRIQUE 12 V (unifilaire de principe) - A VERIFIER.",
        f"Regles: capacite >= 1.25*I, dU <= {design['max_drop_pct']:.0f} %, "
        f"cuivre rho={design['copper_rho']} ohm.mm2/m (HYP.).",
        "* Demarreur: sans fusible en ligne (convention solenoide), cable dimensionne par capacite.",
        "Calques: PUISSANCE=rouge, ECLAIRAGE=jaune, SIGNALISATION=vert, COMMANDE=cyan, MASSE=gris.",
    ]
    return Sheet(name="SCHEMA-01", title=f"Schéma électrique {U:.0f} V",
                 scale=1.0, edges=edges, dims=[], notes=notes,
                 view_labels=labels)
