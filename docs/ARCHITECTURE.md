# AI ENGINEER - Architecture (as built, Phase 1)

```
                 USER (cahier des charges)
                          |
                  FastAPI (REST + WS)          apps/api/main.py
                          |
                  ORCHESTRATOR (Master)        apps/orchestrator.py
                    |        \____________
                    v                     \
        REQUIREMENTS ENGINEER              PLAN ENGINE -> TASK ENGINE (DAG)
        (deterministic FR/EN)              (deps, retries, REQUIRES_REVIEW)
                    |                                |
                    v                                v
        SPECIALIST AGENTS (core/agents/base.py, common Agent interface)
        mechanical | electrical | research | verification | documentation
                    |
        TOOLS (ToolRegistry: whitelist, risk levels, workspace confinement)
                    |
        ENGINES (deterministic, never the LLM):
          - UnitEngine (Pint, SI normalization, incompatible => error)
          - CalculationEngine (registered calculators -> CalculationRecord)
          - RequirementsEngine (regex + SI + gap detection => INCONNU)
                    |
        VERIFICATION ENGINE (independent; recompute & FAIL agent claims)
                    |
        MEMORY (SQLite: requirements, tasks, calcs, verifications,
                assumptions, sources, artifacts, events, versions)
                    |
        ARTIFACTS (workspace/<project>/reports/technical_report.md)
```

Provider abstractions in place (implementations arrive in later phases):

- `providers/llm/gateway.py`: LLMGateway + Mock/OpenAI/Anthropic + ModelRouter
  (guardrail: refuses to send calculations to any LLM).
- Planned, same pattern: `SearchProvider`, `CADProvider` (SolidWorks bridge via
  C#/.NET COM Interop), `EDAProvider` (KiCad via kicad-cli), `SimulationProvider`
  (no engine => no simulation, period).

Key design rules as implemented:

1. Agents share one interface (execute/validate contract) and receive services
   via dependency injection (AgentContext) - no global state.
2. The Verification Engine is a separate class, not a "review prompt": it
   recomputes physics from stored records and can FAIL a design agent's claim.
3. All state changes flow through EventBus (journal + persist hook) - the event
   history is queryable per project (GET /projects/{id}/events).
4. The ToolRegistry is the only path to the filesystem; paths are confined to
   the workspace; CRITICAL/RESTRICTED tools are disabled by default.
