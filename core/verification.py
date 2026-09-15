"""Verification Engine (section 15/19): INDEPENDENT from design agents.

Checks are deterministic rules over stored records. The engine is allowed to
disagree with any agent: e.g. recompute a shaft sizing and FAIL it if the
stress exceeds allowables. Outcomes: PASS / FAIL / WARNING / UNKNOWN.
"""
from __future__ import annotations

import math
from typing import Any

from core.models import (
    VerificationOutcome,
    VerificationResult,
)


class VerificationEngine:
    def __init__(self, memory, bus=None) -> None:
        self.memory = memory
        self.bus = bus

    # ------------------------------------------------------------------ #
    # Electrical design verification (Phase 6 groundwork)
    # ------------------------------------------------------------------ #
    # The engine deliberately uses its OWN constants (not the designer's) so
    # a wrong assumption in the design engine gets caught.
    ELEC_VOLTAGE_V = 12.0
    ELEC_RHO = 0.0235            # ohm.mm^2/m (design uses 0.0225 - tolerance covers it)
    ELEC_MAX_DROP_PCT = 3.0
    ELEC_CAPACITY_FACTOR = 1.25
    ELEC_CAPACITY_TABLE = {
        0.5: 6, 0.75: 8, 1.0: 10, 1.5: 14, 2.5: 20, 4.0: 25, 6.0: 32,
        10.0: 45, 16.0: 60, 25.0: 80, 35.0: 100, 50.0: 130, 70.0: 160, 95.0: 200,
        # HEAVY LV (battery cable, DC-DC feeds): independent values, deliberately
        # more conservative than the design table for 120 mm2 (230 vs 240 A).
        120.0: 230, 150.0: 265, 185.0: 305, 240.0: 360,
    }

    async def verify_electrical_design(self, project_id: str, design: dict) -> list[VerificationResult]:
        """Independently re-check a stored ElectricalDesign. Recomputes currents
        and voltage drops with own constants; FAILs the design on any violation."""
        U = self.ELEC_VOLTAGE_V
        circuits = design["circuits"]
        total_load_w = sum(c["load_w"] for c in circuits if c["kind"] == "load")

        def recomputed_current(c: dict) -> float:
            if c["kind"] in ("load", "starter"):
                return c["load_w"] / U
            if c["kind"] == "feed":
                return total_load_w / U
            return float(design["alternator"]["max_current_a"])

        results: list[VerificationResult] = []

        # 1) Every consumer circuit must be fused (starter excluded by convention).
        unfused = [c["name"] for c in circuits if c["kind"] == "load" and c.get("fuse_a") is None]
        results.append(VerificationResult(
            subject="electrical_fusing",
            outcome=VerificationOutcome.FAIL if unfused else VerificationOutcome.PASS,
            detail=("UNFUSED consumer circuits: " + ", ".join(unfused)) if unfused
            else f"All {sum(1 for c in circuits if c['kind'] == 'load')} consumer circuits are fused "
                 "(starter: solenoid-switched, no inline fuse by convention).",
            related_ids=[c["name"] for c in circuits],
        ))

        # 2) Wire capacity >= 1.25 * I (recomputed).
        cap_violations = []
        for c in circuits:
            i = recomputed_current(c)
            capacity = self.ELEC_CAPACITY_TABLE.get(float(c["gauge_mm2"]), 0.0)
            if capacity < self.ELEC_CAPACITY_FACTOR * i:
                cap_violations.append(f"{c['name']}: {c['gauge_mm2']} mm2 ({capacity} A) < 1.25*{i:.1f} A")
        results.append(VerificationResult(
            subject="electrical_wire_capacity",
            outcome=VerificationOutcome.FAIL if cap_violations else VerificationOutcome.PASS,
            detail=("Capacity violations: " + "; ".join(cap_violations)) if cap_violations
            else f"All {len(circuits)} circuits respect capacity >= 1.25*I (independent table).",
            related_ids=[c["name"] for c in circuits],
        ))

        # 3) Voltage drop recomputation within 20% of the design's claim AND <= 3%.
        drop_violations = []
        for c in circuits:
            i = recomputed_current(c)
            drop_ref = 2.0 * self.ELEC_RHO * c["length_m"] * i / c["gauge_mm2"]
            claimed = float(c["drop_v"])
            if abs(claimed - drop_ref) > 0.20 * max(drop_ref, 1e-9) + 0.05:
                drop_violations.append(
                    f"{c['name']}: claimed {claimed:.3f} V vs recomputed {drop_ref:.3f} V"
                )
            elif float(c["drop_pct"]) > self.ELEC_MAX_DROP_PCT + 0.05:
                drop_violations.append(f"{c['name']}: {c['drop_pct']}% > {self.ELEC_MAX_DROP_PCT}%")
        results.append(VerificationResult(
            subject="electrical_voltage_drop",
            outcome=VerificationOutcome.FAIL if drop_violations else VerificationOutcome.PASS,
            detail=("Voltage drop violations: " + "; ".join(drop_violations)) if drop_violations
            else f"All drops recomputed within tolerance and <= {self.ELEC_MAX_DROP_PCT}% "
                 f"(rho={self.ELEC_RHO} ohm.mm2/m, independent constant).",
            related_ids=[c["name"] for c in circuits],
        ))

        # 4) Ground return path must exist for every circuit.
        ungrounded = [c["name"] for c in circuits if c.get("ground") != "chassis"]
        results.append(VerificationResult(
            subject="electrical_ground_path",
            outcome=VerificationOutcome.FAIL if ungrounded else VerificationOutcome.PASS,
            detail=("Missing chassis return: " + ", ".join(ungrounded)) if ungrounded
            else "Every circuit has a chassis ground return path.",
            related_ids=[c["name"] for c in circuits],
        ))

        # 5) Alternator must cover steady-state loads (balance re-check).
        bal = design.get("power_balance", {})
        margin_w = float(bal.get("margin_w", 0.0))
        results.append(VerificationResult(
            subject="electrical_power_balance",
            outcome=VerificationOutcome.FAIL if margin_w < 0 else VerificationOutcome.PASS,
            detail=(f"Alternator cannot cover steady-state loads: margin {margin_w:.0f} W "
                    "(engine-off operation would discharge the battery).") if margin_w < 0
            else f"Alternator covers steady-state loads with {margin_w:.0f} W margin "
                 "(starting loads are supplied by the battery - HYPOTHESIS).",
            related_ids=["alternator", "loads"],
        ))

        # 6) Battery cranking capacity vs starter draw (CCA estimate re-check).
        bat = design.get("battery", {})
        cca = float(bat.get("cca_estimate_a", 0.0))
        starter_i = float(bat.get("starter_current_a", 0.0))
        if starter_i > 0 and cca < 1.2 * starter_i:
            results.append(VerificationResult(
                subject="battery_cranking_capacity",
                outcome=VerificationOutcome.FAIL,
                detail=(f"Battery CCA estimate {cca:.0f} A < 1.2 x starter draw {starter_i:.0f} A "
                        "- engine may not crank in cold conditions."),
                related_ids=["battery", "starter"],
            ))
        else:
            results.append(VerificationResult(
                subject="battery_cranking_capacity",
                outcome=VerificationOutcome.PASS if starter_i > 0 else VerificationOutcome.UNKNOWN,
                detail=(f"CCA estimate {cca:.0f} A >= 1.2 x starter draw {starter_i:.0f} A "
                        "(rule of thumb CCA ~ 4x Ah - HYPOTHESIS).") if starter_i > 0
                else "No starter circuit in this design.",
                related_ids=["battery", "starter"],
            ))

        for r in results:
            self.memory.add_verification(project_id, r)
            if self.bus is not None:
                kind = "VERIFICATION_PASSED" if r.outcome == VerificationOutcome.PASS else "VERIFICATION_FAILED"
                await self.bus.publish(kind, {"project_id": project_id, "id": r.id,
                                              "subject": r.subject, "outcome": r.outcome.value})
        return results

    # ------------------------------------------------------------------ #
    # HV (electric vehicle) design verification - OWN constants again
    # ------------------------------------------------------------------ #
    HV_VOLTAGE_V = 800.0
    HV_RHO = 0.0235             # design uses 0.0225 - tolerance covers it
    HV_MAX_DROP_PCT = 2.0
    HV_CAPACITY_TABLE = {16.0: 80, 25.0: 110, 35.0: 140, 50.0: 180,
                         70.0: 230, 95.0: 290, 120.0: 350, 150.0: 400}

    async def verify_hv_design(self, project_id: str, design: dict) -> list[VerificationResult]:
        """Independent re-check of an HV network design: IT-network isolation,
        per-pole capacity >= 1.25*I (parallel conductors counted), drop
        recomputation, fuse <= capacity."""
        results: list[VerificationResult] = []
        circuits = [c for c in design["circuits"] if c["kind"] == "hv_link"]

        # 1) IT network: no chassis return allowed on HV links
        bad_ground = [c["name"] for c in circuits
                      if "isolated" not in str(c.get("ground", ""))]
        results.append(VerificationResult(
            subject="hv_it_network_isolation",
            outcome=VerificationOutcome.FAIL if bad_ground else VerificationOutcome.PASS,
            detail=("HV links with chassis return (FORBIDDEN, IT network): "
                    + ", ".join(bad_ground)) if bad_ground
            else "All HV links are isolated from the chassis (IT network) - "
                 "single-fault safe convention.",
            related_ids=[c["name"] for c in circuits],
        ))

        # 2) Per-pole capacity: n_parallel x table(gauge) >= 1.25 * I (recomputed)
        U = float(design.get("system_voltage", self.HV_VOLTAGE_V))
        viol = []
        for c in circuits:
            n = int(c.get("parallel_per_pole", 1))
            cap_ref = n * self.HV_CAPACITY_TABLE.get(float(c["gauge_mm2"]), 0.0)
            if cap_ref < 1.25 * c["current_a"]:
                viol.append(f"{c['name']}: {n}x{c['gauge_mm2']} mm2 ({cap_ref:.0f} A) "
                            f"< 1.25x{c['current_a']:.0f} A")
        results.append(VerificationResult(
            subject="hv_wire_capacity",
            outcome=VerificationOutcome.FAIL if viol else VerificationOutcome.PASS,
            detail=("HV capacity violations: " + "; ".join(viol)) if viol
            else f"All {len(circuits)} HV links respect per-pole capacity "
                 f">= 1.25*I (independent table, U={U:.0f} V).",
            related_ids=[c["name"] for c in circuits],
        ))

        # 3) Voltage drop recomputation (per conductor) within tolerance and <= 2%
        dviol = []
        for c in circuits:
            n = int(c.get("parallel_per_pole", 1))
            drop_ref = 2.0 * self.HV_RHO * c["length_m"] * (c["current_a"] / n) / c["gauge_mm2"]
            claimed = float(c["drop_v"])
            if abs(claimed - drop_ref) > 0.20 * max(drop_ref, 1e-9) + 0.05:
                dviol.append(f"{c['name']}: claimed {claimed:.3f} V vs recomputed {drop_ref:.3f} V")
            elif float(c["drop_pct"]) > self.HV_MAX_DROP_PCT + 0.05:
                dviol.append(f"{c['name']}: {c['drop_pct']}% > {self.HV_MAX_DROP_PCT}%")
        results.append(VerificationResult(
            subject="hv_voltage_drop",
            outcome=VerificationOutcome.FAIL if dviol else VerificationOutcome.PASS,
            detail=("HV drop violations: " + "; ".join(dviol)) if dviol
            else f"All HV drops recomputed within tolerance and <= {self.HV_MAX_DROP_PCT}% "
                 f"(rho={self.HV_RHO} ohm.mm2/m, independent constant).",
            related_ids=[c["name"] for c in circuits],
        ))

        # 4) Fuse must exist, be <= total cable capacity (hosting rule)
        fviol = []
        for c in circuits:
            if c.get("fuse_a") is None:
                fviol.append(f"{c['name']}: no fuse")
            elif float(c["fuse_a"]) > float(c["capacity_a"]) + 1e-9:
                fviol.append(f"{c['name']}: fuse {c['fuse_a']:.0f} A > cable capacity "
                             f"{c['capacity_a']:.0f} A")
        results.append(VerificationResult(
            subject="hv_fusing",
            outcome=VerificationOutcome.FAIL if fviol else VerificationOutcome.PASS,
            detail=("HV fuse violations: " + "; ".join(fviol)) if fviol
            else "Every HV link has a standard fuse within the cable capacity "
                 "(fuse-hosting rule).",
            related_ids=[c["name"] for c in circuits],
        ))

        for r in results:
            self.memory.add_verification(project_id, r)
            if self.bus is not None:
                kind = "VERIFICATION_PASSED" if r.outcome == VerificationOutcome.PASS else "VERIFICATION_FAILED"
                await self.bus.publish(kind, {"project_id": project_id, "id": r.id,
                                              "subject": r.subject, "outcome": r.outcome.value})
        return results

    async def verify_project(self, project_id: str) -> list[VerificationResult]:
        results: list[VerificationResult] = []
        results.extend(self._verify_requirement_coverage(project_id))
        results.extend(self._verify_shaft_sizing(project_id))
        for r in results:
            self.memory.add_verification(project_id, r)
            if self.bus is not None:
                kind = "VERIFICATION_PASSED" if r.outcome == VerificationOutcome.PASS else "VERIFICATION_FAILED"
                await self.bus.publish(
                    kind,
                    {"project_id": project_id, "id": r.id, "subject": r.subject, "outcome": r.outcome.value},
                )
        return results

    # ------------------------------------------------------------------ #
    def _verify_requirement_coverage(self, project_id: str) -> list[VerificationResult]:
        reqs = self.memory.list_requirements(project_id)
        calcs = self.memory.list_calculations(project_id)
        results = []
        linked_req_ids = {rid for c in calcs for rid in c.get("requirement_ids", [])}
        numeric = [r for r in reqs if r.get("value") is not None]
        if numeric:
            covered = sum(1 for r in numeric if r["id"] in linked_req_ids)
            outcome = VerificationOutcome.PASS if covered == len(numeric) else VerificationOutcome.WARNING
            detail = f"{covered}/{len(numeric)} numeric requirements are covered by at least one calculation."
            results.append(
                VerificationResult(
                    subject="requirement_coverage",
                    outcome=outcome,
                    detail=detail,
                    related_ids=[r["id"] for r in numeric],
                )
            )
        return results

    def _verify_shaft_sizing(self, project_id: str) -> list[VerificationResult]:
        """Counter-example check: independently recompute bending stress from
        stored force/length and compare against any claimed shaft diameter."""
        calcs = self.memory.list_calculations(project_id)
        force = next((c for c in calcs if c["name"] == "traction_force"), None)
        if force is None:
            return []
        F = float(force["result"])  # N
        L = 0.25  # m - HYPOTHESIS: 250 mm cantilever overhang to the load point
        allowable_MPa = 165.0  # HYPOTHESIS: S355 steel, static, high safety factor
        Wz_required = F * L / (allowable_MPa * 1e6)
        d_required = (32.0 * Wz_required / math.pi) ** (1.0 / 3.0)
        d_required_mm = d_required * 1000.0

        claimed = None
        for c in calcs:
            if c["name"] == "claimed_shaft_diameter":
                claimed = c

        if claimed is None:
            return [
                VerificationResult(
                    subject="shaft_bending_check",
                    outcome=VerificationOutcome.UNKNOWN,
                    detail=(
                        f"No shaft diameter claimed yet. Independent minimum (bending, F={F:.0f} N, "
                        f"L={L*1000:.0f} mm, sigma_adm={allowable_MPa:.0f} MPa, HYPOTHESIS): "
                        f"{d_required_mm:.1f} mm."
                    ),
                )
            ]

        d_claimed_mm = float(claimed["result"])
        if d_claimed_mm + 1e-9 < d_required_mm:
            outcome = VerificationOutcome.FAIL
            detail = (
                f"Claimed shaft diameter {d_claimed_mm:.1f} mm is INSUFFICIENT. "
                f"Independent minimum is {d_required_mm:.1f} mm "
                f"(F={F:.0f} N, L={L*1000:.0f} mm, sigma_adm={allowable_MPa:.0f} MPa)."
            )
        else:
            outcome = VerificationOutcome.PASS
            detail = f"Claimed diameter {d_claimed_mm:.1f} mm >= required {d_required_mm:.1f} mm."
        return [
            VerificationResult(
                subject="shaft_bending_check",
                outcome=outcome,
                detail=detail,
                related_ids=[claimed["id"], force["id"]],
            )
        ]
