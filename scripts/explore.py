"""Local interactive explorer for the fantasy-nba-27 data + projections.

Run it with:

    python -m streamlit run scripts/explore.py

Three tabs:
  * Draft Board  — the 2026-27 projection with risk ranges; pick a ranking stance, search, filter.
  * Player       — drill into one player: projected line, career history, minutes trend + volatility.
  * Data         — raw dataset browser (season stats, game logs, bio, rosters).

Everything reads the local Parquet cache; projections are computed live (and cached) so they
always reflect the current scoring config.
"""

from __future__ import annotations

import altair as alt
import pandas as pd
import streamlit as st

from fantasy_nba.data import storage
from fantasy_nba.models.projection import project_v2
from fantasy_nba.models.uncertainty import build_gp_pool, rank_board, simulate_ranges
from fantasy_nba.scoring import load_scoring

TARGET_SEASON = "2026-27"
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


@st.cache_data(show_spinner="Computing projections…")
def compute_board(scoring_path: str | None) -> pd.DataFrame:
    raw = load_raw()
    ss, bio = raw["player_season_stats"], raw["player_bio"]
    cfg = load_scoring(scoring_path)
    proj = project_v2(ss, bio, target_season=TARGET_SEASON, cfg=cfg, age_minutes=True)
    pool = build_gp_pool(ss, bio)
    proj = simulate_ranges(proj, pool)
    # Attach a current-ish team label from the most-recent season the player appears in.
    recent = ss.sort_values("SEASON").drop_duplicates("PLAYER_ID", keep="last")
    proj = proj.merge(recent[["PLAYER_ID", "TEAM_ABBREVIATION"]], on="PLAYER_ID", how="left")
    return proj


raw = load_raw()
if raw["player_season_stats"].empty:
    st.error("No data cached yet. Run `python scripts/pull_data.py --seasons …` first.")
    st.stop()

cfg = load_scoring()
board_full = compute_board(None)

st.title("🏀 Fantasy NBA Explorer")
st.caption(
    f"Projection: **v2m** for **{TARGET_SEASON}**  ·  scoring: **{cfg.name}** "
    f"(⚠ default weights are placeholders — set yours in `config/scoring.yaml`)  ·  "
    f"{len(board_full):,} players  ·  seasons {raw['player_season_stats']['SEASON'].min()}–"
    f"{raw['player_season_stats']['SEASON'].max()}"
)

tab_board, tab_player, tab_data = st.tabs(["📋 Draft Board", "🔍 Player", "📚 Data"])


# ---------------------------------------------------------------------------------- draft board
with tab_board:
    c1, c2, c3, c4 = st.columns([1.4, 1.2, 1, 1])
    stance = c1.selectbox("Rank by", list(RANK_HELP), format_func=lambda s: s.capitalize(),
                          help="\n".join(f"{k}: {v}" for k, v in RANK_HELP.items()))
    search = c2.text_input("Search player", placeholder="e.g. Jokic")
    teams = ["All"] + sorted(board_full["TEAM_ABBREVIATION"].dropna().unique().tolist())
    team = c3.selectbox("Team", teams)
    top_n = c4.slider("Show top", 10, 300, 60, step=10)

    board = rank_board(board_full, method=stance)
    if search:
        board = board[board["PLAYER_NAME"].str.contains(search, case=False, na=False)]
    if team != "All":
        board = board[board["TEAM_ABBREVIATION"] == team]
    board = board.head(top_n)

    st.caption(f"**{RANK_HELP[stance]}**")
    cols = ["rank", "PLAYER_NAME", "TEAM_ABBREVIATION", "target_age", "gp", "mpg", "fpts_pg",
            "draft_value", "fpts_p10", "fpts_median", "fpts_p90", "risk"]
    st.dataframe(
        board[cols],
        hide_index=True,
        width="stretch",
        height=560,
        column_config={
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
        },
    )

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


# -------------------------------------------------------------------------------------- player
with tab_player:
    names = board_full.sort_values("rank")["PLAYER_NAME"].tolist()
    default = names.index("Nikola Jokić") if "Nikola Jokić" in names else 0
    who = st.selectbox("Player", names, index=default)
    row = board_full[board_full["PLAYER_NAME"] == who].iloc[0]
    pid = row["PLAYER_ID"]

    m = st.columns(6)
    m[0].metric("Proj rank", int(rank_board(board_full, "safe").set_index("PLAYER_ID").loc[pid, "rank"]))
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
            sel = f1.selectbox("Season", seasons)
            if sel != "All":
                df = df[df["SEASON"] == sel]
        namecol = "PLAYER_NAME" if "PLAYER_NAME" in df.columns else ("PLAYER" if "PLAYER" in df.columns else None)
        if namecol:
            q = f2.text_input("Search player", key="data_search")
            if q:
                df = df[df[namecol].str.contains(q, case=False, na=False)]
        st.caption(f"{len(df):,} rows × {df.shape[1]} columns")
        st.dataframe(df, hide_index=True, width="stretch", height=560)
