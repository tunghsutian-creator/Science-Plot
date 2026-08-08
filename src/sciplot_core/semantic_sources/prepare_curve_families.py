"""Prepare thermal, DMA, chromatography, scattering, swelling, and FTIR sources."""

from __future__ import annotations

from typing import Any

from sciplot_core.dma_temperature_contract import DMA_TEMPERATURE_DEFAULT_Y_MIN

from sciplot_core.semantic_sources.preparation_context import SemanticPreparationContext

from sciplot_core.semantic_sources.curve_output import (
    _write_curve_table,
)

from sciplot_core.semantic_sources.dma_sources import (
    _DMA_CANONICAL_MODULUS_UNIT,
    _DMA_CANONICAL_TEMPERATURE_UNIT,
    _DMA_CANONICAL_TO_DISPLAY_FACTOR,
    _DMA_DISPLAY_MODULUS_UNIT,
    _read_dma_temperature_series_list,
)

from sciplot_core.semantic_sources.ftir_sources import (
    _read_ftir_series_list,
)

from sciplot_core.semantic_sources.gpc_sources import (
    _read_gpc_series_list,
    _retain_positive_saxs_log_domain,
)

from sciplot_core.semantic_sources.models import (
    CurveSeriesPayload,
)

from sciplot_core.semantic_sources.preparation_support import (
    _semantic_preparation_result,
)

from sciplot_core.semantic_sources.series_labels import (
    _constant_sample_label,
)

from sciplot_core.semantic_sources.series_ordering import (
    _order_curve_series,
)

from sciplot_core.semantic_sources.swelling_sources import (
    _read_swelling_series_list,
)

from sciplot_core.semantic_sources.table_scanning import (
    _scan_curve_series_source,
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

    if family == "dsc_curve" and (
        source.suffix.lower() in {".xls", ".xlsx"}
        or source.is_dir()
        and any(
            path.is_file() and path.suffix.lower() in {".xls", ".xlsx"}
            for path in source.iterdir()
        )
    ):
        raise ValueError(
            "dsc_cycle_rule_required: `dsc_curve` accepts only the registered "
            "publication-digitized single-curve source. Cycle workbooks require "
            "a separate authorized `dsc_cycle` rule."
        )

    if family == "dma_temperature_sweep":
        processed_source = processed_dir / "dma_temperature_comparison.csv"
        series_list = _read_dma_temperature_series_list(source)
        series_list = _order_curve_series(series_list, series_order)
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

    if family in {"saxs_profile", "gpc_sec_chromatogram"}:
        if family == "saxs_profile":
            processed_source = processed_dir / f"{source.stem}_saxs_profile.csv"
            series_list = _scan_curve_series_source(
                source,
                x_aliases=("q", "q_nm-1"),
                y_aliases=("intensity",),
                x_label="q",
                y_label="Intensity",
                default_x_unit="nm^-1",
                default_y_unit="a.u.",
                sample_prefix=source.stem,
            )
            series_list = [
                _retain_positive_saxs_log_domain(series) for series in series_list
            ]
            operation = "extract_saxs_q_intensity_profile"
            selected_columns = {"x": "q", "y": "intensity"}
            sample_label = _constant_sample_label(source)
            if sample_label and len(series_list) == 1:
                series = series_list[0]
                series_list = [
                    CurveSeriesPayload(
                        sample=sample_label,
                        x_label=series.x_label,
                        x_unit=series.x_unit,
                        y_label=series.y_label,
                        y_unit=series.y_unit,
                        points=series.points,
                        diagnostics=series.diagnostics,
                    )
                ]
        else:
            processed_source = processed_dir / f"{source.stem}_gpc_chromatogram.csv"
            series_list = _read_gpc_series_list(source)
            operation = "extract_gpc_detector_chromatograms"
            selected_columns = {"x": "elution time", "y": "detector response"}
        if not series_list:
            raise ValueError(f"No canonical {family} curve found in {source}.")
        series_list = _order_curve_series(series_list, series_order)
        _write_curve_table(series_list, processed_source)
        return _semantic_preparation_result(
            source,
            processed_source=processed_source,
            operation=operation,
            parameters={
                "series_order": [series.sample for series in series_list],
                "selected_axis_columns": selected_columns,
                "source_point_counts": [
                    int(
                        (series.diagnostics or {}).get(
                            "source_point_count", len(series.points)
                        )
                    )
                    for series in series_list
                ],
                "selected_point_counts": [len(series.points) for series in series_list],
                "source_selections": [
                    {"sample": series.sample, **(series.diagnostics or {})}
                    for series in series_list
                ],
            },
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

    if family == "tga_curve":
        processed_source = processed_dir / f"{source.stem}_tga_curve.csv"
        series_list = _scan_curve_series_source(
            source,
            x_aliases=("temperature", "temp"),
            y_aliases=("weight", "mass"),
            x_label="Temperature",
            y_label="Mass",
            default_x_unit="C",
            default_y_unit="%",
            sample_prefix=source.stem,
        )
        if not series_list:
            raise ValueError(f"No temperature/mass TGA curve found in {source}.")
        series_list = _order_curve_series(series_list, series_order)
        _write_curve_table(series_list, processed_source)
        return _semantic_preparation_result(
            source,
            processed_source=processed_source,
            operation="extract_tga_temperature_mass_curve",
            parameters={
                "series_order": [series.sample for series in series_list],
                "selected_axis_columns": {"x": "Temperature", "y": "Mass"},
                "source_point_counts": [len(series.points) for series in series_list],
            },
        )

    if family == "ftir_spectrum":
        processed_source = processed_dir / "ftir_comparison.csv"
        series_list = _order_curve_series(_read_ftir_series_list(source), series_order)
        _write_curve_table(series_list, processed_source)
        return _semantic_preparation_result(
            source,
            processed_source=processed_source,
            operation="reformat_and_order_ftir_spectra",
            parameters={
                "series_order": [series.sample for series in series_list],
                "source_selections": [
                    {"sample": series.sample, **(series.diagnostics or {})}
                    for series in series_list
                ],
            },
        )
    return None
