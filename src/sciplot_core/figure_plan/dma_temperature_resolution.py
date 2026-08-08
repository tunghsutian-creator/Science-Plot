"""Resolve one source-bound DMA temperature/storage-modulus task."""

from __future__ import annotations

from dataclasses import dataclass
import math
from pathlib import Path
from typing import Any, NoReturn

from sciplot_core.dma_temperature_contract import (
    DMA_TEMPERATURE_ARTIFACT_STEM,
    DMA_TEMPERATURE_CANONICAL_MODULUS_UNIT,
    DMA_TEMPERATURE_CANONICAL_TEMPERATURE_UNIT,
    DMA_TEMPERATURE_DISPLAY_MODULUS_UNIT,
    DMA_TEMPERATURE_DOCUMENT_STEM,
    DMA_TEMPERATURE_FIGURE_ID,
    DMA_TEMPERATURE_RULE_ID,
    DMA_TEMPERATURE_SELECTION_POLICY,
    DMA_TEMPERATURE_TEMPLATE,
    DMA_TEMPERATURE_X_METRIC,
    DMA_TEMPERATURE_Y_METRIC,
)
from sciplot_core.figure_plan.errors import FigurePlanResolutionError
from sciplot_core.figure_plan.metric_binding import CartesianMetricBinding
from sciplot_core.figure_plan.plan import ResolvedFigurePlan
from sciplot_core.figure_plan.task import FigureTask
from sciplot_core.foundation.source_tree import source_tree_sha256
from sciplot_core.semantic_sources.dma_sources import (
    _read_dma_temperature_series_list,
)


@dataclass(frozen=True, slots=True)
class DmaTemperatureSourceFacts:
    """One validated view of the raw DMA source before materialization."""

    source_sha256: str
    sample_order: tuple[str, ...]
    point_counts: tuple[int, ...]
    source_temperature_units: tuple[str, ...]
    source_modulus_units: tuple[str, ...]
    canonical_temperature_unit: str
    canonical_modulus_unit: str
    display_modulus_unit: str
    negative_display_point_count: int
    minimum_temperature_C: float
    maximum_temperature_C: float
    minimum_display_value_MPa: float
    maximum_display_value_MPa: float


def resolve_dma_temperature_plan(
    *,
    input_path: Path,
    request: dict[str, Any],
) -> ResolvedFigurePlan:
    """Resolve exactly one point-line task from DMA source facts."""

    requested_template = request.get("template")
    if requested_template not in (None, DMA_TEMPERATURE_TEMPLATE):
        raise FigurePlanResolutionError(
            "dma_temperature_template_invalid",
            "The DMA temperature contract supports only 'point_line'.",
        )
    facts = load_dma_temperature_source_facts(input_path)
    task = FigureTask.with_metric_binding(
        figure_id=DMA_TEMPERATURE_FIGURE_ID,
        order=1,
        title="Storage modulus vs temperature",
        metric_binding=CartesianMetricBinding(
            x_metric=DMA_TEMPERATURE_X_METRIC,
            y_metric=DMA_TEMPERATURE_Y_METRIC,
        ),
        template=DMA_TEMPERATURE_TEMPLATE,
        artifact_stem=DMA_TEMPERATURE_ARTIFACT_STEM,
        document_stem=DMA_TEMPERATURE_DOCUMENT_STEM,
        sample_order=facts.sample_order,
        replicate_counts=tuple((sample, 1) for sample in facts.sample_order),
    )
    return ResolvedFigurePlan.planned(
        rule_id=DMA_TEMPERATURE_RULE_ID,
        selection_policy=DMA_TEMPERATURE_SELECTION_POLICY,
        primary_figure_id=task.figure_id,
        tasks=(task,),
        source_sha256=facts.source_sha256,
    )


