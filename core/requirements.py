"""Requirements Engine: cahier des charges -> formal requirements.

Deterministic FR/EN extraction (no LLM required) so results are reproducible.
Values are normalized to SI. Anything not found is reported as INCONNU, never
invented. Missing critical information is listed explicitly for the user.

Strategy: global scan for "<number> <unit>" occurrences (kg, m/min, V, ...),
which is robust to verb-first phrasings like "transporter 500 kg".
"""
from __future__ import annotations

import re

from core import units
from core.models import Priority, Requirement, RequirementStatus

_NUM = r"(\d+(?:[.,]\d+)?)"

# Global unit scanners: dimension -> unit regex (order matters: longest first).
_UNIT_SCANNERS: list[tuple[str, str]] = [
    ("speed", r"(?:km/h|m\s*/\s*s|m/s|m\s*/\s*min|mm/s)"),
    ("mass", r"(?:kilogrammes?|tonnes?|kg|t)"),
    ("voltage", r"(?:kv|v)"),
    ("power", r"(?:kw|mw|cv|ch|w)"),
    ("force", r"(?:kn|dan|n)"),
    ("torque", r"(?:knm|nm)"),
    ("pressure", r"(?:mpa|kpa|bar|pa)"),
    ("temperature", r"(?:°c|°f|k)"),
    ("length", r"(?:mm|cm|km|m)(?!\s*/)"),  # 'm' not followed by '/' (avoid m/min)
]

# Boolean / qualitative requirements recognized without numeric value.
_QUALITATIVE = [
    ("triphasé", "three_phase_supply", "Triphasé requis"),
    ("triphase", "three_phase_supply", "Triphasé requis"),
    ("three-phase", "three_phase_supply", "Triphasé requis"),
    ("arrêt d'urgence", "emergency_stop", "Arrêt d'urgence requis"),
    ("arret d'urgence", "emergency_stop", "Arrêt d'urgence requis"),
    ("emergency stop", "emergency_stop", "Arrêt d'urgence requis"),
    ("capteurs de position", "position_sensors", "Capteurs de position requis"),
    ("capteur de position", "position_sensors", "Capteurs de position requis"),
    ("position sensors", "position_sensors", "Capteurs de position requis"),
    ("automate", "plc", "Automate programmable requis"),
    ("plc", "plc", "Automate programmable requis"),
    ("interface opérateur", "hmi", "Interface opérateur requise"),
    ("interface operateur", "hmi", "Interface opérateur requise"),
    ("hmi", "hmi", "Interface opérateur requise"),
    ("rs485", "com_rs485", "Communication RS485 requise"),
    ("modbus", "com_modbus", "Communication Modbus requise"),
    ("ip65", "ingress_ip65", "Protection IP65 requise"),
]


def _to_float(raw: str) -> float:
    return float(raw.replace(",", ".").replace(" ", ""))


def _clean_unit(unit: str) -> str:
    return re.sub(r"\s+", "", unit)


class RequirementsEngine:
    """Extracts structured requirements from free text (FR or EN)."""

    def extract(self, text: str) -> list[Requirement]:
        requirements: list[Requirement] = []
        low = text.lower()

        # 1) Global numeric+unit scan.
        for dim, unit_re in _UNIT_SCANNERS:
            for m in re.finditer(rf"{_NUM}\s*({unit_re})\b", low):
                value, raw_unit = _to_float(m.group(1)), _clean_unit(m.group(2))
                requirements.append(self._make(dim, value, raw_unit))

        # 2) Qualitative requirements.
        for needle, key, desc in _QUALITATIVE:
            if needle in low:
                requirements.append(
                    Requirement(
                        description=desc,
                        quantity=key,
                        priority=Priority.MANDATORY,
                        source="user",
                        confidence=0.9,
                        status=RequirementStatus.DRAFT,
                    )
                )

        return self._dedup(requirements)

    def _make(self, dim: str, value: float, raw_unit: str) -> Requirement:
        si_val = units.to_si(units.parse(value, raw_unit))
        return Requirement(
            description=f"{dim} = {value} {raw_unit}",
            quantity=dim,
            value=si_val,
            raw_value=f"{value} {raw_unit}",
            unit=raw_unit,
            priority=Priority.MANDATORY,
            source="user",
            confidence=0.95,
            status=RequirementStatus.DRAFT,
        )

    @staticmethod
    def _dedup(reqs: list[Requirement]) -> list[Requirement]:
        seen: set[tuple] = set()
        out: list[Requirement] = []
        for r in reqs:
            key = (r.quantity, r.value, r.raw_value)
            if key not in seen:
                seen.add(key)
                out.append(r)
        return out

    @staticmethod
    def detect_gaps(reqs: list[Requirement], expected_dimensions: list[str]) -> list[str]:
        """Report dimensions that the user did not specify -> INCONNU."""
        have = {r.quantity for r in reqs if r.value is not None}
        return [d for d in expected_dimensions if d not in have]
