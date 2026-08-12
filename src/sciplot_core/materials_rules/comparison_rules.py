"""Declare comparison rules."""

from __future__ import annotations

from sciplot_core.materials_rules.models import (
    AxisSpec,
    SemanticRule,
    _rule,
)


COMPARISON_RULES: tuple[SemanticRule, ...] = (
    _rule(
        "performance_comparison",
        "performance_comparison",
        None,
        "scatter",
        AxisSpec(
            "Selected performance X metric",
            "",
            "Selected performance X metric",
            aliases=("scatter x", "density", "横轴指标"),
        ),
        AxisSpec(
            "Selected performance Y metric",
            "",
            "Selected performance Y metric",
            aliases=("scatter y", "specific impact strength", "纵轴指标"),
        ),
        presentation_data_shape="material_metric_long",
        supported_templates=("scatter", "polar_curve"),
        render_adapter="performance",
        figure_plan_adapter="performance",
        keywords=("scatteraxis", "radarorder", "materialperformance"),
        path_keywords=("performance_comparison", "material_performance"),
        column_aliases=(
            "material",
            "role",
            "metric",
            "value",
            "unit",
            "scatteraxis",
            "radarorder",
        ),
        render_options={
            "size": "120x55",
            "legend_position": "auto",
            "series_label_mode": "legend",
        },
        fixture_path=(
            "tests/fixtures/real_world/performance_comparison/"
            "mrpa_rpa_performance_long.csv"
        ),
        fixture_status="ready",
        priority=1,
        reason=(
            "Accepted tidy material-performance comparison with sample/reference "
            "roles, scatter-axis selection, declared radar bounds, and optional "
            "literature metadata."
        ),
    ),
)
