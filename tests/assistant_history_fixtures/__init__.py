"""Generated historical rows for compatibility controls; no product writer."""

import json
import os
from pathlib import Path
from typing import Any

from sciplot_core.assistant_history import validate_assistant_history_event
from .builder import build_assistant_history_event as build_assistant_history_event

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
