"""The frozen EXP-029 pair must preserve arithmetic without private rationale."""

from datetime import date
import sys

import pandas as pd
import pytest

from fantasy_nba.models.analyst import name_key
from scripts import freeze_preseason
from scripts.freeze_preseason import build_freeze_pair, write_pair


def _model():
    return pd.DataFrame([
        {"PLAYER_ID": 1, "PLAYER_NAME": "Alpha", "rank": 1, "gp": 70, "mpg": 30,
         "fpts_pg": 20.0, "fpts_total": 1400.0, "pts": 12.0},
        {"PLAYER_ID": 2, "PLAYER_NAME": "Beta", "rank": 2, "gp": 70, "mpg": 28,
         "fpts_pg": 18.0, "fpts_total": 1260.0, "pts": 10.0},
    ])


def _entries():
    return [{"name": "Beta", "name_key": name_key("Beta"), "date": pd.Timestamp("2026-10-14"),
             "category": "role", "kind": "fpts_delta", "value": 3.0,
             "target_mpg": None, "fpts_delta": 3.0, "rank_delta": None,
             "rationale": "PRIVATE BBM details must not enter the repository", "_pos": 0}]


def test_cli_requires_separate_final_review_before_preflight(monkeypatch, capsys):
    monkeypatch.setattr(sys, "argv", ["freeze_preseason.py", "--as-of", "2026-10-14", "--write"])
    monkeypatch.setattr(freeze_preseason, "audit", lambda *_: pytest.fail("preflight ran during hold"))
    assert freeze_preseason.main() == 2
    assert "paused by the 2026-10-14 user direction" in capsys.readouterr().out


def test_frozen_pair_reuses_approved_arithmetic_and_redacts_rationale():
    source = _model()
    model, analyst = build_freeze_pair(source, _entries())
    assert source.loc[1, "fpts_pg"] == 18.0
    assert model.equals(source)
    assert analyst.loc[analyst["PLAYER_ID"] == 2, "fpts_pg"].iloc[0] == 21.0
    assert analyst.loc[analyst["PLAYER_ID"] == 2, "model_rank"].iloc[0] == 2
    assert analyst["rank"].tolist() == [1, 2]
    assert "analyst_rationale" not in analyst
    assert "PRIVATE BBM" not in analyst.to_string()


def test_unreviewed_model_columns_fail_closed():
    source = _model().assign(private_note="keep local")
    with pytest.raises(ValueError, match="unexpected"):
        build_freeze_pair(source, _entries())


def test_write_pair_is_immutable_and_records_input_hashes(tmp_path):
    model, analyst = build_freeze_pair(_model(), _entries())
    source = tmp_path / "source.parquet"
    overrides = tmp_path / "overrides.yaml"
    scoring = tmp_path / "scoring.yaml"
    model.to_parquet(source)
    overrides.write_text("private history", encoding="utf-8")
    scoring.write_text("weights", encoding="utf-8")
    paths = [tmp_path / name for name in ("frozen_model.parquet", "frozen_analyst.parquet", "manifest.json")]
    with pytest.raises(ValueError, match="Private analyst rationale"):
        write_pair(model, analyst.assign(analyst_rationale="private"), *paths,
                   source, overrides, scoring, date(2026, 10, 14))
    assert not any(path.exists() for path in paths)
    manifest = write_pair(model, analyst, *paths, source, overrides, scoring, date(2026, 10, 14))
    assert manifest["player_count"] == 2
    assert "analyst_rationale" not in pd.read_parquet(paths[1]).columns
    assert "private history" not in paths[2].read_text(encoding="utf-8")
    before = [path.read_bytes() for path in paths]
    with pytest.raises(FileExistsError):
        write_pair(model, analyst, *paths, source, overrides, scoring, date(2026, 10, 14))
    assert before == [path.read_bytes() for path in paths]
