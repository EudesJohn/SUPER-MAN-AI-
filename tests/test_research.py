"""Phase 2 tests: search providers, trust scoring, research pipeline,
component sourcing rules. All offline (fake provider/fetcher, canned HTML)."""
from __future__ import annotations

import pytest

from core.models import Confidence
from providers.search.search import DuckDuckGoProvider, NullProvider, SearchError, SearchResult, make_provider
from providers.search.trust import trust_for_url


# --------------------------------------------------------------------- #
# Trust scoring
# --------------------------------------------------------------------- #
def test_trust_manufacturer_is_high():
    assert trust_for_url("https://www.sew-eurodrive.fr/products/motor.html") == Confidence.HIGH
    assert trust_for_url("https://www.nord.com/en/products/") == Confidence.HIGH


def test_trust_distributor_is_medium():
    assert trust_for_url("https://fr.rs-online.com/web/p/moteurs/") == Confidence.MEDIUM
    assert trust_for_url("https://www.digikey.fr/en/products/") == Confidence.MEDIUM


def test_trust_forum_is_low():
    assert trust_for_url("https://www.reddit.com/r/engineering/comments/abc") == Confidence.LOW
    assert trust_for_url("https://fr.wikipedia.org/wiki/Moteur") == Confidence.LOW


def test_trust_unknown_domain():
    assert trust_for_url("https://www.mystery-blog.example.com/motors") == Confidence.UNKNOWN


# --------------------------------------------------------------------- #
# Providers
# --------------------------------------------------------------------- #
def test_null_provider_raises_never_fabricates():
    with pytest.raises(SearchError):
        NullProvider().search("moteur 0.5 kW")


def test_factory_known_and_unknown():
    assert isinstance(make_provider("null"), NullProvider)
    with pytest.raises(ValueError):
        make_provider("bogus")


DDG_HTML = """
<html><body>
<div class="result">
  <a class="result__a" href="//duckduckgo.com/l/?uddg=https%3A%2F%2Fwww.sew-eurodrive.fr%2Fmoteurs&amp;rut=abc">
   Moteurs asynchrones SEW-EURODRIVE
  </a>
  <div class="result__snippet">Catalogue moteurs 0.55 kW 400 V triphasé</div>
</div>
<div class="result">
  <a class="result__a" href="https://fr.rs-online.com/web/p/moteurs/">Moteurs chez RS</a>
  <div class="result__snippet">Moteur asynchrone 0.55 kW</div>
</div>
</body></html>
"""


def test_ddg_parse_extracts_and_unwraps_urls():
    results = DuckDuckGoProvider.parse_html(DDG_HTML, max_results=5)
    assert len(results) == 2
    assert results[0].url == "https://www.sew-eurodrive.fr/moteurs"
    assert results[1].url == "https://fr.rs-online.com/web/p/moteurs/"
    assert "0.55 kW" in results[0].snippet


# --------------------------------------------------------------------- #
# Research pipeline with a fake provider
# --------------------------------------------------------------------- #
class FakeProvider:
    name = "fake"

    def __init__(self, urls: list[str]) -> None:
        self.urls = urls

    def search(self, query: str, max_results: int = 8) -> list[SearchResult]:
        return [SearchResult(f"Result {i}", u, "moteur 0.31 kW datasheet", engine="fake")
                for i, u in enumerate(self.urls)]


class FakeFetcher:
    """Returns canned pages without network access."""

    class Page:
        def __init__(self, url: str) -> None:
            self.url = self.final_url = url
            self.status = 200
            self.title = f"Page {url}"
            self.text = "moteur asynchrone 0.31 kW 400 V triphasé"
            self.published_date = "2024-03-01"
            self.fetched_at = "2026-09-11T00:00:00Z"
            self.checksum = "deadbeef"
            self.bytes = 1234

    def __init__(self, reachable: set[str]) -> None:
        self.reachable = reachable

    async def fetch(self, url, client=None):
        if url in self.reachable:
            return FakeFetcher.Page(url)
        raise ConnectionError(f"unreachable: {url}")


