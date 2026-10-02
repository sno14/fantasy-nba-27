"""P4 browser check with isolated synthetic history and no live draft writes."""

from __future__ import annotations

import argparse

from playwright.sync_api import expect, sync_playwright


def row(pid: int, rank: int, fp: float = 30.0) -> dict:
    return {"PLAYER_ID": pid, "PLAYER_NAME": f"Player {pid}", "TEAM_ABBREVIATION": "NYK",
            "rank": rank, "fpts_pg": fp, "mpg": 28.0, "analyst_action": None, "analyst_date": None}


def snapshot(source: str, version: str, asof: str, rows: list[dict]) -> dict:
    return {"schema": 1, "source": source, "version": version, "asof": asof,
            "season": "2026-27", "rankedBy": "FP/G ordinal" if source == "public" else "ROS safe season value",
            "scoringKey": "0123456789abcdef", "rows": rows}


parser = argparse.ArgumentParser()
parser.add_argument("--local-port", type=int, default=8787)
args = parser.parse_args()

with sync_playwright() as playwright:
    browser = playwright.chromium.launch(headless=True)
    errors: list[str] = []
    for port, route in ((8788, "#changes"), (args.local_port, "changes")):
        public = port == 8788
        url = f"http://127.0.0.1:{port}/{route}"
        context = browser.new_context(viewport={"width": 390, "height": 844})
        page = context.new_page()
        page.on("pageerror", lambda error: errors.append(str(error)))
        page.goto(url)
        expect(page.locator("#changes-status" if public else "main")).to_contain_text("baseline is being collected")
        context.close()

        old_version = "2026-10-01" if not public else "20261001T000000Z-aaaaaaaaaa"
        new_version = "2026-10-02" if not public else "20261002T000000Z-bbbbbbbbbb"
        old = snapshot("public" if public else "local", old_version, "2026-10-01", [row(1, 1), row(2, 2)])
        new = snapshot("public" if public else "local", new_version, "2026-10-02", [row(1, 2), row(3, 1, 35)])
        entries = [{key: data[key] for key in ("version", "asof", "season", "rankedBy", "scoringKey", "source")}
                   for data in (old, new)]
        if public:
            for item in entries:
                item["file"] = f"v-{item['version']}.json"
            manifest = {"schema": 1, "versions": entries}
        else:
            manifest = {"schema": 1, "versions": entries, "legacyCount": 0}
        context = browser.new_context(viewport={"width": 390, "height": 844})
        page = context.new_page()
        page.on("pageerror", lambda error: errors.append(str(error)))
        if public:
            page.route("**/data/history/manifest.json", lambda request: request.fulfill(json=manifest))
            page.route("**/data/history/v-*.json", lambda request: request.fulfill(json=old if old_version in request.request.url else new))
        else:
            page.route("**/api/changes/versions", lambda request: request.fulfill(json=manifest))
            page.route("**/api/changes/version/*", lambda request: request.fulfill(json=old if old_version in request.request.url else new))
        page.goto(url)
        root = page.locator("#view-changes" if public else "main")
        expect(root).to_contain_text("3 changed players")
        expect(root).to_contain_text("rank only")
        expect(root).to_contain_text("Absent from this board")
        select = page.locator("#changes-view" if public else "select[aria-label='Change view']")
        select.select_option("watched")
        expect(root).to_contain_text("No changes match this view")
        select.select_option("since")
        expect(root).to_contain_text("3 changed players")
        assert page.evaluate("document.documentElement.scrollWidth <= innerWidth"), f"{port} overflows at 390px"
        marker = "fantasy-nba-changes-last-seen-v1" if public else "fantasy-nba-local-changes-last-seen-v1"
        saved = page.evaluate("key => localStorage.getItem(key)", marker)
        assert (saved.strip('"') if public else saved) == new_version
        page.reload()
        select = page.locator("#changes-view" if public else "select[aria-label='Change view']")
        select.select_option("since")
        expect(root).to_contain_text("0 changed players")
        context.close()
    assert not errors, errors
    browser.close()

print("What Changed? browser checks passed on public and local previews")
