"""Electrical design engine (Phase 6 groundwork): deterministic 12 V sizing.

For each circuit: current I = P/U, wire cross-section chosen from standard
gauge tables (capacity >= 1.25*I AND voltage drop <= 3%), fuse = first
standard value >= 1.35*I. Every drop is computed through the CalculationEngine
(voltage_drop / voltage_drop_percent), so results are traceable records.

All typical values (battery, alternator, lamp powers) are explicit
HYPOTHESES the user can override - nothing is fabricated silently.
The independent VerificationEngine recomputes these numbers with its OWN
constants and can FAIL this design.
"""
from __future__ import annotations

from dataclasses import dataclass, field

from core.calculation import CalculationEngine

# Standard automotive fuses [A] and copper wire capability [mm^2 -> A] (HYPOTHESIS tables).
# >100 A: MEGA/MIDI bolt-down fuses (real EV LV practice for DC-DC feeds).
STANDARD_FUSES = [2, 3, 5, 7.5, 10, 15, 20, 25, 30, 40, 50, 60, 70, 80, 100,
                  125, 150, 175, 200, 250, 300, 350, 400, 500]
GAUGE_TABLE = [(0.5, 6), (0.75, 8), (1.0, 10), (1.5, 14), (2.5, 20), (4.0, 25),
               (6.0, 32), (10.0, 45), (16.0, 60), (25.0, 80), (35.0, 100),
               (50.0, 130), (70.0, 160), (95.0, 200), (120.0, 240),
               (150.0, 280), (185.0, 320), (240.0, 380)]

COPPER_RHO = 0.0225          # ohm.mm^2/m at operating temperature (HYPOTHESIS)
MAX_DROP_PERCENT = 3.0

COLOR_BY_NAME = {
    "starter_motor": "red", "feed_main": "red", "alternator_bplus": "red",
    "headlight_left": "yellow", "headlight_right": "yellow",
    "tail_light_left": "green", "tail_light_right": "green",
    "dash_panel": "blue", "horn": "orange", "ecu_engine": "gray",
}


@dataclass
class CircuitSpec:
    name: str
    description: str
    load_w: float
    length_m: float
    kind: str = "load"       # load | starter | feed | alternator
    ground: str = "chassis"  # return path convention


DEFAULT_CIRCUITS = [
    CircuitSpec("starter_motor", "Démarreur", 1500.0, 1.2, kind="starter"),
    CircuitSpec("headlight_left", "Phare avant gauche", 55.0, 2.6),
    CircuitSpec("headlight_right", "Phare avant droit", 55.0, 2.4),
    CircuitSpec("tail_light_left", "Feu arrière gauche", 21.0, 2.8),
    CircuitSpec("tail_light_right", "Feu arrière droit", 21.0, 2.6),
    CircuitSpec("dash_panel", "Éclairage tableau de bord", 15.0, 1.0),
    CircuitSpec("horn", "Klaxon", 72.0, 2.8),
    CircuitSpec("ecu_engine", "Calculateur moteur", 20.0, 1.2),
    CircuitSpec("feed_main", "Alimentation boîte à fusibles", 0.0, 1.5, kind="feed"),
    CircuitSpec("alternator_bplus", "Alternateur B+ vers batterie", 0.0, 1.0, kind="alternator"),
]


