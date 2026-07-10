"""Local interactive explorer for the fantasy-nba-27 data + projections.

Run it with:

    python -m streamlit run scripts/explore.py

Four tabs:
  * Draft Board  — projection with risk ranges; pick the target season (past seasons are
                   re-projected no-leakage and shown next to actual results), projection model
                   (learned — the Step-15 default — / baseline / v2 / v2m), and ranking stance;
                   D1 decision columns (VOR, ADP) join automatically when the target's
                   draft-sheet parquet exists; search and filter.
  * ROS          — the in-season remaining-of-season board: latest data/processed/ros_board/
                   nightly snapshot (update_daily.py cron) with the naive-updater disagreement.
  * Player       — drill into one player: projected line, career history, minutes trend + volatility.
  * Data         — raw dataset browser (season stats, game logs, bio, rosters).

Everything reads the local Parquet cache; projections are computed live (and cached) so they
always reflect the current scoring config.
"""

from __future__ import annotations

import altair as alt
import pandas as pd
import streamlit as st

from fantasy_nba.config import PROCESSED_DIR
from fantasy_nba.data import storage
from fantasy_nba.models._core import _season_start
from fantasy_nba.models.aging import build_aging_curves
from fantasy_nba.models.backtest import _actual
from fantasy_nba.models.baseline import project_baseline
from fantasy_nba.models.durability import build_gp_age_curve
from fantasy_nba.models.learned import project_learned
from fantasy_nba.models.minutes import build_minutes_age_curve
from fantasy_nba.models.projection import project_v2
from fantasy_nba.models.uncertainty import build_gp_pool, rank_board, simulate_ranges
from fantasy_nba.scoring import load_scoring

DEFAULT_TARGET = "2026-27"
# Seasons you can project. Past ones are re-projected with **no leakage** (only prior-season
# data; aging/GP/minutes curves refit on the training years) so the board is a fair "what would
# the model have said", and actual results are shown alongside.
TARGET_SEASONS = ["2026-27", "2025-26", "2024-25", "2023-24", "2022-23"]
MODELS = {
    "learned": "learned — LightGBM decompositional (EXP-007; the shipped default)",
    "v2m": "v2m — v2 + minutes aging",
    "v2": "v2 — empirical aging curves + durability",
    "baseline": "baseline — Marcel (recency-weighted rates)",
}
RANK_HELP = {
    "safe": "median − ½·downside — as accurate as median but demotes injury-prone players (default)",
    "median": "expected (median) season total",
    "floor": "10th-percentile total — maximise safety",
    "ceiling": "90th-percentile total — maximise upside",
}

st.set_page_config(page_title="Fantasy NBA Explorer", page_icon="🏀", layout="wide")


# --------------------------------------------------------------------------------------- data
@st.cache_data(show_spinner=False)
def load_raw() -> dict[str, pd.DataFrame]:
    out = {}
    for name in ("player_season_stats", "player_bio", "player_game_logs", "team_rosters"):
        try:
            out[name] = storage.read(name)
        except FileNotFoundError:
            out[name] = pd.DataFrame()
    return out


@st.cache_data(show_spinner=False)
def load_injury_profile() -> tuple[pd.DataFrame | None, pd.DataFrame | None]:
    """(spells, chronic_flag_table) for the adopted (age × chronic) GP pools (EXP-015/7.3b);
    (None, None) when the injuries pull isn't cached."""
    if not storage.exists("injuries"):
        return None, None
    from fantasy_nba.models import injuries as inj

    ss = load_raw()["player_season_stats"]
    spells, _ = inj.build_spells(storage.read("injuries"), ss)
    chronic = inj.chronic_flag_table(spells, sorted(ss["SEASON"].unique(), key=_season_start))
    return spells, chronic


