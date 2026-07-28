"""Provide metric naming and export-copy operations for figure bundles."""

from __future__ import annotations

import shutil
from pathlib import Path
from typing import Any


_SHARED_FIGURE_STYLE_KEYS = {
    "size",
    "visual_theme_id",
    "style_preset",
    "palette_preset",
    "marker_alpha",
}


def _metric_token(value: object) -> str:
    return "".join(
        character for character in str(value).casefold() if character.isalnum()
    )


def _rename_metric_exports(
    payload: dict[str, Any],
    *,
    metric_id: str,
    figures_dir: Path,
) -> tuple[list[str], list[dict[str, Any]]]:
    outputs: list[str] = []
    exports: list[dict[str, Any]] = []
    for item in payload.get("exports", []):
        if not isinstance(item, dict):
            continue
        source_value = item.get("path")
        fmt = str(item.get("format") or "").strip().lower()
        if not isinstance(source_value, str) or not fmt:
            continue
        source = Path(source_value)
        if not source.exists():
            continue
        if fmt == "pdf":
            destination = figures_dir / f"{metric_id}.pdf"
        elif fmt in {"tiff", "tiff_300"}:
            destination = figures_dir / f"{metric_id}_300dpi.tiff"
        elif fmt in {"png", "png_300"}:
            destination = figures_dir / f"{metric_id}_300dpi.png"
        else:
            destination = figures_dir / f"{metric_id}{source.suffix}"
        shutil.copy2(source, destination)
        record = {**item, "source": str(source), "path": str(destination)}
        outputs.append(str(destination))
        exports.append(record)
    return outputs, exports
