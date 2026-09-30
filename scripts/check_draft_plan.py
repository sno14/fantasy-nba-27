"""Browser smoke checks for P2. Uses isolated storage and intercepts draft-state reads."""

import json
from pathlib import Path

from playwright.sync_api import expect, sync_playwright

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / ".tmp" / "ux-review"
OUT.mkdir(parents=True, exist_ok=True)
ROWS = json.loads((ROOT / "static/data/board.json").read_text(encoding="utf-8"))["rows"]
PLAYER = ROWS[0]
PLAYER_ID = PLAYER["PLAYER_ID"]
KEY = "fantasy-nba-draft-targets-v1"
OLD_TARGET = {str(PLAYER_ID): {"takeBy": 3, "note": "P2 migration ★"}}


def seed(page):
    page.evaluate("([key, value]) => localStorage.setItem(key, JSON.stringify(value))", [KEY, OLD_TARGET])


with sync_playwright() as playwright:
    browser = playwright.chromium.launch(headless=True)
    errors = []

    public = browser.new_context(viewport={"width": 390, "height": 844})
    page = public.new_page()
    page.on("pageerror", lambda error: errors.append(str(error)))
    page.goto("http://127.0.0.1:8788/#board")
    seed(page)
    page.reload()
    page.goto("http://127.0.0.1:8788/#plan")
    expect(page.locator("#plan-groups")).to_contain_text(PLAYER["PLAYER_NAME"])
    expect(page.locator("#plan-groups")).to_contain_text("Round 1")
    page.locator(f"#plan-groups [data-target-player='{PLAYER_ID}']").click()
    page.locator("#target-round").fill("2")
    page.locator("#target-group").fill("guards")
    page.locator("#target-priority").fill("1")
    page.locator("#target-form button[type=submit]").click()
    expect(page.locator("#plan-groups")).to_contain_text("Round 2")
    expect(page.locator("#plan-groups")).to_contain_text("Backup: guards")
    page.goto("http://127.0.0.1:8788/#board")
    expect(page.locator(f"#rows [data-target-player='{PLAYER_ID}']")).to_have_class("target-star active")
    page.goto("http://127.0.0.1:8788/#plan")
    page.locator("#view-plan [data-go='mock']").click()
    page.locator(f"#mock-rows [data-draft-player='{PLAYER_ID}']").click()
    page.goto("http://127.0.0.1:8788/#plan")
    expect(page.locator("#plan-groups")).to_contain_text("Drafted by you")
    page.locator("#view-plan [data-go='mock']").click()
    page.locator("#mock-undo").click()
    page.goto("http://127.0.0.1:8788/#plan")
    expect(page.locator("#plan-groups")).to_contain_text("Available")
    assert page.evaluate("document.body.scrollWidth <= innerWidth")
    saved = page.evaluate("key => JSON.parse(localStorage.getItem(key))", KEY)
    assert saved[str(PLAYER_ID)]["preferredRound"] == 2
    assert saved[str(PLAYER_ID)]["backupGroup"] == "guards"
    page.screenshot(path=str(OUT / "p2-public-mobile.png"), full_page=True)
    public.close()

    local = browser.new_context(viewport={"width": 390, "height": 844})
    page = local.new_page()
    page.on("pageerror", lambda error: errors.append(str(error)))
    state = {
        "source": "manual", "synthetic_teams": False, "my_team_id": 103,
        "team_ids": [42, 103, 7, 81], "settings": {"size": 4, "pick_order": [42, 103, 7, 81], "order_is_placeholder": False},
        "roster_slots": {"PG": 1, "SG": 1, "SF": 1, "PF": 1, "C": 1, "BENCH": 1, "IR": 1},
        "n_picks": 0, "picks": [], "rosters": [], "has_positions": False,
    }
    def route(request):
        request.fulfill(status=200, content_type="application/json", body=json.dumps(state))
    page.route("**/api/draft/state?top=1", route)
    page.goto("http://127.0.0.1:8787/")
    seed(page)
    page.reload()
    page.goto("http://127.0.0.1:8787/draft-plan")
    expect(page.get_by_role("heading", name="My Draft Plan")).to_be_visible()
    expect(page.locator("main")).to_contain_text("#2 in round 1, #7 in round 2")
    expect(page.locator("main")).to_contain_text("Open starting positions require")
    expect(page.locator("main")).to_contain_text("P2 migration ★")
    page.get_by_role("button", name="Edit plan").click()
    page.get_by_label("Preferred round").fill("2")
    page.get_by_label("Backup group").fill("guards")
    page.get_by_label("Priority order").fill("1")
    page.get_by_role("button", name="Save target").click()
    expect(page.locator("main")).to_contain_text("Round 2")
    page.goto("http://127.0.0.1:8787/")
    expect(page.get_by_role("button", name=f"Edit priority target for {PLAYER['PLAYER_NAME']}").first).to_be_visible()
    page.goto("http://127.0.0.1:8787/draft-plan")
    saved = page.evaluate("key => JSON.parse(localStorage.getItem(key))", KEY)
    assert saved[str(PLAYER_ID)]["preferredRound"] == 2
    assert saved[str(PLAYER_ID)]["backupGroup"] == "guards"
    state["picks"] = [{"overall": 1, "team_id": 42, "player_id": PLAYER_ID}]
    state["n_picks"] = 1
    page.reload()
    expect(page.locator("main")).to_contain_text("Drafted by Team 42")
    state["picks"] = []
    state["n_picks"] = 0
    page.reload()
    expect(page.locator("main")).to_contain_text("Round pick after take-by")
    state["settings"]["order_is_placeholder"] = True
    page.reload()
    expect(page.locator("main")).to_contain_text("Illustrative slot")
    expect(page.locator("main")).to_contain_text("Live draft order is unverified")
    assert page.evaluate("document.body.scrollWidth <= innerWidth")
    page.screenshot(path=str(OUT / "p2-local-mobile.png"), full_page=True)
    local.close()

    assert not errors, errors
    browser.close()
    print("PASS: P2 migration, editing, public pick/undo, verified non-contiguous order, local pick/undo and unknown state")