@pytest.mark.asyncio
async def test_research_pipeline_persists_sources(memory, bus):
    from core.research import WebResearchEngine
    from providers.search.fetcher import Fetcher  # noqa: F401 - import check

    urls = [
        "https://www.sew-eurodrive.fr/moteurs",
        "https://www.nord.com/moteurs",
        "https://www.reddit.com/r/engineering/abc",
    ]
    engine = WebResearchEngine(memory, bus, FakeProvider(urls), FakeFetcher(set(urls)))
    out = await engine.research("PRJ-test", "moteur 0.31 kW", fetch_top=4)

    assert out["status"] == "ok"
    assert len(out["sources"]) == 3
    confs = {s["url"]: s["confidence"] for s in out["sources"]}
    assert confs["https://www.sew-eurodrive.fr/moteurs"] == "high"
    assert confs["https://www.nord.com/moteurs"] == "high"
    assert confs["https://www.reddit.com/r/engineering/abc"] == "low"
    # Sources persisted in memory
    assert len(memory.list_sources("PRJ-test")) == 3
    # Event emitted
    kinds = [e["kind"] for e in bus.journal]
    assert "SEARCH_COMPLETED" in kinds


@pytest.mark.asyncio
async def test_research_pipeline_provider_failure_is_honest(memory, bus):
    from core.research import WebResearchEngine

    engine = WebResearchEngine(memory, bus, NullProvider(), FakeFetcher(set()))
    out = await engine.research("PRJ-test", "query")
    assert out["status"] == "failed"
    assert out["sources"] == []


# --------------------------------------------------------------------- #
# Component sourcing rules
# --------------------------------------------------------------------- #
@pytest.mark.asyncio
async def test_component_sourced_with_two_manufacturers(memory, bus):
    from core.components import ComponentResearcher
    from core.research import WebResearchEngine

    urls = [
        "https://www.sew-eurodrive.fr/datasheet-moteur",
        "https://www.nord.com/fr/moteur-031kw",
        "https://fr.rs-online.com/moteur",
    ]
    engine = WebResearchEngine(memory, bus, FakeProvider(urls), FakeFetcher(set(urls)))
    researcher = ComponentResearcher(engine)
    comp = await researcher.research_motor("PRJ-test", power_w=306.5, voltage_v=400)

    assert comp["status"] == "SOURCED"
    assert len(comp["manufacturer_domains"]) >= 2
    assert comp["confidence"] > 0
    assert memory.list_components("PRJ-test")[0]["status"] == "SOURCED"


@pytest.mark.asyncio
async def test_component_unknown_with_insufficient_manufacturers(memory, bus):
    from core.components import ComponentResearcher
    from core.research import WebResearchEngine

    urls = ["https://fr.rs-online.com/moteur", "https://www.reddit.com/r/motors"]
    engine = WebResearchEngine(memory, bus, FakeProvider(urls), FakeFetcher(set(urls)))
    researcher = ComponentResearcher(engine)
    comp = await researcher.research_motor("PRJ-test", power_w=306.5)

    assert comp["status"] == "INSUFFICIENT_SOURCES"
    assert comp["confidence"] == 0.0
    assert "UNKNOWN" in comp["note"] or "INCONNU" in comp["note"]


@pytest.mark.asyncio
async def test_component_inconnu_with_no_sources(memory, bus):
    from core.components import ComponentResearcher
    from core.research import WebResearchEngine

    engine = WebResearchEngine(memory, bus, NullProvider(), FakeFetcher(set()))
    researcher = ComponentResearcher(engine)
    comp = await researcher.research_motor("PRJ-test", power_w=306.5)

    assert comp["status"] == "INCONNU"
    assert comp["candidates"] == []
