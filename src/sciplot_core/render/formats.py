"""Normalize export requests."""

from __future__ import annotations

from sciplot_core.policy import (
    DEFAULT_EXPORT_FORMATS_POLICY,
    normalize_export_formats,
)


DEFAULT_EXPORT_FORMATS = DEFAULT_EXPORT_FORMATS_POLICY


DEFAULT_RENDER_ENGINE = "veusz"


def _normalize_export_formats(
    export_formats: list[str] | tuple[str, ...] | None,
) -> tuple[str, ...]:
    return normalize_export_formats(export_formats, default=DEFAULT_EXPORT_FORMATS)
