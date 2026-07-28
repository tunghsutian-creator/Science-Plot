"""Load JSON evidence and enumerate fixture files."""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any


DATA_SUFFIXES = frozenset({".csv", ".tsv", ".txt", ".dat", ".tab", ".xlsx", ".xls"})


HASH_PATTERN = re.compile(r"^[0-9a-fA-F]{32}(?:[0-9a-fA-F]{32})?$")


def _load_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return payload if isinstance(payload, dict) else {}


def _fixture_files(fixture: Path) -> list[Path]:
    if fixture.is_file():
        return [fixture]
    if not fixture.is_dir():
        return []
    return sorted(
        path
        for path in fixture.rglob("*")
        if path.is_file() and path.suffix.casefold() in DATA_SUFFIXES
    )
