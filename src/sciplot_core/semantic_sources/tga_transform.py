"""Compatibility wrapper for the registered TGA paired-curve transform."""

from __future__ import annotations

from pathlib import Path

from sciplot_core.materials_rules import get_rule
from sciplot_core.semantic_sources.registered_paired_curve_transform import (
    resolve_registered_paired_curve_transform,
)
from sciplot_core.semantic_sources.scientific_transform import (
    ResolvedScientificTransform,
)


def resolve_tga_transform(
    source: Path,
    *,
    series_order: object = None,
) -> ResolvedScientificTransform:
    """Resolve TGA through the registered paired-curve implementation."""

    return resolve_registered_paired_curve_transform(
        source,
        rule=get_rule("tga_curve"),
        series_order=series_order,
    )


__all__ = ["resolve_tga_transform"]
