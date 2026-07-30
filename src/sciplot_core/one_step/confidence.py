"""Summarize source counts and semantic confidence bands."""

from __future__ import annotations

from pathlib import Path
from typing import Any
from sciplot_core.foundation.iso_timestamps import utc_now_iso
from sciplot_core.readiness import (
    HIGH_CONFIDENCE_THRESHOLD,
    MEDIUM_CONFIDENCE_THRESHOLD,
)


_now = utc_now_iso


def _source_counts(path: Path) -> dict[str, int]:
    if path.is_file():
        return {"file_count": 1, "folder_count": 0}
    if path.is_dir():
        file_count = sum(1 for item in path.rglob("*") if item.is_file())
        folder_count = sum(1 for item in path.rglob("*") if item.is_dir())
        return {"file_count": file_count, "folder_count": folder_count}
    return {"file_count": 0, "folder_count": 0}


def _semantic_confidence(semantic: dict[str, Any]) -> float:
    try:
        return float(semantic.get("confidence") or 0.0)
    except (TypeError, ValueError):
        return 0.0


def confidence_band(semantic: dict[str, Any]) -> str:
    confidence = _semantic_confidence(semantic)
    if bool(semantic.get("needs_ai_intervention")):
        return "low"
    if confidence >= HIGH_CONFIDENCE_THRESHOLD:
        return "high"
    if confidence >= MEDIUM_CONFIDENCE_THRESHOLD:
        return "medium"
    return "low"
