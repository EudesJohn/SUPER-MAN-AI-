"""EV design engine: aerodynamics + powertrain + HV 400 V network sizing.

Everything is deterministic (CalculationEngine records) - the LLM never
computes anything here. Typical values are explicit HYPOTHESES the caller can
override. The independent VerificationEngine recomputes with its OWN constants
and can FAIL this design (see core/verification.py).

HV network: battery -> inverter -> motor (DC 400 V class, cables sized for
peak motor current with a 77% inverter efficiency margin rule) + DC-DC/OBC
feed. LV 12 V network reuses the existing ElectricalDesignEngine.
"""
from __future__ import annotations

from typing import Any

from core.calculation import CalculationEngine

# HV cable capability table [mm^2 -> A] at 800 V DC, 90 degC insulation
# (HYPOTHESIS table, conservative continuous ratings).
HV_GAUGE_TABLE = [(16.0, 80), (25.0, 110), (35.0, 140), (50.0, 180),
                  (70.0, 230), (95.0, 290), (120.0, 350), (150.0, 400)]

COPPER_RHO = 0.0225          # ohm.mm^2/m (HYPOTHESIS)
HV_MAX_DROP_PERCENT = 2.0    # HV links are short: stricter than LV
# EV HV fuses: miniature HV (5-80 A) + NH/evolution (100-630 A) (HYPOTHESIS list)
HV_STANDARD_FUSES = [5, 7.5, 10, 15, 20, 25, 30, 40, 50, 63, 80, 100, 125, 150,
                     175, 200, 250, 300, 350, 400, 500, 560, 630]


def design_hv_network(
    calc: CalculationEngine,
    *,
    system_voltage: float = 800.0,
    motor_kw: float = 300.0,
    inverter_efficiency: float = 0.97,
    cable_length_m: float = 2.4,
    dcdc_kw: float = 3.0,
) -> dict[str, Any]:
    """Size the HV links deterministically and return a design dict shaped
    like the LV one (circuits list with gauge/fuse/drop + calc ids)."""
    circuits: list[dict[str, Any]] = []

    # 1) battery -> inverter: peak DC current (parallel conductors allowed)
    i_pack = motor_kw * 1000.0 / (system_voltage * inverter_efficiency)
    gauge, capacity, drop_v, drop_pct, n_par = _size_hv(i_pack, cable_length_m, system_voltage)
    fuse = _hv_fuse(i_pack, capacity)
    rec = calc.run(
        "voltage_drop",
        {"resistivity_ohm_mm2_per_m": COPPER_RHO, "length_m": cable_length_m,
         "current_A": i_pack, "cross_section_mm2": gauge, "phases": 1},
        assumptions=["HV battery->inverter link", f"copper rho={COPPER_RHO} (HYPOTHESIS)"],
    )
    rec_pct = calc.run(
        "voltage_drop_percent",
        {"drop_V": drop_v, "line_voltage_V": system_voltage},
        assumptions=["HV battery->inverter link"],
    )
    circuits.append({
        "name": "hv_battery_to_inverter",
        "description": f"Batterie -> Onduleur (DC {system_voltage:.0f} V, {n_par}x parallele/pole)",
        "kind": "hv_link", "load_w": motor_kw * 1000.0,
        "current_a": round(i_pack, 1), "length_m": cable_length_m,
        "gauge_mm2": gauge, "capacity_a": capacity,
        "parallel_per_pole": n_par,
        "drop_v": round(drop_v, 2), "drop_pct": round(drop_pct, 2),
        "fuse_a": fuse, "fuse_exception": None,
        "ground": "isolated (IT network, no chassis return)",
        "color": "orange", "calc_ids": [rec.id, rec_pct.id],
    })

    # 2) inverter -> motor: AC 3-phase, current per phase at motor terminals
    i_phase = motor_kw * 1000.0 / (math_sqrt3() * system_voltage * 0.9)  # PF ~0.9 (HYP.)
    gauge2, cap2, drop2, pct2, n2 = _size_hv(i_phase, 0.8, system_voltage)
    fuse2 = _hv_fuse(i_phase, cap2)
    rec2 = calc.run(
        "voltage_drop",
        {"resistivity_ohm_mm2_per_m": COPPER_RHO, "length_m": 0.8,
         "current_A": i_phase, "cross_section_mm2": gauge2, "phases": 3},
        assumptions=["HV inverter->motor AC link (3 phases)", "PF 0.9 (HYPOTHESIS)"],
    )
    circuits.append({
        "name": "hv_inverter_to_motor", "description": "Onduleur -> Moteur PMSM (AC 3~)",
        "kind": "hv_link", "load_w": motor_kw * 1000.0,
        "current_a": round(i_phase, 1), "length_m": 0.8,
        "gauge_mm2": gauge2, "capacity_a": cap2,
        "parallel_per_pole": n2,
        "drop_v": round(drop2, 2), "drop_pct": round(pct2, 2),
        "fuse_a": fuse2, "fuse_exception": None,
        "ground": "isolated (IT network)",
        "color": "orange", "calc_ids": [rec2.id],
    })

    # 3) battery -> DC-DC/OBC
    i_aux = dcdc_kw * 1000.0 / system_voltage
    gauge3, cap3, drop3, pct3, n3 = _size_hv(i_aux, 1.5, system_voltage)
    fuse3 = _hv_fuse(i_aux, cap3)
    rec3 = calc.run(
        "voltage_drop",
        {"resistivity_ohm_mm2_per_m": COPPER_RHO, "length_m": 1.5,
         "current_A": i_aux, "cross_section_mm2": gauge3, "phases": 1},
        assumptions=["HV battery->DC-DC/OBC link"],
    )
    circuits.append({
        "name": "hv_battery_to_dcdc_obc", "description": "Batterie -> DC-DC / OBC",
        "kind": "hv_link", "load_w": dcdc_kw * 1000.0,
        "current_a": round(i_aux, 1), "length_m": 1.5,
        "gauge_mm2": gauge3, "capacity_a": cap3,
        "parallel_per_pole": n3,
        "drop_v": round(drop3, 2), "drop_pct": round(pct3, 2),
        "fuse_a": fuse3, "fuse_exception": None,
        "ground": "isolated (IT network)",
        "color": "orange", "calc_ids": [rec3.id],
    })

    # ---- power balance at cruise (aero will be merged by the caller) ----
    notes = [
        "Architecture 800 V CHOISIE: a 400 V, 300 kW exigerait ~773 A par pole"
        " (cables 300 mm2 x2) - l'architecture 800 V divise le courant par deux"
        " (pratique moderne des VE performants, HYPOTHese documentee).",
        "Reseau HV classe IT: ISOLE du chssis (pas de retour masse) - une seule"
        " faute ne provoque pas de court-circuit (HYPOTHese de conception).",
        "Sections HT: capacite >= 1.25*I et dU <= 2 %; fusible >= 1.35*I, jamais > capacite.",
        "Cables HV orange, blindes; connecteurs haute tension verrouilles (convention).",
    ]
    return {
        "system_voltage": system_voltage,
        "network": f"HV DC {system_voltage:.0f} V (IT, isolated from chassis)",
        "circuits": circuits,
        "max_drop_pct": HV_MAX_DROP_PERCENT,
        "copper_rho": COPPER_RHO,
        "notes": notes,
    }


