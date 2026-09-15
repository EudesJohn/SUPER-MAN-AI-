# SUPER-MAN-AI (AI ENGINEER)

Agentic engineering platform: transforms a cahier des charges into a structured,
verified, traceable engineering project. **The AI briefs, deterministic engines
compute, the Verification Engine checks, everything is traced.**

> **Nouveau — Brief IA (`POST /projects/{id}/brief`)** : le LLM lit le cahier
> des charges et produit un brief structuré VALIDÉ (informations, instructions
> bornées par schéma strict, hypothèses, informations manquantes). Avec
> `"execute": true`, les moteurs déterministes donnent vie au projet
> immédiatement. Le LLM oriente, il ne calcule jamais : une instruction hors
> bornes ou sur une cible inconnue est rejetée, et les moteurs appliquent
> ensuite leurs propres règles physiques (fusibilité, chute de tension, etc.).

> **Honest status (functional):** requirements extraction, planning, task DAG,
> deterministic engineering calculations (bearing life, transmissions,
> deflection, voltage drop), independent verification, SQLite memory with
> event sourcing, versioning, Markdown reports, REST + WebSocket API, React
> console, REAL web research with trust-scored sources, PLUS: parametric 3D
> CAD (internal mesh kernel -> binary STL, mass properties), a complete 12 V
> electrical design flow (wire/fuse sizing, voltage-drop checks, SVG schematic,
> 3D wire harness) demonstrated on a full tractor with 38 parts, **3D DXF export
> (AutoCAD-native 3DFACE, mm)** and an **AutoCAD-ready deliverables folder**
> (3D assembly + per-part 3D DXF files + 2D sheets + wiring CSV + ZIP). A
> natural-language design request via `/ask` ("dessine un tracteur...") runs the
> real pipeline and produces the folder. Runs offline (LLM optional).
> NOT yet included: SolidWorks, KiCad, STEP export (needs CadQuery/OpenCASCADE),
> vision, physical simulation.
> See `docs/ROADMAP.md`.

## What is REAL today (no simulation, no fakery)

