from __future__ import annotations

import math
from contextlib import suppress
from dataclasses import replace
from functools import lru_cache
from pathlib import Path

import pandas as pd

from src.data_loader import CurveSeries
from src.plot_contract import default_options_for_template, default_size_for_template
from src.rendering.cache import (
    load_curve_table_cached,
    load_replicate_table_cached,
    read_raw_table_cached,
    load_stress_relaxation_metric_cached,
)
from src.rendering.common import looks_like_tensile_curve, to_curve_series
from src.rendering.dataset_models import (
    build_normalized_dataset,
    frequency_metric_sheet_signals,
    looks_like_dsc_curve,
    looks_like_ftir_curve,
    looks_like_nmr_curve,
    looks_like_xrd_curve,
    point_line_bundle_signals,
)
from src.rendering.models import InputInspection, Recommendation, TemplateName
from src.rendering.recommendation_policy import build_recommendation_presentation
from src.rendering.raw_plot_intent import RawPlotIntent, detect_raw_plot_intent
from src.rendering.recommender import (
    DEFAULT_RECOMMENDER,
    template_recommendation_from_override,
)
from src.rendering.recommender_models import TemplateRecommendation
from src.wide_nmr import wide_nmr_sidecar_path

INSPECTION_RECOMMENDATION_LIMIT = 10


def _inspection_cache_key(input_path: Path, sheet: str | int) -> tuple[str, int, str | int]:
    return (str(input_path.resolve()), input_path.stat().st_mtime_ns, sheet)


def model_label(model: str) -> str:
    labels = {
        "curve_table": "Paired curve table (curve_table)",
        "tensile_curve": "Tensile stress-strain curve (tensile_curve)",
        "replicate_table": "Replicate wide table (replicate_table)",
        "heatmap_table": "Heatmap long table (xyz_long_table)",
        "frequency_sweep": "Frequency sweep export table",
        "frequency_metric_sheet": "Frequency sweep metric sheet",
        "temperature_sweep": "Temperature sweep export table",
        "stress_relaxation": "Stress relaxation export table",
        "table_summary": "Compact metrics/table figure input",
    }
    return labels.get(model, model)


def axis_dynamic_range(
    series_list: list[CurveSeries],
    axis: str,
) -> tuple[float, float, bool] | None:
    positive_min: float | None = None
    positive_max: float | None = None
    all_positive = True

    for series in series_list:
        values = pd.to_numeric(series.data[axis], errors="coerce").dropna()
        if values.empty:
            continue
        positive = values[values > 0]
        if positive.empty:
            all_positive = False
            continue
        if len(positive) != len(values):
            all_positive = False
        current_min = float(positive.min())
        current_max = float(positive.max())
        positive_min = current_min if positive_min is None else min(positive_min, current_min)
        positive_max = current_max if positive_max is None else max(positive_max, current_max)

    if positive_min is None or positive_max is None or positive_max <= 0:
        return None

    ratio = positive_max / positive_min if positive_min > 0 else 0.0
    orders = math.log10(ratio) if ratio > 0 else 0.0
    return ratio, orders, all_positive


def recommend_axis_scale(
    series_list: list[CurveSeries],
    axis: str,
    *,
    label: str,
    min_orders: float,
) -> tuple[str, str]:
    summary = axis_dynamic_range(series_list, axis)
    if summary is None:
        return "linear", f"{label} does not show a stable positive range, so linear stays on."

    _, orders, all_positive = summary
    if all_positive and orders >= min_orders:
        return "log", f"{label} spans about {orders:.1f} orders of magnitude, so log is recommended."
    if not all_positive:
        return "linear", f"{label} includes non-positive or near-zero values, so linear stays on."
    return "linear", f"{label} varies by about {orders:.1f} orders of magnitude, and linear stays easier to read."


def recommend_curve_scales(series_list: list[CurveSeries]) -> tuple[str, str, tuple[str, ...]]:
    xscale, xsignal = recommend_axis_scale(
        series_list,
        "x",
        label="X axis",
        min_orders=2.0,
    )
    yscale, ysignal = recommend_axis_scale(
        series_list,
        "y",
        label="Y axis",
        min_orders=2.3,
    )
    return xscale, yscale, (xsignal, ysignal)


