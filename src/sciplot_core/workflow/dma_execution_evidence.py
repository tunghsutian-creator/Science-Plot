"""Build route-neutral terminal evidence for one DMA-temperature execution."""

from __future__ import annotations

import json
import math
from pathlib import Path
from typing import Any, NoReturn

from sciplot_core.dma_temperature_contract import (
    DMA_TEMPERATURE_CANONICAL_MODULUS_UNIT,
    DMA_TEMPERATURE_CANONICAL_TEMPERATURE_UNIT,
    DMA_TEMPERATURE_DISPLAY_MODULUS_UNIT,
    DMA_TEMPERATURE_RULE_ID,
    DMA_TEMPERATURE_TEMPLATE,
    DMA_TEMPERATURE_X_LABEL,
    DMA_TEMPERATURE_X_METRIC,
    DMA_TEMPERATURE_Y_LABEL,
    DMA_TEMPERATURE_Y_METRIC,
)
from sciplot_core.figure_plan import FigureTask, ResolvedFigurePlan
from sciplot_core.figure_plan.dma_temperature_resolution import (
    DmaTemperatureSourceFacts,
)
from sciplot_core.foundation.json_hashing import canonical_json_sha256


def build_dma_temperature_execution_evidence(
    *,
    plan: ResolvedFigurePlan,
    task: FigureTask,
    facts: DmaTemperatureSourceFacts,
    result: dict[str, Any],
) -> dict[str, Any]:
    """Validate the installed spec and return a route-independent signature."""

    spec = _single_installed_spec(result)
    if spec.get("template") != DMA_TEMPERATURE_TEMPLATE:
        _fail("terminal template")
    source_request = _object(spec.get("source_request"), label="source_request")
    if (
        source_request.get("rule_id") != DMA_TEMPERATURE_RULE_ID
        or source_request.get("x_metric") != DMA_TEMPERATURE_X_METRIC
        or source_request.get("y_metric") != DMA_TEMPERATURE_Y_METRIC
        or source_request.get("resolved_figure_task") != task.to_payload()
    ):
        _fail("terminal task or metric binding")

    axes = _object(spec.get("axes"), label="axes")
    x_axis = _object(axes.get("x"), label="axes.x")
    y_axis = _object(axes.get("y"), label="axes.y")
    if x_axis.get("label") != DMA_TEMPERATURE_X_LABEL:
        _fail("temperature display unit")
    if y_axis.get("label") != DMA_TEMPERATURE_Y_LABEL:
        _fail("storage-modulus display unit")

    series = _series_projection(spec.get("series"))
    labels = tuple(str(item["label"]) for item in series)
    point_counts = tuple(len(item["x_values"]) for item in series)
    if labels != facts.sample_order or point_counts != facts.point_counts:
        _fail("sample order or point counts")
    if any(
        len(item["x_values"]) != len(item["y_values"]) or not item["x_values"]
        for item in series
    ):
        _fail("paired finite series cardinality")
    all_x = [float(value) for item in series for value in item["x_values"]]
    all_y = [float(value) for item in series for value in item["y_values"]]
    if not all(math.isfinite(value) for value in [*all_x, *all_y]):
        _fail("finite terminal data")
    if sum(value < 0.0 for value in all_y) != facts.negative_display_point_count:
        _fail("negative storage-modulus preservation")

    visibility = _object(
        spec.get("axis_data_visibility"),
        label="axis_data_visibility",
    )
    visibility_y = _object(
        _object(visibility.get("axes"), label="axis_data_visibility.axes").get("y"),
        label="axis_data_visibility.axes.y",
    )
    if (
        visibility.get("clipped_coordinate_count") != 0
        or visibility_y.get("clipped_coordinate_count") != 0
        or visibility_y.get("below_configured_min_count")
        != facts.negative_display_point_count
    ):
        _fail("axis data visibility")

    palette = _object(spec.get("palette_resolution"), label="palette_resolution")
    encoding_contract = _object(
        spec.get("series_encoding_contract"),
        label="series_encoding_contract",
    )
    encodings = [item["encoding"] for item in series]
    if any(not isinstance(value, dict) for value in encodings):
        _fail("series encoding")

    terminal_projection = {
        "template": spec["template"],
        "axis_labels": {
            "x": x_axis["label"],
            "y": y_axis["label"],
        },
        "axes": axes,
        "axis_data_visibility": visibility,
        "palette_resolution": palette,
        "series_encoding_contract": encoding_contract,
        "series_encodings": encodings,
        "series_data_sha256": canonical_json_sha256(series, allow_nan=False),
    }
    evidence = {
        "kind": "sciplot_dma_temperature_execution_evidence",
        "version": 1,
        "plan_id": plan.plan_id,
        "plan_sha256": plan.plan_sha256,
        "source_sha256": facts.source_sha256,
        "task": task.to_payload(),
        "sample_order": list(facts.sample_order),
        "point_counts": list(facts.point_counts),
        "finite_point_count": sum(facts.point_counts),
        "negative_display_point_count": facts.negative_display_point_count,
        "units": {
            "canonical_temperature": DMA_TEMPERATURE_CANONICAL_TEMPERATURE_UNIT,
            "canonical_modulus": DMA_TEMPERATURE_CANONICAL_MODULUS_UNIT,
            "display_modulus": DMA_TEMPERATURE_DISPLAY_MODULUS_UNIT,
        },
        "terminal_spec_projection": terminal_projection,
    }
    evidence["evidence_sha256"] = canonical_json_sha256(evidence, allow_nan=False)
    return evidence


def _single_installed_spec(result: dict[str, Any]) -> dict[str, Any]:
    paths = [
        Path(value) for value in result.get("veusz_specs", []) if isinstance(value, str)
    ]
    if len(paths) != 1 or not paths[0].is_file():
        _fail("single installed spec")
    payload = json.loads(paths[0].read_text(encoding="utf-8"))
    return _object(payload, label="spec")


def _series_projection(value: object) -> list[dict[str, Any]]:
    if not isinstance(value, list) or not value:
        _fail("terminal series")
    projected: list[dict[str, Any]] = []
    for index, item in enumerate(value):
        record = _object(item, label=f"series[{index}]")
        x_values = record.get("x_values")
        y_values = record.get("y_values")
        if not isinstance(x_values, list) or not isinstance(y_values, list):
            _fail("terminal series coordinates")
        projected.append(
            {
                "label": record.get("label"),
                "x_values": x_values,
                "y_values": y_values,
                "encoding": record.get("encoding"),
            }
        )
    return projected


def _object(value: object, *, label: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise ValueError(
            f"dma_temperature_terminal_evidence_mismatch: {label} must be an object."
        )
    return value


def _fail(field: str) -> NoReturn:
    raise ValueError(
        "dma_temperature_terminal_evidence_mismatch: terminal "
        f"{field} conflicts with the selected DMA plan."
    )


__all__ = ["build_dma_temperature_execution_evidence"]