@st.cache_data(show_spinner="Computing projections…")
def compute_board(target: str, model: str, scoring_path: str | None) -> pd.DataFrame:
    """No-leakage projection for ``target`` with ``model``, plus risk ranges and (for past
    seasons) the actual outcome joined on."""
    raw = load_raw()
    ss, bio = raw["player_season_stats"], raw["player_bio"]
    cfg = load_scoring(scoring_path)
    ty = _season_start(target)
    max_year = int(ss["SEASON"].map(_season_start).max())

    tr_ss = ss[ss["SEASON"].map(_season_start) < ty]
    tr_bio = bio[bio["SEASON"].map(_season_start) < ty]

    if model == "learned":
        proj = project_learned(tr_ss, tr_bio, target_season=target, cfg=cfg)
    elif model == "baseline":
        proj = project_baseline(tr_ss, tr_bio, target_season=target, cfg=cfg)
    else:
        curves = build_aging_curves(tr_ss, tr_bio, save=False)
        gpc = build_gp_age_curve(tr_ss, tr_bio, save=False)
        mc = build_minutes_age_curve(tr_ss, tr_bio, save=False) if model == "v2m" else None
        proj = project_v2(tr_ss, tr_bio, target_season=target, cfg=cfg, curves=curves,
                          gp_curve=gpc, mpg_curve=mc, age_minutes=(model == "v2m"))

    # Risk ranges — SD_PG spread (EXP-021 re-affirmed it) on the adopted (age × chronic) pools.
    spells, chronic = load_injury_profile()
    if spells is not None:
        from fantasy_nba.models.injuries import injury_features

        flags = injury_features(spells, f"{ty}-10-01")[["PLAYER_ID", "inj_chronic_flag"]]
        proj = proj.merge(flags, on="PLAYER_ID", how="left")
        proj["inj_chronic_flag"] = proj["inj_chronic_flag"].fillna(0).astype(int)
    pool = build_gp_pool(tr_ss, tr_bio, max_start_year=ty, injury_profile=chronic)
    proj = simulate_ranges(proj, pool)
    recent = tr_ss.sort_values("SEASON").drop_duplicates("PLAYER_ID", keep="last")
    proj = proj.merge(recent[["PLAYER_ID", "TEAM_ABBREVIATION"]], on="PLAYER_ID", how="left")

    # D1 decision columns ride along when the target's draft sheet has been generated.
    sheet_path = PROCESSED_DIR / f"draft_sheet_{target}.parquet"
    if sheet_path.exists():
        sheet = pd.read_parquet(sheet_path)
        d1_cols = [c for c in ("vor", "vor_rank", "adp", "market_priced") if c in sheet.columns]
        proj = proj.merge(sheet[["PLAYER_ID"] + d1_cols].drop_duplicates("PLAYER_ID"),
                          on="PLAYER_ID", how="left")

    if ty <= max_year:  # season already happened — attach actuals + true finish rank
        act = _actual(ss, target, cfg, 0.0).copy()
        act["actual_rank"] = act["act_fpts_total"].rank(ascending=False, method="min").astype(int)
        proj = proj.merge(
            act[["PLAYER_ID", "act_fpts_pg", "act_fpts_total", "act_gp", "actual_rank"]],
            on="PLAYER_ID", how="left",
        )
    return proj


raw = load_raw()
if raw["player_season_stats"].empty:
    st.error("No data cached yet. Run `python scripts/pull_data.py --seasons …` first.")
    st.stop()

cfg = load_scoring()
board_2027 = compute_board(DEFAULT_TARGET, "learned", None)  # canonical board for the Player tab

st.title("🏀 Fantasy NBA Explorer")
st.caption(
    f"Scoring: **{cfg.name}** (edit `config/scoring.yaml` for your league)  ·  "
    f"{len(board_2027):,} players projected  ·  data seasons "
    f"{raw['player_season_stats']['SEASON'].min()}–{raw['player_season_stats']['SEASON'].max()}"
)

tab_board, tab_ros, tab_player, tab_data = st.tabs(
    ["📋 Draft Board", "📈 ROS (in-season)", "🔍 Player", "📚 Data"])