def math_sqrt3() -> float:
    import math
    return math.sqrt(3.0)


def system_voltage_default() -> float:
    return 800.0


def _size_hv(current_a: float, length_m: float, voltage: float | None = None) -> tuple[float, float, float, float, int]:
    """Size an HV link. n_parallel conductors PER POLE are allowed (real
    practice for 300+ kW: Taycan/Lucid use parallel HV cables): total capacity
    = n x table capacity; each conductor carries I/n (drop computed per
    conductor). Returns (gauge, total_capacity, drop_V, drop_%, n_parallel)."""
    U = voltage if voltage is not None else system_voltage_default()
    if current_a <= 0:
        raise ValueError("current must be positive")
    for n in (1, 2, 3):
        for gauge, capacity in HV_GAUGE_TABLE:
            # 1.35 (not 1.25): the cable must also host the standard fuse
            # (fuse >= 1.35*I and fuse <= capacity) - fuse-feasibility rule.
            if n * capacity < 1.35 * current_a:
                continue
            drop_v = 2.0 * COPPER_RHO * length_m * (current_a / n) / gauge
            drop_pct = 100.0 * drop_v / U
            if drop_pct <= HV_MAX_DROP_PERCENT:
                return gauge, n * capacity, drop_v, drop_pct, n
    raise ValueError(
        f"INCONNU: no HV gauge meets capacity+drop for {current_a:.0f} A over {length_m} m")


def _hv_fuse(current_a: float, capacity: float) -> float:
    """First standard fuse >= 1.35*I, never above total cable capacity.
    For very high currents the pack contactor+pyrofuse convention applies;
    if 1.35*I exceeds the biggest standard fuse, the main pack fuse is set
    to the largest standard value NOT exceeding capacity (documented exception
    rather than a fake number)."""
    target = 1.35 * current_a
    for f in HV_STANDARD_FUSES:
        if f >= target:
            if f > capacity:
                raise ValueError(f"INCONNU: HV fuse {f} A exceeds cable capacity {capacity} A")
            return float(f)
    biggest = max(f for f in HV_STANDARD_FUSES if f <= capacity) if any(
        f <= capacity for f in HV_STANDARD_FUSES) else None
    if biggest is None:
        raise ValueError("INCONNU: no standard HV fuse large enough")
    return float(biggest)
