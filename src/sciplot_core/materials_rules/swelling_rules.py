"""Declare swelling rules."""

from __future__ import annotations

from sciplot_core.materials_rules.models import (
    AxisSpec,
    AnalysisSpec,
    SemanticRule,
    _rule,
)


SWELLING_RULES: tuple[SemanticRule, ...] = (
    _rule(
        "swelling_curve",
        "swelling_curve",
        "metrics_swelling",
        "point_line",
        AxisSpec("Time", "h", "Time (h)", aliases=("time",)),
        AxisSpec(
            "Swelling ratio",
            "1",
            "Swelling ratio",
            aliases=("swelling ratio", "Ai/A0", "normalized projected area"),
        ),
        keywords=("swelling ratio",),
        column_aliases=("swelling ratio",),
        analysis=(
            AnalysisSpec(
                "terminal_swelling_ratio",
                "last finite reported swelling ratio per curve; not inferred as equilibrium",
                ("swelling ratio",),
                "1",
            ),
        ),
        fixture_path="tests/fixtures/real_world/swelling_curve/Data_Core_Shell_Hydrogels.xlsx",
        fixture_status="ready",
        priority=55,
        reason=(
            "Use explicit swelling-curve intent for labeled time/Ai-A0 observations; gel fraction alone is not treated as swelling kinetics."
        ),
    ),
)
