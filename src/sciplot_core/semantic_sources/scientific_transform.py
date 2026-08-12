"""Typed source-bound scientific-transform result shared by preview and prepare."""

from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from sciplot_core.semantic_sources.models import CurveSeriesPayload


SCIENTIFIC_TRANSFORM_KIND = "sciplot_scientific_transform"
SCIENTIFIC_TRANSFORM_VERSION = 1


@dataclass(frozen=True)
class ScientificTransformContract:
    """One declarative account of how source measurements become plot data."""

    semantic_family: str
    source_columns: tuple[dict[str, Any], ...]
    unit_conversions: tuple[dict[str, Any], ...]
    anchor: dict[str, Any]
    normalizer: dict[str, Any]
    x_coordinate_policy: dict[str, Any]
    retain_anchor: bool | None
    axis_compatibility: dict[str, Any]
    output: dict[str, Any]
    selected_sources: tuple[str, ...]

    def to_payload(self) -> dict[str, Any]:
        return {
            "kind": SCIENTIFIC_TRANSFORM_KIND,
            "version": SCIENTIFIC_TRANSFORM_VERSION,
            "semantic_family": self.semantic_family,
            "source_columns": deepcopy(list(self.source_columns)),
            "unit_conversions": deepcopy(list(self.unit_conversions)),
            "anchor": deepcopy(self.anchor),
            "normalizer": deepcopy(self.normalizer),
            "x_coordinate_policy": deepcopy(self.x_coordinate_policy),
            "retain_anchor": self.retain_anchor,
            "axis_compatibility": deepcopy(self.axis_compatibility),
            "output": deepcopy(self.output),
            "selected_sources": list(self.selected_sources),
        }


@dataclass(frozen=True)
class ResolvedScientificTransform:
    """The exact transformed series and the contract that describes them."""

    series: tuple[CurveSeriesPayload, ...]
    contract: ScientificTransformContract
    selected_sources: tuple[Path, ...]


__all__ = [
    "SCIENTIFIC_TRANSFORM_KIND",
    "SCIENTIFIC_TRANSFORM_VERSION",
    "ResolvedScientificTransform",
    "ScientificTransformContract",
]