def recommendation(template: TemplateName, reason: str, **overrides: object) -> Recommendation:
    defaults = default_options_for_template(template)
    payload = {
        "template": template,
        "reason": reason,
        "size": defaults.get("size", default_size_for_template(template)),
        "xscale": defaults.get("xscale"),
        "yscale": defaults.get("yscale"),
        "reverse_x": defaults.get("reverse_x"),
        "baseline": defaults.get("baseline"),
        "show_colorbar": defaults.get("show_colorbar"),
        "style_preset": defaults.get("style_preset"),
        "palette_preset": defaults.get("palette_preset"),
        "use_sidecar": defaults.get("use_sidecar"),
        "visual_theme_id": defaults.get("visual_theme_id"),
    }
    payload.update(overrides)
    return Recommendation(**payload)


def _raw_plot_intent_for_path(input_path: Path, sheet: str | int) -> RawPlotIntent | None:
    with suppress(Exception):
        raw = read_raw_table_cached(input_path, sheet).dropna(how="all").dropna(axis=1, how="all")
        return detect_raw_plot_intent(raw, input_path)
    return None


def _inspection_confidence_and_summary(
    *,
    model: str,
    recommendations: tuple[TemplateRecommendation, ...],
    primary_recommendation: tuple[TemplateRecommendation, ...],
) -> tuple[float, str]:
    if not recommendations:
        return 0.0, "No ranked template candidates are available yet."
    top = recommendations[0]
    second = recommendations[1] if len(recommendations) > 1 else None
    gap = round(max(0.0, top.score - (second.score if second else 0.0)), 1)
    confidence = round(max(0.0, min(100.0, top.score + min(8.0, gap * 0.5))), 1)
    if confidence >= 88.0:
        tone = "High confidence"
    elif confidence >= 76.0:
        tone = "Good confidence"
    else:
        tone = "Moderate confidence"
    if len(primary_recommendation) > 1:
        primary_ids = " and ".join(item.template_id for item in primary_recommendation[:2])
        summary = (
            f"{tone}: {primary_ids} are co-primary templates for {model_label(model)} "
            f"(top score {top.score:.1f}, gap {gap:.1f})."
        )
    else:
        summary = (
            f"{tone}: {top.template_id} is the strongest template for {model_label(model)} "
            f"(score {top.score:.1f}, gap {gap:.1f})."
        )
    return confidence, summary


def _inspection(
    *,
    model: str,
    recommendation_value: Recommendation,
    recommendations: tuple[TemplateRecommendation, ...] = (),
    warnings: tuple[str, ...] = (),
    signals: tuple[str, ...] = (),
) -> InputInspection:
    template_recommendation = template_recommendation_from_override(
        template_id=recommendation_value.template,
        reason=recommendation_value.reason,
        size=recommendation_value.size,
        xscale=recommendation_value.xscale,
        yscale=recommendation_value.yscale,
        reverse_x=recommendation_value.reverse_x,
        baseline=recommendation_value.baseline,
        show_colorbar=recommendation_value.show_colorbar,
        style_preset=recommendation_value.style_preset,
        palette_preset=recommendation_value.palette_preset,
        use_sidecar=recommendation_value.use_sidecar,
        visual_theme_id=recommendation_value.visual_theme_id,
    )
    if recommendations:
        matched = next(
            (item for item in recommendations if item.template_id == template_recommendation.template_id),
            None,
        )
        if matched is not None:
            merged = TemplateRecommendation(
                template_id=matched.template_id,
                score=matched.score,
                rank=matched.rank,
                score_gap_to_top=matched.score_gap_to_top,
                reason=template_recommendation.reason,
                suitability_hint=matched.suitability_hint,
                why_hard_match=matched.why_hard_match,
                why_soft_prior=matched.why_soft_prior,
                inferred_mapping=matched.inferred_mapping,
                optional_enhancements=matched.optional_enhancements,
                preview_config_summary={
                    **matched.preview_config_summary,
                    **template_recommendation.preview_config_summary,
                },
                experiment_family=matched.experiment_family,
                role_hints=matched.role_hints,
                recommendation_reason=template_recommendation.recommendation_reason or matched.recommendation_reason,
                recommended_action=matched.recommended_action or template_recommendation.recommended_action,
                default_render_overrides={
                    **(matched.default_render_overrides or {}),
                    **{
                        key: value
                        for key, value in template_recommendation.preview_config_summary.items()
                        if key
                        in {
                            "size",
                            "xscale",
                            "yscale",
                            "reverse_x",
                            "baseline",
                            "show_colorbar",
                            "legend_position",
                            "series_label_mode",
                            "style_preset",
                            "palette_preset",
                            "use_sidecar",
                            "visual_theme_id",
                        }
                        and value is not None
                    },
                },
                canonical_id=matched.canonical_id,
                role=matched.role,
                lifecycle_policy=matched.lifecycle_policy,
                implementation_id=matched.implementation_id,
            )
            ranked = (merged,) + tuple(item for item in recommendations if item.template_id != matched.template_id)
        else:
            ranked = (template_recommendation,) + recommendations
    else:
        ranked = (template_recommendation,)
    presentation = build_recommendation_presentation(ranked)
    visible_recommendations = presentation.visible_recommendations or ranked
    recommendation_confidence, recommendation_summary = _inspection_confidence_and_summary(
        model=model,
        recommendations=visible_recommendations,
        primary_recommendation=presentation.primary_recommendation,
    )
    return InputInspection(
        model=model,
        model_label=model_label(model),
        recommendations=ranked,
        primary_recommendation=presentation.primary_recommendation,
        alternative_recommendations=presentation.alternative_recommendations,
        advanced_templates=presentation.advanced_templates,
        recommendation_confidence=recommendation_confidence,
        recommendation_summary=recommendation_summary,
        warnings=warnings,
        signals=signals,
    )


