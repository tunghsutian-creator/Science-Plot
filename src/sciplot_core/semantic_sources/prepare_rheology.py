"""Prepare rheology sweep, creep, and relaxation sources."""

from __future__ import annotations

from typing import Any


from sciplot_core.semantic_sources.preparation_context import SemanticPreparationContext

from sciplot_core.semantic_sources.curve_output import (
    _write_curve_table,
)

from sciplot_core.semantic_sources.models import (
    _RHEOLOGY_FREQUENCY_OUTPUT_METRICS,
    _RHEOLOGY_SWEEP_METRICS,
)

from sciplot_core.semantic_sources.preparation_support import (
    _SHARED_RHEOLOGY_SWEEP_CONFIG,
    _rheology_replicate_inventory,
    _rheology_unit_conversion_inventory,
    _semantic_preparation_result,
)

from sciplot_core.semantic_sources.rheology_confirmation import (
    _confirmed_column_items,
    _read_confirmed_rheology_sweep_samples,
)

from sciplot_core.semantic_sources.rheology_interval import (
    _read_rheology_interval_series_list,
)

from sciplot_core.semantic_sources.rheology_ordering import (
    _ordered_sweep_samples,
)

from sciplot_core.semantic_sources.rheology_replicates import (
    _coalesce_replicate_sweep_samples,
    _normalized_replicate_mode,
)
from sciplot_core.semantic_sources.rheology_sweep_domain import (
    ResolvedRheologySweepDomain,
    available_rheology_sweep_metrics,
)

from sciplot_core.semantic_sources.rheology_sweep_sources import (
    _read_rheology_frequency_comparison_samples,
    _read_rheology_sweep_comparison_samples,
    _read_rheology_temperature_comparison_samples,
)

from sciplot_core.semantic_sources.rheology_workbooks import (
    _write_rheology_sweep_comparison_workbook,
)

from sciplot_core.semantic_sources.series_ordering import (
    _order_curve_series,
    _series_order_map,
)

from sciplot_core.semantic_sources.stress_relaxation_transform import (
    resolve_stress_relaxation_transform,
)
from sciplot_core.semantic_sources.scientific_transform import (
    ResolvedScientificTransform,
)