| Capability | Implementation | Verified by |
|---|---|---|
| Unit engine (SI normalization) | Pint, case-insensitive aliases, incompatible units rejected | `tests/test_core.py` |
| Requirements extraction (FR/EN) | Deterministic regex scanning, SI-normalized, qualitative flags | `tests/test_core.py` |
| Calculation engine | Registered deterministic calculators, every run stored as a record (formula → inputs → units → result → hypotheses) | `tests/test_core.py` |
| Plan / Task engine | DAG with dependencies, retries, REQUIRES_REVIEW after max retries | `tests/test_workflow.py` |
| Verification Engine | Independent; recomputes shaft bending and can FAIL an agent's claim (the spec's 20 mm counter-example) | `tests/test_workflow.py` |
| Tool registry / sandbox | Whitelist, risk levels, workspace confinement (`../` denied, CRITICAL disabled) | `tests/test_core.py` |
| Memory | SQLite: projects, requirements, tasks, calculations, verifications, assumptions, sources, artifacts, events, versions | integration tests |
| Event sourcing | Every event journaled and persisted; WebSocket streaming | `tests/test_workflow.py` |
| Versioning | V1, V2, ... with summaries per run | integration tests |
| LLM abstraction | Gateway + Mock/OpenAI/Anthropic providers + ModelRouter guardrail (refuses to route calculations to LLM) | design + config |
| Reports | Markdown from stored records only; missing data shown as INCONNU; human-validation warning | demo |
| Calculators (extended) | Bearing L10 (ball + roller), belt length/speed/ratio, chain pitches, rectangular inertia, cantilever & simply-supported deflection, voltage drop (mono/tri) + % | `tests/test_calculators_extended.py` (hand-computed references) |
| Frontend console | React 18 + TypeScript (strict, `tsc` clean build), Vite proxy, typed API client, WebSocket hook with auto-reconnect | `npm run build` + `scripts/ws_smoke.py` (8 live events received) |
| Web research (Phase 2) | `SearchProvider` abstraction (Null/DuckDuckGo keyless/Serper), polite fetcher (rate-limit, size cap, date extraction), domain trust scoring (fabricant HIGH / distributeur MEDIUM / forum LOW), sourced component records with the >=2 manufacturer rule | `tests/test_research.py` + live demo `examples/demo_research_live.py` |
| 3D CAD (internal kernel) | Closed-mesh primitives (box/cylinder/torus/sphere/tube), 4x4 transforms, volume verified by signed-tetrahedron sum, binary STL export/import, mass properties (volume/mass/CoM), thin-shell mass model (area x thickness for panels) | `tests/test_tractor.py` + `tests/test_aero_car.py` (analytic references) |
| Hyper-aero EV car | Full deterministic EV engineering: aero scenario (Cd 0.19, drag/power/accel), motor margin check, battery pack from range target, HV 800 V network (parallel conductors per pole, fuse-feasibility, IT isolation), LV 12 V network, 3D teardrop-Kamm body (shell panels, hollow box rails, 32 parts, 1 543 kg), HV+LV harnesses routed, 33 2D sheets, AutoCAD deliverables (3D_MODELES/2D_PLANS/1D_DONNEES) | `tests/test_aero_car.py` (14 tests incl. mass-plausibility regression guard + HV FAIL counter-example) |
| CAD provider abstraction | `CADProvider` + `MeshCadProvider` (STL); STEP honestly refused while OpenCASCADE is absent | `providers/cad/provider.py` |
| Parametric tractor | 38 parts: chassis, axles, 4 wheels, engine, hood, cabin, glazing, seat, tank, PTO, drawbar... exported as 7 color-group STL files; ~6.9 t mass from explicit material densities | `examples/demo_tractor.py` (14 908 triangles) |
| Electrical design engine (12 V) | Deterministic wire gauge (capacity >= 1.25·I AND ΔU <= 3%), standard fuses (>= 1.35·I, starter solenoid convention), feed aggregation, all drops via CalculationEngine records | `tests/test_tractor.py` |
| Electrical schematic | Deterministic SVG (battery, alternator, starter, fuse box, colored wires, ground bus, legend, title block with À-VÉRIFIER marker) | `core/schematic.py` + demo |
| Independent electrical verification | Recomputes currents/drops with its OWN constants (rho, capacity table) and FAILs unfused/undersized designs (deliberate counter-example test) | `tests/test_tractor.py` |
| 3D wire harness | Battery/alternator/starter/fuse-box/headlights/taillights/horn/dash/ECU + ground straps routed as real tube meshes inside the tractor | `tests/test_tractor.py` (>= 12 wires) |
| Technical drawings (DXF) | 36 sheets: assembly (3 views + overall dims), one per part, wiring sheet; DXF R12 with AutoCAD layers/colors + SVG preview of the same sheets; views are true hidden-line projections of the meshes | `tests/test_tractor.py` (DXF round-trip, dims values) |
| Wire schedule | Terminal-to-terminal schedule (id, from, to, mm², color, fuse, A) derived from the design; rendered in console + CABLAGE sheet | `tests/test_tractor.py` |
| Power balance + cranking checks | Alternator continuous output vs steady-state loads (FAIL counter-example tested); battery CCA ~ 4×Ah vs starter draw (FAIL counter-example tested) | `tests/test_tractor.py` |
| 3D viewer in console | three.js STL viewer with orbit/zoom, group visibility toggles (hide the hood to see the circuit) | `scripts/ui_smoke.py` check 11-12 |
| LLM assistant (NVIDIA) | `NVIDIAProvider` (OpenAI-compatible NIM endpoint) behind `LLMGateway`/`ModelRouter`; key in git-ignored `.env`; `POST /projects/{id}/ask` answers STRICTLY from stored project records (INCONNU if absent, never invented); console panel | `tests/test_llm.py` (offline via MockTransport) + live call verified |
| 3D DXF (AutoCAD-native 3D) | Mesh triangles exported as 3DFACE entities, units mm, one layer per group/part with AutoCAD colors; R12 pure-ASCII; round-trip reader | `tests/test_deliverables.py` |
| AutoCAD-ready deliverables | One folder per project: `3D/TRACTEUR_3D_ENSEMBLE.dxf` (whole machine, 3D), `3D/PIECES/PIECE_*.dxf` (each part alone, 3D), 2D sheets, `cablage/CABLAGE_COMPLET.csv`, `LISEZ-MOI.txt`, `LIVRABLES_COMPLETS.zip`; served via confined `/artifacts/{pid}/...` | `tests/test_deliverables.py` + live run (34 parts, 14 908 3DFACE) |
| Design intent via /ask | A natural-language request ("dessine/conçois/génère ... tracteur/pièces/plans/autocad") does NOT go to the LLM: it runs the real deterministic design pipeline and returns the deliverables; only plain questions reach the LLM | `tests/test_deliverables.py::test_design_intent_regex` + live run |

Core rule enforced everywhere: **INCONNU** stays unknown, **HYPOTHÈSE** is
labeled on every assumption, results are computed by code (not generated), and
nothing is claimed verified unless the Verification Engine ran.

## Installation (votre PC, votre clé API)

Prérequis : Python 3.12+, Node.js 18+. Aucune clé n'est fournie : chacun met
la sienne dans `.env` (jamais commitée).

