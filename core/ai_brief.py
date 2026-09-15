"""AI BRIEF ENGINE : le cerveau prépare, les moteurs déterministes exécutent.

Rôle de l'IA (LLM) dans cette plateforme - et il n'y en a pas d'autre :
  1. LIRE le cahier des charges en langage naturel et produire un BRIEF
     structuré : informations repérées, hypothèses proposées, paramètres
     recommandés pour les moteurs de conception, avertissements.
  2. Le brief est VALIDÉ par un schéma strict (pydantic) : un LLM ne peut
     jamais injecter un type inattendu, une commande, ou une valeur hors bornes.
  3. Les moteurs DÉTERMINISTES (calcul, dimensionnement électrique, CAO,
     vérification) exécutent ensuite le brief. Le LLM ne calcule rien :
     il ORIENTE. Tous ses paramètres sont vérifiés par les mêmes règles
     physiques que les valeurs par défaut (capacité >= 1.35*I, dU <= 3%...).

Traçabilité : chaque brief est archivé dans la mémoire projet (événement
BRIEF_CREATED) et répond avec son identifiant et la réponse brute du modèle.

Sécurité : la clé API vient de l'environnement (.env), jamais du code.
Sans clé configurée, make_brief échoue avec une erreur honnête (jamais de
brief simulé qui ressemblerait à un vrai).
"""
from __future__ import annotations

import json
import re
from typing import Any

from pydantic import BaseModel, Field, ValidationError, field_validator

from core.models import Assumption, EventKind, new_id

# Valeurs autorisées par le schéma - listes fermées, pas de freetext exécuté.
DESIGN_KINDS = ("tractor_electrical", "aero_car", "generic_machine")
PRIORITY_LEVELS = ("mandatory", "desired", "optional")

MAX_TEXT_LEN = 400          # borne anti-injection de payload géant
MAX_ITEMS = 24              # borne sur chaque liste du brief


class BriefItem(BaseModel):
    """Une information repérée par l'IA dans le cahier des charges."""

    label: str = Field(min_length=1, max_length=MAX_TEXT_LEN)
    value_text: str = Field(min_length=1, max_length=120)
    is_quantified: bool = False          # False => Information manquante / à préciser
    note: str = Field(default="", max_length=MAX_TEXT_LEN)


class BriefInstruction(BaseModel):
    """Un paramètre recommandé pour un moteur déterministe.

    L'IA propose ; le moteur dispose. Toute valeur hors des bornes physiques
    de son propre moteur est ignorée par celui-ci (voir clamps ci-dessous).
    """

    target: str = Field(min_length=1, max_length=60)      # ex. "hv_voltage"
    value: float
    reason: str = Field(default="", max_length=MAX_TEXT_LEN)


class AIBrief(BaseModel):
    """Brief structuré produit par le LLM, validé avant exécution."""

    kind: str                                             # dans DESIGN_KINDS
    summary: str = Field(min_length=1, max_length=1200)
    items: list[BriefItem] = Field(default_factory=list, max_length=MAX_ITEMS)
    instructions: list[BriefInstruction] = Field(default_factory=list, max_length=MAX_ITEMS)
    assumptions: list[str] = Field(default_factory=list, max_length=MAX_ITEMS)
    warnings: list[str] = Field(default_factory=list, max_length=MAX_ITEMS)
    missing_info: list[str] = Field(default_factory=list, max_length=MAX_ITEMS)

    @field_validator("kind")
    @classmethod
    def _kind_allowed(cls, v: str) -> str:
        if v not in DESIGN_KINDS:
            raise ValueError(f"kind doit être un de {DESIGN_KINDS}")
        return v

    # Bornes physiques : le LLM propose, ces clampes décident. Les moteurs
    # appliquent ensuite leurs propres règles (fusibilité, chute de tension...)
    # donc même un brief invalide ne peut pas produire une conception fausse.
    CLAMPS: dict[str, tuple[float, float]] = {
        "hv_voltage": (12.0, 1000.0),
        "motor_kw": (1.0, 2000.0),
        "battery_kwh": (0.5, 400.0),
        "target_cd": (0.10, 0.60),
        "system_voltage_lv": (6.0, 48.0),
        "battery_ah_lv": (10.0, 400.0),
        "mass_target_kg": (50.0, 100_000.0),
        "speed_max_kmh": (1.0, 500.0),
        "range_km": (10.0, 3000.0),
        "accel_0_100_s": (1.5, 60.0),
    }

    def clamped_instructions(self) -> list[dict[str, Any]]:
        """Instructions applicables : cibles connues, valeur dans les bornes."""
        out: list[dict[str, Any]] = []
        for ins in self.instructions:
            bounds = self.CLAMPS.get(ins.target)
            if bounds is None:
                continue                                  # cible inconnue -> ignorée
            lo, hi = bounds
            if not (lo <= ins.value <= hi):
                continue                                  # hors bornes -> ignorée
            out.append({"target": ins.target, "value": ins.value, "reason": ins.reason})
        return out


# --------------------------------------------------------------------------- #
# Construction du prompt (tout ce que le modèle doit savoir, rien de plus)
# --------------------------------------------------------------------------- #
_SCHEMA_HINT = """{
  "kind": "tractor_electrical" | "aero_car" | "generic_machine",
  "summary": "résumé technique du besoin en 2-4 phrases",
  "items": [{"label": "...", "value_text": "500 kg", "is_quantified": true, "note": ""}],
  "instructions": [{"target": "hv_voltage", "value": 800.0, "reason": "..."}],
  "assumptions": ["..."],
  "warnings": ["..."],
  "missing_info": ["..."]
}"""

