"""Select recommendation plans for curve-shaped source data."""

from __future__ import annotations

from pathlib import Path

from sciplot_core.source_inspection.curve_scales import recommend_curve_scales
from sciplot_core.source_inspection.model_recognition import (
    RecognizedSource,
    looks_like_dsc,
    looks_like_ftir,
    looks_like_nmr,
    looks_like_xrd,
)
from sciplot_core.source_inspection.plan_models import RecommendationPlan


def curve_recommendation_plan(
    source: Path,
    recognized: RecognizedSource,
) -> RecommendationPlan:
    """Select the supported Veusz curve presentation for recognized evidence."""

    intent = recognized.intent
    curves = recognized.curves
    if recognized.model == "frequency_metric_sheet":
        metrics = ", ".join(sorted({curve.y_label for curve in curves})) or (
            ", ".join(sorted(intent.metric_columns))
            if intent is not None and intent.metric_columns
            else "rheology metric columns"
        )
        return RecommendationPlan(
            template="point_line",
            score=90.0,
            reason=(
                "Detected a Data Studio frequency-sweep metric sheet with all "
                "samples ready for comparison."
            ),
            overrides={"xscale": "log", "yscale": "log", "reverse_x": False},
            signals=(
                "Detected a Data Studio frequency-sweep metric sheet.",
                "The x-axis field is Angular Frequency / ω.",
                f"The y-axis compares {metrics} across samples.",
            ),
            alternatives=(("curve", 84.0, "Curve omits measured-point markers."),),
        )
    if recognized.model == "tensile_curve":
        return RecommendationPlan(
            template="curve",
            score=88.0,
            reason=(
                "The strain / elongation x-axis and stress y-axis suggest a "
                "tensile curve."
            ),
            overrides={
                "size": "60x55",
                "xscale": "linear",
                "yscale": "linear",
                "reverse_x": False,
            },
            signals=(
                intent.signals
                if intent is not None
                else (
                    "The x-axis label or unit matches strain / elongation / %.",
                    "The y-axis label or unit matches stress / MPa.",
                    "Tensile curves always stay on linear x/y axes by default.",
                )
            ),
            alternatives=(
                ("point_line", 83.0, "Markers retain measured tensile points."),
                ("scatter", 76.0, "Scatter emphasizes individual observations."),
            ),
            confidence=90.5,
        )
    if intent is not None:
        family_scores = {
            "spectroscopy": 92.0,
            "thermal": 90.0,
            "scattering": 90.0,
            "swelling_gel": 94.0,
            "chromatography": 90.0,
        }
        return RecommendationPlan(
            template=intent.recommended_template,
            score=family_scores.get(intent.experiment_family, 88.0),
            reason=intent.reason,
            overrides={
                key: value
                for key, value in {
                    "xscale": intent.xscale,
                    "yscale": intent.yscale,
                    "reverse_x": intent.reverse_x,
                    "baseline": intent.baseline,
                }.items()
                if value is not None
            },
            signals=intent.signals,
            alternatives=(
                (
                    "point_line" if intent.recommended_template == "curve" else "curve",
                    82.0,
                    "A supported alternate emphasizes the same source values.",
                ),
            ),
            confidence=(
                100.0
                if intent.experiment_family == "spectroscopy"
                else 94.5
                if intent.experiment_family == "thermal"
                else None
            ),
        )
    if source.with_suffix(".wide_nmr.toml").exists():
        return RecommendationPlan(
            template="stacked_curve",
            score=94.0,
            reason=(
                "Detected a standard curve table and found a wide_nmr sidecar "
                "in the same directory."
            ),
            overrides={"reverse_x": True, "baseline": "linear_endpoints"},
            signals=(
                "Detected a standard paired curve table.",
                "A .wide_nmr.toml sidecar is present in the same directory.",
                "This input is best retained as a supported stacked curve.",
            ),
            alternatives=(("curve", 80.0, "Curve omits stacked separation."),),
        )

    spectrum = _spectrum_plan(recognized)
    if spectrum is not None:
        return spectrum
    xscale, yscale, scale_signals = recommend_curve_scales(curves)
    return RecommendationPlan(
        template="curve",
        score=82.0,
        reason=(
            "Detected a standard paired curve table, so a basic curve plot is "
            "recommended by default."
        ),
        overrides={"xscale": xscale, "yscale": yscale},
        signals=(
            "Detected a standard paired curve table.",
            (
                "The labels and units do not strongly match a spectrum or "
                "rheology export bundle."
            ),
            "The default path is a standard curve plot.",
            *scale_signals,
        ),
        alternatives=(
            ("point_line", 78.0, "Markers make paired observations easier to scan."),
            ("scatter", 70.0, "Scatter emphasizes individual observations."),
            (
                "stacked_curve",
                68.0,
                "Stacking can separate several aligned samples.",
            ),
        ),
    )


def _spectrum_plan(recognized: RecognizedSource) -> RecommendationPlan | None:
    curves = recognized.curves
    spectrum: tuple[str, str, bool, tuple[str, ...]] | None = None
    if looks_like_nmr(curves):
        spectrum = (
            "The Chemical shift / ppm axis suggests an NMR-style spectrum.",
            "linear_endpoints",
            True,
            (
                "The x-axis label or unit matches Chemical shift / ppm.",
                "Multiple sample curves are better shown as a stacked spectrum.",
                ("A reversed x-axis and light baseline correction are recommended."),
            ),
        )
    elif looks_like_ftir(curves):
        spectrum = (
            "The Wavenumber / cm^-1 axis suggests an FTIR-style spectrum.",
            "none",
            True,
            (
                "The x-axis label or unit matches Wavenumber / cm⁻¹.",
                "Multiple sample curves are better shown as a stacked spectrum.",
                (
                    "A reversed x-axis is recommended without forcing baseline "
                    "correction."
                ),
            ),
        )
    elif looks_like_dsc(curves):
        spectrum = (
            "The Heat flow label suggests a DSC-style stacked plot.",
            "linear_endpoints",
            False,
            (
                "The y-axis label matches Heat flow.",
                (
                    "These thermal analysis curves are easier to compare in a "
                    "stacked layout."
                ),
                "Linear-endpoint baseline correction is recommended.",
            ),
        )
    elif looks_like_xrd(curves):
        spectrum = (
            "The 2theta / counts / intensity fields suggest an XRD-style spectrum.",
            "none",
            False,
            (
                "The axis labels or units match 2theta / counts / intensity.",
                "Multiple sample curves are better shown as a stacked spectrum.",
                "A forward x-axis is recommended.",
            ),
        )
    if spectrum is None:
        return None
    reason, baseline, reverse_x, signals = spectrum
    return RecommendationPlan(
        template="stacked_curve",
        score=92.0,
        reason=reason,
        overrides={"reverse_x": reverse_x, "baseline": baseline},
        signals=signals,
        alternatives=(("curve", 80.0, "Curve omits stacked separation."),),
    )


__all__ = ["curve_recommendation_plan"]
