"""Prepare tensile, non-tensile mechanical, torque, and impact sources."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pandas as pd

from sciplot_core.semantic_sources.preparation_context import SemanticPreparationContext

from sciplot_core.semantic_sources.curve_output import (
    _write_curve_table,
)

from sciplot_core.semantic_sources.impact_sources import (
    _read_impact_source,
)

from sciplot_core.semantic_sources.mechanical_materialization import (
    prepare_exact_mechanical_source,
)

from sciplot_core.semantic_sources.preparation_support import (
    _semantic_preparation_result,
)

from sciplot_core.semantic_sources.series_ordering import (
    _order_curve_series,
    _series_order_map,
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

    exact_mechanical = prepare_exact_mechanical_source(context)
    if exact_mechanical is not None:
        return exact_mechanical

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
                "automatic_event_selection_applied": False,
                "event_selection_policy": "explicit_curation_or_full_source",
                "event_selections": event_selections,
                "needs_human_review": any(
                    bool(item.get("needs_human_review")) for item in event_selections
                ),
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
