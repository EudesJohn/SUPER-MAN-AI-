"""API SERVICE (FastAPI): REST + WebSocket for the AI ENGINEER MVP.

Run:  uvicorn apps.api.main:app --reload
Docs: http://127.0.0.1:8000/docs
"""
from __future__ import annotations

import asyncio
import json
import logging
import re
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

from fastapi import Body, FastAPI, HTTPException, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import Response
from pydantic import BaseModel, Field

from apps.orchestrator import Orchestrator
from core.calculation import CalculationEngine
from core.config import AppConfig, load_config
from core.events import EventBus
from core.memory import ProjectMemory
from core.models import Artifact
from core.tools import ToolRegistry, make_file_tools
from core.verification import VerificationEngine

STATE: dict[str, Any] = {}


@asynccontextmanager
async def lifespan(app: FastAPI):
    from core.config import load_env

    load_env()  # secrets stay in .env (git-ignored), never in code
    config: AppConfig = load_config()
    memory = ProjectMemory("ai_engineer.db")
    bus = EventBus()
    calc = CalculationEngine.default_engine(bus)
    workspace = Path(config.storage.root)
    workspace.mkdir(parents=True, exist_ok=True)
    registry = ToolRegistry(workspace)
    make_file_tools(registry)
    verification = VerificationEngine(memory, bus)

    # Web research (Phase 2): provider chosen by config; None = disabled.
    from providers.search.search import make_provider
    from providers.search.trust import trust_for_url  # noqa: F401 - re-export for tests

    try:
        search_provider = make_provider(config.search.provider)
    except ValueError:
        search_provider = None

    component_researcher = None
    if search_provider is not None and config.search.enabled:
        from core.components import ComponentResearcher
        from core.research import WebResearchEngine

        research_engine = WebResearchEngine(memory, bus, search_provider)
        component_researcher = ComponentResearcher(research_engine)

    # LLM gateway (section 26): nvidia/openai/anthropic via config + .env key.
    from providers.llm.gateway import make_gateway_from_config

    llm_gateway, llm_router, llm_notes = make_gateway_from_config(config)
    for n in llm_notes:
        logging.getLogger("ai_engineer").info("%s", n)

    STATE.update(
        config=config, memory=memory, bus=bus, calc=calc, registry=registry,
        verification=verification, component_researcher=component_researcher,
        _search_provider=search_provider, llm_gateway=llm_gateway, llm_router=llm_router,
        orchestrator=Orchestrator(
            memory, bus, calc, registry, verification,
            config.execution.max_retries, component_researcher,
        ),
    )
    yield
    memory.close()


app = FastAPI(title="AI ENGINEER", version="0.1.0", description="Agentic engineering platform (MVP)", lifespan=lifespan)

# CORS: the Vite dev server (5173) calls the API directly or via proxy.
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
    allow_methods=["*"],
    allow_headers=["*"],
)


