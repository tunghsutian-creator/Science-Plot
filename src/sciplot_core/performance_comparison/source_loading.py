"""Assemble a complete typed performance comparison from a tidy table."""

from __future__ import annotations

from pathlib import Path

from sciplot_core.foundation.file_hashing import file_sha256

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


def load_performance_comparison(source: str | Path) -> PerformanceComparison:
    """Load and validate the tidy performance-comparison table."""

    (
        source_path,
        normalized,
        material_first_order,
        metric_first_order,
        source_row_count,
    ) = normalize_performance_rows(source)
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
    )
    if not comparison.samples:
        raise PerformanceComparisonError(
            "performance_samples_missing",
            "Performance comparison data need at least one Role=sample material.",
        )
    return comparison