# ---------------------------------------------------------------------------------- draft board
with tab_board:
    c1, c2, c3, c4 = st.columns([1, 1.6, 1.4, 1])
    target = c1.selectbox("Season", TARGET_SEASONS,
                          help="Past seasons are re-projected with no leakage, then compared to what actually happened.")
    model = c2.selectbox("Projection", list(MODELS), format_func=lambda m: MODELS[m])
    stance = c3.selectbox("Rank by", list(RANK_HELP), format_func=lambda s: s.capitalize(),
                          help="\n".join(f"{k}: {v}" for k, v in RANK_HELP.items()))
    top_n = c4.slider("Show top", 10, 300, 60, step=10)

    c5, c6 = st.columns([2, 1])
    search = c5.text_input("Search player", placeholder="e.g. Jokic")
    board_src = compute_board(target, model, None)
    teams = ["All"] + sorted(board_src["TEAM_ABBREVIATION"].dropna().unique().tolist())
    team = c6.selectbox("Team", teams)

    has_actuals = "actual_rank" in board_src.columns
    board = rank_board(board_src, method=stance)
    if search:
        board = board[board["PLAYER_NAME"].str.contains(search, case=False, na=False)]
    if team != "All":
        board = board[board["TEAM_ABBREVIATION"] == team]
    board = board.head(top_n)

    note = f"**{MODELS[model].split(' — ')[0]}** · {RANK_HELP[stance]}"
    if has_actuals:
        # How well did this board's top-N line up with who actually finished top-N?
        n = min(top_n, len(board_src))
        proj_top = set(rank_board(board_src, stance).head(n)["PLAYER_ID"])
        act_top = set(board_src.dropna(subset=["actual_rank"]).nsmallest(n, "actual_rank")["PLAYER_ID"])
        hit = len(proj_top & act_top) / n if n else 0
        note += f"  ·  ⬅ historical: **{hit*100:.0f}%** of this top-{n} finished in the actual top-{n}"
    st.caption(note)

    cols = ["rank", "PLAYER_NAME", "TEAM_ABBREVIATION", "target_age", "gp", "mpg", "fpts_pg",
            "draft_value", "fpts_p10", "fpts_median", "fpts_p90", "risk"]
    cols += [c for c in ("vor", "vor_rank", "adp") if c in board.columns]  # D1 decision columns
    col_cfg = {
        "vor": st.column_config.NumberColumn("VOR", format="%.1f",
                                             help="fpts/g above the league replacement level (D1.2)"),
        "vor_rank": st.column_config.NumberColumn("VOR rank", format="%d"),
        "adp": st.column_config.NumberColumn("ADP", format="%.0f",
                                             help="platform ADP — draft-day availability only, not value"),
        "PLAYER_NAME": "Player",
        "TEAM_ABBREVIATION": "Team",
        "target_age": st.column_config.NumberColumn("Age", format="%.1f"),
        "gp": st.column_config.NumberColumn("GP", format="%d"),
        "mpg": st.column_config.NumberColumn("MPG", format="%.1f"),
        "fpts_pg": st.column_config.NumberColumn("Avg FP/G", format="%.1f"),
        "draft_value": st.column_config.NumberColumn("Draft value", format="%d"),
        "fpts_p10": st.column_config.NumberColumn("Floor", format="%d"),
        "fpts_median": st.column_config.NumberColumn("Median", format="%d"),
        "fpts_p90": st.column_config.NumberColumn("Ceiling", format="%d"),
        "risk": st.column_config.ProgressColumn("Risk", min_value=0.0, max_value=1.2, format="%.2f"),
    }
    if has_actuals:  # show what actually happened next to the projection
        cols += ["actual_rank", "act_fpts_pg", "act_fpts_total"]
        col_cfg.update({
            "actual_rank": st.column_config.NumberColumn("Actual rank", format="%d",
                                                         help="True finish rank by real season total"),
            "act_fpts_pg": st.column_config.NumberColumn("Actual FP/G", format="%.1f"),
            "act_fpts_total": st.column_config.NumberColumn("Actual total", format="%d"),
        })
    st.dataframe(board[cols], hide_index=True, width="stretch", height=560, column_config=col_cfg)

    st.subheader("Floor → median → ceiling")
    n_chart = min(len(board), 30)
    cd = board.head(n_chart)
    base = alt.Chart(cd)
    rng = base.mark_rule(size=3, opacity=0.4).encode(
        x=alt.X("fpts_p10:Q", title="Projected season fantasy points"),
        x2="fpts_p90:Q",
        y=alt.Y("PLAYER_NAME:N", sort=cd["PLAYER_NAME"].tolist(), title=None),
    )
    med = base.mark_point(size=70, filled=True, color="#e45756").encode(
        x="fpts_median:Q", y=alt.Y("PLAYER_NAME:N", sort=cd["PLAYER_NAME"].tolist()),
        tooltip=["PLAYER_NAME", "fpts_p10", "fpts_median", "fpts_p90", "risk"],
    )
    st.altair_chart((rng + med).properties(height=max(300, n_chart * 22)), width="stretch")


