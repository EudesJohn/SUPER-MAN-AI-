"""EV scenario engine: from performance targets to a consistent design.

Deterministic only: every number comes from a CalculationEngine record.
- aero power at vmax and cruise, acceleration power
- motor power check (motor >= max(required)) with margin
- battery energy from range target + consumption, pack mass from specific energy
- parametric spec consistency for the 3D builder (same Cd/A/mass values)
- merges the LV 12 V design (ElectricalDesignEngine) and the HV design
  (core/ev_design.py) into one electrical package
"""
from __future__ import annotations

from typing import Any

from core.calculation import CalculationEngine

RHO_AIR = 1.225          # kg/m3, ISA sea level (HYPOTHESIS)
ROTATIONAL_ALLOWANCE = 1.08   # +8% for wheel/rotor/aux losses (HYPOTHESIS)


def design_ev_scenario(
    calc: CalculationEngine,
    *,
    mass_kg: float = 1780.0,
    cd: float = 0.19,
    frontal_area_m2: float = 2.05,
    vmax_kmh: float = 250.0,
    cruise_kmh: float = 120.0,
    accel_100_time_s: float = 3.2,
    range_km: float = 550.0,
    consumption_wh_per_km: float = 118.0,
    pack_specific_energy_kwh_kg: float = 0.16,
    motor_kw: float = 480.0,
    battery_kwh: float = 95.0,
) -> dict[str, Any]:
    """Compute the aero/powertrain scenario; returns records + consistency."""
    v_max = vmax_kmh / 3.6
    v_cruise = cruise_kmh / 3.6

    # ---------------- aerodynamics ---------------- #
    drag_vmax = calc.run("aerodynamic_drag_force",
                         {"air_density_kg_m3": RHO_AIR, "drag_coefficient": cd,
                          "frontal_area_m2": frontal_area_m2, "speed_m_s": v_max},
                         assumptions=[f"rho={RHO_AIR} ISA sea level (HYPOTHESIS)",
                                      f"Cd={cd} (target, unvalidated without wind tunnel)"])
    power_vmax = calc.run("aerodynamic_power",
                          {"air_density_kg_m3": RHO_AIR, "drag_coefficient": cd,
                           "frontal_area_m2": frontal_area_m2, "speed_m_s": v_max},
                          assumptions=["steady state at vmax"])
    drag_cruise = calc.run("aerodynamic_drag_force",
                           {"air_density_kg_m3": RHO_AIR, "drag_coefficient": cd,
                            "frontal_area_m2": frontal_area_m2, "speed_m_s": v_cruise},
                           assumptions=["steady state at cruise"])
    power_cruise = calc.run("aerodynamic_power",
                            {"air_density_kg_m3": RHO_AIR, "drag_coefficient": cd,
                             "frontal_area_m2": frontal_area_m2, "speed_m_s": v_cruise},
                            assumptions=["steady state at cruise"])

    # rolling resistance at cruise (Crr = 0.009, HYPOTHESIS - low-rr EV tires)
    CRR = 0.009
    f_roll = mass_kg * 9.80665 * CRR
    p_roll_cruise = calc.run("mechanical_power",
                             {"force_si": f_roll, "speed_si": v_cruise},
                             assumptions=[f"rolling resistance Crr={CRR} (HYPOTHESIS)"])

    # ---------------- acceleration ---------------- #
    p_acc_mean = calc.run("acceleration_power",
                          {"mass_kg": mass_kg, "speed_m_s": v_max_accel(vmax_kmh),
                           "accel_time_s": accel_100_time_s},
                          assumptions=["0-100 km/h in t s, MEAN wheel power "
                                       "(peak is ~2x this - HYPOTHESIS)"])

    # ---------------- motor check ---------------- #
    required_kw = (max(power_vmax.result, p_acc_mean.result * 2.0)  # peak rule
                   * ROTATIONAL_ALLOWANCE) / 1000.0
    motor_ok = motor_kw >= required_kw
    margin_kw = motor_kw - required_kw

    # ---------------- battery + range ---------------- #
    e_needed = calc.run("ev_range_km",
                        {"battery_energy_kwh": battery_kwh,
                         "consumption_wh_per_km": consumption_wh_per_km},
                        assumptions=["WLTP-ish mixed consumption (HYPOTHESIS)"])
    pack_m = calc.run("battery_pack_mass",
                      {"energy_kwh": battery_kwh,
                       "pack_specific_energy_kwh_kg": pack_specific_energy_kwh_kg},
                      assumptions=[f"pack-level {pack_specific_energy_kwh_kg} kWh/kg (HYPOTHESIS)"])

    consistency = {
        "motor_ok": motor_ok,
        "required_motor_kw": round(required_kw, 1),
        "motor_margin_kw": round(margin_kw, 1),
        "range_km": round(e_needed.result, 0),
        "range_target_km": range_km,
        "range_ok": e_needed.result >= range_km * 0.98,
        "pack_mass_kg": round(pack_m.result, 0),
        "mass_check_kg": round(mass_kg - pack_m.result, 0),
        "note": ("mass_check_kg = masse restant pour chassis/moteur/habillage "
                 "apres la batterie; si <= 0, la masse cible est incoherente."),
    }

    return {
        "scenario": {
            "mass_kg": mass_kg, "cd": cd, "frontal_area_m2": frontal_area_m2,
            "vmax_kmh": vmax_kmh, "cruise_kmh": cruise_kmh,
            "accel_100_time_s": accel_100_time_s, "motor_kw": motor_kw,
            "battery_kwh": battery_kwh, "consumption_wh_per_km": consumption_wh_per_km,
        },
        "aero": {
            "drag_vmax_N": round(drag_vmax.result, 1),
            "power_vmax_W": round(power_vmax.result, 0),
            "drag_cruise_N": round(drag_cruise.result, 1),
            "power_cruise_W": round(power_cruise.result, 0),
            "power_roll_cruise_W": round(p_roll_cruise.result, 0),
            "total_cruise_W": round(power_cruise.result + p_roll_cruise.result, 0),
        },
        "acceleration": {"mean_wheel_power_W": round(p_acc_mean.result, 0)},
        "consistency": consistency,
        "calc_ids": [drag_vmax.id, power_vmax.id, drag_cruise.id, power_cruise.id,
                     p_roll_cruise.id, p_acc_mean.id, e_needed.id, pack_m.id],
    }


def v_max_accel(vmax_kmh: float) -> float:
    """0-100 km/h reference: cap the end speed at 100 km/h for the accel calc."""
    return min(vmax_kmh, 100.0) / 3.6


def parametric_spec(scenario: dict[str, Any]) -> dict[str, Any]:
    """Spec for build_aero_car derived FROM the scenario numbers (one source
    of truth: the 3D model, the battery pan length and the documentation all
    use the same values)."""
    sc = scenario["scenario"]
    return {
        "battery_kwh": sc["battery_kwh"],
        "motor_kw": sc["motor_kw"],
        "cd": sc["cd"],
        "frontal_area_m2": sc["frontal_area_m2"],
        "mass_kg": sc["mass_kg"],
        "consumption_wh_per_km": sc["consumption_wh_per_km"],
    }
