"""Verify existing publication evidence in its owning service environment only."""
from collections.abc import Callable
from pathlib import Path
from typing import Any


def current_export(root: Path, head: dict[str, Any], *, eligible: bool,
                   cached_export: Callable[[Path, dict[str, Any]], dict[str, Any] | None]) -> dict[str, Any]:
    """Read recipe and exact inventories; never create, render, export or repair."""
    try:
        cache = cached_export(root, head)
    except (OSError, ValueError, RuntimeError, KeyError, TypeError) as exc:
        return {"current": False, "byte_inventory_verified": False,
                "artifact_build_key": None, "validation": "unknown",
                "reason_code": getattr(exc, "reason_code", "export_evidence_unavailable")}
    ready = cache is not None and eligible
    return {"current": ready, "byte_inventory_verified": cache is not None,
            "artifact_build_key": cache["build_key"] if cache is not None else None,
            "validation": "current" if ready else "stale_or_missing"}
