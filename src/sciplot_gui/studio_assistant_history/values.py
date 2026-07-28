"""Normalize history values, identifiers, hashes, and paths."""

from __future__ import annotations

import hashlib
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from uuid import UUID

from sciplot_core.foundation.json_hashing import canonical_json_sha256
from sciplot_gui.studio_assistant_history.contracts import (
    ASSISTANT_HISTORY_FILENAME,
    _SHA256,
)


def _now() -> str:
    return datetime.now(UTC).isoformat()


def _required_text(value: object, label: str, *, maximum: int = 512) -> str:
    if not isinstance(value, str):
        raise ValueError(f"{label} must be text.")
    text = value.strip()
    if not text:
        raise ValueError(f"{label} must not be empty.")
    if len(text) > maximum:
        raise ValueError(f"{label} must contain at most {maximum} characters.")
    return text


def _optional_text(
    value: object,
    label: str,
    *,
    maximum: int = 512,
) -> str | None:
    if value is None:
        return None
    return _required_text(value, label, maximum=maximum)


def _uuid_text(value: object, label: str) -> str:
    text = _required_text(value, label, maximum=64)
    try:
        return str(UUID(text))
    except ValueError as exc:
        raise ValueError(f"{label} must be a UUID.") from exc


def _sha256(value: object, label: str) -> str:
    text = _required_text(value, label, maximum=64).casefold()
    if _SHA256.fullmatch(text) is None:
        raise ValueError(f"{label} must be a lowercase SHA-256 digest.")
    return text


def canonical_value_sha256(value: Any) -> str:
    """Hash one JSON-safe setting value without retaining the value itself."""

    return canonical_json_sha256(value, allow_nan=False)


def assistant_history_path(document_path: Path) -> Path:
    """Return a project-local sidecar path without exposing it in history rows."""

    resolved = document_path.expanduser().resolve()
    if (
        resolved.parent.name == "studio"
        and (resolved.parent.parent / "plot_request.json").is_file()
    ):
        return resolved.parent.parent / ".sciplot_studio" / ASSISTANT_HISTORY_FILENAME
    path_key = hashlib.sha256(str(resolved).encode("utf-8")).hexdigest()[:12]
    return (
        resolved.parent
        / ".sciplot_studio"
        / f"{resolved.stem}_{path_key}"
        / ASSISTANT_HISTORY_FILENAME
    )