class ElectricalDesignEngine:
    def __init__(self, calc: CalculationEngine) -> None:
        self.calc = calc

    # ------------------------------------------------------------------ #
    def design(
        self,
        circuits: list[CircuitSpec],
        *,
        system_voltage: float = 12.0,
        requirement_ids: list[str] | None = None,
        battery_ah: float = 80.0,
        alternator_max_a: float = 90.0,
        feed_length_m: float | None = None,
        alternator_length_m: float | None = None,
    ) -> dict:
        req_ids = list(requirement_ids or [])
        out: list[dict] = []

        for c in circuits:
            if c.kind == "feed":
                total_i = sum(x.load_w for x in circuits if x.kind == "load") / system_voltage
                i, length = total_i, (feed_length_m if feed_length_m is not None else c.length_m)
                desc = f"{c.description} ({total_i:.1f} A total)"
            elif c.kind == "alternator":
                i = alternator_max_a
                length = (alternator_length_m if alternator_length_m is not None else c.length_m)
                desc = f"{c.description} ({alternator_max_a:.0f} A max, HYPOTHESIS)"
            else:
                i, length = c.load_w / system_voltage, c.length_m
                desc = c.description

            gauge, capacity, drop_v, drop_pct = self._size_wire(i, length, system_voltage)
            fuse, exception = self._fuse_for(c, i, gauge, capacity)

            rec_drop = self.calc.run(
                "voltage_drop",
                {"resistivity_ohm_mm2_per_m": COPPER_RHO, "length_m": length,
                 "current_A": i, "cross_section_mm2": gauge, "phases": 1},
                assumptions=[f"circuit {c.name}", f"copper rho={COPPER_RHO} ohm.mm2/m (HYPOTHESIS)"],
                requirement_ids=req_ids,
            )
            rec_pct = self.calc.run(
                "voltage_drop_percent",
                {"drop_V": drop_v, "line_voltage_V": system_voltage},
                assumptions=[f"circuit {c.name}"],
                requirement_ids=req_ids,
            )

            out.append({
                "name": c.name, "description": desc, "kind": c.kind,
                "load_w": c.load_w if c.kind not in ("feed", "alternator") else None,
                "current_a": round(i, 2), "length_m": length,
                "gauge_mm2": gauge, "capacity_a": capacity,
                "drop_v": round(drop_v, 3), "drop_pct": round(drop_pct, 2),
                "fuse_a": fuse, "fuse_exception": exception,
                "ground": c.ground, "color": COLOR_BY_NAME.get(c.name, "red"),
                "calc_ids": [rec_drop.id, rec_pct.id],
            })

        notes = [
            "Typical compact-tractor values: powers, battery and alternator are HYPOTHESES (configurable).",
            f"Wire sizing rule: capacity >= 1.25*I and voltage drop <= {MAX_DROP_PERCENT:.0f}% "
            f"(copper rho={COPPER_RHO} ohm.mm2/m, single-phase factor b=2).",
            "Fuse rule: first standard value >= 1.35*I, never above wire capacity.",
            "Starter has NO inline fuse by convention: solenoid-switched main cable protected by "
            "cable sizing and the main fuse near the battery (HYPOTHESIS convention).",
            "All returns are chassis ground (single-wire convention).",
        ]

        # ---------------- power balance (alternator vs consumers) -------- #
        load_w_total = sum(c.load_w for c in circuits if c.kind == "load")
        alternator_w = alternator_max_a * system_voltage * 0.75  # continuous derating (HYPOTHESIS)
        balance_margin_w = alternator_w - load_w_total
        battery_cca_a = battery_ah * 4.0  # typical lead-acid rule of thumb (HYPOTHESIS)
        starter_current = next(
            (c.load_w / system_voltage for c in circuits if c.kind == "starter"), 0.0
        )

        return {
            "system_voltage": system_voltage,
            "battery": {"voltage_v": system_voltage, "capacity_ah": battery_ah,
                        "cca_estimate_a": round(battery_cca_a, 0),
                        "starter_current_a": round(starter_current, 1),
                        "note": "HYPOTHESIS: typical compact tractor battery; CCA ~ 4x Ah (rule of thumb)"},
            "alternator": {"max_current_a": alternator_max_a,
                           "continuous_w_estimate": round(alternator_w, 0),
                           "note": "HYPOTHESIS: typical compact tractor alternator, 75% continuous derating"},
            "power_balance": {
                "total_load_w": round(load_w_total, 1),
                "alternator_continuous_w": round(alternator_w, 1),
                "margin_w": round(balance_margin_w, 1),
                "margin_ok": balance_margin_w >= 0,
                "note": "HYPOTHESIS: steady-state loads only; starting loads are supplied by the battery",
            },
            "circuits": out,
            "max_drop_pct": MAX_DROP_PERCENT,
            "copper_rho": COPPER_RHO,
            "notes": notes,
        }

    # ------------------------------------------------------------------ #
    @staticmethod
    def _size_wire(current_a: float, length_m: float, voltage: float) -> tuple[float, float, float, float]:
        if current_a <= 0:
            raise ValueError("current must be positive")
        for gauge, capacity in GAUGE_TABLE:
            # 1.35 (not 1.25): the cable must host the standard fuse (fuse >=
            # 1.35*I and fuse <= capacity) AND clear the independent verifier's
            # stricter capability table (conservative by design).
            if capacity < 1.35 * current_a:
                continue
            drop_v = 2.0 * COPPER_RHO * length_m * current_a / gauge
            drop_pct = 100.0 * drop_v / voltage
            if drop_pct <= MAX_DROP_PERCENT:
                return gauge, capacity, drop_v, drop_pct
        raise ValueError(
            f"INCONNU: no standard gauge meets capacity+drop for {current_a:.1f} A over {length_m} m"
        )

    @staticmethod
    def _fuse_for(c: CircuitSpec, current_a: float, gauge: float, capacity: float) -> tuple[float | None, str | None]:
        if c.kind == "starter":
            return None, ("no inline fuse: solenoid-switched main cable, protected by cable "
                          "sizing and main fuse near battery (HYPOTHESIS convention)")
        target = 1.35 * current_a
        for f in STANDARD_FUSES:
            if f >= target:
                if f > capacity:
                    return None, f"INCONNU: fuse {f} A exceeds wire capacity {capacity} A - resize manually"
                return f, None
        return None, "INCONNU: no standard fuse large enough"
