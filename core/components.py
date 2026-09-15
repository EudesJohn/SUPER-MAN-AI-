"""Component research: candidates must be grounded in real sources.

Rule (spec section 7): an important technical decision must be traceable to
sources. A motor is only considered SOURCED with >= 2 distinct manufacturer
(HIGH trust) sources. Otherwise the component record stays explicitly
INSUFFICIENT_SOURCES / INCONNU - never presented as a validated selection.
"""
from __future__ import annotations

import re
from urllib.parse import urlparse

from providers.search.trust import trust_for_url
from core.models import Confidence, new_id, utc_now_iso

MOTOR_BRANDS = (
    "sew", "nord", "lenze", "abb", "siemens", "weg", "bonfiglioli", "motovario",
    "bauer", "boschrexroth", "leroy-somer", "nidec", "regalrexnord", "vemat",
    "sicmemotori", "yaskawa", "mitsubishi", "rockwell",
)

_KW_RE = re.compile(r"(\d+(?:[.,]\d+)?)\s*k\s*w\b", re.IGNORECASE)


class ComponentResearcher:
    def __init__(self, research_engine) -> None:
        self.engine = research_engine
        self.memory = research_engine.memory
        self.bus = research_engine.bus

    async def research_motor(
        self,
        project_id: str,
        power_w: float,
        voltage_v: float | None = None,
        *,
        max_results: int = 8,
        fetch_top: int = 2,
    ) -> dict:
        """Search real motor sources for the required shaft power and build a
        traceable shortlist. No catalog number is claimed without sources."""
        kw = power_w / 1000.0
        query = f"moteur asynchrone triphasé {kw:.2f} kW fabricant datasheet"
        if voltage_v:
            query += f" {int(voltage_v)} V"

        research = await self.engine.research(
            project_id, query, max_results=max_results, fetch_top=fetch_top
        )
        sources = research.get("sources", [])

        # Build candidates from retrieved sources only.
        candidates: list[dict] = []
        manufacturer_urls: set[str] = set()
        for s in sources:
            url = s.get("url", "")
            conf = Confidence(s.get("confidence", "unknown"))
            text = f"{s.get('title', '')} {s.get('excerpt', '')}".lower()
            brand = next((b for b in MOTOR_BRANDS if b in url.lower() or b in text), None)
            m = _KW_RE.search(text)
            candidates.append(
                {
                    "title": s.get("title"),
                    "url": url,
                    "brand": brand,
                    "claimed_power_kW": float(m.group(1).replace(",", ".")) if m else None,
                    "source_confidence": conf.value,
                    "date": s.get("date"),
                }
            )
            if conf == Confidence.HIGH:
                manufacturer_urls.add(urlparse(url).netloc)

        n_manufacturers = len(manufacturer_urls)
        if n_manufacturers >= 2:
            status = "SOURCED"
            confidence = 0.8
            note = (
                f"{n_manufacturers} distinct manufacturer domains found; "
                "catalog references must still be confirmed against datasheets."
            )
        elif sources:
            status = "INSUFFICIENT_SOURCES"
            confidence = 0.0
            note = (
                f"Only {n_manufacturers} manufacturer domain(s) - requirement is >= 2. "
                "Selection remains UNKNOWN."
            )
        else:
            status = "INCONNU"
            confidence = 0.0
            note = "No sources retrieved - component stays INCONNU."

        component = {
            "id": new_id("COMP"),
            "type": "motor",
            "requirement": f"shaft power ≈ {kw:.2f} kW",
            "status": status,
            "confidence": confidence,
            "note": note,
            "candidates": candidates,
            "manufacturer_domains": sorted(manufacturer_urls),
            "sources": [s.get("url") for s in sources],
            "created_at": utc_now_iso(),
        }
        self.memory.add_component(project_id, component)
        await self.bus.publish(
            "COMPONENT_SELECTED",
            {"project_id": project_id, "component_id": component["id"], "status": status,
             "power_kW": round(kw, 2), "manufacturer_domains": len(manufacturer_urls)},
        )
        return component
