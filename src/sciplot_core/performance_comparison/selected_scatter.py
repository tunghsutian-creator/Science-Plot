"""Keep selected missing observations in provenance and render valid raw pairs."""

from __future__ import annotations

from dataclasses import replace
from typing import Any

from sciplot_core.performance_comparison.models import (
    PerformanceComparison,
    PerformanceComparisonError,
)
from sciplot_core.performance_comparison.scatter import (
    build_performance_scatter_payload,
)


def selected_source_evidence(payload: dict[str, Any]) -> dict[str, Any]:
    fields = (
        "performance_selection",
        "source_row_count",
        "source_material_count",
        "selected_row_count",
        "excluded_metrics",
        "source_observations",
        "valid_pair_count",
        "missing_pair_count",
        "literal_metric_labels",
    )
    if not set(fields) <= set(payload):
        raise ValueError("Selected performance scientific evidence is incomplete.")
    return {key: payload[key] for key in fields}


def build_selected_scatter_payload(comparison: PerformanceComparison) -> dict[str, Any]:
    if comparison.selection is None:
        return build_performance_scatter_payload(comparison)
    valid = {
        item["material"]
        for item in comparison.source_observations
        if item["valid_pair"]
    }
    if not valid:
        raise PerformanceComparisonError(
            "performance_selected_pairs_missing",
            "Selected metrics contain no complete finite original X/Y pairs; missing values remain in the source.",
        )
    plotted = replace(
        comparison,
        materials=tuple(
            item for item in comparison.materials if item.material_id in valid
        ),
    )
    payload = build_performance_scatter_payload(plotted)
    payload.update(
        {
            "performance_selection": comparison.selection,
            "source_observations": list(comparison.source_observations),
            "source_material_count": len(comparison.materials),
            "selected_row_count": comparison.selected_row_count,
            "excluded_metrics": list(comparison.excluded_metrics),
            "literal_metric_labels": list(comparison.literal_metric_labels),
            "valid_pair_count": len(valid),
            "missing_pair_count": len(comparison.materials) - len(valid),
            "missing_observation_policy": "Retain original cells, source rows and missing masks; draw only complete finite pairs without imputation or aggregation.",
        }
    )
    return payload