```bash
git clone https://github.com/EudesJohn/SUPER-MAN-AI-.git
cd SUPER-MAN-AI-

# 1) Backend Python
python -m venv .venv
.venv/Scripts/pip install pydantic pint fastapi "uvicorn[standard]" pyyaml pytest pytest-asyncio httpx numpy sympy structlog

# 2) Votre clé API (NVIDIA NIM recommandé, gratuit sur build.nvidia.com)
copy .env.example .env        # puis éditez .env : NVIDIA_API_KEY=nvapi-...

# 3) Modèle LLM dans config.yaml (section llm.model)
#    La liste des modèles vivants évolue : GET https://integrate.api.nvidia.com/v1/models

# 4) Frontend (second terminal)
cd frontend && npm install && npm run dev

# 5) Lancer le backend
.venv/Scripts/python -m uvicorn apps.api.main:app --reload
# Console : http://localhost:5173   API : http://127.0.0.1:8000/docs
```

Sans clé API, tout fonctionne hors ligne (moteurs déterministes, CAO 3D,
livrables AutoCAD, vérifications) — seuls le brief IA et les réponses du
chat LLM sont désactivés, avec un message honnête.

### Essayer le Brief IA

```bash
curl -X POST http://127.0.0.1:8000/projects/PRJ-xxx/brief \
  -H "Content-Type: application/json" \
  -d '{"cahier_des_charges":"voiture electrique 700 km d autonomie, reseau 800 V","execute":true}'
```

Réponse : brief validé (kind, instructions bornées, hypothèses, missing_info)
+ conception exécutée par les moteurs (scénario EV, réseaux HT/BT, CAO 3D,
vérifications indépendantes, livrables AutoCAD).

## Démos rapides

```bash
.venv/Scripts/python examples/demo_machine_500kg.py
.venv/Scripts/python examples/demo_tractor.py   # tracteur 3D + circuit 12 V complet

# Tests
.venv/Scripts/python -m pytest tests/ -v
```

The console (frontend/) shows the cahier des charges editor, extracted
requirements, task statuses, verification outcomes, the technical report, a
live event feed over WebSocket (auto-reconnect), the project history (reopen
past runs), and the **Tracteur 3D** panel: three.js viewer (orbit/zoom, hide
the hood to see the harness), electrical sizing table, generated schematic and
independent verification badges.

Example cahier des charges used by the demo:

> Je veux concevoir une machine industrielle capable de transporter 500 kg a
> 20 m/min, fonctionnant sous 400 V triphase, avec arret d'urgence, capteurs de
> position, automate programmable et interface operateur.

Demo output: 8 requirements extracted (SI-normalized), shaft power
**306.5 W** (`P = (m·g·μ + m·a)·v / η`, hypotheses labeled), traction force
**735.5 N**, pulley speed **31.8 rpm** (Ø 200 mm hypothesis), line current,
coverage verification PASS, report + V1.

## API (MVP contract)

```
GET  /health
POST /projects                      {name, description}
GET  /projects
GET  /projects/{id}
POST /projects/{id}/execute         {cahier_des_charges}
GET  /projects/{id}/requirements | /calculations | /verifications
GET  /projects/{id}/tasks | /events | /versions | /report
GET  /projects/{id}/sources | /components
POST /projects/{id}/research         {query, max_results}
POST /projects/{id}/tractor          design 3D machine + 12 V circuit + deliverables
GET  /projects/{id}/tractor          reopen stored build (manifest)
POST /projects/{id}/car              design hyper-aero EV (800 V HV + 12 V LV) + 3D
POST /projects/{id}/brief            {cahier_des_charges, execute?} -> AI brief
                                     (LLM structuré, validé) + exécution moteurs
GET  /artifacts/{pid}/{path}         download STL / DXF (2D+3D) / SVG / ZIP / CSV
POST /projects/{id}/ask             {question} -> design intent runs the pipeline,
                                    otherwise grounded LLM answer
GET  /tools | /calculators
WS   /ws/events                     live event stream
```

## Project layout

```
apps/          API (FastAPI) + Orchestrator (Master Engineer)
core/          kernel: models, events, config, units, calculation,
               requirements, planning, tools, verification, report, agents/
providers/     llm/ (gateway + providers)  [search/cad/eda/simulation: next phases]
frontend/      React + TypeScript console (live WS event feed)
scripts/       ws_smoke.py (end-to-end WebSocket verification)
tests/         unit + integration (offline, deterministic)
examples/      end-to-end demo
docs/          ENVIRONMENT, ARCHITECTURE, ROADMAP
config.yaml    central configuration (llm, search, cad, eda, db, execution, security)
```

## License

MIT — voir [LICENSE](LICENSE). Les livrables d'ingénierie générés restent
soumis à validation humaine qualifiée avant fabrication (note dans LICENSE
et avertissements intégrés).

## Principles (non-negotiable)

1. The LLM never performs a calculation a deterministic engine can do.
2. Never claim a simulation/integration that did not actually run.
3. Unknown information stays INCONNU; assumptions are labeled HYPOTHÈSE.
4. Every external claim needs a SOURCE; every result needs verification.
5. Agents never touch the OS directly - only whitelisted, confined tools.
6. Human and/or regulatory validation is required before fabrication.
