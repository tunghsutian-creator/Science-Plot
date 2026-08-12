"""Prepare thermal, DMA, chromatography, scattering, swelling, and FTIR sources."""

from __future__ import annotations

from typing import Any

from sciplot_core.dma_temperature_contract import DMA_TEMPERATURE_DEFAULT_Y_MIN
from sciplot_core.materials_rules import get_rule

from sciplot_core.semantic_sources.preparation_context import SemanticPreparationContext

from sciplot_core.semantic_sources.curve_output import (
    _write_curve_table,
)

from sciplot_core.semantic_sources.dma_sources import (
    _DMA_CANONICAL_MODULUS_UNIT,
    _DMA_CANONICAL_TEMPERATURE_UNIT,
    _DMA_CANONICAL_TO_DISPLAY_FACTOR,
    _DMA_DISPLAY_MODULUS_UNIT,
)

from sciplot_core.semantic_sources.dma_temperature_transform import (
    resolve_dma_temperature_transform,
)
from sciplot_core.semantic_sources.scientific_transform import (
    ResolvedScientificTransform,
)
from sciplot_core.semantic_sources.scientific_source_single_curve import (
    resolve_single_curve_transform,
)

from sciplot_core.semantic_sources.preparation_support import (
    _semantic_preparation_result,
)

from sciplot_core.semantic_sources.series_ordering import (
    _order_curve_series,
)

from sciplot_core.semantic_sources.swelling_sources import (
    _read_swelling_series_list,
)

from sciplot_core.semantic_sources.rheology_sweep_sources import (
    _sweep_source_files,
)


def prepare_curve_family_source(
    context: SemanticPreparationContext,
) -> dict[str, Any] | None:
    source = context.source
    processed_dir = context.processed_dir
    family = context.family
    series_order = context.series_order
    rule = get_rule(context.rule_id or family)

    if family == "dma_temperature_sweep":
        processed_source = processed_dir / "dma_temperature_comparison.csv"
        resolved_transform = (
            context.resolved_scientific_source.require_domain(
                ResolvedScientificTransform
            )
            if context.resolved_scientific_source is not None
            else resolve_dma_temperature_transform(
                source,
                series_order=series_order,
            )
        )
        series_list = list(resolved_transform.series)
        below_default_y_min_count = sum(
            y_value < DMA_TEMPERATURE_DEFAULT_Y_MIN
            for series in series_list
            for _x_value, y_value in series.points
        )
        _write_curve_table(series_list, processed_source)
        return _semantic_preparation_result(
            source,
            processed_source=processed_source,
            operation="extract_and_convert_dma_temperature_curves",
            parameters={
                "canonical_x_unit": _DMA_CANONICAL_TEMPERATURE_UNIT,
                "display_x_unit": _DMA_CANONICAL_TEMPERATURE_UNIT,
                "temperature_conversion_policy": (
                    "Require an explicit Celsius or Kelvin source unit; "
                    "convert Kelvin values to Celsius before materializing "
                    "the processed table."
                ),
                "y_metric": "storage_modulus",
                "canonical_y_unit": _DMA_CANONICAL_MODULUS_UNIT,
                "display_y_unit": _DMA_DISPLAY_MODULUS_UNIT,
                "canonical_to_display_factor": (_DMA_CANONICAL_TO_DISPLAY_FACTOR),
                "conversion_policy": (
                    "Parse source units, canonicalize storage modulus to Pa, "
                    "then materialize display values in MPa."
                ),
                "source_sample_count": len(series_list),
                "series_order": [series.sample for series in series_list],
                "scientific_transform": resolved_transform.contract.to_payload(),
                "source_selections": [
                    {"sample": series.sample, **(series.diagnostics or {})}
                    for series in series_list
                ],
                "negative_display_point_count": sum(
                    int(
                        (series.diagnostics or {}).get(
                            "negative_display_point_count",
                            0,
                        )
                    )
                    for series in series_list
                ),
                "configured_default_y_min": DMA_TEMPERATURE_DEFAULT_Y_MIN,
                "below_configured_default_y_min_count": (below_default_y_min_count),
                # Compatibility key: this is a potential bound count, not
                # evidence that the final axis actually clipped those points.
                "default_y_min_clipped_point_count": below_default_y_min_count,
                "default_y_min_clipped_point_count_semantics": (
                    "legacy_potential_count_not_final_axis_clipping"
                ),
                "final_axis_clipping_authority": "spec.axis_data_visibility",
                "unit_conversion_recorded": True,
            },
            source_attestation_rule_id=context.rule_id or family,
            source_tree_sha256_before=context.source_tree_sha256_before,
            selected_sources=tuple(_sweep_source_files(source)),
        )

    if family == "swelling_curve":
        processed_source = processed_dir / f"{source.stem}_swelling_curve.csv"
        series_list = _order_curve_series(
            _read_swelling_series_list(source), series_order
        )
        if not series_list:
            raise ValueError(f"No sample/time/swelling-ratio curves found in {source}.")
        _write_curve_table(series_list, processed_source)
        return _semantic_preparation_result(
            source,
            processed_source=processed_source,
            operation="extract_swelling_ratio_by_sample",
            parameters={
                "series_order": [series.sample for series in series_list],
                "selected_axis_columns": {"x": "time", "y": "swelling ratio"},
                "excluded_same_table_metrics": ["gel fraction"],
                "source_point_counts": [len(series.points) for series in series_list],
                "source_selections": [
                    {"sample": series.sample, **(series.diagnostics or {})}
                    for series in series_list
                ],
            },
        )

    if rule.figure_plan_adapter == "registered_single_curve":
        processed_source = processed_dir / f"{source.stem}_{rule.rule_id}.csv"
        resolved_transform = (
            context.resolved_scientific_source.require_domain(
                ResolvedScientificTransform
            )
            if context.resolved_scientific_source is not None
            else resolve_single_curve_transform(
                source,
                rule=rule,
                series_order=series_order,
            )
        )
        series_list = list(resolved_transform.series)
        _write_curve_table(series_list, processed_source)
        output = resolved_transform.contract.output
        return _semantic_preparation_result(
            source,
            processed_source=processed_source,
            operation=(
                f"extract_{output['x_metric']}_{output['y_metric']}_curve"
            ),
            parameters={
                "series_order": [series.sample for series in series_list],
                "selected_axis_columns": {
                    "x": str(output.get("x_label") or series_list[0].x_label),
                    "y": str(output.get("y_label") or series_list[0].y_label),
                },
                "source_point_counts": [len(series.points) for series in series_list],
                "scientific_transform": resolved_transform.contract.to_payload(),
                "source_selections": [
                    {"sample": series.sample, **(series.diagnostics or {})}
                    for series in series_list
                ],
            },
        )

    return None
