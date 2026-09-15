"""CadProvider: hyper-aerodynamic electric car (parametric, internal mesh kernel).

Design intent - aerodynamics FIRST (Cd target 0.19, typical modern EV ~0.23):
  - ONE-VOLUME teardrop body, LATHE-GENERATED from an aerodynamic profile:
    blunt rounded nose, maximum section BEHIND the cabin (t ~ 0.37 of length),
    long taper to a KAMM TAIL cut at t = 0.70 (capped flat). Elliptical
    sections (wide, low) with a fixed ground clearance; crest rises toward
    the rear. This profile family is the classic lowest-drag body shape.
  - Enclosed aero wheels (flat discs flush with the body sides).
  - Front splitter + rear diffuser + small active wing, flat underside.
  - Flush glazing, no mirrors (cameras), no grille (EV).

Powertrain (HYPOTHESES, all overridable): 300 kW PMSM, single reducer ~9:1,
95 kWh NMC pack (400 V class), Cd 0.19, frontal area 2.05 m2, ~1650 kg.

Electrical: HV 400 V network (battery -> inverter -> motor + DC-DC/OBC) and
LV 12 V network (lights, HVAC, ECU), sized by the deterministic engine and
routed as real 3D tubes inside the body.
"""
from __future__ import annotations

import math
from typing import Any

import numpy as np

from providers.cad import mesh
from providers.cad.mesh import Mesh
from providers.cad.provider import MeshCadProvider
from providers.cad.tractor import TractorBuild

MM = 0.001

STEEL = 7850.0
ALU = 2700.0
CARBON = 1600.0        # carbon composite body (HYPOTHESIS)
GLASS = 2500.0
RUBBER = 1100.0
COPPER = 8960.0

# Same group names as the tractor -> same colors/legend in viewers.
CAR_GROUPS = {
    "body": "car_body.stl",
    "structure": "car_structure.stl",
    "wheels": "car_wheels.stl",
    "engine": "car_powertrain.stl",
    "cabin": "car_cabin.stl",
    "electrical": "car_electrical_lv.stl",
    "harness": "car_harness_lv.stl",
}

AERO_DEFAULTS = {
    "car_length_mm": 4600,
    "car_width_mm": 1950,
    "car_height_mm": 1300,
    "wheel_r_mm": 340,
    "wheelbase_mm": 2900,
    "battery_kwh": 95.0,
    "motor_kw": 300.0,
    "cd": 0.19,
    "frontal_area_m2": 2.05,
    "mass_kg": 1650.0,
    "consumption_wh_per_km": 118.0,
}

# Aerodynamic profile: f(t) = sin(pi * t^0.75) on the FULL teardrop [0, 1];
# the Kamm tail truncates at t_kamm (still ~2/3 of max section, capped flat).
_PROFILE_N = 0.75
_T_KAMM = 0.70


def _profile(t: float) -> float:
    return math.sin(math.pi * t ** _PROFILE_N)


