"""Validate the publishable change archive before GitHub Pages uploads static/."""

from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from scripts.public_history import FILE_RE, HISTORY_COLUMNS


def validate(directory: Path) -> int:
    manifest = json.loads((directory / "manifest.json").read_text(encoding="utf-8"))
    versions = manifest.get("versions")
    if manifest.get("schema") != 1 or not isinstance(versions, list) or len(versions) > 30:
        raise ValueError("Invalid public history manifest")
    seen = set()
    for entry in versions:
        name = entry.get("file", "")
        if not FILE_RE.fullmatch(name) or name in seen:
            raise ValueError("Invalid or duplicate history filename")
        seen.add(name)
        snapshot = json.loads((directory / name).read_text(encoding="utf-8"))
        if set(snapshot) != {"schema", "version", "asof", "season", "rankedBy", "scoringKey", "source", "rows"}:
            raise ValueError("History snapshot contains unexpected fields")
        if snapshot["schema"] != 1 or snapshot["source"] != "public" or snapshot["rankedBy"] != "FP/G ordinal":
            raise ValueError("Invalid public history semantics")
        if any(snapshot[key] != entry[key] for key in ("version", "asof", "season", "rankedBy", "scoringKey", "source")):
            raise ValueError("Manifest and snapshot disagree")
        rows = snapshot["rows"]
        if not isinstance(rows, list) or len(rows) != entry.get("rowCount") or len(rows) > 2000:
            raise ValueError("Invalid history row count")
        if any(set(row) != set(HISTORY_COLUMNS) for row in rows):
            raise ValueError("History row contains private or missing fields")
        ids = [row["PLAYER_ID"] for row in rows]
        if len(ids) != len(set(ids)):
            raise ValueError("Duplicate history player IDs")
    return len(versions)


if __name__ == "__main__":
    count = validate(Path(__file__).resolve().parents[1] / "static" / "data" / "history")
    print(f"Validated {count} redacted public history versions")
