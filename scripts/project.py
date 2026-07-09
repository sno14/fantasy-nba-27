"""Generate baseline projections for a target season and save the ranked table.

Example
-------
    python scripts/project.py --target 2026-27 --top 30
"""

from __future__ import annotations

import argparse
import sys

# Windows consoles default to cp1252, which can't print accented player names (Jokić, etc.).
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

from fantasy_nba.data import storage
from fantasy_nba.models.baseline import project_baseline
from fantasy_nba.models.learned import project_learned
from fantasy_nba.models.projection import project_v2
from fantasy_nba.scoring import load_scoring


def main() -> None:
    parser = argparse.ArgumentParser(description="Fantasy projections for a season.")
    parser.add_argument("--target", default="2026-27", help="Season to project (e.g. 2026-27).")
    parser.add_argument("--top", type=int, default=30, help="How many rows to print.")
    parser.add_argument(
        "--model",
        default="v2m",
        choices=["baseline", "v2", "v2m", "learned", "learned_ps"],
        help="baseline (Marcel); v2 (+ empirical aging curves & durability); "
        "v2m (+ Stage 3 minutes aging curve); learned (LightGBM decompositional model, EXP-007 — "
        "the Stage-7 foundation: best per-game MAE and least mean-reverting on movers); "
        "learned_ps (+ EXP-027b preseason-October role features — the adopted pre-draft "
        "configuration once the target's October games are cached: pools ~+9pp more eventual "
        "big risers at better aggregate MAE). "
        "Backtests: baseline~v2; v2m improves minutes MAE; learned improves both further.",
    )
    parser.add_argument(
        "--scoring", default=None, help="Path to a scoring YAML (defaults to config/scoring.yaml)."
    )
    parser.add_argument(
        "--ranges", action="store_true",
        help="Add Monte-Carlo risk ranges (floor/median/ceiling totals + risk score). Season "
        "totals are availability-driven and unpredictable, so ranges are the honest output.",
    )
    parser.add_argument(
        "--rank-by", default=None, choices=["safe", "median", "floor", "ceiling"],
        help="Re-rank the board by risk stance (implies --ranges). 'safe' (default when set) "
        "applies a mild downside penalty: as accurate as median but demotes injury-prone players.",
    )
    parser.add_argument(
        "--breakout", action="store_true",
        help="Add the EXP-026 breakout_p column (P(fpts/g jump ≥ +6), walk-forward archetype "
        "classifier). Informational only — it never re-ranks (the rank-boost policy failed its "
        "gate); the D2 analyst pass reads it as the option-value flag.",
    )
    parser.add_argument(
        "--preseason", action="store_true",
        help="Add the Step-9c October-role columns (ps_mpg / ps_mpg_delta / ps_start_share) "
        "from the cached preseason game logs. Ships regardless of the EXP-027b A/B verdict — "
        "'the coach played him 34 minutes with the starters in October' is directly "
        "human-readable days before the draft. No-ops with a note until the target season's "
        "preseason games have been pulled.",
    )
    args = parser.parse_args()

    season_stats = storage.read("player_season_stats")
    bio = storage.read("player_bio")
    cfg = load_scoring(args.scoring)

    if args.model == "learned_ps":
        from fantasy_nba.models import preseason as pre

        logs = storage.read("preseason_game_logs")
        if args.target not in set(logs["SEASON"]):
            raise SystemExit(
                f"--model learned_ps needs {args.target} preseason games cached — re-pull "
                "preseason_game_logs once October exhibition play starts (until then use "
                "--model learned)."
            )
        table = pre.preseason_feature_table(logs, season_stats)
        proj = project_learned(season_stats, bio, target_season=args.target, cfg=cfg,
                               use_preseason=True, preseason_table=table)
    elif args.model == "learned":
        proj = project_learned(season_stats, bio, target_season=args.target, cfg=cfg)
    elif args.model == "v2m":
        proj = project_v2(season_stats, bio, target_season=args.target, cfg=cfg, age_minutes=True)
    elif args.model == "v2":
        proj = project_v2(season_stats, bio, target_season=args.target, cfg=cfg)
    else:
        proj = project_baseline(season_stats, bio, target_season=args.target, cfg=cfg)

    show = ["rank", "PLAYER_NAME", "target_age", "gp", "mpg", "pts", "reb", "ast",
            "stl", "blk", "fg3m", "tov", "fpts_pg", "fpts_total"]
    if args.ranges or args.rank_by:
        from fantasy_nba.models.uncertainty import build_gp_pool, rank_board, simulate_ranges

        injury_profile = None
        if storage.exists("injuries"):
            # EXP-015 (7.3b, adopted): (age × chronic) GP pool — chronic players sample their
            # own fatter left tail. Skipped gracefully when the injuries pull doesn't exist.
            from fantasy_nba.models import injuries as inj
            from fantasy_nba.models._core import _season_start

            spells, _ = inj.build_spells(storage.read("injuries"), season_stats)
            seasons = sorted(season_stats["SEASON"].unique())
            injury_profile = inj.chronic_flag_table(spells, seasons)
            flags = inj.injury_features(spells, f"{_season_start(args.target)}-10-01")
            proj = proj.merge(flags[["PLAYER_ID", "inj_chronic_flag"]], on="PLAYER_ID", how="left")
            proj["inj_chronic_flag"] = proj["inj_chronic_flag"].fillna(0).astype(int)

        pool = build_gp_pool(season_stats, bio, injury_profile=injury_profile)
        proj = simulate_ranges(proj, pool)
        show = ["rank", "PLAYER_NAME", "target_age", "gp", "mpg", "fpts_pg",
                "fpts_p10", "fpts_median", "fpts_p90", "risk"]
        if args.rank_by:
            proj = rank_board(proj, method=args.rank_by)
            show = ["rank", "PLAYER_NAME", "target_age", "gp", "mpg", "fpts_pg", "draft_value",
                    "fpts_p10", "fpts_median", "fpts_p90", "risk"]

    if args.breakout:
        from fantasy_nba.models import breakout as brk

        cached = sorted(season_stats["SEASON"].unique())
        seasons = cached[1:] + ([args.target] if args.target not in cached else [])
        table = brk.breakout_feature_table(season_stats, bio, cfg, seasons=seasons)
        labels = brk.breakout_labels(season_stats, cfg)
        scores = brk.breakout_scores(table, labels, args.target)
        proj = proj.merge(scores, on="PLAYER_ID", how="left")
        proj["breakout_p"] = proj["breakout_p"].fillna(0.0).round(3)
        show.append("breakout_p")

    if args.preseason:
        from fantasy_nba.models import preseason as pre

        logs = storage.read("preseason_game_logs")
        if args.target in set(logs["SEASON"]):
            table = pre.preseason_feature_table(logs, season_stats, seasons=[args.target])
            proj = proj.merge(table.drop(columns="SEASON"), on="PLAYER_ID", how="left")
            for col in pre.PRESEASON_FEATURES:
                proj[col] = proj[col].round(2)
            show += pre.PRESEASON_FEATURES
        else:
            print(f"[preseason] no {args.target} preseason games cached yet — columns skipped "
                  "(re-pull preseason_game_logs once October exhibition play starts).")

    path = storage.write(proj, f"{args.model}_{args.target}", layer="processed")
    print(f"Scoring: {cfg.name}  |  players projected: {len(proj):,}")
    print(f"Saved -> {path}\n")

    with_pd_opts(lambda: print(proj[show].head(args.top).to_string(index=False)))


def with_pd_opts(fn):
    import pandas as pd

    with pd.option_context("display.width", 200, "display.max_columns", None):
        fn()


if __name__ == "__main__":
    main()