@lru_cache(maxsize=64)
def _inspect_input_file_cached(
    resolved_path: str,
    _mtime_ns: int,
    sheet: str | int,
) -> InputInspection:
    input_path = Path(resolved_path)
    normalized_dataset = build_normalized_dataset(input_path, sheet)
    raw_intent = _raw_plot_intent_for_path(input_path, sheet)
    if raw_intent is not None and raw_intent.model != normalized_dataset.model:
        raw_intent = None
    ranked_recommendations = DEFAULT_RECOMMENDER.recommend(
        normalized_dataset,
        limit=INSPECTION_RECOMMENDATION_LIMIT,
    )
    if not ranked_recommendations:
        raise ValueError(
            f"Could not produce template recommendations for normalized dataset model: {normalized_dataset.model}."
        )

    if normalized_dataset.model == "frequency_sweep":
        return _inspection(
            model="frequency_sweep",
            recommendation_value=recommendation(
                "point_line",
                "Detected a frequency sweep rheology export table with 5 columns per bundle.",
                xscale="log",
                yscale="log",
                reverse_x=False,
            ),
            warnings=("This export will generate 4 PDF files.",),
            signals=point_line_bundle_signals("frequency_sweep"),
            recommendations=ranked_recommendations,
        )
    if normalized_dataset.model == "frequency_metric_sheet":
        return _inspection(
            model="frequency_metric_sheet",
            recommendation_value=recommendation(
                "point_line",
                "Detected a Data Studio frequency-sweep metric sheet with all samples ready for comparison.",
                xscale="log",
                yscale="log",
                reverse_x=False,
            ),
            signals=frequency_metric_sheet_signals(load_curve_table_cached(input_path, sheet)),
            recommendations=ranked_recommendations,
        )
    if normalized_dataset.model == "temperature_sweep":
        return _inspection(
            model="temperature_sweep",
            recommendation_value=recommendation(
                "point_line",
                "Detected a temperature sweep rheology export table with 5 columns per bundle.",
                size="120x55",
                xscale="linear",
                yscale="log",
                reverse_x=False,
            ),
            warnings=("This export will generate 2 PDF files.",),
            signals=point_line_bundle_signals("temperature_sweep"),
            recommendations=ranked_recommendations,
        )
    if normalized_dataset.model == "stress_relaxation":
        relaxation_series = to_curve_series(load_stress_relaxation_metric_cached(input_path, "σ/σ₀", sheet))
        xscale, yscale, range_signals = recommend_curve_scales(relaxation_series)
        return _inspection(
            model="stress_relaxation",
            recommendation_value=recommendation(
                "point_line",
                "Detected a stress relaxation export table with 4 columns per bundle.",
                xscale=xscale,
                yscale=yscale,
                reverse_x=False,
            ),
            signals=point_line_bundle_signals("stress_relaxation") + range_signals,
            recommendations=ranked_recommendations,
        )

    if normalized_dataset.model == "heatmap_table":
        return _inspection(
            model="heatmap_table",
            recommendation_value=recommendation(
                "heatmap",
                "Detected a heatmap long table with explicit X / Y / Z role columns.",
                show_colorbar=True,
            ),
            signals=(
                "Detected a 3-column input layout.",
                "Row 1 explicitly defines the X, Y, and Z role columns.",
                "This input is best converted directly into a heatmap matrix.",
            ),
            recommendations=ranked_recommendations,
        )

    if normalized_dataset.model == "table_summary":
        reason = (
            raw_intent.reason
            if raw_intent is not None
            else "Detected a compact mixed table that is better rendered as a table figure."
        )
        signals = raw_intent.semantic_signals if raw_intent is not None else (
            "Detected a small table figure input.",
            "The table is compact enough to render as a figure output.",
            "This path is for presentation tables, not full workbook export.",
        )
        return _inspection(
            model="table_summary",
            recommendation_value=recommendation(
                "table_figure",
                reason,
            ),
            signals=signals,
            recommendations=ranked_recommendations,
        )

    if normalized_dataset.model == "replicate_table" and raw_intent is not None:
        base_recommendations: list[TemplateRecommendation] = []
        for item in ranked_recommendations:
            if item.template_id != raw_intent.recommended_template:
                base_recommendations.append(item)
                continue
            preview_config_summary = {
                **item.preview_config_summary,
                **raw_intent.preview_overrides,
            }
            base_recommendations.append(
                replace(
                    item,
                    score=max(item.score, 86.0),
                    rank=1,
                    score_gap_to_top=0.0,
                    preview_config_summary=preview_config_summary,
                    experiment_family=raw_intent.experiment_family,
                    recommendation_reason=raw_intent.reason,
                    recommended_action="add_as_plot_source",
                    default_render_overrides={
                        key: value
                        for key, value in preview_config_summary.items()
                        if key
                        in {
                            "size",
                            "xscale",
                            "yscale",
                            "reverse_x",
                            "baseline",
                            "show_colorbar",
                            "legend_position",
                            "series_label_mode",
                            "style_preset",
                            "palette_preset",
                            "use_sidecar",
                            "visual_theme_id",
                        }
                        and value is not None
                    },
                )
            )
        return _inspection(
            model="replicate_table",
            recommendation_value=recommendation(
                raw_intent.recommended_template,
                raw_intent.reason,
            ),
            signals=raw_intent.semantic_signals,
            recommendations=tuple(base_recommendations),
        )

    with suppress(Exception):
        series_list = load_curve_table_cached(input_path, sheet)
        if raw_intent is not None and raw_intent.supports_curve_series:
            return _inspection(
                model=normalized_dataset.model,
                recommendation_value=recommendation(
                    raw_intent.recommended_template,
                    raw_intent.reason,
                    xscale=raw_intent.xscale,
                    yscale=raw_intent.yscale,
                    reverse_x=raw_intent.reverse_x,
                    baseline=raw_intent.baseline,
                ),
                recommendations=ranked_recommendations,
                signals=raw_intent.semantic_signals,
            )
        if wide_nmr_sidecar_path(input_path).exists():
            return _inspection(
                model="curve_table",
                recommendation_value=recommendation(
                    "segmented_stacked_curve",
                    "Detected a standard curve table and found a wide_nmr sidecar in the same directory.",
                    reverse_x=True,
                    baseline="linear_endpoints",
                    use_sidecar=True,
                ),
                recommendations=ranked_recommendations,
                signals=(
                    "Detected a standard paired curve table.",
                    "A .wide_nmr.toml sidecar is present in the same directory.",
                    "This input is a better fit for a segmented stacked curve plot.",
                ),
            )
        if looks_like_nmr_curve(series_list):
            return _inspection(
                model="curve_table",
                recommendation_value=recommendation(
                    "stacked_curve",
                    "The Chemical shift / ppm axis suggests an NMR-style spectrum.",
                    reverse_x=True,
                    baseline="linear_endpoints",
                ),
                recommendations=ranked_recommendations,
                signals=(
                    "The x-axis label or unit matches Chemical shift / ppm.",
                    "Multiple sample curves are better shown as a stacked spectrum.",
                    "A reversed x-axis and light baseline correction are recommended.",
                ),
            )
        if looks_like_ftir_curve(series_list):
            return _inspection(
                model="curve_table",
                recommendation_value=recommendation(
                    "stacked_curve",
                    "The Wavenumber / cm^-1 axis suggests an FTIR-style spectrum.",
                    reverse_x=True,
                    baseline="none",
                ),
                recommendations=ranked_recommendations,
                signals=(
                    "The x-axis label or unit matches Wavenumber / cm⁻¹.",
                    "Multiple sample curves are better shown as a stacked spectrum.",
                    "A reversed x-axis is recommended without forcing baseline correction.",
                ),
            )
        if looks_like_dsc_curve(series_list):
            return _inspection(
                model="curve_table",
                recommendation_value=recommendation(
                    "stacked_curve",
                    "The Heat flow label suggests a DSC-style stacked plot.",
                    reverse_x=False,
                    baseline="linear_endpoints",
                ),
                recommendations=ranked_recommendations,
                signals=(
                    "The y-axis label matches Heat flow.",
                    "These thermal analysis curves are easier to compare in a stacked layout.",
                    "Linear-endpoint baseline correction is recommended.",
                ),
            )
        if looks_like_xrd_curve(series_list):
            return _inspection(
                model="curve_table",
                recommendation_value=recommendation(
                    "stacked_curve",
                    "The 2theta / counts / intensity fields suggest an XRD-style spectrum.",
                    reverse_x=False,
                    baseline="none",
                ),
                recommendations=ranked_recommendations,
                signals=(
                    "The axis labels or units match 2theta / counts / intensity.",
                    "Multiple sample curves are better shown as a stacked spectrum.",
                    "A forward x-axis is recommended.",
                ),
            )
        if looks_like_tensile_curve(series_list):
            return _inspection(
                model="tensile_curve",
                recommendation_value=recommendation(
                    "curve",
                    "The strain / elongation x-axis and stress y-axis suggest a tensile curve.",
                    size="60x55",
                    xscale="linear",
                    yscale="linear",
                    reverse_x=False,
                ),
                recommendations=ranked_recommendations,
                signals=(
                    "The x-axis label or unit matches strain / elongation / %.",
                    "The y-axis label or unit matches stress / MPa.",
                    "Tensile curves always stay on linear x/y axes by default.",
                ),
            )
        xscale, yscale, range_signals = recommend_curve_scales(series_list)
        compatibility_template = ranked_recommendations[0].template_id
        compatibility_reason = (
            "Detected a standard paired curve table, so a basic curve plot is recommended by default."
        )
        if compatibility_template == "mean_band":
            compatibility_reason = (
                "Detected aligned paired curves with replicate-like structure, "
                "so mean_band is recommended for deterministic mean±band summary."
            )
        elif compatibility_template == "scatter_fit":
            compatibility_reason = (
                "Detected paired curves with a strong trend pattern, "
                "so scatter fit with deterministic linear overlay is recommended."
            )
        elif compatibility_template == "bubble_scatter":
            compatibility_reason = (
                "Detected paired curves where point-level magnitude encoding may improve readability, "
                "so bubble scatter is recommended."
            )
        return _inspection(
            model="curve_table",
            recommendation_value=recommendation(
                compatibility_template,
                compatibility_reason,
                xscale=xscale,
                yscale=yscale,
            ),
            recommendations=ranked_recommendations,
            signals=(
                "Detected a standard paired curve table.",
                "The labels and units do not strongly match a spectrum or rheology export bundle.",
                "The default path is a standard curve plot.",
                *range_signals,
            ),
        )

    try:
        groups = load_replicate_table_cached(input_path, sheet)
    except Exception as exc:
        raise ValueError(
            "Could not recognize this file. Reformat it as a curve_table, replicate_table, "
            "heatmap xyz_long_table, or one of the supported rheology export tables."
        ) from exc

    warnings: list[str] = []
    if len(groups) >= 6:
        warnings.append("There are many groups, so x-axis labels may wrap or shrink.")
    return _inspection(
        model="replicate_table",
        recommendation_value=recommendation(
            "box",
            "Detected a statistical table with a shared y-axis label, sample names, units, and replicate values.",
        ),
        recommendations=ranked_recommendations,
        warnings=tuple(warnings),
        signals=(
            "Cell A1 provides the shared y-axis label.",
            "Row 2 contains group names and row 3 contains units.",
            "Row 4 onward contains replicate values, which fits statistical plots well.",
        ),
    )


def inspect_input_file(input_path: Path, sheet: str | int = 0) -> InputInspection:
    return _inspect_input_file_cached(*_inspection_cache_key(input_path, sheet))


def clear_inspection_cache() -> None:
    _inspect_input_file_cached.cache_clear()
