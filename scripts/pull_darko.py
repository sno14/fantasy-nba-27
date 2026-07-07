"""Fetch the current DARKO projections CSV from darko.app (ROADMAP Stage 7.E / EXP-010).

DARKO (Kostya Medvedovsky) is a daily-updating Bayesian box-score skill projection. The site
renders its table client-side and exposes a **"Download CSV"** button but no public API, so we
drive a headless browser (Playwright) to click it and capture the labeled export.

Two purposes:
  * **Live use (now):** the freshest DARKO board to blend / disagreement-check against ours
    (``models/darko.py``). Adopted *live-only* — we cannot backtest it (no historical as-of-date
    snapshots are published; see EXPERIMENTS.md EXP-010 and memory darko-data-availability).
  * **Archive (free byproduct):** every pull is stored **append-only, date-stamped**
    (``data/raw/darko/darko_YYYY-MM-DD.csv``). Accumulating these daily is the only way to
    eventually get real as-of-date DARKO history to backtest with.

Requires a Playwright browser: ``python -m playwright install chromium`` (already present here).

Example
-------
    python scripts/pull_darko.py
"""

from __future__ import annotations

import argparse
import datetime as dt
import sys
from pathlib import Path

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

import pandas as pd

from fantasy_nba.config import RAW_DIR

DARKO_URL = "https://www.darko.app/"
DARKO_DIR = RAW_DIR / "darko"


def fetch_darko(dest_dir: Path = DARKO_DIR, url: str = DARKO_URL, timeout_ms: int = 60000) -> Path:
    """Render darko.app, click "Download CSV", and save it date-stamped. Returns the CSV path."""
    from playwright.sync_api import sync_playwright

    dest_dir.mkdir(parents=True, exist_ok=True)
    today = dt.date.today().isoformat()
    csv_path = dest_dir / f"darko_{today}.csv"

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page(accept_downloads=True)
        page.goto(url, wait_until="networkidle", timeout=timeout_ms)
        page.wait_for_timeout(2500)  # let the table hydrate
        with page.expect_download(timeout=timeout_ms) as dl_info:
            page.get_by_role("button", name="Download CSV").click()
        dl_info.value.save_as(str(csv_path))
        browser.close()

    # Normalize to parquet alongside the raw CSV so the rest of the pipeline reads it uniformly.
    df = pd.read_csv(csv_path)
    df.to_parquet(dest_dir / f"darko_{today}.parquet", index=False)
    print(f"Saved {len(df)} rows -> {csv_path}")
    print("Columns:", list(df.columns))
    return csv_path


def main() -> None:
    parser = argparse.ArgumentParser(description="Pull current DARKO projections (Playwright).")
    parser.add_argument("--url", default=DARKO_URL)
    args = parser.parse_args()
    fetch_darko(url=args.url)


if __name__ == "__main__":
    main()