def _lathe_teardrop(L: float, W: float, H: float, z_bottom: float,
                    n_sta: int = 48, n_seg: int = 40) -> Mesh:
    """Body of revolution with elliptical sections along +X (nose at +L/2).

    Section i: t in [0, _T_KAMM]; half-width ry = W/2 * f(t);
    half-height rz = h_avail/2 * f(t); ring bottom kept at z_bottom
    (crest rises then falls with the profile). Closed mesh: rings + nose
    point-fan + flat Kamm cap fan.
    """
    h_avail = H - (z_bottom - 0.0) * 0.0    # clearance handled via ring center
    clearance = 0.13
    h_avail = H - clearance
    xs = [L / 2 - L * _T_KAMM * i / (n_sta - 1) for i in range(n_sta)]
    ts = [_T_KAMM * i / (n_sta - 1) for i in range(n_sta)]

    verts: list[list[float]] = []
    # nose apex point (t=0, f=0): single vertex at the very nose
    nose = [L / 2, 0.0, z_bottom + 0.5 * h_avail * 0.06]
    verts.append(nose)
    rings: list[list[int]] = []
    for i, (x, t) in enumerate(zip(xs, ts)):
        f = _profile(t)
        ry = 0.5 * W * f
        rz = 0.5 * h_avail * f
        zc = z_bottom + clearance * 0.0 + rz  # bottom of section at z_bottom + rz - rz
        zc = z_bottom + rz                    # bottom at z_bottom exactly
        if i == 0:
            f = max(f, 0.02)                  # avoid degenerate first ring
            ry = 0.5 * W * f
            rz = 0.5 * h_avail * f
            zc = z_bottom + rz
        ring = []
        for k in range(n_seg):
            a = 2.0 * math.pi * k / n_seg
            verts.append([x, ry * math.cos(a), zc + rz * math.sin(a)])
            ring.append(len(verts) - 1)
        rings.append(ring)

    tris: list[list[int]] = []
    # nose fan: apex -> first ring
    for k in range(n_seg):
        tris.append([0, rings[0][k], rings[0][(k + 1) % n_seg]])
    # rings
    for i in range(n_sta - 1):
        r0, r1 = rings[i], rings[i + 1]
        for k in range(n_seg):
            k2 = (k + 1) % n_seg
            tris.append([r0[k], r1[k], r1[k2]])
            tris.append([r0[k], r1[k2], r0[k2]])
    # Kamm cap: center + fan on the last ring
    tail = xs[-1]
    zc_t = z_bottom + 0.5 * h_avail * _profile(ts[-1])
    center_idx = len(verts)
    verts.append([tail, 0.0, zc_t])
    last = rings[-1]
    for k in range(n_seg):
        tris.append([center_idx, last[(k + 1) % n_seg], last[k]])

    return Mesh(np.array(verts, dtype=float), np.array(tris, dtype=int))