# ----------------------------------------------------------------------------------------- ROS
with tab_ros:
    ros_dir = PROCESSED_DIR / "ros_board"
    snaps = sorted(ros_dir.glob("*.parquet")) if ros_dir.exists() else []
    if not snaps:
        st.info(
            "No nightly ROS snapshots yet — they appear in `data/processed/ros_board/` once "
            "`scripts/update_daily.py` crons from opening night. Each snapshot is the "
            "as-of-date remaining-of-season board (EWMA config, status overrides) with the "
            "naive-updater benchmark line; DARKO / market disagreement stays in the CLI "
            "reports (`darko_report.py`, `market_report.py`)."
        )
    else:
        pick = st.selectbox("Snapshot date", [p.stem for p in reversed(snaps)])
        ros = pd.read_parquet(ros_dir / f"{pick}.parquet")
        st.caption(f"{len(ros):,} players · as of **{pick}** (nightly `update_daily.py`)")
        ros_cols = [c for c in ("rank", "PLAYER_NAME", "games_so_far", "gp", "mpg", "fpts_pg",
                                "fpts_total", "naive_fpts_pg", "naive_rank", "status_override")
                    if c in ros.columns]
        q = st.text_input("Search player", key="ros_search")
        view = ros[ros["PLAYER_NAME"].str.contains(q, case=False, na=False)] if q else ros
        st.dataframe(view[ros_cols].head(300), hide_index=True, width="stretch", height=480)
        if {"rank", "naive_rank"} <= set(ros.columns):
            st.subheader("Model vs naive updater — biggest disagreements")
            d = ros.dropna(subset=["naive_rank"]).copy()
            d["rank_gap"] = d["naive_rank"] - d["rank"]
            top_d = d.reindex(d["rank_gap"].abs().sort_values(ascending=False).index)
            st.dataframe(
                top_d[["PLAYER_NAME", "rank", "naive_rank", "rank_gap", "fpts_pg",
                       "naive_fpts_pg"]].head(25),
                hide_index=True, width="stretch",
            )
            st.caption("Positive gap = our as-of model is higher on the player than the naive "
                       "shrinkage line — the standing daily disagreement signal (addendum 5).")


