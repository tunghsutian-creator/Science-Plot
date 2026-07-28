"""Declare thermal rules."""

from __future__ import annotations

from sciplot_core.materials_rules.models import (
    AxisSpec,
    AnalysisSpec,
    SemanticRule,
    _rule,
)

from sciplot_core.materials_rules.catalog_axes import (
    RHEOLOGY_X_TEMPERATURE,
)

THERMAL_RULES: tuple[SemanticRule, ...] = (
    _rule(
        "dsc_curve",
        "dsc_curve",
        "thermal",
        "curve",
        RHEOLOGY_X_TEMPERATURE,
        AxisSpec("Heat flow", "W/g", "Heat flow (W g⁻¹)", aliases=("heat flow", "dsc")),
        keywords=("dsc", "heatflow", "heat flow"),
        column_aliases=("heat flow",),
        analysis=(
            AnalysisSpec(
                "tg_candidate_C",
                "largest heat-flow slope candidate",
                ("temperature", "heat flow"),
                "C",
            ),
            AnalysisSpec(
                "peak_temperature_C",
                "largest absolute heat-flow peak",
                ("temperature", "heat flow"),
                "C",
            ),
        ),
        fixture_path="tests/fixtures/real_world/dsc_curve/udc_dsc_digitized.csv",
        fixture_status="ready",
        priority=8,
    ),
    _rule(
        "tga_curve",
        "tga_curve",
        "thermal",
        "curve",
        RHEOLOGY_X_TEMPERATURE,
        AxisSpec("Mass", "%", "Mass (%)", aliases=("weight", "mass", "tga")),
        keywords=("tga", "weightloss", "weight"),
        column_aliases=("temp", "weight"),
        analysis=(
            AnalysisSpec(
                "residual_mass_percent", "last finite mass percent", ("mass",), "%"
            ),
            AnalysisSpec(
                "t5_temperature_C",
                "temperature at 5% mass loss",
                ("temperature", "mass"),
                "C",
            ),
            AnalysisSpec(
                "t10_temperature_C",
                "temperature at 10% mass loss",
                ("temperature", "mass"),
                "C",
            ),
        ),
        fixture_path="tests/fixtures/real_world/tga_curve/evoh1_tga_curve.csv",
        fixture_status="ready",
        priority=42,
    ),
    _rule(
        "dtg_curve",
        "dtg_curve",
        "thermal",
        "curve",
        RHEOLOGY_X_TEMPERATURE,
        AxisSpec(
            "Derivative mass", "%/C", "DTG (% °C⁻¹)", aliases=("dtg", "derivative")
        ),
        keywords=("dtg", "derivativeweight"),
        path_keywords=("dtg_curve", "dtg"),
        column_aliases=("temperature", "dtg", "derivative"),
        analysis=(
            AnalysisSpec(
                "dtg_peak_temperature_C",
                "maximum derivative loss",
                ("temperature", "dtg"),
                "C",
            ),
        ),
        fixture_path="tests/fixtures/real_world/dtg_curve/evoh1_dtg_curve.csv",
        fixture_status="ready",
        priority=32,
    ),
)
