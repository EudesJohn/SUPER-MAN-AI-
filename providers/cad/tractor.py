"""CadProvider: parametric compact tractor in real 3D (internal mesh kernel).

Assemblies (mm): chassis frame, front/rear axles, 4 wheels (rim+tire+tread),
engine block, hood (tapered), cabin (posts+roof), seat, fuel tank, exhaust,
front/rear weight brackets, PTO stub, drawbar, steps.
Electrical 3D: battery, alternator, starter, fuse box, horn, headlights
(x2), taillights (x2), and the WIRE HARNESS routed as real tubes so the
complete 12 V circuit is visible inside the machine.

Body panels and internals are exported as SEPARATE color-group STL files so
the circuit remains inspectable (body can be hidden in the viewer).
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from providers.cad import mesh
from providers.cad.provider import MeshCadProvider
from providers.cad.solver import mass_properties

MM = 0.001  # mm -> m (internal units are meters)

STEEL = 7850.0        # kg/m3 (material database value)
IRON_CAST = 7200.0    # grey cast iron (HYPOTHESIS)
RUBBER = 1100.0
PLASTIC = 1050.0
GLASS = 2500.0
LEAD_ACID = 1500.0    # effective battery box density (HYPOTHESIS)

# Group -> (STL filename, viewer color, density)
GROUP_SPECS = {
    "body": ("tractor_body.stl", "#4caf50", PLASTIC),        # hood, fenders, roof
    "structure": ("tractor_structure.stl", "#8d99ae", STEEL),  # frame, axles, brackets, steps
    "wheels": ("tractor_wheels.stl", "#343a40", RUBBER),
    "engine": ("tractor_engine.stl", "#adb5bd", IRON_CAST),
    "cabin": ("tractor_cabin.stl", "#74c0fc", GLASS),          # posts, roof, seat, tank
    "electrical": ("tractor_electrical.stl", "#f59f00", LEAD_ACID),
    "harness": ("tractor_harness.stl", "#e8590c", PLASTIC),
}


@dataclass
class TractorBuild:
    groups: dict[str, mesh.Mesh] = field(default_factory=dict)
    parts: list[dict[str, Any]] = field(default_factory=list)
    part_meshes: dict[str, mesh.Mesh] = field(default_factory=dict)

    def add(self, group: str, name: str, m: mesh.Mesh, density: float, note: str = "",
            shell_thickness_m: float | None = None) -> mesh.Mesh:
        """Register a part. Solid parts use exact volume integration; thin-walled
        parts (body panels, glazing) MUST pass shell_thickness_m so their mass
        is area x thickness x density instead of the absurd solid volume."""
        if shell_thickness_m is not None:
            from providers.cad.solver import shell_mass
            mp = shell_mass(m, density, shell_thickness_m)
        else:
            mp = mass_properties(m, density)
        self.groups.setdefault(group, mesh.Mesh(np_empty3(), np_empty3_i()))
        self.groups[group] = self.groups[group].merged_with(m)
        self.part_meshes[name] = m  # kept for individual part drawings
        self.parts.append({
            "name": name, "group": group, "triangles": m.n_triangles,
            "mass_kg": round(mp.mass_kg, 2),
            "center_of_mass_mm": [round(c * 1000, 1) for c in mp.center_of_mass],
            "note": note,
            "shell_thickness_mm": (round(shell_thickness_m * 1000, 1)
                                   if shell_thickness_m is not None else None),
            "surface_area_m2": (round(mp.surface_area_m2, 3)
                                if shell_thickness_m is not None else None),
        })
        return m


def np_empty3():
    import numpy as np
    return np.zeros((0, 3))


def np_empty3_i():
    import numpy as np
    return np.zeros((0, 3), dtype=int)


def wheel(radius_m: float, width_m: float, rim_r: float, spokes: int = 6) -> mesh.Mesh:
    """Tire (torus + crown approximated by large-radius torus cross) + rim disc + spokes."""
    tire = mesh.torus(radius_m * 0.86, radius_m * 0.16, 36, 14, axis="y")
    # tread lugs around the tire
    lugs = []
    import numpy as np
    for i in range(16):
        a = 360.0 * i / 16.0
        lug = mesh.box(radius_m * 0.28, width_m * 1.04, radius_m * 0.10)
        lugs.append(mesh.place(lug, x=radius_m * 0.98, y=0.0, z=0.0, rz=a))
    rim = mesh.cylinder(rim_r, rim_r, width_m * 0.72, 28, axis="y")
    hub = mesh.cylinder(rim_r * 0.28, rim_r * 0.28, width_m * 0.9, 20, axis="y")
    sp = []
    for i in range(spokes):
        s = mesh.box(rim_r * 1.7, width_m * 0.4, rim_r * 0.16)
        sp.append(mesh.place(s, rz=360.0 * i / spokes, rx=0.0))
    return mesh.merge_all([tire, rim, hub] + lugs + sp)


def build_tractor(spec: dict[str, Any] | None = None) -> TractorBuild:
    s = {
        "wheelbase_mm": 1600, "track_mm": 1100, "rear_wheel_r_mm": 560,
        "front_wheel_r_mm": 380, "rear_wheel_w_mm": 320, "front_wheel_w_mm": 200,
        "engine_l_mm": 620, "engine_w_mm": 480, "engine_h_mm": 520,
        "hood_l_mm": 900, "hood_w_mm": 640, "hood_h_mm": 420,
        "cabin_l_mm": 1300, "cabin_w_mm": 1200, "cabin_h_mm": 1500,
        "frame_h_mm": 140, "battery_cc_mm": (-250, -380, 420),
        "alternator_cc_mm": (-620, 190, 380),
        "starter_cc_mm": (-560, -260, 120),
        "fuse_box_cc_mm": (200, -430, 620),
        "headlight_dx_mm": 640, "horn_cc_mm": (420, 0, 500),
        "taillight_x_mm": 760,
    }
    if spec:
        s.update(spec)
    b = TractorBuild()

    wb = s["wheelbase_mm"] * MM          # wheelbase (m), x = length, y = width, z = height
    tr = s["track_mm"] * MM / 2.0
    rr, fr = s["rear_wheel_r_mm"] * MM, s["front_wheel_r_mm"] * MM
    rww, fww = s["rear_wheel_w_mm"] * MM, s["front_wheel_w_mm"] * MM

    # ---------------- chassis frame (ladder) ----------------
    frame_parts = []
    for side in (-1, 1):
        rail = mesh.box(wb + 1200 * MM, 120 * MM, s["frame_h_mm"] * MM)
        frame_parts.append(mesh.place(rail, x=0, y=side * (tr - 120 * MM), z=rr + 60 * MM))
    cross1 = mesh.box(120 * MM, 2 * tr - 240 * MM, 120 * MM)
    frame_parts.append(mesh.place(cross1, x=-wb / 2, z=rr + 60 * MM))
    frame_parts.append(mesh.place(mesh.box(120 * MM, 2 * tr - 240 * MM, 120 * MM), x=wb / 2, z=rr + 60 * MM))
    b.add("structure", "chassis_frame", mesh.merge_all(frame_parts), STEEL, "2 longerons + 2 traverses")

    # ---------------- axles ----------------
    front_axle = mesh.cylinder(tr + 60 * MM, tr + 60 * MM, 90 * MM, 24, axis="y")
    b.add("structure", "front_axle", mesh.place(front_axle, x=-wb / 2, z=rr), STEEL)
    rear_housing = mesh.cylinder(tr + 120 * MM, tr + 120 * MM, 160 * MM, 24, axis="y")
    b.add("structure", "rear_axle_housing", mesh.place(rear_housing, x=wb / 2, z=rr), STEEL)

    # ---------------- wheels ----------------
    wheels = []
    for sign in (-1, 1):
        wheels.append(mesh.place(wheel(rr, rww, rr * 0.45), x=wb / 2, y=sign * tr, z=rr))
        wheels.append(mesh.place(wheel(fr, fww, fr * 0.45, 5), x=-wb / 2, y=sign * tr, z=fr))
    b.add("wheels", "wheels_4x", mesh.merge_all(wheels), RUBBER,
          "2 arrière Ø1120 + 2 avant Ø760 (jante + pneu + crampons)")

    # ---------------- engine ----------------
    eng = mesh.box(s["engine_l_mm"] * MM, s["engine_w_mm"] * MM, s["engine_h_mm"] * MM)
    eng_c = (-wb / 2 - 80 * MM, 0.0, rr + 260 * MM)
    engine = mesh.place(eng, *eng_c)
    # cylinders head
    head = mesh.box(s["engine_l_mm"] * MM * 0.5, s["engine_w_mm"] * MM * 0.9, 120 * MM)
    engine = engine.merged_with(mesh.place(head, x=eng_c[0] - 60 * MM, z=eng_c[2] + s["engine_h_mm"] * MM / 2 + 60 * MM))
    b.add("engine", "engine_block_4cyl", engine, IRON_CAST, "moteur diesel 4 cylindres (HYPOTHÈSE)")

    # ---------------- hood + fenders (body) ----------------
    hood = mesh.tapered_box(s["hood_l_mm"] * MM, s["hood_w_mm"] * MM, s["hood_h_mm"] * MM, 0.55, 0.55)
    b.add("body", "hood", mesh.place(hood, x=eng_c[0], y=0, z=rr + 330 * MM), PLASTIC, "capot (panneau amovible)")

    fenders = []
    for sign in (-1, 1):
        f = mesh.box(1000 * MM, 40 * MM, 380 * MM)
        fenders.append(mesh.place(f, x=wb / 2 - 100 * MM, y=sign * (tr + rww * 0.55), z=rr + 480 * MM))
        arch = mesh.torus(rr * 1.06, 24 * MM, 28, 8, axis="y")
        fenders.append(mesh.place(arch, x=wb / 2, y=sign * (tr + rww * 0.75), z=rr))
    b.add("body", "rear_fenders", mesh.merge_all(fenders), PLASTIC)

    # ---------------- cabin (structure + glazing) ----------------
    cl, cw, ch = s["cabin_l_mm"] * MM, s["cabin_w_mm"] * MM, s["cabin_h_mm"] * MM
    cab_cx = wb / 2 - cl / 2 - 120 * MM
    posts = []
    for dx in (-1, 1):
        for dy in (-1, 1):
            p = mesh.box(90 * MM, 90 * MM, ch)
            posts.append(mesh.place(p, x=cab_cx + dx * (cl / 2 - 45 * MM),
                                    y=dy * (cw / 2 - 45 * MM), z=rr + 240 * MM + ch / 2))
    roof = mesh.box(cl + 80 * MM, cw + 80 * MM, 60 * MM)
    posts.append(mesh.place(roof, x=cab_cx, z=rr + 240 * MM + ch + 30 * MM))
    b.add("cabin", "cab_frame_roof", mesh.merge_all(posts), PLASTIC, "montants + toit")

    glass_w = []
    for dy in (-1, 1):
        g = mesh.box(cl - 120 * MM, 14 * MM, ch - 160 * MM)
        glass_w.append(mesh.place(g, x=cab_cx, y=dy * (cw / 2 - 45 * MM), z=rr + 240 * MM + ch / 2))
    front_g = mesh.box(14 * MM, cw - 120 * MM, ch - 160 * MM)
    glass_w.append(mesh.place(front_g, x=cab_cx - (cl / 2 - 45 * MM), z=rr + 240 * MM + ch / 2))
    b.add("cabin", "cab_glazing", mesh.merge_all(glass_w), GLASS, "vitres cabine")

    seat = mesh.box(420 * MM, 440 * MM, 90 * MM)
    b.add("cabin", "seat", mesh.place(seat, x=cab_cx + 60 * MM, z=rr + 500 * MM), PLASTIC, "siège")
    tank = mesh.cylinder(180 * MM, 180 * MM, 400 * MM, 24, axis="x")
    b.add("cabin", "fuel_tank", mesh.place(tank, x=wb / 2 - 900 * MM, z=rr + 320 * MM), PLASTIC,
          "réservoir gasoil (HYPOTHÈSE capacité ~40 L)")

    # ---------------- accessories ----------------
    weight = mesh.box(120 * MM, 700 * MM, 260 * MM)
    b.add("structure", "front_weights", mesh.place(weight, x=-wb / 2 - 640 * MM, z=rr + 130 * MM), STEEL)
    drawbar = mesh.box(60 * MM, 700 * MM, 90 * MM)
    b.add("structure", "drawbar", mesh.place(drawbar, x=wb / 2 + 620 * MM, z=rr - 180 * MM), STEEL)
    pto = mesh.cylinder(45 * MM, 45 * MM, 120 * MM, 16, axis="x")
    b.add("structure", "pto_stub", mesh.place(pto, x=wb / 2 + 480 * MM, z=rr + 40 * MM), STEEL,
          "prise de force Ø35 (simplifiée)")
    steps = mesh.box(240 * MM, 320 * MM, 20 * MM)
    b.add("structure", "access_step", mesh.place(steps, x=cab_cx - cl / 2 - 120 * MM, y=-cw / 2 - 60 * MM, z=rr - 120 * MM), STEEL)
    exhaust = mesh.cylinder(38 * MM, 38 * MM, 720 * MM, 14)
    b.add("engine", "exhaust_pipe", mesh.place(exhaust, x=eng_c[0] - 200 * MM, y=210 * MM, z=rr + 700 * MM), STEEL)

    # ================= ELECTRICAL 3D =================
    elec_parts = []

    def battery(cc, ah=80):
        body = mesh.box(340 * MM, 180 * MM, 220 * MM)
        terminals = [
            mesh.place(mesh.cylinder(12 * MM, 12 * MM, 30 * MM, 12), x=120 * MM, z=115 * MM),
            mesh.place(mesh.cylinder(12 * MM, 12 * MM, 30 * MM, 12), x=-120 * MM, z=115 * MM),
        ]
        return mesh.place(mesh.merge_all([body] + terminals), *cc)

    b.add("electrical", "battery_12V_80Ah", battery(s["battery_cc_mm"]), LEAD_ACID,
          "batterie 12 V 80 Ah (HYPOTHÈSE)")

    alt = mesh.merge_all([
        mesh.cylinder(90 * MM, 90 * MM, 160 * MM, 20, axis="x"),
        mesh.place(mesh.cylinder(30 * MM, 30 * MM, 90 * MM, 12, axis="x"), x=120 * MM),
    ])
    b.add("electrical", "alternator_90A", mesh.place(alt, *s["alternator_cc_mm"]), IRON_CAST,
          "alternateur 90 A (HYPOTHÈSE)")

    st = mesh.merge_all([
        mesh.cylinder(70 * MM, 70 * MM, 260 * MM, 18, axis="x"),
        mesh.place(mesh.cylinder(45 * MM, 45 * MM, 120 * MM, 12, axis="x"), x=170 * MM),
    ])
    b.add("electrical", "starter_motor", mesh.place(st, *s["starter_cc_mm"]), IRON_CAST, "démarreur")

    fbox = mesh.box(220 * MM, 160 * MM, 120 * MM)
    b.add("electrical", "fuse_box", mesh.place(fbox, *s["fuse_box_cc_mm"]), PLASTIC, "boîte à fusibles/relais")

    horn = mesh.merge_all([mesh.torus(70 * MM, 22 * MM, 20, 10, axis="x")])
    b.add("electrical", "horn", mesh.place(horn, *s["horn_cc_mm"]), IRON_CAST)

    lights = []
    hx = s["headlight_dx_mm"] * MM
    for sign in (-1, 1):
        h = mesh.cylinder(110 * MM, 130 * MM, 90 * MM, 20, axis="x")
        lights.append(mesh.place(h, x=hx, y=sign * 260 * MM, z=rr + 430 * MM))
    b.add("electrical", "headlights_2x", mesh.merge_all(lights), GLASS, "phares H4 55 W (HYPOTHÈSE)")
    for sign in (-1, 1):
        t = mesh.box(60 * MM, 130 * MM, 90 * MM)
        lights = mesh.place(t, x=s["taillight_x_mm"] * MM, y=sign * (tr + 100 * MM), z=rr + 380 * MM)
        b.add("electrical", "taillight", lights, GLASS, "feu arrière 21 W (HYPOTHÈSE)")

    # ---------------- harness: real routed wires ----------------
    bat = s["battery_cc_mm"]
    fbx = s["fuse_box_cc_mm"]
    routes: dict[str, list[list[float]]] = {
        "feed_main_bat_fusebox": [bat, [bat[0], bat[1] - 120 * MM, fbx[2]], fbx],
        "alt_bplus_bat": [s["alternator_cc_mm"], [bat[0] + 60 * MM, bat[1], bat[2] + 260 * MM],
                          [bat[0] + 120 * MM, bat[1], bat[2] + 130 * MM]],
        "starter_bplus": [bat, [s["starter_cc_mm"][0] + 150 * MM, s["starter_cc_mm"][1], s["starter_cc_mm"][2]],
                          s["starter_cc_mm"]],
        "headlight_left": [fbx, [400 * MM, -200 * MM, 480 * MM], [hx, -260 * MM, rr + 430 * MM]],
        "headlight_right": [fbx, [400 * MM, 200 * MM, 480 * MM], [hx, 260 * MM, rr + 430 * MM]],
        "tail_left": [fbx, [600 * MM, -350 * MM, 420 * MM], [s["taillight_x_mm"] * MM, -(tr + 100 * MM), rr + 380 * MM]],
        "tail_right": [fbx, [600 * MM, 350 * MM, 420 * MM], [s["taillight_x_mm"] * MM, tr + 100 * MM, rr + 380 * MM]],
        "dash_panel": [fbx, [cab_cx, 0, rr + 240 * MM + ch - 60 * MM]],
        "horn_wire": [fbx, [s["horn_cc_mm"][0] - 60 * MM, 0, s["horn_cc_mm"][2] + 60 * MM], s["horn_cc_mm"]],
        "ecu_wire": [fbx, [eng_c[0] + 200 * MM, -240 * MM, rr + 420 * MM], [eng_c[0], -240 * MM, rr + 380 * MM]],
    }
    wire_r = {"feed_main_bat_fusebox": 8 * MM, "alt_bplus_bat": 7 * MM, "starter_bplus": 14 * MM}
    for name, pts in routes.items():
        r = wire_r.get(name, 4 * MM)
        w = mesh.tube_along(pts, r, 8)
        b.add("harness", name, w, PLASTIC, "faisceau (gaine Ø" + str(round(2 * r * 1000)) + " mm)")
    # ground straps (chassis return)
    for tgt in [s["alternator_cc_mm"], s["starter_cc_mm"], [hx, -260 * MM, rr + 430 * MM],
                [s["taillight_x_mm"] * MM, -(tr + 100 * MM), rr + 380 * MM]]:
        g = mesh.tube_along([tgt, [0.0, tgt[1] * 0.5, rr + 60 * MM]], 3 * MM, 6)
        b.add("harness", "ground_strap", g, PLASTIC, "return to chassis ground (mass)")
    return b


def export_mechanical_groups(
    b: TractorBuild,
    out_dir: str,
    writer,
    provider: MeshCadProvider | None = None,
) -> dict[str, Any]:
    """Export only mechanical groups (no STL harness/electrical) - used by the
    car deliverables where electricity lives in separate HV/LV DXF+CSV data."""
    prov = provider or MeshCadProvider()
    files: dict[str, dict] = {}
    total_mass = 0.0
    for group, m in b.groups.items():
        if group not in GROUP_SPECS:
            continue
        fname, color, density = GROUP_SPECS[group]
        rel_path = f"{out_dir}/{fname}"
        written = writer(rel_path, prov.export_mesh_bytes(m, "stl"))
        files[group] = {"path": rel_path, "triangles": m.n_triangles,
                        "color": color, "checksum": written.get("checksum", "")}
        total_mass += mass_properties(m, density).mass_kg
    return {"files": files, "parts": b.parts, "total_mass_kg": round(total_mass, 1),
            "total_triangles": sum(p["triangles"] for p in b.parts)}


def export_tractor(
    b: TractorBuild,
    out_dir: str,
    writer,
    provider: MeshCadProvider | None = None,
) -> dict[str, Any]:
    """Export all groups as separate STL files through the sandboxed writer.

    writer(path: str, data: bytes) -> dict  (e.g. ToolRegistry write_file_bytes)
    """
    prov = provider or MeshCadProvider()
    files: dict[str, dict] = {}
    total_mass = 0.0
    for group, m in b.groups.items():
        fname, color, density = GROUP_SPECS[group]
        rel_path = f"{out_dir}/{fname}"
        written = writer(rel_path, prov.export_mesh_bytes(m, "stl"))
        files[group] = {"path": rel_path, "triangles": m.n_triangles,
                        "color": color, "checksum": written.get("checksum", "")}
        total_mass += mass_properties(m, density).mass_kg
    return {"files": files, "parts": b.parts, "total_mass_kg": round(total_mass, 1),
            "total_triangles": sum(p["triangles"] for p in b.parts)}
