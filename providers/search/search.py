"""Search provider abstraction (spec sections 7 and 27).

The platform never talks to a specific search engine directly: agents use a
SearchProvider selected by config. Every result carries its URL and retrieval
metadata so information can be traced and re-checked. Implementations must
NEVER invent results - on failure they raise, and the pipeline degrades
honestly.
"""
from __future__ import annotations

import time
from abc import ABC, abstractmethod

import httpx

from core.models import utc_now_iso


class SearchError(RuntimeError):
    pass


def _clean(text: str) -> str:
    return " ".join(text.split())


class SearchResult:
    def __init__(self, title: str, url: str, snippet: str = "", engine: str = "") -> None:
        self.title = _clean(title)
        self.url = url
        self.snippet = _clean(snippet)
        self.engine = engine
        self.retrieved_at = utc_now_iso()

    def to_dict(self) -> dict:
        return {
            "title": self.title,
            "url": self.url,
            "snippet": self.snippet,
            "engine": self.engine,
            "retrieved_at": self.retrieved_at,
        }


class SearchProvider(ABC):
    name: str = "abstract"

    @abstractmethod
    def search(self, query: str, max_results: int = 8) -> list[SearchResult]:
        """Run a web search. Raises SearchError on failure - never fabricates."""


class NullProvider(SearchProvider):
    """Search disabled: raises so callers degrade to INCONNU, not to fake data."""

    name = "null"

    def search(self, query: str, max_results: int = 8) -> list[SearchResult]:
        raise SearchError("web search disabled (search.provider=null)")


class DuckDuckGoProvider(SearchProvider):
    """Keyless search via duckduckgo.com/html (no API key required)."""

    name = "duckduckgo"

    def __init__(self, timeout_s: float = 15.0) -> None:
        self.timeout_s = timeout_s

    def search(self, query: str, max_results: int = 8) -> list[SearchResult]:
        headers = {
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                "(KHTML, like Gecko) Chrome/124.0 Safari/537.36"
            )
        }
        try:
            resp = httpx.post(
                "https://html.duckduckgo.com/html/",
                data={"q": query},
                headers=headers,
                timeout=self.timeout_s,
                follow_redirects=True,
            )
            resp.raise_for_status()
        except httpx.HTTPError as exc:
            raise SearchError(f"duckduckgo request failed: {exc}") from exc

        return self.parse_html(resp.text, max_results)

    @staticmethod
    def parse_html(html: str, max_results: int = 8) -> list[SearchResult]:
        # Static method so offline tests can feed canned HTML.
        from bs4 import BeautifulSoup

        soup = BeautifulSoup(html, "html.parser")
        results: list[SearchResult] = []
        for div in soup.select("div.result")[: max_results * 3]:
            a = div.select_one("a.result__a")
            if a is None:
                continue
            title = a.get_text(strip=True)
            url = a.get("href", "")
            # DDG wraps target URLs: /l/?uddg=<encoded-url>&rut=...
            if url.startswith("//duckduckgo.com/l/") or url.startswith("/l/"):
                from urllib.parse import parse_qs, urlparse

                q = parse_qs(urlparse("https:" + url if url.startswith("//") else url).query)
                url = (q.get("uddg") or [url])[0]
            snippet_el = div.select_one(".result__snippet")
            snippet = snippet_el.get_text(" ", strip=True) if snippet_el else ""
            if not title or not url.startswith("http"):
                continue
            results.append(SearchResult(title, url, snippet, engine="duckduckgo"))
            if len(results) >= max_results:
                break
        return results


class SerperProvider(SearchProvider):
    """Serper.dev search API (requires SERPER_API_KEY in the environment)."""

    name = "serper"

    def __init__(self, api_key_env: str = "SERPER_API_KEY", timeout_s: float = 15.0) -> None:
        import os

        self.api_key = os.environ.get(api_key_env)
        self.api_key_env = api_key_env
        self.timeout_s = timeout_s

    def search(self, query: str, max_results: int = 8) -> list[SearchResult]:
        if not self.api_key:
            raise SearchError(
                f"environment variable {self.api_key_env} is not set - cannot use Serper"
            )
        try:
            resp = httpx.post(
                "https://google.serper.dev/search",
                headers={"X-API-KEY": self.api_key, "Content-Type": "application/json"},
                json={"q": query, "num": max_results},
                timeout=self.timeout_s,
            )
            resp.raise_for_status()
        except httpx.HTTPError as exc:
            raise SearchError(f"serper request failed: {exc}") from exc

        results: list[SearchResult] = []
        for item in resp.json().get("organic", [])[:max_results]:
            results.append(
                SearchResult(
                    item.get("title", ""),
                    item.get("link", ""),
                    item.get("snippet", ""),
                    engine="serper",
                )
            )
        return results


def make_provider(name: str) -> SearchProvider:
    """Factory from config value -> provider instance."""
    providers = {
        "none": NullProvider,
        "null": NullProvider,
        "duckduckgo": DuckDuckGoProvider,
        "serper": SerperProvider,
    }
    cls = providers.get(name)
    if cls is None:
        raise ValueError(f"unknown search provider: {name} (known: {sorted(providers)})")
    return cls()
