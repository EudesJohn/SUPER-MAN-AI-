# Roadmap (phased, each phase keeps the app functional)

## LLM - DONE (NVIDIA NIM connected)
- DONE: `NVIDIAProvider` behind the `LLMGateway` abstraction (config `llm.provider: nvidia`), key loaded from git-ignored `.env` (never in code), model verified live against the account's callable list (`z-ai/glm-5.3-flash`; reasoning model -> generous read timeout 240 s, max_tokens 1024).
- Grounded Q&A: `POST /projects/{id}/ask` embeds the project's stored report (requirements, calculations, verifications, hypotheses) into the prompt; the model answers ONLY from those records and says INCONNU when absent - it never invents numbers and never performs calculations (ModelRouter guardrail).
- Console: Assistant IA panel on any project. Tests: 9 offline (MockTransport, JSON fences, honest degradation without key, /ask grounded + 400 without LLM).


## Phase 1 - DONE in this session (MVP core, offline)
Kernel, unit engine, calculation engine, requirements engine, plan/task DAG,
tool registry + sandbox, verification engine (with the spec's shaft
counter-example), SQLite memory, event sourcing, versioning, Markdown
reports, REST + WebSocket API, 20 passing tests, end-to-end demo.

## Phase 2 - Web Research Engine - DONE (first version)
- DONE: `SearchProvider` abstraction (Null / DuckDuckGo keyless / Serper via API key), polite fetcher (per-host rate limiting, size cap, meta/date extraction, checksum), domain trust scoring (manufacturer HIGH, distributor MEDIUM, forum LOW, else UNKNOWN), `WebResearchEngine` pipeline (search -> dedupe -> fetch -> trust -> persist -> events), `ComponentResearcher` with the >=2 distinct manufacturer domains rule (else INSUFFICIENT_SOURCES/UNKNOWN), `sources` + `components` tables, API endpoints `POST /projects/{id}/research`, `GET /projects/{id}/sources|components`.
- Verified live: real DuckDuckGo motor search returned Leroy-Somer + ABB (HIGH), distributors (MEDIUM/UNKNOWN), 4 dead links honestly reported; motor ~0.31 kW classified SOURCED with 2 manufacturer domains.
- Remaining for later: PDF datasheet parsing, reranking, LocalDocumentProvider (user files), date-confidence adjustments.

## Phase 3 - Calculation Engine expansion - DONE (first version)
- DONE: belt/chain transmissions, bearing life (L10 ball + roller), rectangular inertia, cantilever & simply-supported deflection, voltage drop (mono/tri) + %.
- Remaining: key shear, thermal duty, short-circuit current, material property tables with source labeling.
- Acceptance met: every calculator has a unit test against a hand-computed reference value.

## Phase 4 - CAD - PARTIALLY DONE (internal kernel; SolidWorks requires license)
- DONE: `CADProvider` abstraction; `MeshCadProvider` (numpy closed-mesh kernel: primitives, transforms, binary STL, volume/mass/CoM); parametric **tractor** (38 parts, 7 STL groups incl. routed 3D harness); **technical drawings: 36 DXF+SVG sheets** (assembly + every part + wiring) with true orthographic projections, hidden-line removal, overall dimensions, standard scales, title blocks; sandboxed artifact export; `/projects/{id}/tractor` + confined `/artifacts/{pid}/...` endpoints; three.js viewer + drawings table in the console.
- Honest limits: DXF is R12 (LINE/TEXT/CIRCLE/ARC - opens in AutoCAD/QCAD/LibreCAD); STEP/IGES refused until CadQuery/OpenCASCADE is installed; SolidWorks provider reports NOT_AVAILABLE (no .NET SDK / no SolidWorks on this machine) - never simulated.
- DONE (AutoCAD deliverables): **3D DXF export** (`dxf3d.py`: mesh triangles as 3DFACE, units mm, one layer per group/part with AutoCAD colors, round-trip reader) and the **deliverables folder** (`deliverables.py`): `3D/TRACTEUR_3D_ENSEMBLE.dxf` (whole machine, opens in AutoCAD as 3D), `3D/PIECES/PIECE_*.dxf` (one 3D file per part), wiring CSV, README, `LIVRABLES_COMPLETS.zip`. `/ask` detects design intent ("dessine un tracteur...") and runs the REAL pipeline (LLM never used for design). Verified live: 34 part files, 14 908 3DFACE in the assembly, ZIP 37 entries, downloads 200.
- Remaining: CadQuery adapter for STEP, GD&T tolerances, section views, hatching.

## Phase 5 - Vision
- OpenCV pipeline for drawings (line/circle detection, OCR via tesseract), outputs marked UNCERTAIN when ambiguous.

## Phase 6 - Electrical + Automation - PARTIALLY DONE (12 V machine harness)
- DONE: deterministic 12 V design engine (wire gauge via capacity + ΔU <= 3%, standard fuses >= 1.35·I, feed aggregation, starter convention), SVG schematic generator, independent electrical verification (6 rules incl. power balance and battery cranking - FAIL counter-examples tested), **terminal-to-terminal wire schedule**, 3D harness routing, console display.
- Remaining: IEC symbol library, 400 V three-phase power circuits + armoire, cable schedule export, Grafcet/SFC -> structured text.

## Phase 6bis - Hyper-aero EV car (DONE, extension of 6)
- EV scenario engine (aero drag/power, acceleration, motor margin, battery/range) - all CalculationEngine records
- HV 800 V network: parallel-conductor sizing, fuse-feasibility rule, IT isolation; independent HV verification (IT isolation, capacity, drop, fusing) with FAIL counter-example
- Parametric 3D: teardrop+Kamm body (lathe), aero wheels, box-section rails, pack in floor, HV/LV harnesses; SHELL mass model for panels (mass plausibility regression test)
- API POST/GET /projects/{id}/car, natural-language routing ("dessine une voiture..."), console panel with 3D viewer + HV/LV tables + deliverables

## Phase 7 - Electronics
- Component selection with datasheet-grounded constraints (Phase 2 sources), analog/digital calculators, BOM with availability.

## Phase 8 - KiCad / PCB
- `KiCadProvider` via `kicad-cli` + s-expression generation: schematic, footprints, PCB, DRC/ERC loops, Gerbers. Never claim a routed PCB is functional.

## Phase 9 - Simulation
- Providers only where a real engine exists (e.g. CalculiX for FEA, NGSpice for circuits); otherwise results are UNKNOWN.

## Phase 10 - Multi-agent verification at scale
- Requirement traceability graph (REQ -> calc -> CAD -> verification), design graph, cross-domain consistency rules.

## Phase 11 - Frontend + autonomy levels - PARTIALLY DONE
- DONE (first version): React/TS console - cahier des charges editor, requirements, tasks, verifications, report view, live WebSocket event feed with auto-reconnect, **project history with reopen**, **Tracteur 3D panel** (three.js STL viewer, visibility toggles, electrical table, schematic, verification badges). UI validated in real Chrome (`scripts/ui_smoke.py`, 12 checks).
- Remaining: approval gates for assisted/supervised/autonomous execution modes.