# -------------------------------------------------------------------------------------- player
with tab_player:
    st.caption(f"Projected line for **{DEFAULT_TARGET}** (learned — the shipped default).")
    names = board_2027.sort_values("rank")["PLAYER_NAME"].tolist()
    default = names.index("Nikola Jokić") if "Nikola Jokić" in names else 0
    who = st.selectbox("Player", names, index=default)
    row = board_2027[board_2027["PLAYER_NAME"] == who].iloc[0]
    pid = row["PLAYER_ID"]

    m = st.columns(6)
    m[0].metric("Proj rank", int(rank_board(board_2027, "safe").set_index("PLAYER_ID").loc[pid, "rank"]))
    m[1].metric("Age", f"{row['target_age']:.0f}")
    m[2].metric("Proj GP", f"{row['gp']:.0f}")
    m[3].metric("Proj MPG", f"{row['mpg']:.1f}")
    m[4].metric("FP / game", f"{row['fpts_pg']:.1f}")
    m[5].metric("Median total", f"{row['fpts_median']:.0f}",
                help=f"Floor {row['fpts_p10']:.0f} · Ceiling {row['fpts_p90']:.0f} · risk {row['risk']:.2f}")

    st.markdown(
        f"**Range:** floor **{row['fpts_p10']:.0f}** → median **{row['fpts_median']:.0f}** "
        f"→ ceiling **{row['fpts_p90']:.0f}**  (risk {row['risk']:.2f})"
    )

    ss = raw["player_season_stats"]
    hist = ss[ss["PLAYER_ID"] == pid].copy()
    hist = hist.groupby("SEASON", as_index=False).agg(
        AGE=("AGE", "max"), TEAM=("TEAM_ABBREVIATION", "last"), GP=("GP", "sum"),
        MIN=("MIN", "sum"), PTS=("PTS", "sum"), REB=("REB", "sum"), AST=("AST", "sum"),
        STL=("STL", "sum"), BLK=("BLK", "sum"), FG3M=("FG3M", "sum"), TOV=("TOV", "sum"),
        USG=("USG_PCT", "mean"),
    ).sort_values("SEASON")
    for s in ["PTS", "REB", "AST", "STL", "BLK", "FG3M", "TOV", "MIN"]:
        hist[s] = (hist[s] / hist["GP"]).round(1)
    hist["MPG"] = hist["MIN"]
    hist = hist.rename(columns={"MIN": "_min"})

    left, right = st.columns([1.1, 1])
    with left:
        st.subheader("Career (per game)")
        st.dataframe(
            hist[["SEASON", "AGE", "TEAM", "GP", "MPG", "PTS", "REB", "AST", "STL", "BLK", "FG3M", "TOV", "USG"]],
            hide_index=True, width="stretch",
            column_config={"USG": st.column_config.NumberColumn("USG%", format="%.1f")},
        )
        st.subheader("Minutes per game by season")
        mchart = alt.Chart(hist).mark_line(point=True).encode(
            x=alt.X("SEASON:N", title=None), y=alt.Y("MPG:Q", title="MPG"),
            tooltip=["SEASON", "MPG", "GP"],
        )
        st.altair_chart(mchart.properties(height=220), width="stretch")

    with right:
        gl = raw["player_game_logs"]
        if not gl.empty:
            plog = gl[gl["PLAYER_ID"] == pid].copy()
            latest = plog["SEASON"].max() if not plog.empty else None
            if latest:
                st.subheader(f"Per-game minutes — {latest}")
                cur = plog[plog["SEASON"] == latest].sort_values("GAME_DATE")
                cur = cur.reset_index(drop=True); cur["game"] = cur.index + 1
                gchart = alt.Chart(cur).mark_bar(size=6).encode(
                    x=alt.X("game:Q", title="Game #"),
                    y=alt.Y("MIN:Q", title="Minutes"),
                    tooltip=["GAME_DATE", "MIN", "PTS"],
                )
                st.altair_chart(gchart.properties(height=220), width="stretch")
                st.caption(
                    f"{len(cur)} games · mean {cur['MIN'].mean():.1f} · "
                    f"std {cur['MIN'].std():.1f} (higher = more volatile role)"
                )


# ---------------------------------------------------------------------------------------- data
with tab_data:
    labels = {
        "player_season_stats": "Season stats (per-player-season totals + advanced)",
        "player_game_logs": "Game logs (one row per player per game)",
        "player_bio": "Bio (age, height, draft, college)",
        "team_rosters": "Current rosters",
    }
    ds = st.selectbox("Dataset", list(labels), format_func=lambda k: labels[k])
    df = raw[ds]
    if df.empty:
        st.info("Not cached. Pull it with `python scripts/pull_data.py`.")
    else:
        f1, f2 = st.columns(2)
        if "SEASON" in df.columns:
            seasons = ["All"] + sorted(df["SEASON"].unique(), reverse=True)
            sel = f1.selectbox("Season", seasons, key="data_season")
            if sel != "All":
                df = df[df["SEASON"] == sel]
        namecol = "PLAYER_NAME" if "PLAYER_NAME" in df.columns else ("PLAYER" if "PLAYER" in df.columns else None)
        if namecol:
            q = f2.text_input("Search player", key="data_search")
            if q:
                df = df[df[namecol].str.contains(q, case=False, na=False)]
        st.caption(f"{len(df):,} rows × {df.shape[1]} columns")
        st.dataframe(df, hide_index=True, width="stretch", height=560)
