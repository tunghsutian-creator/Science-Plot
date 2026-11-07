"""Read and validate existing line-delimited assistant history, without writes."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from sciplot_core.assistant_history.validation import (
    validate_assistant_history_event,
)

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
