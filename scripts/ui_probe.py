"""Quick diagnostic probe of the console page."""
from __future__ import annotations

import sys

from playwright.sync_api import sync_playwright


def main() -> int:
    with sync_playwright() as p:
        browser = p.chromium.launch(channel="chrome", headless=True)
        page = browser.new_page(viewport={"width": 1440, "height": 960})
        errors: list[str] = []
        page.on("console", lambda m: errors.append(f"{m.type}: {m.text}") if m.type in ("error", "warning") else None)
        page.on("pageerror", lambda e: errors.append(f"pageerror: {e}"))

        page.goto("http://localhost:5173", wait_until="domcontentloaded", timeout=30000)
        page.wait_for_timeout(6000)

        h1 = page.locator("h1").inner_text() if page.locator("h1").count() else "(no h1)"
        badges = page.locator(".badge").all_inner_texts()
        events = page.locator(".event").count()
        history = page.locator(".history-item").count()

        print(f"h1: {h1}")
        print(f"badges: {badges}")
        print(f"events in feed: {events}")
        print(f"history items: {history}")
        print("console/page errors:")
        for e in errors[:10]:
            print("  ", e)
        if not errors:
            print("   (none)")
        browser.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