def build_aero_car(spec: dict[str, Any] | None = None) -> TractorBuild:
    s = dict(AERO_DEFAULTS)
    if spec:
        s.update(spec)

    L = s["car_length_mm"] * MM
    W = s["car_width_mm"] * MM
    H = s["car_height_mm"] * MM
    r_w = s["wheel_r_mm"] * MM
    wb = s["wheelbase_mm"] * MM
    z0 = r_w                                  # ground line: wheels touch z=0
    z_bottom = z0 + 0.13                      # body ground clearance (13 cm)
    tail_x = L / 2 - L * _T_KAMM              # Kamm cut plane (rear end)

    b = TractorBuild()

    # ================= 1. BODY: lathe teardrop + Kamm tail ============== #
    body = _lathe_teardrop(L, W, H, z_bottom, n_sta=48, n_seg=40)
    # nose points +x: flip so the TAIL (Kamm) is at the rear of the car and
    # the rounded nose leads? Aerodynamic teardrop: rounded nose FRONT, tail
    # REAR. Keep nose at +x as the FRONT of the car (x axis: +x = front).
    # Thin-walled carbon monocoque: 3 mm panel (HYPOTHESIS, CFRP body panels:
    # 2-4 mm). Solid modeling would give ~6 t for the enclosed volume - absurd.
    b.add("body", "monovolume_teardrop_body", body, CARBON,
          "corps monovolume goutte d'eau, queue Kamm (Cd 0.19 vise, HYP.) - "
          "panneau composite 3 mm",
          shell_thickness_m=0.003)

    # ================= 2. Aero wheels (enclosed discs) ================== #
    # Enclosed aero disc wheel: composite/rubber SHELL 12 mm (like solar-car
    # covers) + tire mass folded in (HYPOTHESIS). Solid discs would weigh 95 kg
    # each - absurd.
    wheels = []
    for sx in (-1, 1):
        for (x, wdt) in ((-wb / 2, 0.62 * r_w), (wb / 2, 0.78 * r_w)):
            disc = mesh.cylinder(r_w, r_w, wdt, 36, axis="y")
            wheels.append(mesh.place(disc, x=x, y=sx * (W / 2 - wdt / 2), z=r_w))
    b.add("wheels", "aero_wheels_4x", mesh.merge_all(wheels), RUBBER,
          "roues carenees (disques affleurants, enveloppe 12 mm + pneu, HYP.)",
          shell_thickness_m=0.012)

    # ================= 3. Chassis / battery floor ======================= #
    b.add("structure", "battery_floor_pan", mesh.place(
        mesh.box(0.55 * L, 0.72 * W, 0.11), x=0.05 * L, z=z0 + 0.10), ALU,
        f"plateau batterie ({s['battery_kwh']:.0f} kWh) - tole 4 mm",
        shell_thickness_m=0.004)
    # HV battery pack: cells + case + voids -> effective density 1850 kg/m3
    # (NMC cells ~2600 kg/m3, ~30% packing/case voids - HYPOTHESIS). The pack
    # sits IN the floor pan: skateboard architecture.
    pack_eff_density = 1850.0
    pack = mesh.box(0.52 * L, 0.70 * W, 0.10)
    b.add("structure", "hv_battery_pack",
          mesh.place(pack, x=0.05 * L, z=z0 + 0.10), pack_eff_density,
          f"pack traction {s['battery_kwh']:.0f} kWh (densite effective 1850 kg/m3, HYP.)")
    # Rails: REAL hollow box sections (2 rails x 4 plates each). Solid bars
    # would give 710 kg - real longerons are ~50 kg per rail.
    rails = []
    t_rail = 0.004
    rail_len, rail_w, rail_h = 0.78 * L, 0.09, 0.14
    for sy in (-1, 1):
        y0 = sy * 0.30 * W
        rails.append(mesh.place(mesh.box(rail_len, rail_w, t_rail),
                                x=0, y=y0, z=z0 + 0.05 + rail_h / 2 - t_rail / 2))
        rails.append(mesh.place(mesh.box(rail_len, rail_w, t_rail),
                                x=0, y=y0, z=z0 + 0.05 - rail_h / 2 + t_rail / 2))
        rails.append(mesh.place(mesh.box(rail_len, t_rail, rail_h - 2 * t_rail),
                                x=0, y=y0 - rail_w / 2 + t_rail / 2, z=z0 + 0.05))
        rails.append(mesh.place(mesh.box(rail_len, t_rail, rail_h - 2 * t_rail),
                                x=0, y=y0 + rail_w / 2 - t_rail / 2, z=z0 + 0.05))
    b.add("structure", "chassis_rails", mesh.merge_all(rails), STEEL,
          f"longerons caisson {int(rail_w*1000)}x{int(rail_h*1000)} mm, paroi {t_rail*1000:.0f} mm")
    # Half-axles: real rods (r 45 mm) from center differential to each wheel.
    r_rod = 0.045
    axle_f = mesh.merge_all([
        mesh.place(mesh.cylinder(r_rod, r_rod, W / 2, 20, axis="y"),
                   x=-wb / 2, y=sy * W / 4, z=r_w) for sy in (-1, 1)])
    b.add("structure", "front_axle", axle_f, STEEL, "demi-arbres avant (r 45 mm)")
    axle_r = mesh.merge_all([
        mesh.place(mesh.cylinder(r_rod, r_rod, W / 2, 20, axis="y"),
                   x=wb / 2, y=sy * W / 4, z=r_w) for sy in (-1, 1)])
    b.add("structure", "rear_axle", axle_r, STEEL, "demi-arbres arriere (r 45 mm)")

    # ================= 4. Powertrain: 300 kW PMSM ======================= #
    # Motor/gearbox/inverter: compact solids with DOCUMENTED effective
    # densities (mixed materials: laminations+Cu+housing, HYPOTHESIS).
    motor = mesh.cylinder(0.16, 0.16, 0.34, 28, axis="x")
    b.add("engine", "pmsm_motor_300kW",
          mesh.place(motor, x=wb / 2 - 0.10, z=r_w + 0.02), 4500.0,
          f"moteur PMSM {s['motor_kw']:.0f} kW (densite effective 4500 kg/m3, HYP.)")
    reducer = mesh.cylinder(0.11, 0.11, 0.12, 22, axis="x")
    b.add("engine", "reducer_gearbox",
          mesh.place(reducer, x=wb / 2 + 0.18, z=r_w), ALU,
          "redacteur primaire ~9:1 (HYP.)")
    b.add("engine", "inverter_SiC",
          mesh.place(mesh.box(0.42, 0.30, 0.12), x=wb / 2 - 0.05, z=z0 + 0.30),
          900.0, "onduleur SiC 800 A (densite effective boitier+electronique, HYP.)")

    # ================= 5. Cabin (flush glazing) ========================= #
    gl = mesh.scale(mesh.sphere(1.0, 40, 20), 0.30 * L, 0.44 * W, 0.26 * H)
    gl = mesh.place(gl, x=-0.02 * L, z=z_bottom + 0.62 * H)
    b.add("cabin", "flush_glazing", gl, GLASS,
          "vitrinage affleurant (cameras, pas de retroviseurs) - vitrage 5 mm",
          shell_thickness_m=0.005)
    b.add("cabin", "cabin_floor", mesh.place(
        mesh.box(0.9, 0.66 * W, 0.05), x=0.10 * L, z=z0 + 0.28), CARBON,
        "plancher cabine - sandwich 6 mm", shell_thickness_m=0.006)

    # ================= 6. Aero devices ================================== #
    b.add("body", "front_splitter",
          mesh.place(mesh.box(0.30, 0.92 * W, 0.03), x=L / 2 - 0.14, z=z0 + 0.015),
          CARBON, "splitter avant - sandwich 6 mm", shell_thickness_m=0.006)
    b.add("body", "rear_diffuser",
          mesh.place(mesh.box(0.45, 0.85 * W, 0.03), x=tail_x + 0.22, z=z0 + 0.06),
          CARBON, "diffuseur arriere - sandwich 6 mm", shell_thickness_m=0.006)
    b.add("body", "active_wing",
          mesh.place(mesh.box(0.16, 0.80 * W, 0.025),
                     x=tail_x - 0.05, z=z0 + 0.92 * H),
          CARBON, "aileron actif - sandwich 6 mm", shell_thickness_m=0.006)
    for sx in (-1, 1):
        cov = mesh.cylinder(r_w * 1.10, r_w * 1.10, 0.03, 28, axis="y")
        b.add("body", "rear_wheel_cover" + ("_left" if sx < 0 else "_right"),
              mesh.place(cov, x=wb / 2, y=sx * (W / 2 - 0.015), z=r_w), CARBON,
              "carenage de roue arriere - 3 mm", shell_thickness_m=0.003)

    # ================= 7. LV 12 V components in 3D ====================== #
    def lum(x: float, y: float, z: float) -> Mesh:
        return mesh.place(mesh.cylinder(0.09, 0.06, 0.06, 18, axis="x"), x=x, y=y, z=z)

    b.add("electrical", "led_headlights_2x",
          mesh.merge_all([lum(L / 2 - 0.18, sy * 0.28 * W, z_bottom + 0.28 * H)
                          for sy in (-1, 1)]),
          GLASS, "blocs LED avant")
    b.add("electrical", "led_taillight_bar",
          mesh.place(mesh.box(0.04, 0.70 * W, 0.06), x=tail_x - 0.02,
                     z=z_bottom + 0.42 * H),
          GLASS, "barre LED arriere")
    b.add("electrical", "lv_battery_12V",
          mesh.place(mesh.box(0.28, 0.18, 0.16), x=-0.30 * L, z=z0 + 0.24), ALU,
          "batterie LV 12 V (Li-ion, HYP.)")
    b.add("electrical", "hvac_unit",
          mesh.place(mesh.box(0.35, 0.30, 0.14), x=0.0, z=z0 + 0.30), ALU,
          "groupe HVAC")
    b.add("electrical", "infotainment_ecu",
          mesh.place(mesh.box(0.30, 0.22, 0.08), x=-0.10 * L, z=z0 + 0.40), ALU,
          "calculateur + infotainment")

    # ================= 8. HV 400 V network (3D tubes) =================== #
    hv_routes = {
        "hv_battery_to_inverter": ([0.05 * L, 0.0, z0 + 0.16],
                                   [wb / 2 - 0.35, 0.10 * W, z0 + 0.28],
                                   [wb / 2 - 0.05, 0.10 * W, z0 + 0.28]),
        "hv_inverter_to_motor": ([wb / 2 - 0.05, 0.10 * W, z0 + 0.28],
                                 [wb / 2 - 0.10, 0.04 * W, r_w + 0.02]),
        "hv_battery_to_dcdc_obc": ([0.05 * L, 0.0, z0 + 0.16],
                                   [-0.28 * L, 0.15 * W, z0 + 0.22]),
    }
    for name, pts in hv_routes.items():
        w = mesh.tube_along([np.array(p) for p in pts], 0.014, 8)
        b.add("harness", name, w, COPPER, "cable HV 800 V (blinde, orange)")

    # ================= 9. LV 12 V harness (3D tubes) ==================== #
    lv_hub = [-0.10 * L, 0.12 * W, z0 + 0.38]
    lv_routes = {
        "lv_feed_fusebox": ([-0.30 * L, 0.10 * W, z0 + 0.26], lv_hub),
        "lv_headlights": (lv_hub, [L / 2 - 0.22, 0.28 * W, z_bottom + 0.28 * H]),
        "lv_tail_bar": (lv_hub, [tail_x - 0.06, 0.0, z_bottom + 0.42 * H]),
        "lv_infotainment": (lv_hub, [-0.10 * L, 0.0, z0 + 0.40]),
        "lv_hvac": (lv_hub, [0.0, 0.0, z0 + 0.30]),
    }
    for name, pts in lv_routes.items():
        w = mesh.tube_along([np.array(p) for p in pts], 0.006, 8)
        b.add("harness", name, w, COPPER, "faisceau LV 12 V")

    for i, tgt in enumerate((([wb / 2 - 0.10, 0.0, r_w],
                              [tail_x + 0.05, 0.0, z_bottom + 0.42 * H]))):
        g = mesh.tube_along([np.array(tgt), np.array([0.0, tgt[1] * 0.5, z0 + 0.05])],
                            0.004, 6)
        b.add("harness", f"ground_strap_{i + 1}", g, COPPER, "retour masse carrosserie")

    return b


def export_aero_car(
    b: TractorBuild,
    out_dir: str,
    writer,
    provider: MeshCadProvider | None = None,
) -> dict[str, Any]:
    """Export car groups as separate STL files through the sandboxed writer,
    using the car group filenames (car_*.stl)."""
    from providers.cad.tractor import GROUP_SPECS

    prov = provider or MeshCadProvider()
    files: dict[str, dict] = {}
    for group, m in b.groups.items():
        if group not in CAR_GROUPS:
            continue
        rel_path = f"{out_dir}/{CAR_GROUPS[group]}"
        written = writer(rel_path, prov.export_mesh_bytes(m, "stl"))
        _, color, _ = GROUP_SPECS[group]
        files[group] = {"path": rel_path, "triangles": m.n_triangles,
                        "color": color, "checksum": written.get("checksum", "")}
    # Total mass = sum of REGISTERED part masses (shells use area x thickness;
    # recomputing solid volumes here would resurrect the 6-tonne body bug).
    total_mass = sum(p["mass_kg"] for p in b.parts)
    return {"files": files, "parts": b.parts, "total_mass_kg": round(total_mass, 1),
            "total_triangles": sum(p["triangles"] for p in b.parts)}
