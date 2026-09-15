"""Engineering Calculation Engine (sections 10 and 17).

Deterministic computation only. The LLM NEVER performs calculations: it may
choose *which* calculator to call, the numbers come from here. Every
calculation produces a CalculationRecord: formula -> inputs -> units ->
result -> assumptions, reproducible and traceable to requirements.
"""
from __future__ import annotations

from typing import Any

from core import units
from core.models import CalculationRecord, new_id, utc_now_iso


class CalculationEngine:
    def __init__(self, event_bus=None) -> None:
        self._bus = event_bus
        self.registry: dict[str, dict[str, Any]] = {}

    # ------------------------------------------------------------------ #
    # Registration
    # ------------------------------------------------------------------ #
    def register(self, name: str, description: str, func) -> None:
        self.registry[name] = {"description": description, "func": func}

    def list(self) -> list[dict[str, str]]:
        return [
            {"name": n, "description": m["description"]}
            for n, m in sorted(self.registry.items())
        ]

    # ------------------------------------------------------------------ #
    # Execution
    # ------------------------------------------------------------------ #
    def run(
        self,
        name: str,
        inputs: dict[str, float | str],
        *,
        units_map: dict[str, str] | None = None,
        assumptions: list[str] | None = None,
        sources: list[str] | None = None,
        requirement_ids: list[str] | None = None,
    ) -> CalculationRecord:
        """Run a registered calculator by name; returns a traceable record."""
        if name not in self.registry:
            raise KeyError(f"unknown calculator: {name}")
        units_map = units_map or {}
        assumptions = assumptions or []
        sources = sources or []

        # Normalize inputs to SI magnitudes right away.
        si_inputs: dict[str, float] = {}
        for key, val in inputs.items():
            if isinstance(val, str):
                q = units.parse(val)  # e.g. "20 m/min", "500 kg"
                si_inputs[key] = units.to_si(q)
            else:
                unit = units_map.get(key)
                if unit:
                    si_inputs[key] = units.convert(float(val), unit, self._si_unit_of(unit))
                else:
                    si_inputs[key] = float(val)

        meta = self.registry[name]
        result_val, result_unit, formula = meta["func"](**si_inputs)

        record = CalculationRecord(
            name=name,
            formula=formula,
            inputs={k: float(v) for k, v in si_inputs.items()},
            units={**{k: "SI" for k in si_inputs}, "result": result_unit},
            result=float(result_val),
            result_unit=result_unit,
            assumptions=list(assumptions),
            sources=list(sources),
            requirement_ids=list(requirement_ids or []),
            timestamp=utc_now_iso(),
        )
        if self._bus is not None:
            # Synchronous publish: journal + persistence happen now; async
            # subscribers (UI, WebSocket) are scheduled without delaying us.
            self._bus.publish_sync("CALCULATION_COMPLETED", dict(record.model_dump()))
        return record

    @staticmethod
    def _si_unit_of(unit: str) -> str:
        q = units.ureg().parse_expression(unit)
        return format((1 * q).to_base_units().units, "~")

    # ------------------------------------------------------------------ #
    # Built-in calculators (documented formulas)
    # ------------------------------------------------------------------ #
    @staticmethod
    def default_engine(bus=None) -> "CalculationEngine":
        eng = CalculationEngine(bus)

        def linear_speed_to_rotational(speed_si: float, diameter_si: float):
            """v = pi * d * n / 60  (m/s, m -> rpm)"""
            n = speed_si / (3.141592653589793 * diameter_si) * 60.0
            return n, "rpm", "n = v / (pi * d) * 60"

        def mechanical_power(speed_si: float, force_si: float):
            """P = F * v  (N, m/s -> W)"""
            p = force_si * speed_si
            return p, "W", "P = F * v"

        def power_with_efficiency(power_si: float, efficiency: float):
            """P_shaft = P_useful / eta"""
            if not 0 < efficiency <= 1:
                raise ValueError("efficiency must be in (0, 1]")
            return power_si / efficiency, "W", "P_shaft = P_useful / eta"

        def traction_force(mass_si: float, friction_coefficient: float, acceleration_si: float = 0.0):
            """F = m * g * mu + m * a (Coulomb friction on horizontal plane + inertia)"""
            g = 9.80665
            f = mass_si * g * friction_coefficient + mass_si * acceleration_si
            return f, "N", "F = m * g * mu + m * a"

        def cantilever_bending_stress(force_si: float, length_si: float, section_modulus_si: float):
            """sigma = F * L / Wz  (N, m, m^3 -> Pa)"""
            sigma = force_si * length_si / section_modulus_si
            return sigma, "Pa", "sigma = F * L / Wz"

        def round_solid_section_modulus(diameter_si: float):
            """Wz = pi * d^3 / 32 (m -> m^3)"""
            import math

            w = math.pi * diameter_si**3 / 32.0
            return w, "m^3", "Wz = pi * d^3 / 32"

        def motor_sizing_from_specs(
            mass_si: float,
            speed_si: float,
            friction_coefficient: float,
            efficiency: float,
            acceleration_si: float = 0.0,
        ):
            """End-to-end useful->shaft power: P = (m g mu + m a) * v / eta."""
            g = 9.80665
            f = mass_si * g * friction_coefficient + mass_si * acceleration_si
            p_shaft = f * speed_si / efficiency
            return p_shaft, "W", "P_shaft = (m*g*mu + m*a) * v / eta"

        # -------------------------------------------------------------- #
        # Bearing life (roller-element bearings)
        # -------------------------------------------------------------- #
        def bearing_life_L10_hours(
            dynamic_capacity_N: float, equivalent_load_N: float, speed_rpm: float
        ):
            """Ball-bearing basic rating life in hours: L10h = (C/P)^3 * 1e6 / (60 n).
            Exponent 3 = ball bearings (10/3 for rollers). C = dynamic capacity [N],
            P = equivalent radial load [N], n = speed [rpm]."""
            import math

            if dynamic_capacity_N <= 0 or equivalent_load_N <= 0 or speed_rpm <= 0:
                raise ValueError("C, P and n must be strictly positive")
            L10_mrev = (dynamic_capacity_N / equivalent_load_N) ** 3
            hours = L10_mrev * 1e6 / (60.0 * speed_rpm)
            return hours, "h", "L10h = (C/P)^3 * 1e6 / (60 n)"

        def bearing_life_L10_roller_hours(
            dynamic_capacity_N: float, equivalent_load_N: float, speed_rpm: float
        ):
            """Roller-bearing basic rating life: L10h = (C/P)^(10/3) * 1e6 / (60 n)."""
            if dynamic_capacity_N <= 0 or equivalent_load_N <= 0 or speed_rpm <= 0:
                raise ValueError("C, P and n must be strictly positive")
            L10_mrev = (dynamic_capacity_N / equivalent_load_N) ** (10.0 / 3.0)
            hours = L10_mrev * 1e6 / (60.0 * speed_rpm)
            return hours, "h", "L10h = (C/P)^(10/3) * 1e6 / (60 n)"

        # -------------------------------------------------------------- #
        # Belt / chain transmissions
        # -------------------------------------------------------------- #
        def belt_length(d1_m: float, d2_m: float, center_distance_m: float):
            """Open flat/V-belt approximate length: L = 2a + pi(d1+d2)/2 + (d2-d1)^2/(4a)."""
            import math

            a = center_distance_m
            if a <= 0:
                raise ValueError("center distance must be positive")
            L = 2 * a + math.pi * (d1_m + d2_m) / 2.0 + (d2_m - d1_m) ** 2 / (4 * a)
            return L, "m", "L = 2a + pi(d1+d2)/2 + (d2-d1)^2/(4a)"

        def belt_speed(d1_m: float, n1_rpm: float):
            """Belt linear speed at the driver pulley: v = pi d1 n1 / 60."""
            import math

            v = math.pi * d1_m * n1_rpm / 60.0
            return v, "m/s", "v = pi d1 n1 / 60"

        def transmission_ratio(d1_m: float, d2_m: float):
            """Speed ratio i = d2/d1 (n2 = n1 / i)."""
            if d1_m <= 0:
                raise ValueError("d1 must be positive")
            return d2_m / d1_m, "-", "i = d2 / d1"

        def chain_length_pitches(pitch_mm: float, z1: float, z2: float, center_distance_mm: float):
            """Roller-chain length in pitches:
            Lp = 2a/p + (z1+z2)/2 + (p/a) * ((z2-z1)/(2 pi))^2"""
            import math

            a, p = center_distance_mm, pitch_mm
            if a <= 0 or p <= 0:
                raise ValueError("center distance and pitch must be positive")
            Lp = 2 * a / p + (z1 + z2) / 2.0 + (p / a) * ((z2 - z1) / (2 * math.pi)) ** 2
            return Lp, "pitches", "Lp = 2a/p + (z1+z2)/2 + (p/a)((z2-z1)/2pi)^2"

        # -------------------------------------------------------------- #
        # Beam deflection
        # -------------------------------------------------------------- #
        def rect_section_inertia(width_m: float, height_m: float):
            """Second moment of area of a rectangle, bending in the height direction:
            I = b h^3 / 12."""
            if width_m <= 0 or height_m <= 0:
                raise ValueError("width and height must be positive")
            return width_m * height_m**3 / 12.0, "m^4", "I = b h^3 / 12"

        def cantilever_deflection(force_N: float, length_m: float, young_modulus_Pa: float, inertia_m4: float):
            """Tip deflection of a cantilever with an end load: delta = F L^3 / (3 E I)."""
            if young_modulus_Pa <= 0 or inertia_m4 <= 0:
                raise ValueError("E and I must be positive")
            delta = force_N * length_m**3 / (3.0 * young_modulus_Pa * inertia_m4)
            return delta, "m", "delta = F L^3 / (3 E I)"

        def simply_supported_center_deflection(force_N: float, length_m: float, young_modulus_Pa: float, inertia_m4: float):
            """Mid-span deflection, simply supported beam, central load:
            delta = F L^3 / (48 E I)."""
            if young_modulus_Pa <= 0 or inertia_m4 <= 0:
                raise ValueError("E and I must be positive")
            delta = force_N * length_m**3 / (48.0 * young_modulus_Pa * inertia_m4)
            return delta, "m", "delta = F L^3 / (48 E I)"

        # -------------------------------------------------------------- #
        # Electrical: voltage drop
        # -------------------------------------------------------------- #
        def voltage_drop(
            resistivity_ohm_mm2_per_m: float,
            length_m: float,
            current_A: float,
            cross_section_mm2: float,
            phases: float = 1.0,
        ):
            """Line voltage drop: dU = b * rho * L * I / S.
            b = 2 (single-phase) or sqrt(3) (balanced three-phase).
            rho in ohm.mm^2/m (copper ~0.0225 at operating temp, aluminum ~0.036)."""
            import math

            b = {1: 2.0, 3: math.sqrt(3.0)}.get(round(float(phases)))
            if b is None:
                raise ValueError("phases must be 1 or 3")
            if cross_section_mm2 <= 0:
                raise ValueError("cross-section must be positive")
            dU = b * resistivity_ohm_mm2_per_m * length_m * current_A / cross_section_mm2
            return dU, "V", "dU = b * rho * L * I / S"

        def voltage_drop_percent(drop_V: float, line_voltage_V: float):
            """Voltage drop as a percentage of the nominal voltage."""
            if line_voltage_V <= 0:
                raise ValueError("line voltage must be positive")
            return 100.0 * drop_V / line_voltage_V, "%", "dU% = 100 * dU / U"

        eng.register(
            "linear_speed_to_rotational",
            "Rotational speed from linear belt/pulley speed: n = v / (pi*d) * 60",
            linear_speed_to_rotational,
        )
        eng.register("mechanical_power", "P = F * v", mechanical_power)
        eng.register("power_with_efficiency", "P_shaft = P_useful / eta", power_with_efficiency)
        eng.register("traction_force", "F = m g mu + m a", traction_force)
        eng.register(
            "cantilever_bending_stress",
            "Cantilever bending stress sigma = F*L/Wz",
            cantilever_bending_stress,
        )
        eng.register(
            "round_solid_section_modulus",
            "Section modulus of a round solid section Wz = pi d^3 / 32",
            round_solid_section_modulus,
        )
        eng.register(
            "motor_sizing_from_specs",
            "Motor shaft power from mass, speed, friction, efficiency, acceleration",
            motor_sizing_from_specs,
        )
        eng.register(
            "bearing_life_L10_hours",
            "Ball bearing rating life in hours L10h = (C/P)^3 * 1e6 / (60 n)",
            bearing_life_L10_hours,
        )
        eng.register(
            "bearing_life_L10_roller_hours",
            "Roller bearing rating life in hours L10h = (C/P)^(10/3) * 1e6 / (60 n)",
            bearing_life_L10_roller_hours,
        )
        eng.register(
            "belt_length",
            "Open belt approximate length L = 2a + pi(d1+d2)/2 + (d2-d1)^2/(4a)",
            belt_length,
        )
        eng.register("belt_speed", "Belt speed v = pi d1 n1 / 60", belt_speed)
        eng.register("transmission_ratio", "Speed ratio i = d2/d1", transmission_ratio)
        eng.register(
            "chain_length_pitches",
            "Roller chain length in pitches Lp = 2a/p + (z1+z2)/2 + (p/a)((z2-z1)/2pi)^2",
            chain_length_pitches,
        )
        eng.register("rect_section_inertia", "Rectangle second moment I = b h^3 / 12", rect_section_inertia)
        eng.register(
            "cantilever_deflection",
            "Cantilever tip deflection delta = F L^3 / (3 E I)",
            cantilever_deflection,
        )
        eng.register(
            "simply_supported_center_deflection",
            "Simply supported beam, central load: delta = F L^3 / (48 E I)",
            simply_supported_center_deflection,
        )
        eng.register(
            "voltage_drop",
            "Line voltage drop dU = b * rho * L * I / S (b=2 mono, b=sqrt3 tri)",
            voltage_drop,
        )
        eng.register(
            "voltage_drop_percent",
            "Voltage drop percentage dU% = 100 dU / U",
            voltage_drop_percent,
        )

        # ------------------------------------------------------------ #
        # Aerodynamics + electric vehicle (Phase: EV design)
        # ------------------------------------------------------------ #
        def aerodynamic_drag_force(
            air_density_kg_m3: float, drag_coefficient: float,
            frontal_area_m2: float, speed_m_s: float,
        ):
            """F_aero = 0.5 * rho * Cd * A * v^2 [N].
            Quadratic drag law; rho ~ 1.225 kg/m3 at sea level (ISA)."""
            if frontal_area_m2 <= 0 or speed_m_s < 0 or air_density_kg_m3 <= 0:
                raise ValueError("rho, A must be positive; v >= 0")
            f = 0.5 * air_density_kg_m3 * drag_coefficient * frontal_area_m2 * speed_m_s**2
            return f, "N", "F_aero = 0.5 * rho * Cd * A * v^2"

        def aerodynamic_power(
            air_density_kg_m3: float, drag_coefficient: float,
            frontal_area_m2: float, speed_m_s: float,
        ):
            """P_aero = 0.5 * rho * Cd * A * v^3 [W] (drag force times speed)."""
            if frontal_area_m2 <= 0 or speed_m_s < 0 or air_density_kg_m3 <= 0:
                raise ValueError("rho, A must be positive; v >= 0")
            p = 0.5 * air_density_kg_m3 * drag_coefficient * frontal_area_m2 * speed_m_s**3
            return p, "W", "P_aero = 0.5 * rho * Cd * A * v^3"

        def kinetic_energy(mass_kg: float, speed_m_s: float):
            """E = 0.5 * m * v^2 [J]."""
            if mass_kg <= 0 or speed_m_s < 0:
                raise ValueError("mass must be positive; v >= 0")
            e = 0.5 * mass_kg * speed_m_s**2
            return e, "J", "E = 0.5 * m * v^2"

        def acceleration_power(mass_kg: float, speed_m_s: float, accel_time_s: float):
            """Mean power to reach v in t from standstill: P = E/t = 0.5 m v^2 / t [W].
            (Mean over the run; peak wheel power is about twice this.)"""
            if accel_time_s <= 0 or mass_kg <= 0 or speed_m_s < 0:
                raise ValueError("t and mass must be positive; v >= 0")
            p = 0.5 * mass_kg * speed_m_s**2 / accel_time_s
            return p, "W", "P_acc = 0.5 * m * v^2 / t"

        def battery_pack_mass(energy_kwh: float, pack_specific_energy_kwh_kg: float):
            """m_pack = E / e_pack [kg]. e_pack ~ 0.16 kWh/kg cell-to-pack (HYPOTHESIS
            typical NMC/LFP pack level)."""
            if energy_kwh <= 0 or pack_specific_energy_kwh_kg <= 0:
                raise ValueError("energy and specific energy must be positive")
            m = energy_kwh / pack_specific_energy_kwh_kg
            return m, "kg", "m_pack = E / e_pack"

        def ev_range_km(
            battery_energy_kwh: float, consumption_wh_per_km: float,
        ):
            """Range [km] = E_pack [kWh] * 1000 / consumption [Wh/km]."""
            if battery_energy_kwh <= 0 or consumption_wh_per_km <= 0:
                raise ValueError("energy and consumption must be positive")
            r = battery_energy_kwh * 1000.0 / consumption_wh_per_km
            return r, "km", "d = E_pack * 1000 / consumption"

        eng.register(
            "aerodynamic_drag_force",
            "Aerodynamic drag force F = 0.5 rho Cd A v^2",
            aerodynamic_drag_force,
        )
        eng.register(
            "aerodynamic_power",
            "Aerodynamic power P = 0.5 rho Cd A v^3",
            aerodynamic_power,
        )
        eng.register("kinetic_energy", "Kinetic energy E = 0.5 m v^2", kinetic_energy)
        eng.register(
            "acceleration_power",
            "Mean acceleration power P = 0.5 m v^2 / t",
            acceleration_power,
        )
        eng.register(
            "battery_pack_mass",
            "Battery pack mass m = E / e_pack",
            battery_pack_mass,
        )
        eng.register(
            "ev_range_km",
            "EV range d = E_pack / consumption",
            ev_range_km,
        )
        return eng
