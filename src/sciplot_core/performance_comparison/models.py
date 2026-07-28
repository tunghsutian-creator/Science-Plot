"""Define validated performance-comparison domain models and identifiers."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from sciplot_core.materials_rules import format_unit_label


PERFORMANCE_COMPARISON_RULE_ID = "performance_comparison"


PERFORMANCE_SCATTER_TEMPLATE_ID = "scatter"


PERFORMANCE_RADAR_TEMPLATE_ID = "polar_curve"


class PerformanceComparisonError(ValueError):
    """Fail-closed source-contract error for performance comparisons."""

    def __init__(self, reason_code: str, message: str) -> None:
        self.reason_code = reason_code
        super().__init__(message)


@dataclass(frozen=True)
class PerformanceMetric:
    metric_id: str
    display_label: str
    unit: str
    source_order: int
    scatter_axis: str | None = None
    scatter_min: float | None = None
    scatter_max: float | None = None
    radar_order: int | None = None
    direction: str | None = None
    scale_min: float | None = None
    scale_max: float | None = None

    @property
    def axis_label(self) -> str:
        return (
            f"{self.display_label} ({_display_unit(self.unit)})"
            if self.unit
            else self.display_label
        )

    @property
    def radar_label(self) -> str:
        return self.display_label


@dataclass(frozen=True)
class PerformanceMaterial:
    material_id: str
    role: str
    group: str
    envelope_include: bool
    legend_label: str
    legend_label_explicit: bool
    legend_group: str
    legend_identity: str
    legend_column: int
    legend_items_per_row: int
    source_order: int
    material_order: float | None
    journal: str
    year: str
    doi: str
    marker: str | None
    marker_line_color: str | None
    marker_fill_color: str | None
    values: dict[str, float]

    @property
    def citation(self) -> str:
        if self.journal and self.year:
            return f"{self.journal} ({self.year})"
        return self.journal or self.year


@dataclass(frozen=True)
class PerformanceComparison:
    source: Path
    source_sha256: str
    source_row_count: int
    metrics: tuple[PerformanceMetric, ...]
    materials: tuple[PerformanceMaterial, ...]

    @property
    def samples(self) -> tuple[PerformanceMaterial, ...]:
        return tuple(item for item in self.materials if item.role == "sample")

    @property
    def references(self) -> tuple[PerformanceMaterial, ...]:
        return tuple(item for item in self.materials if item.role == "reference")

    @property
    def scatter_metrics(self) -> tuple[PerformanceMetric, PerformanceMetric]:
        x_metrics = [item for item in self.metrics if item.scatter_axis == "x"]
        y_metrics = [item for item in self.metrics if item.scatter_axis == "y"]
        if len(x_metrics) != 1 or len(y_metrics) != 1:
            raise PerformanceComparisonError(
                "performance_scatter_axes_invalid",
                "Performance scatter data need exactly one metric marked x and "
                "one metric marked y in the ScatterAxis column.",
            )
        return x_metrics[0], y_metrics[0]

    @property
    def radar_metrics(self) -> tuple[PerformanceMetric, ...]:
        metrics = sorted(
            (item for item in self.metrics if item.radar_order is not None),
            key=lambda item: (int(item.radar_order or 0), item.source_order),
        )
        if len(metrics) < 3:
            raise PerformanceComparisonError(
                "performance_radar_needs_three_metrics",
                "Performance radar data need at least three metrics with a "
                "RadarOrder value.",
            )
        orders = [int(item.radar_order or 0) for item in metrics]
        if len(orders) != len(set(orders)):
            raise PerformanceComparisonError(
                "performance_radar_order_duplicate",
                "RadarOrder values must be unique across radar metrics.",
            )
        return tuple(metrics)


def _display_unit(value: str) -> str:
    return format_unit_label(value)
