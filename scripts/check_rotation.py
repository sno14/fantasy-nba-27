"""P5 smoke check: real cached team views, read-only browser requests, phone width."""

from __future__ import annotations

import argparse

from playwright.sync_api import expect, sync_playwright


parser = argparse.ArgumentParser()
parser.add_argument("--local-port", type=int, default=8787)
args = parser.parse_args()

with sync_playwright() as playwright:
    browser = playwright.chromium.launch(headless=True)
    errors: list[str] = []
    for port, route in ((8788, "#rotation?nbaTeam=ATL"), (args.local_port, "rotation?team=ATL")):
        context = browser.new_context(viewport={"width": 390, "height": 844})
        page = context.new_page()
        page.set_default_timeout(120000)
        page.on("pageerror", lambda error: errors.append(str(error)))
        page.goto(f"http://127.0.0.1:{port}/{route}")
        if port == 8788:
            expect(page.locator("#rotation-status")).to_contain_text("Published board")
            expect(page.locator("#rotation-team")).to_have_value("ATL")
            expect(page.locator("#rotation-summary")).to_contain_text("Known projected MPG")
            expect(page.locator(".rotation-player").first).to_be_visible()
            page.locator("#rotation-team").select_option("CHA")
            expect(page.locator("#rotation-team")).to_have_value("CHA")
            assert "nbaTeam=CHA" in page.url
            page.reload()
            expect(page.locator("#rotation-team")).to_have_value("CHA")
            page.locator("#mobile-nav").click()
            page.locator("[data-view='teams']").click()
            page.locator("[data-open-rotation='ATL']").click()
            expect(page.locator("#rotation-team")).to_have_value("ATL")
        else:
            expect(page.get_by_role("heading", name="Rotation & Opportunity")).to_be_visible()
            expect(page.locator("main")).to_contain_text("Board A minutes")
            expect(page.locator("main")).to_contain_text("240 allocated")
            page.get_by_label("NBA team").select_option("CHA")
            expect(page.locator("main")).to_contain_text("No closed budget")
            expect(page.locator("main")).to_contain_text("2026-09-29")
            page.reload()
            expect(page.get_by_label("NBA team")).to_have_value("CHA")
        assert page.evaluate("document.documentElement.scrollWidth <= innerWidth"), f"{port} overflows at 390px"
        context.close()
    assert not errors, errors
    browser.close()

print("Rotation & Opportunity browser checks passed on public and local previews")
