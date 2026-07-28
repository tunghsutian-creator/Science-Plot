"""Resolve the exact document path currently owned by a Veusz window."""

from __future__ import annotations

from pathlib import Path
from typing import Any


def resolved_window_document_path(window: Any) -> Path | None:
    filename = str(getattr(window, "filename", "") or "").strip()
    if not filename:
        return None
    try:
        return Path(filename).expanduser().resolve()
    except (OSError, RuntimeError, ValueError):
        return None


__all__ = ["resolved_window_document_path"]
