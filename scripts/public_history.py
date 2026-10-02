"""Redacted, versioned public projection history for What Changed?.

Only exporter-created snapshots enter this archive. The existing current board is
never relabelled as a historical baseline. A manifest advertises up to 30 versions;
older files are removed only after the new manifest is safely written.
"""

from __future__ import annotations

import hashlib
import json
import re
from datetime import UTC, datetime
from pathlib import Path


HISTORY_COLUMNS = (
    "PLAYER_ID", "PLAYER_NAME", "TEAM_ABBREVIATION", "rank", "fpts_pg", "mpg",
    "analyst_action", "analyst_date",
)
MAX_VERSIONS = 30
FILE_RE = re.compile(r"^v-[0-9]{8}T[0-9]{6}Z-[0-9a-f]{10}\.json$")


def scoring_key(scoring_path: Path) -> str:
    """Tie comparisons to the exact scoring config used at export time."""
    return hashlib.sha256(scoring_path.read_bytes()).hexdigest()[:16]


def public_snapshot(board: dict) -> dict:
    if board.get("ranked_by") != "fpts_pg" or not re.fullmatch(r"\d{4}-\d{2}", board.get("season", "")):
        raise ValueError("Public history needs an FP/G-ranked season board")
    if not re.fullmatch(r"[0-9a-f]{16}", board.get("scoring_key", "")):
        raise ValueError("Public history needs a scoring fingerprint")
    asof = board.get("generated_at", "")
    stamp = datetime.fromisoformat(asof.replace("Z", "+00:00"))
    if stamp.tzinfo is None:
        raise ValueError("Public history needs a timezone-aware export time")
    rows = board.get("rows")
    if not isinstance(rows, list) or not rows:
        raise ValueError("Public history needs nonempty rows")
    clean = [{key: row.get(key) for key in HISTORY_COLUMNS} for row in rows]
    ids = [row["PLAYER_ID"] for row in clean]
    if any(not isinstance(pid, int) or pid == 0 for pid in ids) or len(set(ids)) != len(ids):
        raise ValueError("Public history needs unique nonzero player IDs")
    for row in clean:
        if not isinstance(row["rank"], int) or row["rank"] < 1:
            raise ValueError("Public history needs ordinal ranks")
    body = json.dumps({"season": board["season"], "rankedBy": "FP/G ordinal",
                       "scoringKey": board["scoring_key"], "rows": clean},
                      ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    digest = hashlib.sha256(body).hexdigest()[:10]
    version = f"{stamp.astimezone(UTC).strftime('%Y%m%dT%H%M%SZ')}-{digest}"
    return {"schema": 1, "version": version, "asof": asof, "season": board["season"],
            "rankedBy": "FP/G ordinal", "scoringKey": board["scoring_key"],
            "source": "public", "rows": clean}


def archive_public_board(board: dict, directory: Path) -> dict:
    """Write one immutable snapshot and an atomic manifest; prune only known old files."""
    snapshot = public_snapshot(board)
    directory.mkdir(parents=True, exist_ok=True)
    manifest_path = directory / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8")) if manifest_path.exists() else {"schema": 1, "versions": []}
    if manifest.get("schema") != 1 or not isinstance(manifest.get("versions"), list):
        raise ValueError("Invalid public history manifest")
    filename = f"v-{snapshot['version']}.json"
    path = directory / filename
    encoded = json.dumps(snapshot, ensure_ascii=False, separators=(",", ":"))
    if path.exists() and path.read_text(encoding="utf-8") != encoded:
        raise ValueError("Immutable history version has different content")
    if not path.exists():
        path.write_text(encoded, encoding="utf-8")
    entry = {key: snapshot[key] for key in ("version", "asof", "season", "rankedBy", "scoringKey", "source")}
    entry.update({"file": filename, "rowCount": len(snapshot["rows"])})
    previous = [item for item in manifest["versions"] if item.get("version") != snapshot["version"]]
    entries = sorted([*previous, entry], key=lambda item: (item["asof"], item["version"]))
    retained = entries[-MAX_VERSIONS:]
    updated = {"schema": 1, "versions": retained}
    temp = directory / "manifest.tmp"
    temp.write_text(json.dumps(updated, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    temp.replace(manifest_path)
    for item in entries[:-MAX_VERSIONS]:
        old_name = item.get("file", "")
        if FILE_RE.fullmatch(old_name):
            old = directory / old_name
            if old.is_file() and old.parent.resolve() == directory.resolve():
                old.unlink()
    return updated
