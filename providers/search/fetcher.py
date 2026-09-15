"""Polite page fetcher + HTML text/date extraction for the research pipeline."""
from __future__ import annotations

import asyncio
import hashlib
import re
import time
from dataclasses import dataclass
from urllib.parse import urlparse

import httpx
from bs4 import BeautifulSoup

from core.models import utc_now_iso

MAX_BYTES = 600_000
MAX_TEXT_CHARS = 20_000

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/124.0 Safari/537.36 AIEngineerResearch/0.1"
    ),
    "Accept-Language": "en,fr;q=0.8",
}


@dataclass
class FetchedPage:
    url: str
    final_url: str
    status: int
    title: str
    text: str
    published_date: str | None
    fetched_at: str
    checksum: str
    bytes: int


DATE_PATTERNS = [
    # meta tags first
    ("meta[property=article:published_time]", "content"),
    ("meta[name=date]", "content"),
    ("meta[name=publication_date]", "content"),
    ("time[datetime]", "datetime"),
]

_ISO_RE = re.compile(r"\b(20\d{2})-(\d{2})-(\d{2})\b")
_TEXT_DATE_RE = re.compile(
    r"\b(20\d{2})[-/](\d{1,2})[-/](\d{1,2})\b|\b(\d{1,2})[ /](\d{1,2})[ /](20\d{2})\b"
)


def _extract_date(soup: BeautifulSoup, raw_html: str) -> str | None:
    for selector, attr in DATE_PATTERNS:
        el = soup.select_one(selector)
        if el is not None:
            value = el.get(attr)
            if value:
                m = _ISO_RE.search(value)
                if m:
                    return m.group(0)
    m = _ISO_RE.search(raw_html[:60_000])
    return m.group(0) if m else None


class Fetcher:
    """Fetches pages politely: max size cap, timeout, per-host rate limiting."""

    def __init__(self, timeout_s: float = 10.0, per_host_delay_s: float = 1.5) -> None:
        self.timeout_s = timeout_s
        self.per_host_delay_s = per_host_delay_s
        self._last_hit: dict[str, float] = {}
        self._lock = asyncio.Lock()

    async def fetch(self, url: str, client: httpx.AsyncClient | None = None) -> FetchedPage:
        host = urlparse(url).netloc
        async with self._lock:
            last = self._last_hit.get(host)
            if last is not None:
                wait = self.per_host_delay_s - (time.monotonic() - last)
                if wait > 0:
                    await asyncio.sleep(wait)
            self._last_hit[host] = time.monotonic()

        owns_client = client is None
        if client is None:
            client = httpx.AsyncClient(headers=HEADERS, follow_redirects=True, timeout=self.timeout_s)
        try:
            resp = await client.get(url)
            raw = resp.content[:MAX_BYTES]
        finally:
            if owns_client:
                await client.aclose()

        html = raw.decode(resp.encoding or "utf-8", errors="replace")
        soup = BeautifulSoup(html, "html.parser")
        for tag in soup(["script", "style", "nav", "footer", "header", "aside", "form"]):
            tag.decompose()
        title_el = soup.find("title")
        title = title_el.get_text(strip=True) if title_el else ""
        text = " ".join(soup.get_text(" ").split())[:MAX_TEXT_CHARS]

        return FetchedPage(
            url=url,
            final_url=str(resp.url),
            status=resp.status_code,
            title=title,
            text=text,
            published_date=_extract_date(soup, html),
            fetched_at=utc_now_iso(),
            checksum=hashlib.sha256(raw).hexdigest()[:16],
            bytes=len(raw),
        )


async def fetch_all(urls: list[str], fetcher: Fetcher | None = None) -> list[FetchedPage | BaseException]:
    """Fetch several pages; individual failures are returned as exceptions."""
    fetcher = fetcher or Fetcher()
    async with httpx.AsyncClient(headers=HEADERS, follow_redirects=True, timeout=fetcher.timeout_s) as client:
        results: list[FetchedPage | BaseException] = []
        for url in urls:
            try:
                results.append(await fetcher.fetch(url, client))
            except Exception as exc:  # noqa: BLE001 - one bad page must not kill the batch
                results.append(exc)
        return results
