"""Assemble a complete typed performance comparison from a tidy table."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from sciplot_core.foundation.file_hashing import file_sha256
from sciplot_core.source_tables.parsing import DECIMAL_ROUND_TRIP_ENCODING

from sciplot_core.performance_comparison.material_loading import (
    load_performance_materials,
)
from sciplot_core.performance_comparison.metric_loading import (
    load_performance_metrics,
)
from sciplot_core.performance_comparison.models import (
    PerformanceComparison,
    PerformanceComparisonError,
)
from sciplot_core.performance_comparison.source_rows import (
    normalize_performance_rows,
)


def load_performance_comparison(source: str | Path, *, selection: dict[str, Any] | None = None,
                                source_numeric_encoding: str = DECIMAL_ROUND_TRIP_ENCODING,
                                compatibility_fused_digits: bool | None = True) -> PerformanceComparison:
    """Load and validate the tidy performance-comparison table."""

    (
        source_path,
        normalized,
        material_first_order,
        metric_first_order,
        source_row_count,
    ) = normalize_performance_rows(source, selection=selection, source_numeric_encoding=source_numeric_encoding,
                                  compatibility_fused_digits=compatibility_fused_digits)
    comparison = PerformanceComparison(
        source=source_path,
        source_sha256=file_sha256(source_path),
        source_row_count=source_row_count,
        metrics=tuple(
            load_performance_metrics(
                normalized,
                metric_first_order=metric_first_order,
            )
        ),
        materials=tuple(
            load_performance_materials(
                normalized,
                material_first_order=material_first_order,
            )
        ),
        selection=normalized.attrs.get("performance_selection"),
        source_observations=tuple(normalized.attrs.get("source_observations", [])),
        selected_row_count=len(normalized) if selection is not None else None,
        excluded_metrics=tuple(normalized.attrs.get("excluded_metrics", [])),
        literal_metric_labels=tuple(normalized.attrs.get("literal_metric_labels", [])),
    )
    if not comparison.samples:
        raise PerformanceComparisonError(
            "performance_samples_missing",
            "Performance comparison data need at least one Role=sample material.",
        )
    if selection is not None and comparison.source_sha256 != selection["source_sha256"]:
        raise PerformanceComparisonError("performance_selection_source_changed", "Original table changed while loading the selected performance metrics.")
    return comparison
