from __future__ import annotations

import importlib.util
from pathlib import Path

import pandas as pd
import pytest


SCRIPT = Path(__file__).parents[1] / "scripts" / "import_external_projection.py"
SPEC = importlib.util.spec_from_file_location("import_external_projection", SCRIPT)
IMPORTER = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(IMPORTER)


def test_parse_projection_export_repairs_multiline_positions(tmp_path: Path) -> None:
    source = tmp_path / "projections.csv"
    source.write_text(
        "R#\tADP\tPLAYER\tAVG\tPOS\tTEAM\tGP\tMPG\n"
        "1\t1.7\tNikola Jokic\t67.4\t\n"
        "C\n"
        "DEN\t72\t35.1\n"
        "2\t5.6\tGiannis Antetokounmpo\t58.3\t\n"
        "PF\n"
        "C\n"
        "MIA\t69\t34.2\n",
        encoding="utf-8",
    )

    got = IMPORTER.parse_projection_export(source)

    assert list(got.columns) == [
        "external_rank", "player", "team", "pos", "external_fpts_pg", "adp", "gp", "mpg"
    ]
    assert got.to_dict("records") == [
        {
            "external_rank": 1,
            "player": "Nikola Jokic",
            "team": "DEN",
            "pos": "C",
            "external_fpts_pg": 67.4,
            "adp": 1.7,
            "gp": 72,
            "mpg": 35.1,
        },
        {
            "external_rank": 2,
            "player": "Giannis Antetokounmpo",
            "team": "MIA",
            "pos": "PF/C",
            "external_fpts_pg": 58.3,
            "adp": 5.6,
            "gp": 69,
            "mpg": 34.2,
        },
    ]
    assert pd.api.types.is_float_dtype(got["adp"])


def test_parse_projection_export_rejects_rank_gaps(tmp_path: Path) -> None:
    source = tmp_path / "bad.csv"
    source.write_text(
        "R#\tADP\tPLAYER\tAVG\tPOS\tTEAM\tGP\tMPG\n"
        "2\t4.2\tLuka Doncic\t60.3\t\nPG\nLAL\t68\t35.4\n",
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="contiguous"):
        IMPORTER.parse_projection_export(source)