def prepare_rheology_source(
    context: SemanticPreparationContext,
) -> dict[str, Any] | None:
    source = context.source
    processed_dir = context.processed_dir
    family = context.family
    series_order = context.series_order
    column_confirmations = context.column_confirmations
    replicate_mode = context.replicate_mode

    shared_sweep = _SHARED_RHEOLOGY_SWEEP_CONFIG.get(family)

    if shared_sweep is not None and source.is_dir():
        processed_source = processed_dir / f"{family}_comparison.xlsx"
        source_samples = _read_rheology_sweep_comparison_samples(
            source,
            x_aliases=shared_sweep["x_aliases"],
            x_label=shared_sweep["x_label"],
            default_x_unit=shared_sweep["x_unit"],
            metrics=shared_sweep["metrics"],
        )
        if not source_samples:
            raise ValueError(
                f"{family} folders need at least one parseable sample export."
            )
        samples = _coalesce_replicate_sweep_samples(
            source_samples, replicate_mode=replicate_mode
        )
        samples = _ordered_sweep_samples(samples, series_order=series_order)
        _write_rheology_sweep_comparison_workbook(
            samples,
            processed_source,
            comparison_sheet=shared_sweep["comparison_sheet"],
            metrics=shared_sweep["metrics"],
            source_replicates=source_samples,
        )
        return _semantic_preparation_result(
            source,
            processed_source=processed_source,
            operation="aggregate_shared_rheology_sweep_replicates",
            parameters={
                "semantic_family": family,
                "replicate_mode": _normalized_replicate_mode(replicate_mode),
                "source_sample_count": len(source_samples),
                "output_sample_count": len(samples),
                "source_sample_files": [
                    str(sample.source) for sample in source_samples
                ],
                "output_sample_labels": [sample.sample for sample in samples],
                "replicate_inventory": _rheology_replicate_inventory(source_samples),
                "source_replicates_preserved_in_workbook": True,
                "unit_conversions": _rheology_unit_conversion_inventory(source_samples),
                "mean_definition": "arithmetic mean at exactly matching x values",
                "representative_definition": "longest trace then closest terminal storage modulus to group median",
                "series_order": list(series_order)
                if isinstance(series_order, list | tuple)
                else [],
            },
        )

    if family == "rheology_frequency" and source.is_dir():
        processed_source = processed_dir / "rheology_frequency_comparison.xlsx"
        frequency_domain = (
            context.resolved_scientific_source.require_domain(
                ResolvedRheologySweepDomain
            )
            if context.resolved_scientific_source is not None
            else None
        )
        if frequency_domain is not None:
            source_samples = list(frequency_domain.raw_samples)
            samples = list(frequency_domain.prepared_samples)
            available_metrics = frequency_domain.facts.available_metrics
        else:
            try:
                source_samples = _read_rheology_frequency_comparison_samples(source)
            except ValueError as automatic_error:
                if not _confirmed_column_items(column_confirmations):
                    raise
                try:
                    source_samples = _read_confirmed_rheology_sweep_samples(
                        source,
                        column_confirmations,
                        x_label="Angular Frequency",
                        default_x_unit="rad/s",
                        metrics=_RHEOLOGY_FREQUENCY_OUTPUT_METRICS,
                    )
                except ValueError as confirmed_error:
                    raise ValueError(
                        "Rheology frequency preparation failed both automatic and "
                        f"confirmed parsing (automatic: {automatic_error}; "
                        f"confirmed: {confirmed_error})."
                    ) from confirmed_error
            samples = _coalesce_replicate_sweep_samples(
                source_samples,
                replicate_mode=replicate_mode,
            )
            samples = _ordered_sweep_samples(samples, series_order=series_order)
            available_metrics = available_rheology_sweep_metrics(samples)
        source_sample_count = len(source_samples)
        source_sample_files = [str(sample.source) for sample in source_samples]
        if not samples:
            raise ValueError(
                "Rheology frequency folders need at least one parseable sample export."
            )
        _write_rheology_sweep_comparison_workbook(
            samples,
            processed_source,
            comparison_sheet="Frequency_Comparison",
            metrics=tuple(
                metric
                for metric in _RHEOLOGY_FREQUENCY_OUTPUT_METRICS
                if metric[0] in available_metrics
            ),
        )
        return _semantic_preparation_result(
            source,
            processed_source=processed_source,
            operation="aggregate_rheology_frequency_replicates",
            parameters={
                "replicate_mode": _normalized_replicate_mode(replicate_mode),
                "source_sample_count": source_sample_count,
                "output_sample_count": len(samples),
                "source_sample_files": source_sample_files,
                "output_sample_labels": [sample.sample for sample in samples],
                "available_metrics": list(available_metrics),
                "unit_conversions": _rheology_unit_conversion_inventory(source_samples),
                "mean_definition": "arithmetic mean at exactly matching x values",
                "representative_definition": "longest trace then closest terminal storage modulus to group median",
                "series_order": list(series_order)
                if isinstance(series_order, list | tuple)
                else [],
            },
        )

    if family == "rheology_temperature_sweep":
        processed_source = processed_dir / "rheology_temperature_comparison.xlsx"
        temperature_domain = (
            context.resolved_scientific_source.require_domain(
                ResolvedRheologySweepDomain
            )
            if context.resolved_scientific_source is not None
            else None
        )
        if temperature_domain is not None:
            source_samples = list(temperature_domain.raw_samples)
            samples = list(temperature_domain.prepared_samples)
        else:
            try:
                source_samples = _read_rheology_temperature_comparison_samples(source)
            except ValueError as automatic_error:
                if not _confirmed_column_items(column_confirmations):
                    raise
                try:
                    source_samples = _read_confirmed_rheology_sweep_samples(
                        source,
                        column_confirmations,
                        x_label="Temperature",
                        default_x_unit="°C",
                        metrics=_RHEOLOGY_SWEEP_METRICS,
                    )
                except ValueError as confirmed_error:
                    raise ValueError(
                        "Rheology temperature preparation failed both automatic "
                        f"and confirmed parsing (automatic: {automatic_error}; "
                        f"confirmed: {confirmed_error})."
                    ) from confirmed_error
            samples = _coalesce_replicate_sweep_samples(
                source_samples,
                replicate_mode=replicate_mode,
            )
            samples = _ordered_sweep_samples(samples, series_order=series_order)
        source_sample_count = len(source_samples)
        source_sample_paths = [sample.source for sample in source_samples]
        source_sample_files = [str(path) for path in source_sample_paths]
        interval_selections = [
            {
                "sample": sample.sample,
                "source": str(sample.source),
                "detected_interval_count": sample.interval_count,
                "selected_interval_index": sample.selected_interval_index,
                "selection_policy": sample.interval_selection_policy,
                "selected_point_count": len(sample.rows),
                "x_direction": (
                    "increasing"
                    if len(sample.rows) < 2
                    or sample.rows[-1]["x"] >= sample.rows[0]["x"]
                    else "decreasing"
                ),
            }
            for sample in source_samples
        ]
        if not samples:
            raise ValueError(
                "Rheology temperature folders need at least one parseable sample export."
            )
        _write_rheology_sweep_comparison_workbook(
            samples,
            processed_source,
            comparison_sheet="Temperature_Comparison",
        )
        return _semantic_preparation_result(
            source,
            processed_source=processed_source,
            operation="aggregate_rheology_temperature_replicates",
            source_attestation_rule_id=context.rule_id or family,
            source_tree_sha256_before=context.source_tree_sha256_before,
            selected_sources=tuple(source_sample_paths),
            parameters={
                "replicate_mode": _normalized_replicate_mode(replicate_mode),
                "source_sample_count": source_sample_count,
                "output_sample_count": len(samples),
                "source_sample_files": source_sample_files,
                "output_sample_labels": [sample.sample for sample in samples],
                "mean_definition": "arithmetic mean at exactly matching x values",
                "representative_definition": "longest trace then closest terminal storage modulus to group median",
                "series_order": list(series_order)
                if isinstance(series_order, list | tuple)
                else [],
                "interval_selection_policy": "last_numeric_interval",
                "interval_selections": interval_selections,
            },
        )

    if family == "rheology_creep":
        processed_source = processed_dir / f"{source.stem}_creep_curve.csv"
        series_list = _read_rheology_interval_series_list(
            source,
            y_candidates=("creepcompliance", "compliance", "蠕变柔量"),
            y_label="Creep compliance",
            y_unit="1/Pa",
            preferred_result_tokens=("creep",),
        )
        series_list = _order_curve_series(series_list, series_order)
        _write_curve_table(series_list, processed_source)
        return _semantic_preparation_result(
            source,
            processed_source=processed_source,
            operation="extract_rheology_creep_curve",
            parameters={
                "y_metric": "creep_compliance",
                "unit": "1/Pa",
                "source_sample_count": len(series_list),
                "series_order": [series.sample for series in series_list],
                "source_selections": [
                    {"sample": series.sample, **(series.diagnostics or {})}
                    for series in series_list
                ],
            },
        )

    if family == "rheology_stress_relaxation":
        processed_source = processed_dir / f"{source.stem}_stress_relaxation_curve.csv"
        resolved_transform = (
            context.resolved_scientific_source.require_domain(
                ResolvedScientificTransform
            )
            if context.resolved_scientific_source is not None
            else resolve_stress_relaxation_transform(
                source,
                series_order=series_order,
            )
        )
        series_list = list(resolved_transform.series)
        _write_curve_table(series_list, processed_source)
        return _semantic_preparation_result(
            source,
            processed_source=processed_source,
            operation="extract_and_normalize_stress_relaxation_curves",
            parameters={
                "normalization_definition": (
                    "strain-controlled interval sources: detect the terminal "
                    "shear-strain hold, crop the loading ramp, preserve source "
                    "time, retain the hold-onset point, and divide by the onset "
                    "response; "
                    "sources without a control signal: preserve source time "
                    "and divide by the first finite non-zero response; already "
                    "normalized sources are preserved"
                ),
                "series_order": [series.sample for series in series_list],
                "automatic_visual_ordering": not bool(_series_order_map(series_order))
                and source.is_dir(),
                "scientific_transform": resolved_transform.contract.to_payload(),
                "source_normalizations": [
                    {"sample": series.sample, **(series.diagnostics or {})}
                    for series in series_list
                ],
            },
        )
    return None
