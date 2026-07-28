"""Append and read line-delimited assistant history events."""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

from sciplot_gui.studio_assistant_history.validation import (
    validate_assistant_history_event,
)


def append_assistant_history_event(
    path: Path,
    payload: dict[str, Any],
) -> Path:
    event = validate_assistant_history_event(payload)
    target = path.expanduser().resolve()
    target.parent.mkdir(parents=True, exist_ok=True)
    encoded = json.dumps(
        event,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    )
    with target.open("a", encoding="utf-8") as handle:
        handle.write(encoded)
        handle.write("\n")
        handle.flush()
        os.fsync(handle.fileno())
    return target


def read_assistant_history(path: Path) -> list[dict[str, Any]]:
    target = path.expanduser()
    if not target.is_file():
        return []
    events: list[dict[str, Any]] = []
    for line_number, line in enumerate(
        target.read_text(encoding="utf-8").splitlines(),
        1,
    ):
        if not line.strip():
            continue
        payload = json.loads(line)
        if not isinstance(payload, dict):
            raise ValueError(f"Assistant history line {line_number} is not an object.")
        events.append(validate_assistant_history_event(payload))
    return events