def load_dma_temperature_source_facts(
    input_path: Path,
) -> DmaTemperatureSourceFacts:
    """Parse once between two source-tree hashes and validate unit/point facts."""

    source = input_path.expanduser().resolve()
    before = source_tree_sha256(source)
    if before is None:
        _fail("dma_temperature_source_unavailable", "The DMA source does not exist.")
    try:
        series_list = _read_dma_temperature_series_list(source)
    except (OSError, ValueError) as exc:
        raise FigurePlanResolutionError(
            "dma_temperature_source_contract_invalid",
            f"The DMA temperature source could not be resolved: {exc}",
        ) from exc
    after = source_tree_sha256(source)
    if after != before:
        _fail(
            "dma_temperature_source_changed_during_resolution",
            "The DMA temperature source changed during FigurePlan resolution.",
        )

    sample_order = tuple(series.sample for series in series_list)
    if not sample_order or len(sample_order) != len(set(sample_order)):
        _fail(
            "dma_temperature_source_contract_invalid",
            "DMA temperature sample identities must be non-empty and unique.",
        )
    point_counts: list[int] = []
    source_temperature_units: list[str] = []
    source_modulus_units: list[str] = []
    display_values: list[float] = []
    temperature_values: list[float] = []
    diagnosed_negative_count = 0
    for series in series_list:
        diagnostics = series.diagnostics or {}
        points = tuple(series.points)
        if not points or not all(
            math.isfinite(float(x_value)) and math.isfinite(float(y_value))
            for x_value, y_value in points
        ):
            _fail(
                "dma_temperature_source_contract_invalid",
                f"DMA temperature series {series.sample!r} has no closed finite point set.",
            )
        _require_diagnostic(
            diagnostics,
            "canonical_x_unit",
            DMA_TEMPERATURE_CANONICAL_TEMPERATURE_UNIT,
        )
        _require_diagnostic(
            diagnostics,
            "canonical_y_unit",
            DMA_TEMPERATURE_CANONICAL_MODULUS_UNIT,
        )
        _require_diagnostic(
            diagnostics,
            "display_y_unit",
            DMA_TEMPERATURE_DISPLAY_MODULUS_UNIT,
        )
        if series.x_unit != DMA_TEMPERATURE_CANONICAL_TEMPERATURE_UNIT or (
            series.y_unit != DMA_TEMPERATURE_DISPLAY_MODULUS_UNIT
        ):
            _fail(
                "dma_temperature_source_contract_invalid",
                "DMA materialized series units disagree with the shared unit contract.",
            )
        point_counts.append(len(points))
        temperature_values.extend(float(x_value) for x_value, _y_value in points)
        display_values.extend(float(y_value) for _x_value, y_value in points)
        diagnosed_negative_count += int(
            diagnostics.get("negative_display_point_count") or 0
        )
        _append_unique(source_temperature_units, diagnostics.get("source_x_unit"))
        _append_unique(source_modulus_units, diagnostics.get("source_y_unit"))
    observed_negative_count = sum(value < 0.0 for value in display_values)
    if observed_negative_count != diagnosed_negative_count:
        _fail(
            "dma_temperature_source_contract_invalid",
            "DMA negative-point diagnostics disagree with the parsed measurements.",
        )
    return DmaTemperatureSourceFacts(
        source_sha256=before,
        sample_order=sample_order,
        point_counts=tuple(point_counts),
        source_temperature_units=tuple(source_temperature_units),
        source_modulus_units=tuple(source_modulus_units),
        canonical_temperature_unit=DMA_TEMPERATURE_CANONICAL_TEMPERATURE_UNIT,
        canonical_modulus_unit=DMA_TEMPERATURE_CANONICAL_MODULUS_UNIT,
        display_modulus_unit=DMA_TEMPERATURE_DISPLAY_MODULUS_UNIT,
        negative_display_point_count=observed_negative_count,
        minimum_temperature_C=min(temperature_values),
        maximum_temperature_C=max(temperature_values),
        minimum_display_value_MPa=min(display_values),
        maximum_display_value_MPa=max(display_values),
    )


def dma_temperature_source_sha256(source: Path) -> str | None:
    """Return the validated relocation-stable DMA source identity, if available."""

    try:
        return load_dma_temperature_source_facts(source).source_sha256
    except (FigurePlanResolutionError, OSError):
        return None


def _require_diagnostic(
    diagnostics: dict[str, Any],
    key: str,
    expected: str,
) -> None:
    if diagnostics.get(key) != expected:
        _fail(
            "dma_temperature_source_contract_invalid",
            f"DMA source diagnostic {key!r} does not equal {expected!r}.",
        )


def _append_unique(values: list[str], value: object) -> None:
    normalized = str(value or "").strip()
    if not normalized:
        _fail(
            "dma_temperature_source_contract_invalid",
            "DMA source unit diagnostics are incomplete.",
        )
    if normalized not in values:
        values.append(normalized)


def _fail(reason_code: str, message: str) -> NoReturn:
    raise FigurePlanResolutionError(reason_code, message)


__all__ = [
    "DmaTemperatureSourceFacts",
    "dma_temperature_source_sha256",
    "load_dma_temperature_source_facts",
    "resolve_dma_temperature_plan",
]
