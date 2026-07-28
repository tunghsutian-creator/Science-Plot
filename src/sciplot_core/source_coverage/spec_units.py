"""Derive rendered data units from renderer-neutral specifications."""

from __future__ import annotations

from typing import Any
from sciplot_core.foundation.json_values import json_safe
from sciplot_core.scalar_visual import scalar_visual_contract

from sciplot_core.source_coverage.artifacts import (
    _series_source_artifacts,
)


def _spec_render_data_units(
    spec: dict[str, Any],
    *,
    artifact_inventory: dict[str, str],
) -> list[dict[str, Any]]:
    axes = spec.get("axes")
    if (
        not isinstance(axes, dict)
        or not isinstance(axes.get("x"), dict)
        or not isinstance(axes.get("y"), dict)
    ):
        raise ValueError("Veusz specification has no closed x/y axis contract.")
    axis_contract = json_safe(
        {
            "x": dict(axes["x"]),
            "y": dict(axes["y"]),
        }
    )
    categorical = spec.get("categorical")
    categorical_groups = {
        str(group.get("y_name") or ""): group
        for group in (
            categorical.get("groups", []) if isinstance(categorical, dict) else []
        )
        if isinstance(group, dict)
    }
    reference_guides = (
        spec.get("reference_guides")
        if isinstance(spec.get("reference_guides"), list)
        else []
    )
    direct_labels = (
        spec.get("direct_labels") if isinstance(spec.get("direct_labels"), list) else []
    )
    units: list[dict[str, Any]] = []
    series = spec.get("series")
    if not isinstance(series, list):
        raise ValueError("Veusz specification has no series list.")
    for index, raw_series in enumerate(series, start=1):
        if not isinstance(raw_series, dict):
            raise ValueError(f"Veusz specification series {index} is invalid.")
        y_name = str(raw_series.get("y_name") or "")
        group = categorical_groups.get(y_name)
        units.append(
            {
                "kind": "series",
                "name": str(raw_series.get("name") or ""),
                "label": str(raw_series.get("label") or ""),
                "x_name": str(raw_series.get("x_name") or ""),
                "y_name": y_name,
                "x_values": raw_series.get("x_values"),
                "y_values": raw_series.get("y_values"),
                "presentation_kind": str(
                    raw_series.get("presentation_kind") or "curve"
                ),
                "category_position": raw_series.get("category_position"),
                "plot_line_hide": raw_series.get("plot_line_hide") is True,
                "raw_points_visible": (
                    raw_series.get("raw_points_visible") is not False
                ),
                "boxplot_eligible": (
                    group.get("boxplot_eligible") is True
                    if isinstance(group, dict)
                    else False
                ),
                "axes": axis_contract,
                "reference_guides": json_safe(reference_guides),
                "direct_labels": json_safe(direct_labels),
                "source_artifacts": _series_source_artifacts(
                    raw_series.get("source_artifacts"),
                    label=f"specification series {index}",
                    artifact_inventory=artifact_inventory,
                ),
            }
        )
    scalar = spec.get("scalar_field")
    if isinstance(scalar, dict):
        units.append(
            {
                "kind": "scalar_field",
                "data_name": str(scalar.get("data_name") or ""),
                "x_values": scalar.get("x_values"),
                "y_values": scalar.get("y_values"),
                "z_values": scalar.get("z_values"),
                "z_label": str(scalar.get("z_label") or ""),
                "scalar_visual": scalar_visual_contract(
                    scalar,
                    label="specification scalar field",
                ),
                "axes": axis_contract,
                "reference_guides": json_safe(reference_guides),
                "direct_labels": json_safe(direct_labels),
                "source_artifacts": _series_source_artifacts(
                    scalar.get("source_artifacts"),
                    label="specification scalar field",
                    artifact_inventory=artifact_inventory,
                ),
            }
        )
    return units
