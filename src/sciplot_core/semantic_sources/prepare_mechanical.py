"""Prepare tensile, non-tensile mechanical, torque, and impact sources."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pandas as pd

from sciplot_core.materials_rules import ELONGATION_AT_BREAK_METRIC

from sciplot_core.semantic_sources.preparation_context import SemanticPreparationContext

from sciplot_core.semantic_sources.curve_output import (
    _write_curve_table,
)

from sciplot_core.semantic_sources.impact_sources import (
    _read_impact_source,
)

from sciplot_core.semantic_sources.mechanical_sources import (
    _NON_TENSILE_MECHANICAL_CONTRACTS,
    _read_non_tensile_mechanical_series,
    _read_non_tensile_mechanical_workbook_directory,
    _write_non_tensile_mechanical_summary_table,
)

from sciplot_core.semantic_sources.preparation_support import (
    _has_intake_grouped_series,
    _semantic_preparation_result,
)

from sciplot_core.semantic_sources.rheology_replicates import (
    _normalized_replicate_mode,
)

from sciplot_core.semantic_sources.series_ordering import (
    _order_curve_series,
    _order_recycled_pa_pair_control_first,
    _series_order_map,
)

from sciplot_core.semantic_sources.tensile_exports import (
    _read_tensile_export_series_list,
    _representative_tensile_series,
    _tensile_export_files,
    _write_tensile_summary_table,
)

from sciplot_core.semantic_sources.tensile_workbooks import (
    _read_tensile_workbook_directory,
    _read_tensile_workbook_series,
)

from sciplot_core.semantic_sources.torque_labels import (
    _compact_torque_series_labels,
)

from sciplot_core.semantic_sources.torque_sources import (
    _load_torque_curation,
    _read_torque_series,
    _torque_source_files,
)


def prepare_mechanical_source(
    context: SemanticPreparationContext,
) -> dict[str, Any] | None:
    source = context.source
    processed_dir = context.processed_dir
    family = context.family
    curation_path = context.curation_path
    series_order = context.series_order
    replicate_mode = context.replicate_mode

    if family in _NON_TENSILE_MECHANICAL_CONTRACTS:
        processed_source = processed_dir / f"{source.stem}_{family}_curves.csv"
        curated_workbooks = (
            _read_non_tensile_mechanical_workbook_directory(
                source,
                family=family,
            )
            if source.is_dir()
            else None
        )
        if curated_workbooks is None:
            series_list = _read_non_tensile_mechanical_series(
                source,
                family=family,
            )
            summary_rows = None
        else:
            series_list, summary_rows = curated_workbooks
        if not _series_order_map(series_order):
            series_list = _order_recycled_pa_pair_control_first(
                series_list,
                sample_of=lambda series: series.sample,
            )
            if summary_rows is not None:
                summary_rows = _order_recycled_pa_pair_control_first(
                    summary_rows,
                    sample_of=lambda row: row.get("sample"),
                )
        input_series_labels = [series.sample for series in series_list]
        summary_source = processed_source.with_name(
            f"{processed_source.stem}_summary.csv"
        )
        if summary_rows is None:
            _write_non_tensile_mechanical_summary_table(
                series_list,
                summary_source,
                family=family,
            )
        else:
            pd.DataFrame(summary_rows).to_csv(summary_source, index=False)
        requested_replicate_mode = _normalized_replicate_mode(replicate_mode)
        representative_applied = False
        grouped_input = _has_intake_grouped_series(series_list)
        additional_outputs = (summary_source,)
        if grouped_input:
            all_source = processed_source.with_name(f"{processed_source.stem}_all.csv")
            _write_curve_table(series_list, all_source)
            additional_outputs = (all_source, summary_source)
            if requested_replicate_mode != "individual":
                series_list = _representative_tensile_series(series_list)
                representative_applied = True
        series_list = _order_curve_series(series_list, series_order)
        _write_curve_table(series_list, processed_source)
        strength_metric = str(
            _NON_TENSILE_MECHANICAL_CONTRACTS[family]["strength_metric"]
        )
        return _semantic_preparation_result(
            source,
            processed_source=processed_source,
            operation=f"extract_{family}_curves",
            parameters={
                "input_series_labels": input_series_labels,
                "output_series_labels": [series.sample for series in series_list],
                "series_order": [series.sample for series in series_list],
                "requested_replicate_mode": requested_replicate_mode,
                "applied_curve_replicate_mode": (
                    "representative" if representative_applied else "individual"
                ),
                "representative_selection_applied": representative_applied,
                "all_series_preserved_in_supporting_output": grouped_input,
                "summary_metric_source": str(summary_source),
                "summary_replicate_count": (
                    len(summary_rows)
                    if summary_rows is not None
                    else len(input_series_labels)
                ),
                "summary_raw_specimen_count": (
                    len(summary_rows) if summary_rows is not None else None
                ),
                "summary_metric_source_kind": (
                    "All_Specimens workbook sheets"
                    if summary_rows is not None
                    else "retained curve maxima"
                ),
                "summary_metric_definitions": {
                    strength_metric: (
                        "maximum stress magnitude from each retained curve"
                        if family == "compression_curve"
                        else "maximum stress from each retained curve"
                    ),
                },
            },
            additional_outputs=additional_outputs,
        )

    if family == "tensile_curve" and source.is_dir():
        csv_sources = _tensile_export_files(source)
        workbook_sources = [
            path
            for path in sorted(source.rglob("*"))
            if path.is_file() and path.suffix.lower() in {".xlsx", ".xls"}
        ]
        if not csv_sources and workbook_sources:
            processed_source = processed_dir / f"{source.stem}_tensile_curves.csv"
            series_list, summary_rows = _read_tensile_workbook_directory(source)
            if not _series_order_map(series_order):
                series_list = _order_recycled_pa_pair_control_first(
                    series_list,
                    sample_of=lambda series: series.sample,
                )
                summary_rows = _order_recycled_pa_pair_control_first(
                    summary_rows,
                    sample_of=lambda row: row.get("sample"),
                )
            series_list = _order_curve_series(series_list, series_order)
            _write_curve_table(series_list, processed_source)
            summary_source = processed_source.with_name(
                f"{processed_source.stem}_summary.csv"
            )
            pd.DataFrame(summary_rows).to_csv(summary_source, index=False)
            return _semantic_preparation_result(
                source,
                processed_source=processed_source,
                operation="extract_tensile_workbook_directory",
                parameters={
                    "input_workbooks": [str(path) for path in workbook_sources],
                    "output_series_labels": [series.sample for series in series_list],
                    "series_order": [series.sample for series in series_list],
                    "representative_definition": "Representative_Curve sheet from each workbook",
                    "summary_metric_source": "All_Specimens sheet from each workbook",
                    "summary_replicate_count": len(summary_rows),
                },
                additional_outputs=(summary_source,),
            )

    if family == "tensile_curve" and (
        source.is_dir() or source.suffix.lower() == ".csv"
    ):
        processed_source = processed_dir / f"{source.stem}_tensile_curves.csv"
        series_list = _read_tensile_export_series_list(source)
        input_series_labels = [series.sample for series in series_list]
        summary_source = processed_source.with_name(
            f"{processed_source.stem}_summary.csv"
        )
        _write_tensile_summary_table(series_list, summary_source)
        requested_replicate_mode = _normalized_replicate_mode(replicate_mode)
        representative_applied = False
        grouped_input = _has_intake_grouped_series(series_list)
        additional_outputs: tuple[Path, ...] = (summary_source,)
        if grouped_input:
            all_source = processed_source.with_name(f"{processed_source.stem}_all.csv")
            _write_curve_table(series_list, all_source)
            additional_outputs = (all_source, summary_source)
            if requested_replicate_mode != "individual":
                series_list = _representative_tensile_series(series_list)
                representative_applied = True
        series_list = _order_curve_series(series_list, series_order)
        _write_curve_table(series_list, processed_source)
        return _semantic_preparation_result(
            source,
            processed_source=processed_source,
            operation="extract_tensile_curves",
            parameters={
                "input_series_labels": input_series_labels,
                "output_series_labels": [series.sample for series in series_list],
                "requested_replicate_mode": requested_replicate_mode,
                "applied_curve_replicate_mode": (
                    "representative" if representative_applied else "individual"
                ),
                "representative_selection_applied": representative_applied,
                "representative_definition": (
                    "closest to group median tensile strength, then break strain, with deterministic sample order"
                    if representative_applied
                    else None
                ),
                "all_series_preserved_in_supporting_output": grouped_input,
                "summary_metric_source": str(summary_source),
                "summary_replicate_count": len(input_series_labels),
                "summary_metric_definitions": {
                    "strength_MPa": "instrument-reported maximum tensile stress, else curve maximum",
                    ELONGATION_AT_BREAK_METRIC: "instrument-reported elongation at break, else curve terminal strain",
                    "modulus_MPa": (
                        "instrument-reported 0.05%-0.25% program-segment modulus, else curve fit with "
                        "percent strain converted to a fraction"
                    ),
                    "toughness_MJ_m3": "stress integral over engineering-strain fraction up to break",
                },
            },
            additional_outputs=additional_outputs,
        )

    if family == "tensile_curve" and source.suffix.lower() in {".xlsx", ".xls"}:
        processed_source = processed_dir / f"{source.stem}_tensile_workbook_curves.csv"
        series_list = _read_tensile_workbook_series(source)
        series_list = _order_curve_series(series_list, series_order)
        _write_curve_table(series_list, processed_source)
        return _semantic_preparation_result(
            source,
            processed_source=processed_source,
            operation="extract_tensile_workbook_curves",
            parameters={"series_order": [series.sample for series in series_list]},
        )

    if family == "torque_curve":
        processed_source = processed_dir / "torque_comparison.csv"
        curation = _load_torque_curation(curation_path)
        series_list = [
            _read_torque_series(path, curation=curation)
            for path in _torque_source_files(source)
        ]
        if not series_list:
            raise ValueError(f"No torque exports found under {source}.")
        series_list = _order_curve_series(series_list, series_order)
        if curation is None and not _series_order_map(series_order):
            series_list = _compact_torque_series_labels(series_list)
        _write_curve_table(series_list, processed_source)
        event_selections = [
            {
                "sample": series.sample,
                **((series.diagnostics or {}).get("event_selection") or {}),
                "source_point_count": (series.diagnostics or {}).get(
                    "source_point_count"
                ),
                "selected_point_count": (series.diagnostics or {}).get(
                    "selected_point_count"
                ),
            }
            for series in series_list
        ]
        return _semantic_preparation_result(
            source,
            processed_source=processed_source,
            operation="extract_torque_curves",
            parameters={
                "curation_path": str(Path(curation_path).expanduser())
                if curation_path is not None
                else None,
                "curation_applied": curation is not None,
                "series_order": [series.sample for series in series_list],
                "automatic_event_selection_applied": curation is None,
                "event_selection_policy": (
                    "explicit_curation"
                    if curation is not None
                    else "last_confident_feed_peak_to_discharge_drop"
                ),
                "event_selections": event_selections,
                "needs_human_review": any(
                    bool(item.get("needs_human_review")) for item in event_selections
                ),
                "unconfirmed_events_preserve_full_curve": True,
            },
        )

    if family == "impact_metric" and (
        source.is_dir() or source.suffix.lower() in {".xlsx", ".xls", ".csv"}
    ):
        impact = _read_impact_source(source)
        processed_source = processed_dir / f"{source.stem}_impact_replicates.csv"
        pd.DataFrame(impact.rows).to_csv(processed_source, header=False, index=False)
        return _semantic_preparation_result(
            source,
            processed_source=processed_source,
            operation="extract_impact_replicates",
            parameters={
                "group_count": len(impact.samples),
                "sample_order": list(impact.samples),
                "replicate_counts": dict(
                    zip(impact.samples, impact.replicate_counts, strict=True)
                ),
                "replicate_count_total": impact.total_replicates,
                "raw_values_preserved": True,
                "canonical_unit": impact.unit,
                "summary_statistic_default": "median_iqr",
                "minimum_box_replicates": 2,
            },
        )
    return None
