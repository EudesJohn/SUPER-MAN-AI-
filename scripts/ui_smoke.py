"""UI validation: drive the real console in headless Chrome.

Loads http://localhost:5173, checks the WebSocket badge goes green, runs a
full project from the default cahier des charges, waits for tasks and
verifications to render, counts live events received in the feed, and takes
a screenshot (ui_validation.png).

Run:  .venv/Scripts/python scripts/ui_smoke.py   (backend + vite must be up)
"""
from __future__ import annotations

import sys

from playwright.sync_api import sync_playwright

URL = "http://localhost:5173"


def click_enabled(page, selector: str, timeout_ms: int = 60000) -> None:
    """Wait until the button is clickable (busy-gated buttons disable during
    async reloads - a click on a disabled button silently no-ops)."""
    import time

    loc = page.locator(selector).first
    loc.wait_for(state="visible", timeout=timeout_ms)
    deadline = time.time() + timeout_ms / 1000.0
    while not loc.is_enabled():
        if time.time() > deadline:
            raise TimeoutError(f"button still disabled after {timeout_ms} ms: {selector}")
        time.sleep(0.25)
    loc.click()


def main() -> int:
    from datetime import datetime
    from pathlib import Path

    shot_dir = Path("screenshots") / datetime.now().strftime("run_%Y%m%d_%H%M%S")
    shot_dir.mkdir(parents=True, exist_ok=True)

    def shot(page, name: str) -> str:
        """Screenshot into a fresh timestamped folder (never blocked by an
        image viewer holding an old file open)."""
        path = shot_dir / name
        page.screenshot(path=str(path), full_page=True)
        return str(path)

    with sync_playwright() as p:
        browser = p.chromium.launch(channel="chrome", headless=True)
        page = browser.new_page(viewport={"width": 1440, "height": 960})
        page.goto(URL, wait_until="domcontentloaded", timeout=30000)

        # 1) App mounted
        assert page.locator("h1").inner_text() == "AI ENGINEER", "app title missing"

        # 2) WebSocket connected (badge turns green; retry window 30 s because
        #    the hook auto-reconnects every 2 s after a failed first attempt).
        page.wait_for_selector("text=WS connecté", timeout=30000)
        print("[1] WebSocket connected: OK")

        # 3) Launch a full project run from the default spec
        page.click("button:has-text('Nouveau projet + Exécuter')")
        print("[2] Run started...")

        # 4) Wait for results to render (live web research can take ~30-60 s)
        page.wait_for_selector("text=Vérifications", timeout=150000)
        page.wait_for_selector("text=Exigences (", timeout=30000)
        print("[3] Requirements + verifications rendered")

        # 5) Live event feed received events
        page.wait_for_selector(".event", timeout=30000)
        n_events = page.locator(".event").count()
        print(f"[4] Live events displayed in feed: {n_events}")
        assert n_events >= 5, "expected several live events in the feed"

        # 6) Task table shows SUCCESS statuses
        body = page.locator("main").inner_text()
        assert "SUCCESS" in body, "no SUCCESS task status visible"
        print("[5] Task statuses visible (SUCCESS found)")

        # 7) Open the technical report
        page.click("button:has-text('Voir le rapport technique')")
        page.wait_for_selector("pre.report", timeout=20000)
        report_text = page.locator("pre.report").inner_text()
        assert "Rapport technique" in report_text, "report content missing"
        print(f"[6] Report rendered in console ({len(report_text)} chars)")

        p1 = shot(page, "ui_validation.png")
        print(f"[7] Screenshot saved: {p1}")

        # 8) HISTORY: reload the page (fresh app state), then reopen the run
        #    from the history panel - results and report must come back.
        page.reload(wait_until="domcontentloaded")
        page.wait_for_selector(".history-item", timeout=20000)
        n_items = page.locator(".history-item").count()
        assert n_items >= 1, "history panel is empty after a run"
        print(f"[8] History panel lists {n_items} project(s)")

        page.locator(".history-item").first.click()
        page.wait_for_selector("text=Vérifications", timeout=30000)
        page.wait_for_selector("pre.report", timeout=20000)
        reopened = page.locator("main").inner_text()
        assert "SUCCESS" in reopened, "reopened run lacks task statuses"
        print("[9] Reopened past run from history: results + report restored")

        p2 = shot(page, "ui_history.png")
        print(f"[10] Screenshot saved: {p2}")

        # 11) TRACTOR 3D: build the parametric tractor + 12 V circuit from the
        #     reopened project, wait for the 3D viewer and the electrical table.
        page.click("button:has-text('Concevoir le tracteur 3D')")
        page.wait_for_selector("text=Circuit électrique 12 V —", timeout=120000)
        canvas = page.wait_for_selector("canvas", timeout=60000)
        assert canvas is not None, "3D viewer canvas missing"
        page.wait_for_selector("text=Masse totale estimée", timeout=30000)
        body_text = page.locator("main").inner_text()
        assert "kg" in body_text and "mm²" in body_text, "electrical sizing table missing"
        assert "electrical_fusing" in body_text, "independent electrical verifications missing"
        n_fuses = body_text.count("sans fusible")
        print(f"[11] Tracteur 3D construit: viewer OK, circuits dimensionnés ({n_fuses} sans fusible = démarreur/alternateur)")

        # 12) TECHNICAL DRAWINGS + WIRE SCHEDULE rendered with DXF links
        page.wait_for_selector("text=Dessins techniques (", timeout=30000)
        page.wait_for_selector("text=Tableau de cablage (", timeout=30000)
        n_dxf_links = page.locator("a[download]").count()
        assert n_dxf_links >= 5, "expected DXF download links in the drawings table"
        assert "MASSE CHASSIS" in body_text or "BOITE FUSIBLES" in body_text or "BAT+" in body_text, \
            "wire schedule rows missing"
        print(f"[12] Dessins techniques affichés ({n_dxf_links} liens DXF) + tableau de cablage")

        # 13) AUTOCAD DELIVERABLES: folder manifest + ZIP / 3D DXF download links
        page.wait_for_selector("text=Livrables AutoCAD", timeout=30000)
        body_text = page.locator("main").inner_text()
        assert "TRACTEUR_3D_ENSEMBLE.dxf" in body_text, "3D assembly DXF link missing"
        assert "LIVRABLES_COMPLETS.zip" in body_text, "deliverables ZIP link missing"
        assert "CABLAGE_COMPLET.csv" in body_text, "wiring CSV link missing"
        n_deliv = page.locator("a[download][href*='deliverables']").count()
        assert n_deliv >= 3, "expected the 3 deliverables links (3D DXF + CSV + ZIP)"
        n_downloads = page.locator("a[download]").count()
        print(f"[13] Livrables AutoCAD affichés: {n_deliv} liens livrables, {n_downloads} téléchargements au total")

        # 14) ASSISTANT IA: design intent in natural language re-runs the REAL
        #     pipeline (not the LLM) and refreshes the deliverables panel.
        page.fill("input[placeholder*='question']", "dessine un tracteur avec ses pieces")
        click_enabled(page, "button:has-text('Demander')")
        page.wait_for_selector("text=Conception exécutée", timeout=180000)
        page.wait_for_selector("text=Livrables AutoCAD", timeout=60000)
        print("[14] Demande en langage naturel: conception réellement exécutée + livrables régénérés")

        p3 = shot(page, "ui_tractor_plans.png")
        print(f"[15] Screenshot saved: {p3}")

        # 15) AERO CAR: dedicated button runs the full EV pipeline; the 3D
        #     viewer, HV/LV tables, verifications and deliverables must render.
        click_enabled(page, "button:has-text('Concevoir la voiture aéro EV')")
        page.wait_for_selector("text=Réseau haute tension", timeout=120000)
        page.wait_for_selector("text=VOITURE_3D_ENSEMBLE.dxf", timeout=60000)
        body_text = page.locator("main").inner_text()
        assert "kW" in body_text and "Cd 0.19" in body_text, "scenario stats missing"
        assert "hv_battery_to_inverter" in body_text or "Batterie -> Onduleur" in body_text \
            or "Onduleur" in body_text, "HV circuit table missing"
        assert "hv_wire_capacity" in body_text, "independent HV verifications missing"
        n_car_deliv = page.locator("a[download][href*='/cad/car/']").count()
        assert n_car_deliv >= 2, "expected car 3D DXF + ZIP deliverables links"
        canvases = page.locator("canvas").count()
        assert canvases >= 2, "expected a second 3D viewer for the car"
        print(f"[16] Voiture aero EV construite: viewer 3D + HV/BT + {n_car_deliv} liens livrables")

        # 16) Natural-language CAR design request routes to the car pipeline.
        page.fill("input[placeholder*='question']", "dessine une voiture hyper aerodynamique")
        click_enabled(page, "button:has-text('Demander')")
        page.wait_for_selector("text=3D_MODELES/VOITURE_3D_ENSEMBLE.dxf", timeout=180000)
        print("[17] Demande 'voiture' en langage naturel: pipeline EV exécuté")

        p4 = shot(page, "ui_aero_car.png")
        print(f"[18] Screenshot saved: {p4}")

        browser.close()
    print("UI VALIDATION: ALL CHECKS PASSED")
    return 0


if __name__ == "__main__":
    sys.exit(main())
