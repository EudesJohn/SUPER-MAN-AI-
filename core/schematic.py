"""Electrical schematic renderer: deterministic SVG from the design netlist.

This is a genuine generated drawing (components, colored wires, fuse labels,
ground bus, legend, title block) computed from the stored ElectricalDesign.
It is a schematic for review - clearly marked as requiring human validation.
"""
from __future__ import annotations

import html
from typing import Any

SVG_COLORS = {
    "red": "#d62828", "black": "#1d1d1d", "yellow": "#e9c46a",
    "green": "#2a9d8f", "blue": "#457bd9", "orange": "#f77f00", "gray": "#9a9a9a",
}

W = 1100
H = 800


def _text(x, y, s, size=13, anchor="start", color="#222", bold=False):
    weight = ' font-weight="bold"' if bold else ""
    return (f'<text x="{x}" y="{y}" font-family="Segoe UI, Arial" font-size="{size}" '
            f'text-anchor="{anchor}" fill="{color}"{weight}>{html.escape(str(s))}</text>')


def _rect(x, y, w, h, fill="#fff", stroke="#333", sw=1.5, rx=3):
    return (f'<rect x="{x}" y="{y}" width="{w}" height="{h}" fill="{fill}" '
            f'stroke="{stroke}" stroke-width="{sw}" rx="{rx}"/>')


def _poly(points: str, color: str, width: float) -> str:
    """Orthogonal wire polyline."""
    return (f'<polyline points="{points}" fill="none" stroke="{color}" '
            f'stroke-width="{width}" stroke-linejoin="round"/>')


