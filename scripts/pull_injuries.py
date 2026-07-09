"""Scrape prosportstransactions.com (Step 7 / EXP-015, shared with Step 8 / EXP-016).

One general scraper for the PST basketball search categories we consume:

* ``injury``   — "Missed games due to injury/illness" (InjuriesChkBx)
* ``il``       — "Movement to/from injured/inactive list" (ILChkBx)
* ``movement`` — "Player movement" (PlayerMovementChkBx) — Step 8's transactions pull

Datasets (category groups → one parquet each, with a ``category`` column):

* ``injuries``     = injury + il  → ``data/raw/injuries.parquet``      (Step 7)
* ``transactions`` = movement     → ``data/raw/transactions.parquet``  (Step 8)

Rows are kept **verbatim** (``date, team, acquired, relinquished, notes, category`` — ISO
dates, bullet-prefixed name strings untouched); all parsing/normalization happens downstream
in :mod:`fantasy_nba.models.injuries` so a re-parse never needs a re-scrape.

Cloudflare: PST sits behind a JS challenge that blocks plain ``requests``/curl-impersonation
and *headless* browsers, but passes with the machine's real Edge/Chrome driven headed
(verified 2026-07-09). So this script launches the installed browser via Playwright —
**a visible browser window opens while the pull runs**; leave it alone. Politeness: one
page per second, retry ×3 with backoff (the ``_with_retry`` discipline from ``ingest.py``).

First run pulls 2009-07-01 → today (~1-2k pages, 30-60 min under the throttle). Later runs
are incremental: they resume from the max cached date (overlap de-duped on all columns).

Examples
--------
    python scripts/pull_injuries.py                          # injuries, incremental
    python scripts/pull_injuries.py --dataset transactions   # Step 8
    python scripts/pull_injuries.py --full                   # ignore cache, re-pull all
"""

from __future__ import annotations

import argparse
import datetime as dt
import sys
import time

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

import pandas as pd
from bs4 import BeautifulSoup

from fantasy_nba.data import storage

SEARCH_URL = "https://www.prosportstransactions.com/basketball/Search/SearchResults.php"
PAGE_SIZE = 25  # PST's fixed page length
THROTTLE = 1.0  # seconds between page fetches (politeness rule, implementation-plan 7.1)
RETRY_ATTEMPTS = 3
RETRY_BACKOFF = 5.0  # seconds, × attempt number
CHALLENGE_WAIT_S = 90  # max seconds to let the Cloudflare challenge auto-solve
MAX_PAGES = 8000  # hard safety cap per category
HISTORY_BEGIN = "2009-07-01"  # matches the season-stats cache (2009-10 onward)

CATEGORY_PARAMS = {
    "injury": "InjuriesChkBx",
    "il": "ILChkBx",
    "movement": "PlayerMovementChkBx",
}
DATASETS = {
    "injuries": ("injury", "il"),
    "transactions": ("movement",),
}
# Launch preferences: real-browser channels pass the CF challenge; headless never has.
BROWSER_ATTEMPTS = (("msedge", False), ("chrome", False))


def _search_url(category: str, begin: str, end: str, start: int) -> str:
    from urllib.parse import urlencode

    params = {
        "Player": "", "Team": "", "BeginDate": begin, "EndDate": end,
        CATEGORY_PARAMS[category]: "yes", "Submit": "Search", "start": start,
    }
    return f"{SEARCH_URL}?{urlencode(params)}"


def _launch(p):
    """First real-browser channel that launches; the CF check happens on the seed page."""
    last_err: Exception | None = None
    for channel, headless in BROWSER_ATTEMPTS:
        try:
            browser = p.chromium.launch(
                headless=headless, channel=channel,
                args=["--disable-blink-features=AutomationControlled"],
            )
            print(f"[browser] {channel} (headless={headless})")
            return browser
        except Exception as err:
            last_err = err
    raise RuntimeError("No real browser channel (msedge/chrome) available for Playwright.") from last_err


def _page_html(page, url: str) -> str:
    """Navigate and return HTML once past any Cloudflare interstitial."""
    page.goto(url, wait_until="domcontentloaded", timeout=60000)
    deadline = time.monotonic() + CHALLENGE_WAIT_S
    while time.monotonic() < deadline:
        try:
            html = page.content()
        except Exception:  # mid-navigation (challenge redirect) — poll again
            page.wait_for_timeout(500)
            continue
        if "datatable" in html or ("Just a moment" not in html and "<table" in html):
            return html
        if "No matching transactions found" in html:
            return html
        page.wait_for_timeout(1000)
    raise RuntimeError(f"Cloudflare challenge did not clear within {CHALLENGE_WAIT_S}s for {url}")


