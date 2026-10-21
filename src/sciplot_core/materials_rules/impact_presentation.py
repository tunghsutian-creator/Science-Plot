"""Declare the fixed statistics of the existing Impact presentation executors."""

from __future__ import annotations

from typing import Any


def impact_presentation_statistics(template: str, *, summary_statistic: str | None = None) -> dict[str, Any]:
    """Keep display statistics separate from the default box render option."""
    if template in {"box", "box_strip"} and summary_statistic == "raw_only":
        return {
            "summary_statistic": "raw_only", "center": None, "spread": None,
            "summary_layers": [], "summary_calculation": "none",
            "source_requirement": "impact_replicates", "n_disclosure": "none",
        }
    if template in {"box", "box_strip"}:
        return {
            "summary_statistic": "median_iqr", "center": "median",
            "spread": "interquartile_range", "quartile_method": "linear_interpolation",
            "source_requirement": "impact_replicates",
            "n_disclosure": "internal_analysis_metrics_only",
        }
    if template in {"bar", "point_line"}:
        return {
            "summary_statistic": "mean_sample_sd_n" if template == "bar" and summary_statistic == "mean_sample_sd_n" else "mean_sample_sd", "center": "arithmetic_mean",
            "spread": "sample_standard_deviation", "ddof": 1,
            "minimum_replicates_for_sample_sd": 2,
            "singleton_rendering": "blocked_undefined_sample_sd" if summary_statistic == "mean_sample_sd_n" else "zero_error_without_a_defined_sample_sd",
            "source_requirement": ("at_least_two_compatible_workbook_conditions"
                                   if template == "point_line" else "impact_replicates"),
            "n_disclosure": "delivered_summary_csv" if template == "bar" and summary_statistic == "mean_sample_sd_n" else "internal_analysis_metrics_only",
        }
    raise ValueError(f"Unsupported Impact presentation: {template!r}.")


def impact_statistics_by_template() -> dict[str, dict[str, Any]]:
    return {template: impact_presentation_statistics(template)
            for template in ("bar", "box", "box_strip", "point_line")}
