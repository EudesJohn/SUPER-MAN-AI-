"""LIVE web research demo (Phase 2): real DuckDuckGo search, real page fetches,
trust-scored sources, and a sourced motor shortlist for the 500 kg machine
(shaft power 306.5 W -> next standard size ~0.31 kW query).

Run:  .venv/Scripts/python examples/demo_research_live.py   (needs internet)
"""
from __future__ import annotations

import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from core.components import ComponentResearcher  # noqa: E402
from core.memory import ProjectMemory  # noqa: E402
from core.research import WebResearchEngine  # noqa: E402
from core.events import EventBus  # noqa: E402
from providers.search.fetcher import Fetcher  # noqa: E402
from providers.search.search import make_provider  # noqa: E402


async def main() -> int:
    memory = ProjectMemory("demo_research.db")
    bus = EventBus()
    provider = make_provider("duckduckgo")
    engine = WebResearchEngine(memory, bus, provider, Fetcher())
    researcher = ComponentResearcher(engine)

    print("=" * 70)
    print("AI ENGINEER - Phase 2 live demo: real web research (DuckDuckGo)")
    print("=" * 70)

    project = memory.create_project("Recherche moteur 0.31 kW", "demo live")

    # --- 1) Direct query: motor datasheets --------------------------- #
    out = await engine.research(
        project["id"], "moteur asynchrone triphasé 0.37 kW 400 V datasheet fabricant",
        max_results=8, fetch_top=4,
    )
    print(f"\n[1] Query: {out['query']}")
    print(f"    status={out['status']}  results={out.get('results_found')}  fetch_failures={len(out.get('failed_fetches', []))}")
    for s in out["sources"]:
        flag = {"high": "HIGH", "medium": "MEDIUM", "low": "LOW", "unknown": "UNKNOWN"}[s["confidence"]]
        date = s.get("date") or "date inconnue"
        kind = " (page)" if not s.get("snippet_only") else " (extrait SERP)"
        print(f"    [{flag:>7}] {date} {s['url'][:80]}{kind}")

    # --- 2) Component research: sourced motor shortlist -------------- #
    comp = await researcher.research_motor(project["id"], power_w=306.5, voltage_v=400)
    print("\n[2] Composant: moteur ~0.31 kW")
    print(f"    statut: {comp['status']}  confiance: {comp['confidence']}")
    print(f"    domaines fabricant distincts: {comp['manufacturer_domains']}")
    print(f"    note: {comp['note']}")
    for c in comp["candidates"][:6]:
        brand = c["brand"] or "?"
        print(f"    - [{c['source_confidence']:>7}] {brand:<14} {c['url'][:70]}")

    print("\nSources et composant persistes dans la memoire du projet.")
    memory.close()
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