# --------------------------------------------------------------------- #
# Schemas
# --------------------------------------------------------------------- #
class ProjectIn(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    description: str = ""


class ExecuteIn(BaseModel):
    cahier_des_charges: str = Field(min_length=1)


# --------------------------------------------------------------------- #
# REST
# --------------------------------------------------------------------- #
@app.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok", "mode": STATE["config"].execution.mode}


@app.post("/projects", status_code=201)
async def create_project(body: ProjectIn) -> dict[str, Any]:
    return await STATE["orchestrator"].create_project(body.name, body.description)


@app.get("/projects")
async def list_projects() -> list[dict[str, Any]]:
    return STATE["memory"].list_projects()


@app.get("/projects/{pid}")
async def get_project(pid: str) -> dict[str, Any]:
    p = STATE["memory"].get_project(pid)
    if not p:
        raise HTTPException(404, "project not found")
    return p


@app.post("/projects/{pid}/execute")
async def execute_project(pid: str, body: ExecuteIn) -> dict[str, Any]:
    try:
        return await STATE["orchestrator"].execute(pid, body.cahier_des_charges)
    except KeyError:
        raise HTTPException(404, "project not found") from None


@app.post("/projects/{pid}/research")
async def project_research(pid: str, body: dict) -> dict[str, Any]:
    """Run a standalone research query and persist sourced results."""
    from core.research import WebResearchEngine
    from providers.search.fetcher import Fetcher

    if STATE.get("component_researcher") is None:
        raise HTTPException(400, "web research disabled (config: search.provider / enabled)")
    query = str(body.get("query", "")).strip()
    if not query:
        raise HTTPException(422, "body must contain a non-empty 'query'")
    engine = WebResearchEngine(STATE["memory"], STATE["bus"], STATE["_search_provider"], Fetcher())
    return await engine.research(pid, query, max_results=int(body.get("max_results", 8)))


@app.get("/projects/{pid}/components")
async def project_components(pid: str) -> list[dict[str, Any]]:
    return STATE["memory"].list_components(pid)


@app.get("/projects/{pid}/sources")
async def project_sources(pid: str) -> list[dict[str, Any]]:
    return STATE["memory"].list_sources(pid)


@app.get("/projects/{pid}/requirements")
async def project_requirements(pid: str) -> list[dict[str, Any]]:
    return STATE["memory"].list_requirements(pid)


@app.get("/projects/{pid}/calculations")
async def project_calculations(pid: str) -> list[dict[str, Any]]:
    return STATE["memory"].list_calculations(pid)


@app.get("/projects/{pid}/verifications")
async def project_verifications(pid: str) -> list[dict[str, Any]]:
    return STATE["memory"].list_verifications(pid)


@app.get("/projects/{pid}/tasks")
async def project_tasks(pid: str) -> list[dict[str, Any]]:
    return STATE["memory"].list_tasks(pid)


@app.get("/projects/{pid}/events")
async def project_events(pid: str) -> list[dict[str, Any]]:
    return STATE["memory"].list_events(pid)


@app.get("/projects/{pid}/versions")
async def project_versions(pid: str) -> list[dict[str, Any]]:
    return STATE["memory"].list_versions(pid)


@app.get("/projects/{pid}/summary")
async def project_summary(pid: str) -> dict[str, Any]:
    """Reassemble a stored run so the console can reopen past executions."""
    mem: ProjectMemory = STATE["memory"]
    if mem.get_project(pid) is None:
        raise HTTPException(404, "project not found")
    project = mem.get_project(pid)
    reqs = mem.list_requirements(pid)
    tasks = mem.list_tasks(pid)
    verifs = mem.list_verifications(pid)
    versions = mem.list_versions(pid)
    components = mem.list_components(pid)

    power_w = None
    for c in mem.list_calculations(pid):
        if c.get("name") == "motor_sizing_from_specs":
            power_w = c.get("result")

    have = {r.get("quantity") for r in reqs if r.get("value") is not None}
    known_gaps = [d for d in ("mass", "speed") if d not in have]

    outcomes = [v.get("outcome") for v in verifs]
    all_pass = bool(verifs) and "FAIL" not in outcomes

    return {
        "project_id": pid,
        "name": project["name"],
        "description": project["description"],
        "requirements": reqs,
        "known_gaps": known_gaps,
        "power_w": power_w,
        "tasks": tasks,
        "verifications": verifs,
        "component": components[-1] if components else None,
        "versions": versions,
        "all_verifications_pass": all_pass,
    }


@app.get("/projects/{pid}/report")
async def project_report(pid: str) -> dict[str, Any]:
    from core.report import generate_report

    path = generate_report(pid, STATE["memory"], STATE["registry"])
    return {"path": path, "content": Path(path).read_text(encoding="utf-8")}


# --------------------------------------------------------------------- #
# LLM assistant (section 26): grounded strictly in stored project records.
# The model NEVER invents numbers: the prompt embeds the real requirements,
# calculations, verifications and hypotheses; anything absent stays INCONNU.
#
# Design intent: a natural-language request to DRAW/DESIGN something does not
# go to the LLM at all - it runs the real deterministic design pipeline and
# returns the AutoCAD-ready deliverables. The LLM is for questions, tools
# build the parts (rule: never claim what was not actually produced).
# --------------------------------------------------------------------- #
_DESIGN_VERBS = r"(dessin\w*|con[çc]oi\w*|conception|g[ée]n[ée]r\w*|cr[ée]\w*|fai\w*|produi\w*|fabriqu\w*)"
_CAR_RE = re.compile(r"voiture|v[ée]hicule|automobile", re.IGNORECASE)
_CAR_INTENT_RE = re.compile(
    rf"{_DESIGN_VERBS}[^.?!]{{0,60}}(voiture|v[ée]hicule|automobile)"
    rf"|(voiture|v[ée]hicule|automobile)[^.?!]{{0,40}}autocad",
    re.IGNORECASE,
)
_DESIGN_OBJECTS = r"(tracteur|machine|pi[eè]ces?|plans?|dessins?\w*|livrables?|sch[ée]ma\w*|cablage|circuit|dossier)"
DESIGN_INTENT_RE = re.compile(
    rf"{_DESIGN_VERBS}[^.?!]{{0,60}}{_DESIGN_OBJECTS}"
    rf"|{_DESIGN_OBJECTS}[^.?!]{{0,40}}autocad",
    re.IGNORECASE,
)


# --------------------------------------------------------------------- #
# AI BRIEF: the LLM prepares structured engineering instructions, the
# deterministic engines execute them (rule: LLM orients, engines compute).
# --------------------------------------------------------------------- #
from core.ai_brief import AIBrief  # noqa: E402  (type hint for _execute_brief)


@app.post("/projects/{pid}/brief")
async def project_brief(pid: str, body: dict = Body(default={})) -> dict[str, Any]:
    """AI brief: the LLM reads the cahier des charges and returns a VALIDATED
    structured brief (informations, instructions bornées, hypothèses, manque)
    that the deterministic engines can execute. Nothing is fabricated:
    unquantified info lands in missing_info, raw model answer is archived."""
    mem: ProjectMemory = STATE["memory"]
    if mem.get_project(pid) is None:
        raise HTTPException(404, "project not found")
    cdc = str(body.get("cahier_des_charges", "")).strip()
    if not cdc:
        raise HTTPException(422, "body must contain a non-empty 'cahier_des_charges'")

    gateway = STATE.get("llm_gateway")
    router = STATE.get("llm_router")
    if gateway is None or router is None:
        raise HTTPException(
            400,
            "LLM non configuré (llm.provider=mock ou clé absente dans .env). "
            "Le brief IA exige un vrai modèle; aucun brief simulé n'est produit.",
        )

    from core.ai_brief import (
        brief_assumptions,
        brief_event,
        build_brief_prompt,
        new_brief_id,
        parse_brief_response,
    )

    prompt = build_brief_prompt(cdc)
    try:
        raw = await gateway.generate(router.default, prompt, system=(
            "Tu es un ingénieur d'études. Tu analyses un cahier des charges et tu "
            "réponds UNIQUEMENT avec le JSON demandé. Tu n'inventes aucune donnée: "
            "une information absente va dans missing_info. Réponds en français."
        ))
    except Exception as exc:
        raise HTTPException(
            504,
            f"Le modèle LLM n'a pas répondu ({type(exc).__name__}). "
            "Le brief IA exige un modèle joignable; réessayez ou changez de modèle "
            "dans config.yaml (llm.model).",
        ) from None

    try:
        brief = parse_brief_response(raw)
    except ValueError as exc:
        raise HTTPException(502, f"Réponse du modèle inexploitable: {exc}") from None

    # Audit trail: archive the brief + raw answer in project memory.
    brief_id = new_brief_id()
    mem.append_event(pid, brief_event(brief, raw))
    for asm in brief_assumptions(brief):
        mem.add_assumption(pid, asm)

    # Option "execute": the engines give life to the brief immediately.
    if bool(body.get("execute")):
        try:
            executed = await _execute_brief(pid, brief)
        except ValueError as exc:
            # Le moteur d'ingénierie refuse honnêtement une combinaison
            # incohérente (ex: autonomie 3000 km avec 95 kWh).
            raise HTTPException(
                422,
                f"Brief archivé ({brief_id}) mais conception refusée par le "
                f"moteur déterministe: {exc}",
            ) from None
        executed["brief"] = {
            "brief_id": brief_id,
            "kind": brief.kind,
            "summary": brief.summary,
            "instructions": brief.clamped_instructions(),
            "warnings": brief.warnings,
            "missing_info": brief.missing_info,
        }
        return executed

    return {
        "project_id": pid,
        "brief_id": brief_id,
        "intent": "brief",
        "kind": brief.kind,
        "summary": brief.summary,
        "items": [i.model_dump() for i in brief.items],
        "instructions": brief.clamped_instructions(),
        "instructions_raw": [i.model_dump() for i in brief.instructions],
        "assumptions": brief.assumptions,
        "warnings": brief.warnings,
        "missing_info": brief.missing_info,
        "grounding": "brief structuré validé par schéma strict; paramètres bornés; "
                     "les moteurs déterministes restent les seuls à calculer",
    }


async def _execute_brief(pid: str, brief: "AIBrief") -> dict[str, Any]:
    """Donne vie au brief : traduit les instructions validées en paramètres des
    moteurs déterministes et exécute la conception correspondante."""
    from core.ai_brief import apply_brief_to_ev_scenario

    if brief.kind == "aero_car":
        kwargs: dict[str, Any] = {}
        hv_voltage = 800.0
        for ins in brief.clamped_instructions():
            if ins["target"] == "hv_voltage":
                hv_voltage = ins["value"]
        scenario_kwargs = apply_brief_to_ev_scenario(brief, {})
        if scenario_kwargs:
            kwargs["scenario"] = scenario_kwargs
        kwargs["hv_voltage"] = hv_voltage
        return await design_aero_car(pid, kwargs)
    # tractor_electrical et generic_machine -> pipeline machine (12 V).
    return await design_tractor(pid, {})


@app.post("/projects/{pid}/ask")
async def ask_project(pid: str, body: dict = Body(default={})) -> dict[str, Any]:
    """Two behaviors:
    - design request (dessine/conçois/génère...) -> runs the REAL design
      pipeline and returns the deliverables folder (3D DXF assembly, per-part
      AutoCAD files, plans, wiring CSV, ZIP);
    - any other question -> grounded LLM answer over stored project records."""
    mem: ProjectMemory = STATE["memory"]
    if mem.get_project(pid) is None:
        raise HTTPException(404, "project not found")
    question = str(body.get("question", "")).strip()
    if not question:
        raise HTTPException(422, "body must contain a non-empty 'question'")

    # ---------- design intent: DO the design, don't talk about it ---------- #
    if _CAR_INTENT_RE.search(question):
        design_result = await design_aero_car(pid, {})
        deliv = design_result["deliverables"]
        sc = design_result["scenario"]["scenario"]
        co = design_result["scenario"]["consistency"]
        answer = (
            f"Conception exécutée (moteurs déterministes, pas un discours de LLM) - "
            f"livrables dans workspace/{deliv['folder']}/ :\n"
            f"- 3D_MODELES/VOITURE_3D_ENSEMBLE.dxf : la voiture complète en 3D "
            f"(une couche par groupe, unités mm, s'ouvre dans AutoCAD) ;\n"
            f"- 3D_MODELES/PIECES/ : {deliv['parts_count']} fichiers PIECE_*.dxf ;\n"
            f"- 2D_PLANS/ : {len(design_result['drawings'])} feuilles DXF (ensemble, "
            f"chaque pièce, schéma électrique HT/BT) ;\n"
            f"- 1D_DONNEES/ : nomenclature, cablage, circuits, vérifications, index ;\n"
            f"- LIVRABLES_COMPLETS.zip : tout en un téléchargement.\n"
            f"Ingénierie : moteur {sc['motor_kw']:.0f} kW, batterie {sc['battery_kwh']:.0f} kWh, "
            f"Cd {sc['cd']}, autonomie {co['range_km']:.0f} km, réseau HV "
            f"{design_result['hv']['system_voltage']:.0f} V + LV 12 V, "
            f"masse {design_result['cad']['total_mass_kg']:.0f} kg.\n"
            f"Vérifications indépendantes : "
            + ", ".join(f"{v['subject']}={v['outcome']}" for v in design_result["verifications"])
            + f". Version créée : V{design_result['version']['number']}.\n"
            f"AUCUNE garantie de conduite: validation humaine et essais reels requis."
        )
        return {
            "project_id": pid,
            "question": question,
            "intent": "design",
            "answer": answer,
            "deliverables": deliv,
            "parts_count": len(design_result["cad"]["parts"]),
            "version": design_result["version"],
            "grounding": "conception réelle: scenario EV + réseaux HV/BT + noyau CAO "
                         "interne (aucun chiffre inventé par un LLM)",
        }

    if DESIGN_INTENT_RE.search(question):
        design_result = await design_tractor(pid, {})
        deliv = design_result["deliverables"]
        n_parts = len(design_result["cad"]["parts"])
        answer = (
            f"Conception exécutée (pas une simulation de langage) - livrables créés dans "
            f"workspace/{deliv['folder']}/ :\n"
            f"- 3D/TRACTEUR_3D_ENSEMBLE.dxf : machine complète en 3D, une couche par "
            f"groupe, unités mm -> s'ouvre directement dans AutoCAD ;\n"
            f"- 3D/PIECES/ : {deliv['parts_count']} fichiers PIECE_*.dxf, une pièce = un fichier 3D AutoCAD ;\n"
            f"- PLANS (../drawings) : {len(design_result['drawings'])} feuilles 2D DXF+SVG "
            f"(ensemble + chaque pièce + cablage) ;\n"
            f"- cablage/CABLAGE_COMPLET.csv : {len(design_result['wire_schedule'])} fils "
            f"(de -> vers, section, couleur, fusible) ;\n"
            f"- LIVRABLES_COMPLETS.zip : tout le dossier en un téléchargement.\n"
            f"Vérifications indépendantes : "
            + ", ".join(f"{v['subject']}={v['outcome']}" for v in design_result["verifications"])
            + f". Version créée : V{design_result['version']['number']}."
        )
        return {
            "project_id": pid,
            "question": question,
            "intent": "design",
            "answer": answer,
            "deliverables": deliv,
            "parts_count": n_parts,
            "version": design_result["version"],
            "grounding": "conception réelle: moteurs déterministes + noyau CAO interne "
                         "(aucun chiffre inventé par un LLM)",
        }

    # ---------- normal question: grounded LLM answer ---------- #
    gateway = STATE.get("llm_gateway")
    if gateway is None:
        raise HTTPException(400, "LLM non configuré (llm.provider=mock ou clé absente)")
    from core.report import generate_report

    report_path = generate_report(pid, mem)
    project_records = Path(report_path).read_text(encoding="utf-8", errors="replace")
    system = (
        "Tu es l'assistant d'ingénierie de la plateforme AI ENGINEER. "
        "Tu réponds UNIQUEMENT à partir des données du projet fournies. "
        "Si une information est absente, dis INCONNU. "
        "Ne recalcule rien, n'invente aucun chiffre: les calculs viennent des moteurs déterministes. "
        "Réponds en français, de façon concise et technique."
    )
    prompt = (
        f"DONNEES DU PROJET ({pid}):\n{project_records[:8000]}\n\n"
        f"QUESTION: {question}\n\n"
        "Réponds en te basant exclusivement sur les données ci-dessus, de façon concise."
    )
    router = STATE.get("llm_router")
    try:
        answer = await gateway.generate(router.default, prompt, system=system)
    except Exception as exc:  # timeout/connection: fail HONESTLY, not with a fake answer
        raise HTTPException(
            504, f"Le modèle LLM n'a pas répondu à temps ({type(exc).__name__}). "
                 "Réessayez, ou reformulez en demande de conception (ex: 'dessine...')."
        ) from None
    return {
        "project_id": pid,
        "question": question,
        "intent": "question",
        "answer": answer,
        "grounding": "rapport technique du projet (exigences, calculs, vérifications, hypothèses)",
    }


@app.get("/tools")
async def list_tools() -> list[dict[str, str]]:
    return [
        {"name": s.name, "risk": s.risk.value, "description": s.description}
        for s in STATE["registry"].list_tools()
    ]


# --------------------------------------------------------------------- #
# Tractor 3D + complete 12 V electrical circuit (Phase 4+6 groundwork)
# --------------------------------------------------------------------- #
@app.post("/projects/{pid}/tractor")
async def design_tractor(pid: str, body: dict = Body(default={})) -> dict[str, Any]:
    """Design the 3D tractor (all parts) + its complete 12 V electrical
    circuit: deterministic wire/fuse sizing, 3D harness, SVG schematic,
    independent verification, sandboxed artifact export."""
    mem: ProjectMemory = STATE["memory"]
    if mem.get_project(pid) is None:
        raise HTTPException(404, "project not found")

    from core.electrical_design import DEFAULT_CIRCUITS, CircuitSpec, ElectricalDesignEngine
    from providers.cad.provider import detect_provider
    from providers.cad.tractor import build_tractor, export_tractor
    from core.schematic import render_schematic_svg

    circuits_raw = body.get("circuits") or [
        {"name": c.name, "description": c.description, "load_w": c.load_w,
         "length_m": c.length_m, "kind": c.kind}
        for c in DEFAULT_CIRCUITS
    ]
    try:
        circuits = [CircuitSpec(**c) for c in circuits_raw]
        design = ElectricalDesignEngine(STATE["calc"]).design(
            circuits,
            system_voltage=float(body.get("system_voltage", 12.0)),
            battery_ah=float(body.get("battery_ah", 80.0)),
            alternator_max_a=float(body.get("alternator_max_a", 90.0)),
        )
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from None

    # Independent verification (recomputes with its own constants).
    verifs = await STATE["verification"].verify_electrical_design(pid, design)

    provider, cad_notes = detect_provider(STATE["config"].cad.provider)
    ok, reason = provider.availability()
    if not ok:
        raise HTTPException(503, f"CAD provider unavailable: {reason}")

    build = build_tractor(body.get("tractor_spec"))
    out_rel = f"{pid}/cad/tractor"
    registry = STATE["registry"]

    # Purge stale outputs from any previous run of this design in this project
    # (a regenerated folder must not mix old and new files).
    for sub in ("drawings", "deliverables"):
        registry.execute("clear_dir", agent="tractor_cad_engineer",
                         path=f"{out_rel}/{sub}")

    def writer(rel_path: str, data: bytes) -> dict[str, Any]:
        return registry.execute("write_file_bytes", agent="tractor_cad_engineer",
                                path=rel_path, content=data)

    cad = export_tractor(build, out_rel, writer, provider)

    svg = render_schematic_svg(design, title=f"Tracteur 12 V - projet {pid}")
    registry.execute("write_text", agent="tractor_cad_engineer",
                     path=f"{out_rel}/electrical_schematic.svg", content=svg)

    # ---------------- technical drawings (DXF + SVG previews) --------- #
    from providers.cad.drawings import write_sheet
    from providers.cad.sheets import (
        build_arrangement_sheet,
        build_part_sheet,
        build_wire_schedule,
        build_wiring_sheet,
    )

    sheets_info: list[dict[str, Any]] = []
    drawing_sheets = [build_arrangement_sheet(build)]
    # per-part sheets, with mass/material meta (like a real part drawing)
    from providers.cad.tractor import GROUP_SPECS

    density_by_group = {g: d for g, (_, _, d) in GROUP_SPECS.items()}
    drawing_sheets += [
        build_part_sheet(name, m, note, group, density_by_group.get(group))
        for name, m, (group, note) in (
            (n, build.part_meshes[n], next((p["group"], p["note"]) for p in cad["parts"] if p["name"] == n))
            for n in build.part_meshes
        )
    ]
    wiring = build_wiring_sheet(design, pid)
    drawing_sheets.append(wiring)
    for sheet in drawing_sheets:
        info = write_sheet(sheet, pid, out_rel + "/drawings", writer)
        info["note"] = sheet.notes[0] if sheet.notes else ""
        sheets_info.append(info)

    # -------- electrical schematic ALSO as a DXF sheet (AutoCAD) -------- #
    from providers.cad.sheets import build_schematic_sheet

    schematic_sheet = build_schematic_sheet(design, pid)
    sch_info = write_sheet(schematic_sheet, pid, out_rel + "/drawings", writer)
    sch_info["note"] = "Schema electrique 12 V (calques PUISSANCE/ECLAIRAGE/SIGNALISATION/COMMANDE/MASSE)"
    sheets_info.append(sch_info)

    wire_schedule = build_wire_schedule(design)

    # ------------- AutoCAD-ready deliverables folder + ZIP ------------- #
    from providers.cad.deliverables import package_deliverables

    part_sheets = drawing_sheets[:-1]   # arrangement + parts (wiring excluded)
    extra_2d = [
        (f"{out_rel}/deliverables/2D_PLANS/SCHEMA-01.dxf", "Schema electrique 12 V (calques fonctionnels)"),
        (f"{out_rel}/deliverables/2D_PLANS/CABLAGE-01.dxf", "Plan de cablage"),
    ]
    # copy schematic + wiring sheets into 2D_PLANS/
    from providers.cad.drawings import DXF_LAYERS, dxf_document, sheet_to_dxf

    writer(f"{out_rel}/deliverables/2D_PLANS/SCHEMA-01.dxf",
           dxf_document(DXF_LAYERS, sheet_to_dxf(schematic_sheet, pid)).encode("ascii", errors="replace"))
    writer(f"{out_rel}/deliverables/2D_PLANS/CABLAGE-01.dxf",
           dxf_document(DXF_LAYERS, sheet_to_dxf(wiring, pid)).encode("ascii", errors="replace"))

    verifs_json = [v.model_dump(mode="json") for v in verifs]
    deliverables = package_deliverables(
        build, wire_schedule, design, verifs_json, out_rel, pid, writer,
        registry.workspace_root, part_sheets=part_sheets, extra_2d=extra_2d,
    )
    mem.add_artifact(pid, Artifact(path=deliverables["zip"], kind="drawing",
                                   created_by="tractor_cad_engineer"))

    manifest = {
        "project_id": pid,
        "cad": cad,
        "electrical_design": design,
        "wire_schedule": wire_schedule,
        "drawings": sheets_info,
        "deliverables": deliverables,
        "verifications": verifs_json,
        "cad_notes": cad_notes,
    }
    for f in cad["files"].values():
        mem.add_artifact(pid, Artifact(path=f["path"], kind="cad",
                                       created_by="tractor_cad_engineer"))
    for s in sheets_info:
        mem.add_artifact(pid, Artifact(path=s["dxf"], kind="drawing", created_by="tractor_cad_engineer"))
    version = mem.create_version(
        pid,
        f"Tracteur 3D: {len(cad['parts'])} pieces, {len(sheets_info)} feuilles DXF/SVG, "
        f"livrables AutoCAD (ensemble 3D DXF + {deliverables['parts_count']} pieces 3D + ZIP), "
        f"masse {cad['total_mass_kg']} kg, {len(design['circuits'])} circuits 12 V",
        created_by="tractor_cad_engineer",
    )
    # Store the manifest AFTER the version exists so the stored JSON always
    # carries its version number (the console reopens this file directly).
    manifest["version"] = version
    registry.execute("write_text", agent="tractor_cad_engineer",
                     path=f"{out_rel}/tractor_build.json",
                     content=json.dumps(manifest, ensure_ascii=False, indent=2))

    mem.add_artifact(pid, Artifact(path=f"{out_rel}/tractor_build.json", kind="cad",
                                   created_by="tractor_cad_engineer"))
    await STATE["bus"].publish("CAD_CREATED", {
        "project_id": pid, "out": out_rel, "groups": sorted(cad["files"]),
        "total_mass_kg": cad["total_mass_kg"],
    })
    return {**manifest, "version": version}


@app.post("/projects/{pid}/car")
async def design_aero_car(pid: str, body: dict = Body(default={})) -> dict[str, Any]:
    """Design the hyper-aerodynamic electric car END TO END (deterministic):
    aero/powertrain scenario -> motor/battery consistency -> HV 800 V network
    + LV 12 V network -> independent verification (LV+HV) -> parametric 3D
    (teardrop Kamm body, aero wheels, 480 kW PMSM, 95 kWh pack, harnesses
    routed) -> deliverables folder (3D/2D/1D) + ZIP.

    NEVER claims the car is drivable: it is an engineering synthesis validated
    by independent checks, requiring human review before any fabrication."""
    mem: ProjectMemory = STATE["memory"]
    if mem.get_project(pid) is None:
        raise HTTPException(404, "project not found")

    from core.ev_design import design_hv_network
    from core.ev_scenario import design_ev_scenario, parametric_spec
    from providers.cad.aero_car import build_aero_car, export_aero_car
    from providers.cad.provider import detect_provider
    from core.electrical_design import ElectricalDesignEngine, CircuitSpec

    calc: CalculationEngine = STATE["calc"]
    registry = STATE["registry"]

    def writer(rel_path: str, data: bytes) -> dict[str, Any]:
        return registry.execute("write_file_bytes", agent="ev_engineer",
                                path=rel_path, content=data)

    # ---------------- 1. scenario (aero + powertrain + battery) -------- #
    try:
        scenario = design_ev_scenario(calc, **(body.get("scenario") or {}))
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from None
    if not scenario["consistency"]["motor_ok"]:
        raise HTTPException(
            422, f"INCOHERENT: required motor {scenario['consistency']['required_motor_kw']} kW "
                 f"> chosen {scenario['scenario']['motor_kw']} kW - increase motor_kw")
    if not scenario["consistency"]["range_ok"]:
        raise HTTPException(422, "INCOHERENT: battery does not reach the range target")

    # ---------------- 2. electrical: HV 800 V + LV 12 V ---------------- #
    try:
        hv = design_hv_network(calc, system_voltage=float(body.get("hv_voltage", 800.0)),
                               motor_kw=scenario["scenario"]["motor_kw"])
        lv = ElectricalDesignEngine(calc).design(
            [CircuitSpec("led_lights", "Feux LED (2x30 W)", 60.0, 3.0),
             CircuitSpec("hvac_blower", "Ventilation HVAC", 350.0, 2.5),
             CircuitSpec("infotainment", "Calculateur + ecrans", 120.0, 2.0),
             CircuitSpec("pumps_dc", "Pompes thermique + frein", 180.0, 2.2),
             CircuitSpec("lv_feed", "Alimentation boite LV", 0.0, 1.0, kind="feed"),
             CircuitSpec("dcdc_lv", "DC-DC 3 kW vers 12 V", 0.0, 1.0, kind="alternator")],
            system_voltage=12.0, battery_ah=60.0, alternator_max_a=250.0,
        )
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from None

    verifs = await STATE["verification"].verify_hv_design(pid, hv)
    verifs += await STATE["verification"].verify_electrical_design(pid, lv)

    # ---------------- 3. parametric 3D --------------------------------- #
    provider, cad_notes = detect_provider(STATE["config"].cad.provider)
    ok, reason = provider.availability()
    if not ok:
        raise HTTPException(503, f"CAD provider unavailable: {reason}")
    spec3d = parametric_spec(scenario)
    build = build_aero_car(spec3d)
    out_rel = f"{pid}/cad/car"
    for sub in ("drawings", "deliverables"):
        registry.execute("clear_dir", agent="ev_engineer", path=f"{out_rel}/{sub}")
    cad = export_aero_car(build, out_rel, writer, provider)

    # ---------------- 4. drawings (assembly + parts) ------------------- #
    from providers.cad.drawings import write_sheet
    from providers.cad.sheets import build_arrangement_sheet, build_part_sheet
    from providers.cad.tractor import GROUP_SPECS

    sheets_info: list[dict[str, Any]] = []
    density_by_group = {g: d for g, (_, _, d) in GROUP_SPECS.items()}
    part_sheets = [build_arrangement_sheet(build)]
    part_sheets += [
        build_part_sheet(name, m, note, group, density_by_group.get(group))
        for name, m, (group, note) in (
            (n, build.part_meshes[n], next((p["group"], p["note"]) for p in cad["parts"] if p["name"] == n))
            for n in build.part_meshes
        )
    ]
    for sheet in part_sheets:
        info = write_sheet(sheet, pid, out_rel + "/drawings", writer)
        info["note"] = sheet.notes[0] if sheet.notes else ""
        sheets_info.append(info)

    # ---------------- 5. deliverables (VOITURE label) ------------------ #
    from providers.cad.deliverables import package_deliverables

    wire_rows = []
    for c in lv["circuits"]:
        wire_rows.append({"id": f"LV-{c['name']}", "de": "BOITE LV", "vers": c["description"],
                          "circuit": c["name"], "a": f"{c['current_a']:.1f}",
                          "mm2": f"{c['gauge_mm2']:g}", "couleur": c["color"],
                          "fusible": f"F{c['fuse_a']:g}" if c["fuse_a"] else "-",
                          "layer": "COMMANDE"})
    for c in hv["circuits"]:
        wire_rows.append({"id": f"HV-{c['name']}", "de": "BATTERIE 800V", "vers": c["description"],
                          "circuit": c["name"], "a": f"{c['current_a']:.1f}",
                          "mm2": f"{c['gauge_mm2']:g} x{c['parallel_per_pole']}",
                          "couleur": "orange", "fusible": f"F{c['fuse_a']:g}",
                          "layer": "PUISSANCE"})

    verifs_json = [v.model_dump(mode="json") for v in verifs]
    deliverables = package_deliverables(
        build, wire_rows, {**lv, "circuits": lv["circuits"] + hv["circuits"]},
        verifs_json, out_rel, pid, writer, registry.workspace_root,
        part_sheets=part_sheets, label="VOITURE",
    )
    mem.add_artifact(pid, Artifact(path=deliverables["zip"], kind="drawing",
                                   created_by="ev_engineer"))
    for f in cad["files"].values():
        mem.add_artifact(pid, Artifact(path=f["path"], kind="cad", created_by="ev_engineer"))

    version = mem.create_version(
        pid,
        f"Voiture aero EV: {len(cad['parts'])} pieces, {len(part_sheets)} feuilles 2D, "
        f"moteur {scenario['scenario']['motor_kw']:.0f} kW, {scenario['scenario']['battery_kwh']:.0f} kWh, "
        f"Cd {scenario['scenario']['cd']}, autonomie {scenario['consistency']['range_km']:.0f} km, "
        f"HV {hv['system_voltage']:.0f} V + LV 12 V, masse {cad['total_mass_kg']:.0f} kg",
        created_by="ev_engineer",
    )
    await STATE["bus"].publish("CAD_CREATED", {
        "project_id": pid, "out": out_rel, "groups": sorted(cad["files"]),
        "total_mass_kg": cad["total_mass_kg"], "kind": "aero_car",
    })

    manifest = {
        "project_id": pid,
        "kind": "aero_car",
        "scenario": scenario,
        "hv": hv,
        "lv": lv,
        "cad": cad,
        "drawings": sheets_info,
        "deliverables": deliverables,
        "verifications": verifs_json,
        "cad_notes": cad_notes + [
            "AUCUNE garantie de conduite: synthese d'ingenierie verifiee par des "
            "controles independants; validation humaine + essais reels requis.",
        ],
        "version": version,
    }
    registry.execute("write_text", agent="ev_engineer",
                     path=f"{out_rel}/car_build.json",
                     content=json.dumps(manifest, ensure_ascii=False, indent=2))
    mem.add_artifact(pid, Artifact(path=f"{out_rel}/car_build.json", kind="cad",
                                   created_by="ev_engineer"))
    return manifest


@app.get("/projects/{pid}/car")
async def get_aero_car(pid: str) -> dict[str, Any]:
    """Reopen a stored car build (manifest, no rebuild)."""
    from pathlib import Path

    mem: ProjectMemory = STATE["memory"]
    if mem.get_project(pid) is None:
        raise HTTPException(404, "project not found")
    path = Path(STATE["config"].storage.root) / pid / "cad/car/car_build.json"
    if not path.exists():
        raise HTTPException(404, "no car build for this project")
    return json.loads(path.read_text(encoding="utf-8"))


@app.get("/projects/{pid}/tractor")
async def get_tractor(pid: str) -> dict[str, Any]:
    """Reopen a stored tractor build (manifest + schematic, no rebuild)."""
    from pathlib import Path

    mem: ProjectMemory = STATE["memory"]
    if mem.get_project(pid) is None:
        raise HTTPException(404, "project not found")
    path = Path(STATE["config"].storage.root) / pid / "cad/tractor/tractor_build.json"
    if not path.exists():
        raise HTTPException(404, "no tractor build for this project")
    return json.loads(path.read_text(encoding="utf-8"))


@app.get("/artifacts/{pid}/{rel_path:path}")
async def get_artifact(pid: str, rel_path: str) -> Response:
    """Serve workspace artifacts (STL, SVG) - strictly confined to the workspace."""
    from pathlib import Path

    root = Path(STATE["config"].storage.root).resolve()
    full = (root / pid / rel_path).resolve()
    try:
        full.relative_to(root)
    except ValueError:
        raise HTTPException(403, "path escapes the workspace - denied") from None
    if not full.exists() or not full.is_file():
        raise HTTPException(404, "artifact not found")
    media = {"stl": "model/stl", "svg": "image/svg+xml", "json": "application/json",
             "dxf": "application/dxf", "zip": "application/zip", "csv": "text/csv"}
    suffix = full.suffix.lower().lstrip(".")
    return Response(content=full.read_bytes(), media_type=media.get(suffix, "application/octet-stream"))


@app.get("/calculators")
async def list_calculators() -> list[dict[str, str]]:
    return STATE["calc"].list()


# --------------------------------------------------------------------- #
# WebSocket: live event stream
# --------------------------------------------------------------------- #
@app.websocket("/ws/events")
async def ws_events(ws: WebSocket) -> None:
    await ws.accept()
    queue: asyncio.Queue = asyncio.Queue()
    bus: EventBus = STATE["bus"]

    async def forward(kind: str, payload: dict, event: dict) -> None:
        await queue.put(event)

    kinds = (
        "PROJECT_CREATED", "REQUIREMENT_ADDED", "PLAN_CREATED", "TASK_STARTED",
        "TASK_COMPLETED", "TASK_FAILED", "CALCULATION_COMPLETED", "CAD_CREATED",
        "SEARCH_COMPLETED", "COMPONENT_SELECTED",
        "VERIFICATION_PASSED", "VERIFICATION_FAILED", "PROJECT_VALIDATED", "INFO",
    )
    for k in kinds:
        bus.subscribe(k, forward)
    try:
        while True:
            event = await queue.get()
            await ws.send_text(json.dumps(event, ensure_ascii=False))
    except WebSocketDisconnect:
        return
