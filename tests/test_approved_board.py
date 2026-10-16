"""Approved changes must reach held snapshots once, including external-only rows."""
import numpy as np
import pandas as pd
import pytest

from scripts.approved_board import proposal_base, refresh_board
from scripts.apply_proposals import check_sizing
from fantasy_nba.models._core import COUNTING, rescale_to_minutes
from fantasy_nba.models.analyst import parse_overrides
from fantasy_nba.scoring import load_scoring, score_frame


def inputs():
    model = pd.DataFrame([
        dict(PLAYER_ID=1, PLAYER_NAME="One", rank=1, fpts_pg=30., mpg=30., gp=60.,
             fpts_total=1800., target_age=25., fpts_p10=1000., fpts_p25=1300.,
             fpts_p50=1800., fpts_p75=2100., fpts_p90=2300., fpts_median=1800., risk=.7),
        dict(PLAYER_ID=2, PLAYER_NAME="Held", rank=2, fpts_pg=25., mpg=25., gp=65.,
             fpts_total=1625., target_age=28., fpts_p10=950., fpts_p25=1200.,
             fpts_p50=1600., fpts_p75=1900., fpts_p90=2100., fpts_median=1600., risk=.8),
    ])
    model["draft_value"] = [1400., 1293.5]
    accepted = pd.concat([model, pd.DataFrame([dict(PLAYER_ID=3, PLAYER_NAME="Source",
        rank=3, fpts_pg=20., mpg=20., gp=50., fpts_total=1000., market_priced=1,
        seed_class="external_only", adp=np.nan)])], ignore_index=True)
    accepted.loc[accepted.PLAYER_ID.eq(1), "fpts_pg"] = 40.  # earlier analyst boost
    accepted.loc[accepted.PLAYER_ID.eq(2), "fpts_p10"] = 987.  # accepted range != model A
    source = pd.DataFrame([dict(player="Source", external_fpts_pg=20., mpg=20., gp=50.)])
    entries = parse_overrides([
        dict(name="One", date="2026-10-17", category="role", action={"fpts_delta":5.}, rationale="replacement"),
        dict(name="Source", date="2026-10-17", category="role", action={"fpts_delta":2.}, rationale="source replacement"),
    ])
    pool = pd.DataFrame(dict(GP=[60.,65.,70.]*30, AGE=[25.,28.,30.]*30))
    return model, accepted, source, entries, pool


def test_refresh_replaces_instead_of_stacking_and_keeps_held_ranges_and_gp():
    model, old, source, entries, pool = inputs()
    result = refresh_board(model, old, source, entries, pool).set_index("PLAYER_ID")
    assert result.loc[1,"fpts_pg"] == 35.
    assert result.loc[3,"fpts_pg"] == 22.
    assert result.loc[2,"fpts_p10"] == 987.
    assert result.loc[1,"fpts_median"] != 1800.
    assert result.loc[3,"seed_class"] == "external_only"
    assert pd.isna(result.loc[3,"fpts_median"])
    assert pd.isna(result.loc[3,"draft_value"])
    assert result.loc[1,"model_rank"] == 1
    pd.testing.assert_series_equal(result.gp.sort_index(), old.set_index("PLAYER_ID").gp.sort_index())
    assert model.loc[0,"fpts_pg"] == 30. and old.loc[0,"fpts_pg"] == 40.


def test_refresh_retry_and_row_order_do_not_change_values_or_ranges():
    model, old, source, entries, pool = inputs()
    once = refresh_board(model, old, source, entries, pool)
    twice = refresh_board(model.iloc[::-1], once.iloc[::-1], source, entries, pool)
    columns = ["rank", "fpts_pg", "mpg", "gp", "fpts_total", "fpts_p10", "fpts_median", "risk"]
    pd.testing.assert_frame_equal(once.set_index("PLAYER_ID")[columns].sort_index(),
                                  twice.set_index("PLAYER_ID")[columns].sort_index())


def test_missing_original_external_source_fails_closed():
    model, old, source, _, _ = inputs()
    with pytest.raises(ValueError, match="No original source"):
        proposal_base(model, old, source.iloc[:0])


def test_model_toggle_does_not_leak_approved_external_adjustment(tmp_path, monkeypatch):
    import json
    from fantasy_nba.api import boards
    model, accepted, source, _, _ = inputs()
    accepted.loc[accepted.PLAYER_ID.eq(3), "fpts_pg"] = 22.
    accepted["analyst_action"] = ["", "", "fpts_delta:+2"]
    public = accepted.copy()
    public["source_rank"] = public["rank"]
    public["model_source_rank"] = public["rank"]
    directory = tmp_path / "static" / "data"
    directory.mkdir(parents=True)
    (directory/"board.json").write_text(json.dumps(dict(season="2026-27",rows=public.to_dict("records"))))
    model.to_parquet(tmp_path/"learned_2026-27.parquet")
    accepted.to_parquet(tmp_path/"learned_2026-27_analyst.parquet")
    monkeypatch.setattr(boards,"ROOT",tmp_path)
    monkeypatch.setattr(boards,"PROCESSED_DIR",tmp_path)
    monkeypatch.setattr(boards,"load_external_projection",lambda:source)
    assert boards.accepted_board(True).set_index("PLAYER_ID").loc[3,"fpts_pg"] == 22.
    original = boards.accepted_board(False).set_index("PLAYER_ID").loc[3]
    assert original.fpts_pg == 20. and original.analyst_action == ""


def test_default_proposal_preview_includes_original_external_seed(tmp_path, monkeypatch, capsys):
    from scripts import apply_proposals
    from fantasy_nba.api import boards
    from fantasy_nba.models import external_projection
    model, accepted, source, _, _ = inputs()
    path = tmp_path / "learned_2026-27.parquet"
    model.to_parquet(path)
    monkeypatch.setattr(apply_proposals,"PROCESSED_DIR",tmp_path)
    monkeypatch.setattr(boards,"accepted_board",lambda _:accepted)
    monkeypatch.setattr(external_projection,"load_latest",lambda:source)
    proposal=dict(name="Source",date="2026-10-17",category="role",status="approved",
        action={"fpts_delta":2.},rationale="User approval",sizing=dict(base_fpts=20.,
        base_mpg=20.,target_mpg=20.,target_fpm=1.1,target_fpts=22.))
    apply_proposals.preview([proposal],"approved",path)
    output=capsys.readouterr().out
    assert "Source" in output and "20.0" in output and "22.0" in output
    assert "all entries reconcile" in output


def test_exact_sizing_rescores_rounding_and_rejects_false_base():
    stats = dict.fromkeys(COUNTING, .23)
    stats.update(pts=13.37, fgm=4.41, fga=10.29, ftm=2.13, fta=2.61,
                 reb=3.17, ast=2.49, stl=.61, blk=.31, tov=1.27, fg3m=1.71)
    cfg = load_scoring()
    base = round(float(score_frame(pd.DataFrame([stats]), cfg).iloc[0]),2)
    frame = pd.DataFrame([{**stats,"mpg":26.,"fpts_pg":base}])
    rescale_to_minutes(frame,pd.Series([True]),18.,cfg)
    proposal = dict(name="Test",date="2026-10-17",action=dict(target_mpg=18.,
        fpts_delta=16.-frame.loc[0,"fpts_pg"]),sizing=dict(base_fpts=base,base_mpg=26.,
        target_mpg=18.,target_fpm=16./18.,target_fpts=16.,base_stats=stats))
    assert check_sizing([proposal]) == []
    proposal["sizing"]["base_stats"]["pts"] += 1.
    assert any("do not score" in problem for problem in check_sizing([proposal]))
