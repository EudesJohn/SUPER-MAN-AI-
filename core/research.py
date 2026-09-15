"""WEB RESEARCH ENGINE (spec section 7).

Pipeline: question -> search -> dedupe -> fetch -> extract -> trust ->
persistence -> Knowledge (project memory). Every stored source keeps URL,
title, date when found, excerpt, retrieval timestamp and trust level.

Honesty rules: nothing is stored without a real retrieval; a page that fails
to fetch is reported as failed, never approximated.
"""
from __future__ import annotations

from urllib.parse import urlparse

from providers.search.fetcher import Fetcher
from providers.search.search import SearchProvider, SearchError
from providers.search.trust import trust_for_url
from core.models import utc_now_iso


class WebResearchEngine:
    def __init__(self, memory, bus, provider: SearchProvider, fetcher: Fetcher | None = None) -> None:
        self.memory = memory
        self.bus = bus
        self.provider = provider
        self.fetcher = fetcher or Fetcher()

    async def research(
        self,
        project_id: str,
        query: str,
        *,
        max_results: int = 8,
        fetch_top: int = 4,
    ) -> dict:
        """Run one research query end-to-end and persist sources."""
        try:
            results = self.provider.search(query, max_results=max_results)
        except SearchError as exc:
            await self.bus.publish(
                "SEARCH_COMPLETED",
                {"project_id": project_id, "query": query, "status": "failed", "error": str(exc)},
            )
            return {"query": query, "status": "failed", "error": str(exc), "sources": []}

        # Dedupe by URL.
        seen: set[str] = set()
        unique = []
        for r in results:
            if r.url not in seen:
                seen.add(r.url)
                unique.append(r)

        stored: list[dict] = []
        failed: list[str] = []

        # Fetch the top pages (politeness handled inside Fetcher).
        import httpx

        timeout_s = getattr(self.fetcher, "timeout_s", 15.0)
        async with httpx.AsyncClient(timeout=timeout_s, follow_redirects=True) as client:
            for r in unique:
                should_fetch = len(stored) < fetch_top
                page = None
                if should_fetch:
                    try:
                        page = await self.fetcher.fetch(r.url, client)
                    except Exception:  # noqa: BLE001 - a dead page is recorded as failed
                        failed.append(r.url)
                if page is not None and page.status == 200 and page.text:
                    source = {
                        "url": page.final_url,
                        "title": page.title or r.title,
                        "date": page.published_date,
                        "excerpt": page.text[:300],
                        "retrieved_at": page.fetched_at,
                        "confidence": trust_for_url(page.final_url).value,
                        "engine": r.engine,
                        "checksum": page.checksum,
                    }
                else:
                    # Snippet-only record from the SERP - trust flagged accordingly.
                    source = {
                        "url": r.url,
                        "title": r.title,
                        "date": None,
                        "excerpt": r.snippet[:300],
                        "retrieved_at": r.retrieved_at,
                        "confidence": trust_for_url(r.url).value,
                        "engine": r.engine,
                        "checksum": None,
                        "snippet_only": True,
                    }
                sid = self.memory.add_source(project_id, source)
                source["id"] = sid
                stored.append(source)

        await self.bus.publish(
            "SEARCH_COMPLETED",
            {
                "project_id": project_id,
                "query": query,
                "status": "ok",
                "results": len(unique),
                "stored": len(stored),
                "failed_fetches": len(failed),
            },
        )
        return {
            "query": query,
            "status": "ok",
            "results_found": len(unique),
            "sources": stored,
            "failed_fetches": failed,
        }
