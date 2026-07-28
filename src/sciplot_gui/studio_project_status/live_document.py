"""Describe the currently open Veusz document."""

from __future__ import annotations

from pathlib import Path
from typing import Any
from sciplot_core.foundation.file_hashing import existing_file_sha256
from sciplot_core._paths import resolved_path_is_within


def _live_document_payload(
    *,
    document_path: Path,
    document: Any,
    render_sha256: str | None,
    saved_sha256: str | None = None,
) -> dict[str, Any]:
    resolved_document = document_path.expanduser().resolve()
    modified = bool(document.isModified())
    if saved_sha256 is None or not modified:
        saved_sha256 = existing_file_sha256(resolved_document)
    return {
        "path": str(resolved_document),
        "exists": resolved_document.is_file(),
        "modified": modified,
        "revision": int(document.changeset),
        "saved_sha256": saved_sha256,
        "live_render_sha256": render_sha256,
        "hash_scope": (
            "saved_vsz_and_exact_current_render" if render_sha256 else "saved_vsz_only"
        ),
    }


def _evidence_path(
    value: object,
    *,
    evidence_root: Path,
) -> Path | None:
    if not isinstance(value, str) or not value.strip():
        return None
    candidate = Path(value).expanduser()
    if not candidate.is_absolute():
        candidate = evidence_root / candidate
    try:
        candidate = candidate.resolve()
    except (OSError, RuntimeError, ValueError):
        return None
    return candidate if resolved_path_is_within(candidate, evidence_root) else None