_INSTRUCTION_TARGETS = (
    "hv_voltage (12-1000 V, réseau HT de traction ; ex. 400, 800)",
    "motor_kw (1-2000 kW, puissance crête moteur)",
    "battery_kwh (0.5-400 kWh, énergie de traction)",
    "target_cd (0.10-0.60, coefficient de traînée visé)",
    "system_voltage_lv (6-48 V, réseau basse tension)",
    "battery_ah_lv (10-400 Ah, capacité batterie BT)",
    "mass_target_kg (50-100000 kg)",
    "speed_max_kmh (1-500 km/h)",
    "range_km (10-3000 km, autonomie visée)",
    "accel_0_100_s (1.5-60 s)",
)


def build_brief_prompt(cahier_des_charges: str, engine_knowledge: str = "") -> str:
    """Prompt du brief : le modèle organise l'information, il n'invente pas
    de résultat. engine_knowledge = le savoir-faire des moteurs disponibles."""
    cdc = cahier_des_charges.strip()[:6000]
    targets = "\n".join(f"  - {t}" for t in _INSTRUCTION_TARGETS)
    knowledge = engine_knowledge.strip()[:2000] or (
        "Moteurs disponibles : conception électrique 12 V (sections + fusibles), "
        "groupe motopropulseur VE (aéro, autonomie, batterie), réseau HT (400/800 V), "
        "CAO paramétrique tracteur et voiture, vérification indépendante."
    )
    return (
        "Tu es l'ingénieur d'études d'une plateforme de conception. Ton rôle : "
        "ANALYSER le cahier des charges ci-dessous et produire un BRIEF structuré "
        "pour les moteurs de conception déterministes. Tu ne calcules pas les "
        "résultats finaux : les moteurs le font avec leurs règles physiques.\n\n"
        f"SAVOIR DES MOTEURS DISPONIBLES :\n{knowledge}\n\n"
        "INSTRUCTIONS POSSIBLES (cibles fermées, la valeur sera bornée) :\n"
        f"{targets}\n\n"
        "RÈGLES :\n"
        "- is_quantified=false pour toute info absente ou vague ; liste-la dans missing_info.\n"
        "- assumptions: uniquement des hypothèses d'ingénierie raisonnables et explicites.\n"
        "- warnings: risques, normes à prévoir, limites de la plateforme.\n"
        "- Réponds UNIQUEMENT avec le JSON, sans texte autour.\n\n"
        f"SCHEMA:\n{_SCHEMA_HINT}\n\n"
        f"CAHIER DES CHARGES:\n\"\"\"{cdc}\"\"\""
    )


_JSON_RE = re.compile(r"\{.*\}", re.DOTALL)


def parse_brief_response(raw: str) -> AIBrief:
    """Extrait et valide le JSON du modèle. Lève ValueError si invalide :
    jamais de brief partiellement deviné."""
    match = _JSON_RE.search(raw)
    if not match:
        raise ValueError("aucun JSON trouvé dans la réponse du modèle")
    try:
        data = json.loads(match.group(0))
    except json.JSONDecodeError as exc:
        raise ValueError(f"JSON invalide du modèle: {exc}") from None
    # Tolérance: kind manquant mais devinable par mots-clés, sinon erreur.
    if "kind" not in data:
        text = json.dumps(data, ensure_ascii=False).lower()
        if "tracteur" in text:
            data["kind"] = "tractor_electrical"
        elif "voiture" in text or "aero" in text or "cd" in text:
            data["kind"] = "aero_car"
        else:
            data["kind"] = "generic_machine"
    try:
        return AIBrief.model_validate(data)
    except ValidationError as exc:
        raise ValueError(f"brief non conforme au schéma: {exc}") from None


# --------------------------------------------------------------------------- #
# Application du brief aux moteurs déterministes
# --------------------------------------------------------------------------- #
def apply_brief_to_ev_scenario(brief: AIBrief, defaults: dict[str, Any]) -> dict[str, Any]:
    """Traduit les instructions du brief en kwargs pour design_ev_scenario().
    Les cibles hors bornes (déjà filtrées par clamped_instructions) ne passent pas."""
    kwargs = dict(defaults)
    for ins in brief.clamped_instructions():
        mapping = {
            "motor_kw": "motor_kw",
            "battery_kwh": "battery_kwh",
            "target_cd": "cd",
            "speed_max_kmh": "vmax_kmh",
            "range_km": "range_km",
            "accel_0_100_s": "accel_100_time_s",
            "mass_target_kg": "mass_kg",
        }
        key = mapping.get(ins["target"])
        if key:
            kwargs[key] = ins["value"]  # cible connue du moteur EV
    return kwargs


def brief_assumptions(brief: AIBrief, creator: str = "LLMBriefEngineer") -> list[Assumption]:
    """Convertit les hypothèses du brief en hypothèses tracées de la mémoire."""
    return [
        Assumption(statement=a[:MAX_TEXT_LEN], rationale="hypothèse proposée par l'IA "
                   "dans le brief", created_by=creator)
        for a in brief.assumptions[:MAX_ITEMS]
    ]


def brief_event(brief: AIBrief, raw: str) -> dict[str, Any]:
    """Événement d'audit pour la mémoire (event sourcing, section 28)."""
    return {
        "kind": EventKind.INFO.value,
        "payload": {
            "event": "BRIEF_CREATED",
            "kind": brief.kind,
            "summary": brief.summary[:300],
            "n_items": len(brief.items),
            "n_instructions": len(brief.instructions),
            "n_assumptions": len(brief.assumptions),
            "raw_model_response": raw[:2000],
        },
    }


def new_brief_id() -> str:
    return new_id("BRIEF")
