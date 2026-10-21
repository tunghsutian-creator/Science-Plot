"""Closed source options shared by planning and exact-current plan replay."""

from __future__ import annotations

from pathlib import Path
from typing import Any


_ORDINARY_KEYS = frozenset({"xscale", "summary_statistic", "replicate_summary_disclosure", "performance_selection"})
_CATEGORICAL_KEYS = frozenset({"categorical_binding", "missing_values", "render_options", "summary_statistic", "replicate_summary_disclosure"})
SOURCE_OPTION_KEYS = _ORDINARY_KEYS | _CATEGORICAL_KEYS


def source_options(request: dict[str, Any]) -> dict[str, Any]:
    keys = _CATEGORICAL_KEYS if "categorical_binding" in request else _ORDINARY_KEYS
    return {key: request[key] for key in sorted(keys) if key in request}


def validate_source_options(source: Path, request: dict[str, Any], *, rule_id: str | None, template: str) -> dict[str, Any]:
    options = source_options(request)
    if "performance_selection" in options:
        from sciplot_core.performance_comparison.selection import parse_performance_selection
        if rule_id != "performance_comparison" or template != "scatter":
            raise ValueError("Performance metric selection is supported only for performance_comparison scatter.")
        options["performance_selection"] = parse_performance_selection(options["performance_selection"])
    if "xscale" in options and (rule_id != "rheology_stress_relaxation" or options["xscale"] not in ("log", "linear")):
        raise ValueError("Explicit xscale is supported only for stress-relaxation log/linear time.")
    if "summary_statistic" in options:
        summary = options["summary_statistic"]
        if rule_id != "impact_metric" or not (
            (template in {"box", "box_strip"} and summary == "raw_only")
            or (template == "bar" and summary == "mean_sample_sd_n")
        ):
            raise ValueError("Categorical source options support raw_only for Impact box/box_strip and mean_sample_sd_n for Impact bar; other fixed methods remain unchanged.")
        if summary == "mean_sample_sd_n":
            from sciplot_core.semantic_sources.impact_replicate_disclosure import validate_replicate_disclosure

            options["replicate_summary_disclosure"] = validate_replicate_disclosure(source, options.get("replicate_summary_disclosure"))
    if "replicate_summary_disclosure" in options and options.get("summary_statistic") != "mean_sample_sd_n":
        raise ValueError("Replicate disclosure is valid only with the delivered mean_sample_sd_n contract.")
    return options


def expected_source_options(value: object) -> dict[str, Any]:
    if not isinstance(value, dict) or not value:
        raise ValueError("Expected plan has invalid source options.")
    keys = _CATEGORICAL_KEYS if "categorical_binding" in value else _ORDINARY_KEYS
    if not set(value) <= keys:
        raise ValueError("Expected plan has invalid source options.")
    return dict(value)