def _fetch_page(page, url: str) -> str:
    last_err: Exception | None = None
    for attempt in range(1, RETRY_ATTEMPTS + 1):
        try:
            return _page_html(page, url)
        except Exception as err:
            last_err = err
            wait = RETRY_BACKOFF * attempt
            print(f"  attempt {attempt}/{RETRY_ATTEMPTS} failed: {err} — retrying in {wait:.0f}s")
            time.sleep(wait)
    raise RuntimeError(f"Failed to fetch {url} after {RETRY_ATTEMPTS} attempts") from last_err


def _parse_rows(html: str) -> list[dict]:
    """Verbatim data rows from the results table (header row skipped)."""
    soup = BeautifulSoup(html, "html.parser")
    table = soup.find("table", class_="datatable")
    if table is None:
        return []
    rows = []
    for tr in table.find_all("tr"):
        tds = tr.find_all("td")
        if len(tds) != 5:
            continue
        cells = [td.get_text(" ", strip=True) for td in tds]
        if cells[0] in ("Date", "\xa0Date"):  # header row
            continue
        rows.append({
            "date": cells[0], "team": cells[1], "acquired": cells[2],
            "relinquished": cells[3], "notes": cells[4],
        })
    return rows


def scrape_category(page, category: str, begin: str, end: str) -> pd.DataFrame:
    """All rows for one PST category in [begin, end], paginated at PST's 25/page."""
    frames: list[dict] = []
    start = 0
    for _ in range(MAX_PAGES):
        html = _fetch_page(page, _search_url(category, begin, end, start))
        rows = _parse_rows(html)
        frames.extend(rows)
        if start % 500 == 0 or len(rows) < PAGE_SIZE:
            last = rows[-1]["date"] if rows else "—"
            print(f"[{category}] start={start}: +{len(rows)} rows (through {last}, total {len(frames)})")
        if len(rows) < PAGE_SIZE:  # short page = last page
            break
        start += PAGE_SIZE
        time.sleep(THROTTLE)
    else:
        raise RuntimeError(f"[{category}] exceeded MAX_PAGES={MAX_PAGES} — aborting rather than hammering PST.")
    out = pd.DataFrame(frames, columns=["date", "team", "acquired", "relinquished", "notes"])
    out.insert(0, "category", category)
    return out


def pull_dataset(
    dataset: str, begin: str | None = None, end: str | None = None, full: bool = False
) -> pd.DataFrame:
    """Pull (or incrementally extend) one dataset; caches to ``data/raw/<dataset>.parquet``."""
    from playwright.sync_api import sync_playwright

    end = end or dt.date.today().isoformat()
    existing: pd.DataFrame | None = None
    if not full and storage.exists(dataset):
        existing = storage.read(dataset)
        cache_max = existing["date"].max()
        begin = begin or cache_max  # re-pull the max date (page may have been partial); de-duped below
        print(f"[{dataset}] cache has {len(existing):,} rows through {cache_max}; resuming from {begin}")
    begin = begin or HISTORY_BEGIN

    frames = []
    with sync_playwright() as p:
        browser = _launch(p)
        page = browser.new_page()
        try:
            for category in DATASETS[dataset]:
                frames.append(scrape_category(page, category, begin, end))
        finally:
            browser.close()

    new = pd.concat(frames, ignore_index=True)
    combined = pd.concat([existing, new], ignore_index=True) if existing is not None else new
    combined = combined.drop_duplicates().sort_values(["date", "category"]).reset_index(drop=True)
    path = storage.write(combined, dataset)
    print(f"[{dataset}] cached {len(combined):,} rows ({len(new):,} fetched) -> {path}")
    return combined


def main() -> None:
    parser = argparse.ArgumentParser(description="Scrape prosportstransactions (injuries / transactions).")
    parser.add_argument("--dataset", choices=sorted(DATASETS), default="injuries")
    parser.add_argument("--begin", default=None, help=f"Override start date (default: incremental, else {HISTORY_BEGIN}).")
    parser.add_argument("--end", default=None, help="Override end date (default: today).")
    parser.add_argument("--full", action="store_true", help="Ignore the cache and re-pull the whole history.")
    args = parser.parse_args()
    pull_dataset(args.dataset, begin=args.begin, end=args.end, full=args.full)


if __name__ == "__main__":
    main()
