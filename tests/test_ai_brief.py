"""Tests: AI Brief engine - le LLM prépare, les moteurs déterministes exécutent.

Couverture : parsing tolérant (fences), validation stricte de schéma,
rejet hors bornes / cible inconnue (anti-injection), traduction vers les
kwargs des moteurs, hypothèses tracées, endpoint API avec clé absente
(échec honnête, jamais de brief simulé).
"""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from apps.api.main import STATE, app
from core.ai_brief import (
    apply_brief_to_ev_scenario,
    brief_assumptions,
    brief_event,
    build_brief_prompt,
    parse_brief_response,
)


GOOD_BRIEF = """```json
{
  "kind": "aero_car",
  "summary": "Voiture electrique hyper aero, autonomie longue.",
  "items": [
    {"label": "Autonomie", "value_text": "800 km", "is_quantified": true},
    {"label": "Couleur", "value_text": "non precise", "is_quantified": false}
  ],
  "instructions": [
    {"target": "range_km", "value": 800, "reason": "exigence utilisateur"},
    {"target": "motor_kw", "value": 480, "reason": "perf"}
  ],
  "assumptions": ["densite pack 1850 kg/m3"],
  "warnings": ["validation humaine requise"],
  "missing_info": ["couleur"]
}
```"""


# --------------------------------------------------------------------------- #
# Parsing + validation
# --------------------------------------------------------------------------- #
def test_parse_accepts_fenced_json() -> None:
    brief = parse_brief_response(GOOD_BRIEF)
    assert brief.kind == "aero_car"
    assert len(brief.items) == 2
    assert brief.items[0].is_quantified is True
    assert brief.items[1].is_quantified is False


def test_parse_rejects_non_json() -> None:
    with pytest.raises(ValueError, match="aucun JSON"):
        parse_brief_response("Je ne peux pas répondre en JSON.")


def test_parse_rejects_schema_violation() -> None:
    # kind hors liste fermée -> refus (jamais de devinette silencieuse ici)
    bad = GOOD_BRIEF.replace('"aero_car"', '"nuclear_plant"')
    with pytest.raises(ValueError, match="non conforme"):
        parse_brief_response(bad)


def test_parse_missing_kind_is_inferred_honestly() -> None:
    raw = GOOD_BRIEF.replace('"kind": "aero_car",', "")
    brief = parse_brief_response(raw)
    assert brief.kind == "aero_car"  # déduit des mots-clés du contenu


# --------------------------------------------------------------------------- #
# Anti-injection: bornes + cibles fermées
# --------------------------------------------------------------------------- #
def test_out_of_bounds_and_unknown_targets_are_dropped() -> None:
    raw = GOOD_BRIEF.replace(
        '"instructions": [',
        '"instructions": ['
        '{"target": "hv_voltage", "value": 5000, "reason": "injection"},'
        '{"target": "evil_command", "value": 1, "reason": "cible inconnue"},',
    )
    brief = parse_brief_response(raw)
    kept = {i["target"] for i in brief.clamped_instructions()}
    assert kept == {"range_km", "motor_kw"}  # seules les instructions sûres passent


# --------------------------------------------------------------------------- #
# Traduction vers les moteurs déterministes
# --------------------------------------------------------------------------- #
def test_apply_brief_maps_to_ev_scenario_kwargs() -> None:
    brief = parse_brief_response(GOOD_BRIEF)
    kwargs = apply_brief_to_ev_scenario(brief, {"motor_kw": 480.0, "cd": 0.19})
    assert kwargs["range_km"] == 800.0
    assert kwargs["motor_kw"] == 480.0
    assert kwargs["cd"] == 0.19  # non touché par le brief


def test_brief_assumptions_are_traced() -> None:
    brief = parse_brief_response(GOOD_BRIEF)
    asms = brief_assumptions(brief)
    assert len(asms) == 1
    assert asms[0].created_by == "LLMBriefEngineer"
    assert "1850" in asms[0].statement


def test_brief_event_is_audit_ready() -> None:
    brief = parse_brief_response(GOOD_BRIEF)
    event = brief_event(brief, "raw-model-answer")
    assert event["kind"] == "INFO"
    assert event["payload"]["event"] == "BRIEF_CREATED"
    assert event["payload"]["raw_model_response"].startswith("raw-model-answer")


def test_prompt_contains_schema_and_bounds() -> None:
    prompt = build_brief_prompt("Je veux une voiture de 800 km d'autonomie.")
    assert "SCHEMA" in prompt
    assert "hv_voltage" in prompt
    assert "800 km d'autonomie" in prompt


# --------------------------------------------------------------------------- #
# Endpoint API: échec honnête sans clé (jamais de brief simulé)
# --------------------------------------------------------------------------- #
@pytest.fixture()
def client(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    STATE.clear()
    monkeypatch.setenv("AI_ENGINEER_TEST", "1")
    with TestClient(app) as c:
        from core.config import AppConfig

        STATE["config"] = AppConfig()
        STATE["component_researcher"] = None
        STATE["orchestrator"].component_researcher = None
        yield c


def test_brief_endpoint_requires_llm(client) -> None:
    pid = client.post("/projects", json={"name": "brief-t"}).json()["id"]
    r = client.post(
        f"/projects/{pid}/brief",
        json={"cahier_des_charges": "voiture 800 km"},
    )
    # L'environnement de tests n'a pas de LLM configuré -> 400 explicite.
    assert r.status_code == 400
    assert "LLM non configur" in r.json()["detail"]


def test_brief_endpoint_validates_body(client) -> None:
    pid = client.post("/projects", json={"name": "brief-t2"}).json()["id"]
    r = client.post(f"/projects/{pid}/brief", json={})
    assert r.status_code == 422
    r404 = client.post("/projects/PRJ-inconnu/brief", json={"cahier_des_charges": "x"})
    assert r404.status_code == 404
