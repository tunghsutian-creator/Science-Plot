"""Build stable recommendation payloads for supported Veusz templates."""

from __future__ import annotations

from typing import Any

from sciplot_core.contract import (
    default_options_for_template,
    default_size_for_template,
)
from sciplot_core.source_inspection.models import TemplateRecommendation


_RENDER_OVERRIDE_KEYS = {
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


def template_recommendation(
    template_id: str,
    *,
    score: float,
    reason: str,
    rank: int,
    top_score: float,
    model: str,
    inferred_mapping: dict[str, str] | None = None,
    experiment_family: str | None = None,
    role_hints: tuple[str, ...] = (),
    soft_reasons: tuple[str, ...] = (),
    enhancements: tuple[str, ...] = (),
    **overrides: Any,
) -> TemplateRecommendation:
    """Build one JSON-stable recommendation from template policy defaults."""

    defaults = default_options_for_template(template_id)
    preview: dict[str, Any] = {
        "template": template_id,
        "size": defaults.get("size", default_size_for_template(template_id)),
        "xscale": defaults.get("xscale"),
        "yscale": defaults.get("yscale"),
        "reverse_x": defaults.get("reverse_x"),
        "baseline": defaults.get("baseline"),
        "show_colorbar": defaults.get("show_colorbar"),
        "legend_position": defaults.get("legend_position", "auto"),
        "series_label_mode": defaults.get("series_label_mode", "legend"),
        "style_preset": defaults.get("style_preset"),
        "palette_preset": defaults.get("palette_preset"),
        "use_sidecar": defaults.get("use_sidecar"),
        "visual_theme_id": defaults.get("visual_theme_id"),
        "experiment_family": experiment_family,
        "recommended_action": "add_as_plot_source",
        "model": model,
    }
    preview.update(overrides)
    preview = {key: value for key, value in preview.items() if value is not None}
    render_overrides = {
        key: value for key, value in preview.items() if key in _RENDER_OVERRIDE_KEYS
    }
    bounded_score = round(max(0.0, min(100.0, score)), 1)
    if bounded_score >= 88.0:
        suitability = "Strong structural and semantic match for the detected model."
    elif bounded_score >= 76.0:
        suitability = "Good fit with minor trade-offs compared with the primary choice."
    else:
        suitability = "Compatible fallback when you need a different visual emphasis."
    return TemplateRecommendation(
        template_id=template_id,
        score=bounded_score,
        rank=rank,
        score_gap_to_top=round(max(0.0, top_score - bounded_score), 1),
        reason=reason,
        suitability_hint=suitability,
        why_hard_match=(reason,),
        why_soft_prior=soft_reasons,
        inferred_mapping=dict(inferred_mapping or {}),
        optional_enhancements=enhancements,
        preview_config_summary=preview,
        experiment_family=experiment_family,
        role_hints=role_hints,
        recommendation_reason=reason,
        recommended_action="add_as_plot_source",
        default_render_overrides=render_overrides,
        canonical_id=template_id,
        role="canonical",
        lifecycle_policy="canonical",
        implementation_id=template_id,
    )


def recommendation_confidence(
    recommendations: tuple[TemplateRecommendation, ...],
) -> float:
    """Compute the compatibility confidence used by inspection summaries."""

    if not recommendations:
        return 0.0
    top = recommendations[0]
    second_score = recommendations[1].score if len(recommendations) > 1 else 0.0
    gap = max(0.0, top.score - second_score)
    return round(max(0.0, min(100.0, top.score + min(8.0, gap * 0.5))), 1)


def recommendation_summary(
    *,
    model_label: str,
    recommendations: tuple[TemplateRecommendation, ...],
    confidence: float,
) -> str:
    if not recommendations:
        return "No ranked template candidates are available yet."
    top = recommendations[0]
    second_score = recommendations[1].score if len(recommendations) > 1 else 0.0
    gap = round(max(0.0, top.score - second_score), 1)
    tone = (
        "High confidence"
        if confidence >= 88.0
        else "Good confidence"
        if confidence >= 76.0
        else "Moderate confidence"
    )
    return (
        f"{tone}: {top.template_id} is the strongest template for {model_label} "
        f"(score {top.score:.1f}, gap {gap:.1f})."
    )


__all__ = [
    "recommendation_confidence",
    "recommendation_summary",
    "template_recommendation",
]
