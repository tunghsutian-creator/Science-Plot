"""Read verified page geometry for a Studio figure-set entry."""

from __future__ import annotations

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
    try:
        size = _read_json(spec_path).get("size_mm")
    except (OSError, ValueError):
        size = None
    if (
        isinstance(size, list)
        and len(size) == 2
        and all(
            not isinstance(value, bool)
            and isinstance(value, int | float)
            and float(value) > 0
            for value in size
        )
    ):
        return [float(value) for value in size]
    return [60, 55]


__all__ = ["registry_figure_size_mm"]
