"""Serialize and transactionally replace visual-review artifacts."""

from __future__ import annotations

import hashlib
import json
import os
import tempfile
from pathlib import Path
from typing import Any
from sciplot_core.foundation.json_values import json_safe


PHYSICAL_SIZE_TOLERANCE_MM = 0.25


TIFF_DPI_TOLERANCE = 0.5


CONTACT_SHEET_COLUMNS = 4


CONTACT_SHEET_ROWS = 2


CONTACT_SHEET_TILE_SIZE = (620, 660)


FINAL_SIZE_VISUAL_REVIEW_VERSION = 2


FINAL_SIZE_VISUAL_DECISION_VERSION = 2


REVIEW_SURFACE = "uncalibrated_screen_preview"


PENDING_REVIEW_STATUS = "pending_uncalibrated_preview_review"


REQUIRED_PREVIEW_CHECKS = (
    "labels_visible_in_uncalibrated_preview",
    "legend_not_occluding_data_in_preview",
    "no_visible_text_or_data_clipping_in_preview",
    "markers_and_lines_distinguishable_in_preview",
    "no_unexplained_blank_or_corrupt_panel_in_preview",
)


def _json_bytes(payload: dict[str, Any]) -> bytes:
    return (
        json.dumps(
            json_safe(payload),
            indent=2,
            ensure_ascii=False,
            allow_nan=False,
        )
        + "\n"
    ).encode("utf-8")


def _bytes_sha256(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _stage_bytes(target: Path, content: bytes) -> Path:
    target.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(
        mode="wb",
        dir=target.parent,
        prefix=f".{target.name}.",
        suffix=".tmp",
        delete=False,
    ) as handle:
        handle.write(content)
        handle.flush()
        os.fsync(handle.fileno())
        return Path(handle.name)


def _replace_files_transactionally(outputs: dict[Path, bytes]) -> None:
    """Replace a related artifact set and restore every target on failure."""

    resolved_outputs = {
        path.expanduser().resolve(): content for path, content in outputs.items()
    }
    if len(resolved_outputs) != len(outputs):
        raise ValueError("Transactional output paths must be unique.")

    originals: dict[Path, bytes | None] = {}
    staged: dict[Path, Path] = {}
    committed: list[Path] = []
    try:
        for target in resolved_outputs:
            if target.exists() and not target.is_file():
                raise ValueError(f"Transactional output target is not a file: {target}")
            originals[target] = target.read_bytes() if target.is_file() else None
        for target, content in resolved_outputs.items():
            staged[target] = _stage_bytes(target, content)
        for target in resolved_outputs:
            os.replace(staged[target], target)
            committed.append(target)
    except Exception as exc:
        rollback_errors: list[str] = []
        for target in reversed(committed):
            try:
                original = originals[target]
                if original is None:
                    target.unlink(missing_ok=True)
                else:
                    os.replace(_stage_bytes(target, original), target)
            except (
                Exception
            ) as rollback_exc:  # pragma: no cover - catastrophic filesystem failure
                rollback_errors.append(f"{target}: {rollback_exc}")
        if rollback_errors:
            raise RuntimeError(
                "Visual-review transaction failed and rollback was incomplete: "
                + "; ".join(rollback_errors)
            ) from exc
        raise
    finally:
        for temporary in staged.values():
            temporary.unlink(missing_ok=True)