def render_schematic_svg(design: dict[str, Any], title: str = "Circuit électrique 12 V") -> str:
    U = design["system_voltage"]
    circuits = design["circuits"]
    loads = [c for c in circuits if c["kind"] in ("load", "starter")]
    feed = next((c for c in circuits if c["kind"] == "feed"), None)
    alt = next((c for c in circuits if c["kind"] == "alternator"), None)
    starter = next((c for c in loads if c["kind"] == "starter"), None)

    parts: list[str] = []
    parts.append(f'<svg xmlns="http://www.w3.org/2000/svg" width="{W}" height="{H}" viewBox="0 0 {W} {H}">')
    parts.append(_rect(0, 0, W, H, fill="#fafafa", stroke="#999"))

    # ---------------- left column: sources ----------------
    bx, by, bw, bh = 60, 340, 110, 170
    parts.append(_rect(bx, by, bw, bh, fill="#2f3e46"))
    parts.append(_text(bx + bw / 2, by + 40, "BATTERIE", size=14, anchor="middle", color="#fff", bold=True))
    parts.append(_text(bx + bw / 2, by + 62, f"{U:.0f} V / {design['battery']['capacity_ah']:.0f} Ah", size=12, anchor="middle", color="#fff"))
    parts.append(_text(bx + bw / 2, by + 80, "(HYPOTHÈSE)", size=10, anchor="middle", color="#cbd5d1"))
    parts.append(f'<circle cx="{bx + 25}" cy="{by}" r="5" fill="{SVG_COLORS["red"]}"/>')
    parts.append(f'<circle cx="{bx + 25}" cy="{by + bh}" r="5" fill="{SVG_COLORS["black"]}"/>')

    # alternator above the battery
    ax, ay, aw, ah = 60, 130, 150, 70
    parts.append(_rect(ax, ay, aw, ah, fill="#e8eaed"))
    parts.append(_text(ax + aw / 2, ay + 30, "ALTERNATEUR", size=13, anchor="middle", bold=True))
    parts.append(_text(ax + aw / 2, ay + 50, f"{design['alternator']['max_current_a']:.0f} A max (HYP.)", size=11, anchor="middle"))

    # starter below the battery
    sx, sy, sw_, sh_ = 60, 570, 150, 70
    parts.append(_rect(sx, sy, sw_, sh_, fill="#e8eaed"))
    parts.append(_text(sx + sw_ / 2, sy + 30, "DÉMARREUR", size=13, anchor="middle", bold=True))
    if starter:
        parts.append(_text(sx + sw_ / 2, sy + 50,
                           f"{starter['load_w']:.0f} W - {starter['gauge_mm2']} mm² - sans fusible*",
                           size=11, anchor="middle"))

    # main fuse between battery+ and distribution
    fx, fy, fw, fh = 260, 380, 80, 36
    parts.append(_rect(fx, fy, fw, fh, fill="#fff", stroke="#d62828", sw=2))
    main_lbl = f"{alt['fuse_a'] or 100:.0f} A" if alt else "100 A"
    parts.append(_text(fx + fw / 2, fy + 23, f"Fusible principal {main_lbl}", size=10, anchor="middle"))

    # ---------------- distribution box (fuses) ----------------
    fbx, fby, fbw, fbh = 430, 100, 210, 60 + 58 * len(loads)
    parts.append(_rect(fbx, fby, fbw, fbh, fill="#eef2f7", stroke="#3d5a80", sw=2))
    parts.append(_text(fbx + fbw / 2, fby + 22, "BOÎTE À FUSIBLES", size=13, anchor="middle", bold=True))

    bus_y = fy + fh / 2
    # battery+ -> main fuse -> distribution box
    if feed:
        parts.append(_poly(f"{bx + bw},{by + 25} {fx},{bus_y}", SVG_COLORS["red"], 1 + feed["gauge_mm2"] / 8))
        parts.append(_poly(f"{fx + fw},{bus_y} {fbx},{fby + 50}", SVG_COLORS["red"], 1 + feed["gauge_mm2"] / 8))
        parts.append(_text(fx + fw + 10, bus_y - 6, f'{feed["gauge_mm2"]} mm² - F{feed["fuse_a"]:.0f} A', size=10, color=SVG_COLORS["red"]))
    # alternator B+ -> battery+
    if alt:
        parts.append(_poly(f"{ax + aw},{ay + ah / 2} {bx + bw / 2 + 60},{ay + ah / 2} {bx + bw / 2 + 60},{by - 12} {bx + bw / 2},{by - 12}",
                           SVG_COLORS["red"], 1 + alt["gauge_mm2"] / 8))
        parts.append(_text(ax + aw + 8, ay + ah / 2 - 6, f'B+ {alt["gauge_mm2"]} mm²', size=10, color=SVG_COLORS["red"]))
    # battery+ -> starter (no fuse; solenoid-switched, thick cable)
    if starter:
        parts.append(_poly(f"{bx + 25},{by} {bx + 25},{sy + sh_ / 2} {sx},{sy + sh_ / 2}",
                           SVG_COLORS["red"], 1 + starter["gauge_mm2"] / 6))

    # ---------------- fuse rows + loads + wires ----------------
    row_y = fby + 52
    lx, lw_, lh = 760, 210, 44
    ground_bus_y = H - 70
    top_route_y = fby - 30
    for idx, c in enumerate(loads):
        color = SVG_COLORS.get(c["color"], "#888")
        fuse_txt = f'F{c["fuse_a"]:.4g} A' if c["fuse_a"] else "sans fusible*"
        parts.append(f'<circle cx="{fbx + 28}" cy="{row_y}" r="9" fill="#fff" stroke="{color}" stroke-width="2"/>')
        parts.append(_text(fbx + 44, row_y + 4, fuse_txt, size=11))
        # wire: fuse -> up above the box -> across -> down to the load
        xw = fbx + 28
        xl = lx + lw_ / 2 + (idx - len(loads) / 2) * 8
        parts.append(_poly(f"{xw},{row_y} {xw},{top_route_y} {xl},{top_route_y} {xl},{lh / 2}",
                           color, 1 + c["gauge_mm2"] / 8))
        parts.append(_text(xl + 6, top_route_y - 4, f'{c["gauge_mm2"]} mm²', size=9, color=color))
        # load box
        parts.append(_rect(lx, row_y - lh / 2, lw_, lh, fill="#fff", stroke=color, sw=2))
        parts.append(_text(lx + 10, row_y - 4, c["description"][:30], size=12, bold=True))
        pw = f'{c["load_w"]:.0f} W' if c["load_w"] else "-"
        parts.append(_text(lx + 10, row_y + 14, f'{pw} - {c["current_a"]:.1f} A - ΔU {c["drop_pct"]:.2f} %', size=10))
        # ground drop to the chassis bus
        parts.append(f'<line x1="{lx + lw_}" y1="{row_y}" x2="{ground_bus_y and (lx + lw_)}" y2="{ground_bus_y}" '
                     f'stroke="{SVG_COLORS["black"]}" stroke-width="0"/>')  # placeholder removed below
        parts.append(f'<line x1="{lx + lw_ / 2}" y1="{row_y + lh / 2}" x2="{lx + lw_ / 2}" y2="{ground_bus_y}" '
                     f'stroke="{SVG_COLORS["black"]}" stroke-width="2"/>')
        row_y += 58

    # ---------------- ground bus (chassis) ----------------
    parts.append(f'<line x1="60" y1="{ground_bus_y}" x2="{W - 60}" y2="{ground_bus_y}" '
                 f'stroke="{SVG_COLORS["black"]}" stroke-width="5"/>')
    gx = 70
    for _ in range(8):
        parts.append(f'<line x1="{gx}" y1="{ground_bus_y}" x2="{gx - 10}" y2="{ground_bus_y + 12}" '
                     f'stroke="#1d1d1d" stroke-width="2"/>')
        gx += 26
    parts.append(_text(W - 60, ground_bus_y - 8, "MASSE CHÂSSIS", size=12, anchor="end", bold=True))
    # battery - to the ground bus
    parts.append(f'<line x1="{bx + 25}" y1="{by + bh}" x2="{bx + 25}" y2="{ground_bus_y}" '
                 f'stroke="#1d1d1d" stroke-width="4"/>')

    # ---------------- legend + title block ----------------
    lgx, lgy, lgw, lgh = 690, 620, 380, 110
    parts.append(_rect(lgx, lgy, lgw, lgh, fill="#fff", stroke="#999"))
    parts.append(_text(lgx + 10, lgy + 20, "Légende", size=12, bold=True))
    parts.append(f'<rect x="{lgx + 10}" y="{lgy + 28}" width="16" height="10" fill="{SVG_COLORS["red"]}"/>')
    parts.append(_text(lgx + 34, lgy + 37, "rouge = alimentation B+ / démarreur", size=11))
    parts.append(_text(lgx + 34, lgy + 55, "jaune/vert/bleu/orange/gris = circuits récepteurs", size=11))
    parts.append(f'<rect x="{lgx + 10}" y="{lgy + 64}" width="16" height="10" fill="{SVG_COLORS["black"]}"/>')
    parts.append(_text(lgx + 34, lgy + 73, "noir = masse châssis (retours)", size=11))
    parts.append(_text(lgx + 10, lgy + 95,
                       f"Sections: ΔU ≤ {design['max_drop_pct']:.0f} %, cuivre ρ={design['copper_rho']} Ω·mm²/m (HYP.)",
                       size=10))

    parts.append(_rect(60, 690, 400, 80, fill="#fff", stroke="#333", sw=2))
    parts.append(_text(72, 712, f"Schéma: {title}", size=13, bold=True))
    parts.append(_text(72, 732, "Généré automatiquement par AI ENGINEER", size=11))
    parts.append(_text(72, 752, "À VÉRIFIER - validation humaine requise avant fabrication", size=11, color="#b23"))
    parts.append(_text(72, 768, "* démarreur: convention sans fusible en ligne (voir notes du design)", size=9, color="#666"))

    parts.append("</svg>")
    return "\n".join(parts)
