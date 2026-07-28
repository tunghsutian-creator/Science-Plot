"""Select recommendation plans for non-curve source shapes."""

from __future__ import annotations

from pathlib import Path

from sciplot_core.source_inspection.curve_plans import (
    curve_recommendation_plan,
)
from sciplot_core.source_inspection.model_recognition import RecognizedSource
from sciplot_core.source_inspection.plan_models import RecommendationPlan


def _bundle_plan(model: str) -> RecommendationPlan:
    if model == "frequency_sweep":
        return RecommendationPlan(
            template="point_line",
            score=86.0,
            reason=(
                "Detected a frequency sweep rheology export table with 5 "
                "columns per bundle."
            ),
            overrides={"xscale": "log", "yscale": "log", "reverse_x": False},
            warnings=("This export will generate 4 PDF files.",),
            signals=(
                "Detected a 5-column rheology export bundle.",
                "The first x-axis field is Angular Frequency / ω.",
                (
                    "Each bundle includes Storage/Loss Modulus, Loss Factor, "
                    "and Complex Viscosity."
                ),
            ),
            alternatives=(("curve", 81.0, "Curve remains a lighter bundle view."),),
        )
    if model == "temperature_sweep":
        return RecommendationPlan(
            template="point_line",
            score=86.0,
            reason=(
                "Detected a temperature sweep rheology export table with 5 "
                "columns per bundle."
            ),
            overrides={
                "size": "120x55",
                "xscale": "linear",
                "yscale": "log",
                "reverse_x": False,
            },
            warnings=("This export will generate 2 PDF files.",),
            signals=(
                "Detected a 5-column rheology export bundle.",
                "The first x-axis field is Temperature.",
                (
                    "Each bundle includes Storage/Loss Modulus, Loss Factor, "
                    "and Complex Viscosity."
                ),
            ),
            alternatives=(("curve", 81.0, "Curve remains a lighter bundle view."),),
        )
    return RecommendationPlan(
        template="point_line",
        score=88.0,
        reason=("Detected a stress relaxation export table with 4 columns per bundle."),
        overrides={"xscale": "linear", "yscale": "linear", "reverse_x": False},
        signals=(
            "Detected a 4-column stress relaxation export bundle.",
            "The first x-axis field is Time.",
            "The bundle includes the σ/σ₀ metric.",
        ),
        alternatives=(("curve", 82.0, "Curve remains a lighter bundle view."),),
    )


def _replicate_plan(recognized: RecognizedSource) -> RecommendationPlan:
    intent = recognized.intent
    template = intent.recommended_template if intent is not None else "box"
    reason = (
        intent.reason
        if intent is not None
        else (
            "Detected a statistical table with a shared y-axis label, sample "
            "names, units, and replicate values."
        )
    )
    warnings = (
        ("There are many groups, so x-axis labels may wrap or shrink.",)
        if len(recognized.replicate_groups) >= 6
        else ()
    )
    signals = (
        intent.signals
        if intent is not None
        else (
            "Cell A1 provides the shared y-axis label.",
            "Row 2 contains group names and row 3 contains units.",
            (
                "Row 4 onward contains replicate values, which fits "
                "statistical plots well."
            ),
        )
    )
    return RecommendationPlan(
        template=template,
        score=86.0 if intent is not None else 83.0,
        reason=reason,
        overrides={},
        signals=signals,
        warnings=warnings,
        alternatives=(
            ("box_strip", 80.0, "Box-strip retains raw replicate visibility."),
            ("bar", 76.0, "Bar emphasizes a categorical summary."),
        ),
        confidence=83.5 if intent is None else None,
    )


def recommendation_plan(
    source: Path,
    recognized: RecognizedSource,
) -> RecommendationPlan:
    """Select a supported presentation plan for recognized source evidence."""

    if recognized.model in {
        "frequency_sweep",
        "temperature_sweep",
        "stress_relaxation",
    }:
        return _bundle_plan(recognized.model)
    if recognized.model in {
        "curve_table",
        "tensile_curve",
        "frequency_metric_sheet",
    }:
        return curve_recommendation_plan(source, recognized)
    if recognized.model == "heatmap_table":
        return RecommendationPlan(
            template="heatmap",
            score=90.0,
            reason=(
                "Detected a heatmap long table with explicit X / Y / Z role columns."
            ),
            overrides={"show_colorbar": True},
            signals=(
                "Detected a 3-column input layout.",
                "Row 1 explicitly defines the X, Y, and Z role columns.",
                "This input is best converted directly into a heatmap matrix.",
            ),
            confidence=91.0,
        )
    if recognized.model == "replicate_table":
        return _replicate_plan(recognized)
    intent = recognized.intent
    return RecommendationPlan(
        template="bar",
        score=80.0,
        reason=(
            intent.reason
            if intent is not None
            else (
                "Detected a compact mixed table that is best summarized by a "
                "supported categorical view."
            )
        ),
        overrides={},
        signals=(
            intent.signals
            if intent is not None
            else (
                "Detected a small table figure input.",
                "The table is compact enough to summarize as a figure output.",
                "This path is for presentation summaries, not workbook export.",
            )
        ),
        alternatives=(("scatter", 70.0, "Scatter is available for paired metrics."),),
    )


__all__ = ["recommendation_plan"]
