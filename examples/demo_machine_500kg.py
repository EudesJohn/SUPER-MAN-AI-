"""End-to-end demo: cahier des charges -> verified engineering project.

Run:  .venv/Scripts/python examples/demo_machine_500kg.py
Everything runs offline; no SolidWorks/KiCad/LLM keys required.
"""
from __future__ import annotations

import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from apps.orchestrator import Orchestrator  # noqa: E402
from core.calculation import CalculationEngine  # noqa: E402
from core.events import EventBus  # noqa: E402
from core.memory import ProjectMemory  # noqa: E402
from core.tools import ToolRegistry, make_file_tools  # noqa: E402
from core.verification import VerificationEngine  # noqa: E402

SPEC = (
    "Je veux concevoir une machine industrielle capable de transporter 500 kg "
    "a 20 m/min, fonctionnant sous 400 V triphase, avec arret d'urgence, "
    "capteurs de position, automate programmable et interface operateur."
)


async def main() -> None:
    memory = ProjectMemory("ai_engineer.db")
    bus = EventBus()
    calc = CalculationEngine.default_engine(bus)

    async def print_events(kind: str, payload: dict, event: dict) -> None:
        print(f"  [event] {kind}: {payload}")

    for k in ("PROJECT_CREATED", "REQUIREMENT_ADDED", "PLAN_CREATED", "TASK_STARTED",
              "TASK_COMPLETED", "CALCULATION_COMPLETED", "VERIFICATION_PASSED",
              "VERIFICATION_FAILED", "PROJECT_VALIDATED"):
        bus.subscribe(k, print_events)

    workspace = Path("workspace")
    workspace.mkdir(exist_ok=True)
    registry = ToolRegistry(workspace)
    make_file_tools(registry)
    verification = VerificationEngine(memory, bus)
    orch = Orchestrator(memory, bus, calc, registry, verification)

    print("=" * 70)
    print("AI ENGINEER - MVP demo (offline)")
    print("=" * 70)
    print(f"Cahier des charges:\n  {SPEC}\n")

    project = await orch.create_project("Machine transport 500 kg", SPEC)
    result = await orch.execute(project["id"], SPEC)

    print("\n--- RESULT ---")
    print(f"Project: {result['project_id']}")
    print(f"Requirements: {len(result['requirements'])} extracted")
    for r in result["requirements"]:
        print(f"  - {r['id']}: {r['description']}")
    print(f"Known gaps (INCONNU): {result['known_gaps'] or 'none'}")
    if result["power_w"] is not None:
        print(f"Shaft power (deterministic): {result['power_w']:.1f} W")

    print("\nTasks:")
    for t in result["tasks"]:
        print(f"  [{t['status']:>16}] {t['agent']:<24} {t['title']}")

    print("\nVerifications:")
    for v in result["verifications"]:
        print(f"  [{v['outcome']:>7}] {v['subject']}: {v['detail'][:110]}")

    print(f"\nVersion: V{result['version']['number']} - {result['version']['summary']}")
    print(f"All verifications pass: {result['all_verifications_pass']}")
    print("\nReport generated under workspace/<project_id>/reports/technical_report.md")
    print("WARNING: human validation required before any fabrication (see report).")

    memory.close()


if __name__ == "__main__":
    asyncio.run(main())
