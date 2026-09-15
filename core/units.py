"""Unit Engine (section 18): strict unit handling built on Pint.

All internal values are normalized to SI. Calculations between incompatible
units are forbidden and raise immediately - unit errors cannot silently pass.
"""
from __future__ import annotations

from functools import lru_cache
from typing import Any

import pint

UnitParseError = pint.errors.UndefinedUnitError

# Case-insensitive alias map: raw (lowercased) unit -> canonical Pint unit.
# Pint is case-sensitive (V=volt, v=undefined), user input is not.
_UNIT_ALIASES = {
    "v": "V", "kv": "kV", "mv": "mV",
    "w": "W", "kw": "kW", "mw": "MW",
    "a": "A", "ma": "mA", "ka": "kA",
    "n": "N", "kn": "kN", "dan": "daN", "mn": "mN",
    "nm": "N*m", "knm": "kN*m",
    "pa": "Pa", "kpa": "kPa", "mpa": "MPa", "gpa": "GPa",
    "j": "J", "kj": "kJ", "hz": "Hz", "khz": "kHz", "mhz": "MHz",
    "k": "K",
    "°c": "degC", "°f": "degF",
    "cv": "cv", "ch": "ch",  # metric horsepower (Pint knows both)
    "t": "t",                 # metric tonne
}


@lru_cache(maxsize=1)
def _ureg() -> pint.UnitRegistry:
    return pint.UnitRegistry()


def ureg() -> pint.UnitRegistry:
    return _ureg()


# Normalized dimension names used across the platform (requirement taxonomy).
DIMENSION_ALIASES = {
    "mass": "mass",
    "masse": "mass",
    "weight": "mass",
    "force": "force",
    "effort": "force",
    "speed": "speed",
    "vitesse": "speed",
    "velocity": "speed",
    "length": "length",
    "longueur": "length",
    "distance": "length",
    "diameter": "length",
    "diametre": "length",
    "power": "power",
    "puissance": "power",
    "torque": "torque",
    "couple": "torque",
    "voltage": "voltage",
    "tension": "voltage",
    "current": "current",
    "courant": "current",
    "pressure": "pressure",
    "pression": "pressure",
    "temperature": "temperature",
    "temperature_": "temperature",
    "flow": "volumetric_flow",
    "debit": "volumetric_flow",
    "angle": "angle",
    "time": "time",
    "temps": "time",
    "frequency": "frequency",
    "frequence": "frequency",
}


def normalize_quantity_name(name: str) -> str:
    """Map a (possibly French) quantity name to the platform dimension name."""
    key = name.strip().lower().replace("é", "e").replace("è", "e")
    return DIMENSION_ALIASES.get(key, key)


def _canonical(unit: str) -> str:
    key = str(unit).strip().lower().replace(" ", "")
    return _UNIT_ALIASES.get(key, key)


def parse(value: float | str, unit: str | None = None) -> Any:
    """Parse a Quantity. Raises UnitParseError for unknown units."""
    u = ureg()
    if unit is None:
        return u.parse_expression(str(value))
    return float(value) * u.parse_expression(_canonical(unit))


def to_si(q: Any) -> float:
    """Return the SI-magnitude of a Quantity (temperature uses kelvin)."""
    return float(q.to_base_units().magnitude)


def convert(value: float, from_unit: str, to_unit: str) -> float:
    """Convert a numeric value between compatible units; raises on incompatibility."""
    q = float(value) * ureg().parse_expression(_canonical(from_unit))
    target = ureg().parse_expression(_canonical(to_unit))
    if q.dimensionality != target.dimensionality:
        raise ValueError(
            f"Incompatible units: {from_unit} ({q.dimensionality}) -> {to_unit} ({target.dimensionality})"
        )
    return float(q.to(target).magnitude)


def unit_name(q: Any) -> str:
    return format(q.units, "~")


def dimension_of(unit: str) -> str:
    q = ureg().parse_expression(unit)
    return str(q.dimensionality)
