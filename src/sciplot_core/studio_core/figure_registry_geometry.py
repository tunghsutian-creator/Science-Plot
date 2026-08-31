"""Read verified page geometry for a Studio figure-set entry."""

from __future__ import annotations

import math
from pathlib import Path

from sciplot_core.studio_core.json_files import _read_json
from sciplot_core.studio_core.registry_state import _veusz_spec_path


def registry_figure_size_mm(
    document_path: Path,
    *,
    state_document_path: Path | None,
) -> list[float | int]:
    """Return actual spec geometry, retaining a bounded legacy fallback."""

    spec_path = _veusz_spec_path(state_document_path or document_path)
    if spec_path.is_symlink():
        raise ValueError(
            "studio_figure_geometry_mismatch: a Studio figure spec cannot be "
            "a symbolic link."
        )
    if not spec_path.exists() and not spec_path.is_symlink():
        return [60, 55]
    try:
        size = _read_json(spec_path).get("size_mm")
    except (OSError, ValueError) as exc:
        raise ValueError(
            "studio_figure_geometry_mismatch: an existing Studio figure spec "
            "must be a readable JSON object."
        ) from exc
    if isinstance(size, list) and len(size) == 2:
        normalized = [_positive_finite_number(value) for value in size]
        if all(value is not None for value in normalized):
            return [value for value in normalized if value is not None]
    raise ValueError(
        "studio_figure_geometry_mismatch: an existing Studio figure spec "
        "must contain two finite positive size_mm values."
    )


def _positive_finite_number(value: object) -> float | None:
    if isinstance(value, bool) or not isinstance(value, int | float):
        return None
    try:
        normalized = float(value)
    except OverflowError:
        return None
    return normalized if math.isfinite(normalized) and normalized > 0 else None


__all__ = ["registry_figure_size_mm"]
