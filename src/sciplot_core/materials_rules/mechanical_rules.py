"""Declare mechanical rules."""

from __future__ import annotations

from sciplot_core.policy import (
    CATEGORICAL_DISTRIBUTION_RENDER_OPTIONS,
    TORQUE_CURVE_RENDER_OPTIONS,
)
from sciplot_core.materials_rules.models import (
    ELONGATION_AT_BREAK_METRIC,
    AxisSpec,
    AnalysisSpec,
    SemanticRule,
    _rule,
)

from sciplot_core.materials_rules.catalog_axes import (
    TIME_AXIS,
    TENSILE_STRAIN_AXIS,
    TENSILE_STRESS_AXIS,
    COMPRESSION_STRAIN_AXIS,
    COMPRESSION_STRESS_AXIS,
    FLEXURAL_STRAIN_AXIS,
    FLEXURAL_STRESS_AXIS,
    TORQUE_AXIS,
)

MECHANICAL_RULES: tuple[SemanticRule, ...] = (
    _rule(
        "tensile_curve",
        "tensile_curve",
        "tensile",
        "curve",
        TENSILE_STRAIN_AXIS,
        TENSILE_STRESS_AXIS,
        keywords=("tensile", "拉伸", "结果表格2"),
        path_keywords=("tensile", ".is_tens_exports"),
        vendor_models=("tensile_curve",),
        analysis=(
            AnalysisSpec(
                "modulus_MPa", "low-strain linear slope", ("strain", "stress"), "MPa"
            ),
            AnalysisSpec("strength_MPa", "maximum tensile stress", ("stress",), "MPa"),
            AnalysisSpec(ELONGATION_AT_BREAK_METRIC, "last strain", ("strain",), "%"),
            AnalysisSpec(
                "toughness_MJ_m3",
                "area under stress-strain curve using engineering strain as a fraction",
                ("strain", "stress"),
                "MJ/m3",
            ),
        ),
        fixture_path="tests/fixtures/real_world/tensile_curve/E0 2MM.is_tens_Exports",
        fixture_status="ready",
        priority=40,
        render_adapter="mechanical",
        figure_plan_adapter="mechanical",
        preparation_adapter="mechanical",
    ),
    _rule(
        "torque_curve",
        "torque_curve",
        "rheology_dma",
        "curve",
        TIME_AXIS,
        TORQUE_AXIS,
        keywords=(
            "screwtorque",
            "screw torque",
            "screw speed",
            "setting torque",
            "转矩",
        ),
        path_keywords=("torque", "转矩"),
        column_aliases=("screw torque", "转矩"),
        analysis=(
            AnalysisSpec(
                "selected_event_mean_torque_Nm_by_sample",
                "mean torque over the recorded selected final event, reported separately for each sample",
                ("Screw Torque",),
                "N·m",
            ),
        ),
        render_options=dict(TORQUE_CURVE_RENDER_OPTIONS),
        fixture_path="tests/fixtures/real_world/torque_curve/260607",
        fixture_status="ready",
        priority=42,
        preparation_adapter="mechanical",
        reason="Torque rheometer export with Screw Torque over time.",
    ),
    _rule(
        "compression_curve",
        "compression_curve",
        "tensile",
        "curve",
        COMPRESSION_STRAIN_AXIS,
        COMPRESSION_STRESS_AXIS,
        keywords=("compression", "compressive", "压缩"),
        path_keywords=("compression_curve", "compressive"),
        analysis=(
            AnalysisSpec(
                "compressive_strength_MPa",
                "maximum magnitude of compressive stress",
                ("strain", "stress"),
                "MPa",
            ),
        ),
        fixture_path="tests/fixtures/real_world/compression_curve/conventional_pu_compression.csv",
        fixture_status="ready",
        priority=34,
        render_adapter="mechanical",
        figure_plan_adapter="mechanical",
        preparation_adapter="mechanical",
    ),
    _rule(
        "flexural_curve",
        "flexural_curve",
        "tensile",
        "curve",
        FLEXURAL_STRAIN_AXIS,
        FLEXURAL_STRESS_AXIS,
        keywords=("flexural", "bending", "弯曲"),
        path_keywords=("flexural_curve", "bending"),
        analysis=(
            AnalysisSpec(
                "flexural_strength_MPa",
                "maximum flexural stress",
                ("strain", "stress"),
                "MPa",
            ),
        ),
        fixture_path="tests/fixtures/real_world/flexural_curve/A_HA56_dry_flexural.csv",
        fixture_status="ready",
        priority=34,
        render_adapter="mechanical",
        figure_plan_adapter="mechanical",
        preparation_adapter="mechanical",
    ),
    _rule(
        "impact_metric",
        "impact_metric",
        "metrics_swelling",
        "box_strip",
        AxisSpec("Sample", "", "Sample", aliases=("sample",)),
        AxisSpec(
            "Impact strength",
            "kJ/m2",
            "Impact strength (kJ m⁻²)",
            aliases=("impact strength", "冲击"),
        ),
        keywords=("impact", "冲击"),
        render_options={
            **CATEGORICAL_DISTRIBUTION_RENDER_OPTIONS,
            "x_label_override": "Sample",
            "y_label_override": "Impact strength (kJ m⁻²)",
            "summary_statistic": "median_iqr",
        },
        analysis=(
            AnalysisSpec(
                "impact_group_n", "per-sample raw replicate count", ("impact",), "count"
            ),
            AnalysisSpec(
                "impact_group_median",
                "per-sample median of raw values",
                ("impact",),
                "kJ/m2",
            ),
            AnalysisSpec(
                "impact_group_iqr",
                "per-sample interquartile range when at least two raw values are available",
                ("impact",),
                "kJ/m2",
            ),
        ),
        fixture_path="tests/fixtures/real_world/impact_metric/impact strength.xlsx",
        fixture_status="ready",
        priority=5,
        reason=(
            "Impact-strength groups preserve every raw observation; groups with at least two replicates use a native Veusz median/IQR box summary, while smaller groups remain raw-point only."
        ),
        presentation_data_shape="categorical_replicates",
        supported_templates=("bar", "box", "box_strip", "point_line"),
        render_adapter="impact",
        figure_plan_adapter="impact",
        preparation_adapter="mechanical",
    ),
)
