"""P3 browser checks. Isolated storage; never posts to the real Draft Room."""

import json
from pathlib import Path

from playwright.sync_api import expect, sync_playwright

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / ".tmp" / "ux-review"
OUT.mkdir(parents=True, exist_ok=True)
KEY = "fantasy-nba-practice-v1"
MOCK_KEY = "fantasy-nba-mock"


with sync_playwright() as playwright:
    browser = playwright.chromium.launch(headless=True)
    errors = []
    for port, route in [(8788, "#practice"), (8787, "practice")]:
        ctx = browser.new_context(viewport={"width": 390, "height": 844}, accept_downloads=True)
        page = ctx.new_page()
        page.set_default_timeout(120000)
        page.on("pageerror", lambda error: errors.append(str(error)))
        draft_posts = []
        page.on("request", lambda request: draft_posts.append(request.url) if request.method == "POST" and "/api/draft/" in request.url else None)
        page.goto(f"http://127.0.0.1:{port}/{route}")
        if port == 8788:
            mock_before = page.evaluate("key => localStorage.getItem(key)", MOCK_KEY)
            expect(page.locator("#practice-teams")).to_have_value("12")
            page.locator("#practice-teams").select_option("8")
            page.locator("#practice-position").select_option("2")
            page.locator("#practice-name").fill("ADP practice")
            page.locator("#practice-form button[type=submit]").click()
            expect(page.locator("#practice-current")).to_contain_text("Your pick #2")
            first = page.locator("#practice-current [data-practice-pick]").first
            first.click()
            expect(page.locator("#practice-current")).to_contain_text("Your pick #15")
            page.reload()
            expect(page.locator("#practice-current")).to_contain_text("Your pick #15")
            page.locator("[data-practice-undo]").click()
            expect(page.locator("#practice-current")).to_contain_text("Your pick #2")
            page.locator("#practice-rule").select_option("board")
            page.locator("#practice-name").fill("Board practice")
            page.locator("#practice-form button[type=submit]").click()
            expect(page.locator(".practice-run")).to_have_count(2)
            with page.expect_download() as download:
                page.locator("#practice-current [data-practice-export]").click()
            exported = json.loads(download.value.path().read_text(encoding="utf-8"))
            assert exported["version"] == 1 and exported["snapshot"]["players"]
            page.locator("#practice-import").set_input_files(str(download.value.path()))
            expect(page.locator(".practice-run")).to_have_count(2)
            assert page.evaluate("key => localStorage.getItem(key)", MOCK_KEY) == mock_before
            page.screenshot(path=str(OUT / "p3-public-mobile.png"), full_page=True)
        else:
            expect(page.get_by_role("heading", name="Practice My Draft")).to_be_visible()
            expect(page.get_by_label("Practice teams")).to_have_value("12")
            page.get_by_label("Practice teams").select_option("8")
            page.get_by_label("Practice draft position").select_option("2")
            page.get_by_label("Run name").fill("Local ADP run")
            page.get_by_role("button", name="Start practice").click()
            expect(page.locator("main")).to_contain_text("Your pick #2")
            page.get_by_role("button", name="Pick", exact=True).first.click()
            expect(page.locator("main")).to_contain_text("Your pick #15")
            page.reload()
            expect(page.locator("main")).to_contain_text("Your pick #15")
            page.get_by_role("button", name="Undo my last pick").click()
            expect(page.locator("main")).to_contain_text("Your pick #2")
            with page.expect_download() as download:
                page.get_by_role("button", name="Export run").click()
            exported = json.loads(download.value.path().read_text(encoding="utf-8"))
            assert exported["version"] == 1 and exported["snapshot"]["ranking"] == "learned/safe season value"
            page.get_by_label("Import practice run").set_input_files(str(download.value.path()))
            expect(page.locator("main")).to_contain_text("Local ADP run")
            page.screenshot(path=str(OUT / "p3-local-mobile.png"), full_page=True)
        runs = page.evaluate("key => JSON.parse(localStorage.getItem(key))", KEY)
        assert runs and runs[0]["snapshot"]["players"]
        assert page.evaluate("document.body.scrollWidth <= innerWidth")
        assert not draft_posts, draft_posts
        ctx.close()
    assert not errors, errors
    browser.close()
    print("PASS: public and local practice create, scripted turns, undo/reload, export, snapshot persistence, mobile fit and live-session isolation")
