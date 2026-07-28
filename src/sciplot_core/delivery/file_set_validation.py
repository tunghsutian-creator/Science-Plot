"""Validate recorded delivery files against live paths and hashes."""

from __future__ import annotations

from pathlib import Path
from typing import Any
from sciplot_core.foundation.file_hashing import existing_file_sha256


def _recorded_file_set(
    records: object,
    *,
    directory: Path,
    suffixes: set[str],
    hash_field: str,
) -> dict[str, Any]:
    live_files = (
        {
            path.resolve()
            for path in directory.iterdir()
            if path.is_file() and path.suffix.casefold() in suffixes
        }
        if directory.is_dir()
        else set()
    )
    recorded_files: set[Path] = set()
    invalid: list[dict[str, Any]] = []
    if not isinstance(records, list):
        return {
            "passed": False,
            "live_files": sorted(str(path) for path in live_files),
            "recorded_files": [],
            "invalid": [{"reason": "records_missing"}],
        }
    for record in records:
        if not isinstance(record, dict):
            invalid.append({"reason": "record_not_object"})
            continue
        path_value = record.get("path")
        if not isinstance(path_value, str) or not path_value.strip():
            invalid.append({"reason": "path_missing", "record": record})
            continue
        path = Path(path_value).expanduser().resolve()
        expected_hash = str(record.get(hash_field) or "").strip()
        actual_hash = existing_file_sha256(path)
        valid = bool(
            path.parent == directory.resolve()
            and path.suffix.casefold() in suffixes
            and path.is_file()
            and path.stat().st_size > 0
            and expected_hash
            and actual_hash == expected_hash
        )
        if not valid:
            invalid.append(
                {
                    "reason": "file_or_hash_invalid",
                    "path": str(path),
                    "expected_sha256": expected_hash or None,
                    "actual_sha256": actual_hash,
                }
            )
        recorded_files.add(path)
    return {
        "passed": bool(live_files) and not invalid and live_files == recorded_files,
        "live_files": sorted(str(path) for path in live_files),
        "recorded_files": sorted(str(path) for path in recorded_files),
        "invalid": invalid,
    }
