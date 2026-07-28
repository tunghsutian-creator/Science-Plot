"""Inspect source tables and merge material-rule recommendations with generic inspection."""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from typing import Any
from sciplot_core.foundation.json_values import json_safe
from sciplot_core.ingest import normalized_source
from sciplot_core.source_inspection import inspect_input_file
from sciplot_core.semantic import classify_source


_GENERIC_PRESENTATION_WARNING_MARKERS = (
    "axis label",
    "axis labels",
    "box plot",
    "boxplot",
    "categories",
    "category labels",
    "crowd",
    "density plot",
    "heatmap",
    "legend",
    "many groups",
    "matrix view",
    "shrink",
    "violin",
    "wrap",
)


_GENERIC_DATA_RISK_WARNING_MARKERS = (
    "duplicate",
    "empty",
    "failed",
    "inconsistent",
    "invalid",
    "missing",
    "nan",
    "negative",
    "non-finite",
    "nonfinite",
    "out of range",
    "zero",
)


_GENERIC_PRESENTATION_ONLY_MISSING_PHRASES = (
    "missing axis label",
    "missing axis labels",
    "missing category label",
    "missing category labels",
)


def _material_rule_recommendation(semantics: dict[str, Any]) -> dict[str, Any]:
    axis_plan = (
        semantics.get("axis_plan")
        if isinstance(semantics.get("axis_plan"), dict)
        else {}
    )
    x_axis = axis_plan.get("x") if isinstance(axis_plan.get("x"), dict) else {}
    y_axis = axis_plan.get("y") if isinstance(axis_plan.get("y"), dict) else {}
    semantic_family = str(semantics.get("semantic_family") or "unknown")
    template = str(semantics.get("template") or "curve")
    confidence = float(semantics.get("confidence") or 0.0)
    reason = str(
        semantics.get("reason") or f"Matched SciPlot material rule `{semantic_family}`."
    )
    return {
        "template_id": template,
        "score": confidence,
        "why_hard_match": [reason],
        "why_soft_prior": [
            "SciPlot material semantics take precedence over generic table-shape inspection."
        ],
        "inferred_mapping": {
            "x": x_axis.get("canonical_label") or "x",
            "y": y_axis.get("canonical_label") or "y",
        },
        "optional_enhancements": [],
        "preview_config_summary": {
            "template": template,
            **dict(semantics.get("render_options") or {}),
            "experiment_family": semantics.get("recommended_recipe"),
            "recommended_action": "add_as_plot_source",
            "model": semantic_family,
        },
        "experiment_family": semantics.get("recommended_recipe"),
        "role_hints": [
            f"x:{x_axis.get('canonical_label') or 'x'}",
            f"y:{y_axis.get('canonical_label') or 'y'}",
        ],
        "recommendation_reason": reason,
        "recommended_action": "add_as_plot_source",
        "default_render_overrides": dict(semantics.get("render_options") or {}),
        "rank": 1,
        "reason": reason,
        "suitability_hint": "Authoritative SciPlot material-rule match.",
        "score_gap_to_top": 0.0,
        "canonical_id": template,
        "role": "canonical",
        "lifecycle_policy": "canonical",
        "implementation_id": template,
        "recommendation_source": "sciplot_material_rule",
    }


def _generic_warning_is_superseded_by_ready_rule(message: str) -> bool:
    normalized = " ".join(str(message).strip().lower().split())
    if not normalized:
        return True
    # Remove only the known presentation-only use of "missing" before looking
    # for data-risk words. This keeps "Missing axis labels" suppressible while
    # preserving mixed warnings such as "Missing axis labels and values".
    risk_text = normalized
    for phrase in _GENERIC_PRESENTATION_ONLY_MISSING_PHRASES:
        risk_text = risk_text.replace(phrase, "")
    if any(marker in risk_text for marker in _GENERIC_DATA_RISK_WARNING_MARKERS):
        return False
    if any(marker in normalized for marker in _GENERIC_PRESENTATION_WARNING_MARKERS):
        return True
    # Unknown generic warnings are review input, not safe to suppress.
    return False


def _resolve_ready_rule_inspection_warnings(
    warnings: list[Any],
    *,
    rule_id: str,
) -> tuple[list[str], list[dict[str, str]]]:
    user_warnings: list[str] = []
    provenance: list[dict[str, str]] = []
    for raw_warning in warnings:
        message = str(raw_warning).strip()
        if not message:
            continue
        superseded = _generic_warning_is_superseded_by_ready_rule(message)
        disposition = (
            "superseded_by_ready_rule" if superseded else "preserved_for_review"
        )
        provenance.append(
            {
                "message": message,
                "source": "generic_table_inspection",
                "disposition": disposition,
                "resolved_by": f"sciplot_material_rule:{rule_id}" if superseded else "",
            }
        )
        if not superseded:
            user_warnings.append(f"[generic_table_inspection] {message}")
    return user_warnings, provenance


def _semantic_only_inspection_payload(
    source: Path,
    semantics: dict[str, Any],
    *,
    inspection_error: Exception,
) -> dict[str, Any]:
    rule_id = str(semantics.get("rule_id") or "")
    if rule_id == "performance_comparison":
        recommendation = _material_rule_recommendation(semantics)
        warning = (
            "The generic table reader does not implement the explicit "
            "performance-comparison long-table shape; the validated SciPlot "
            "source contract is authoritative."
        )
        return {
            "source": str(source),
            "model": "performance_comparison",
            "model_label": "performance_comparison (performance_comparison)",
            "recommendations": [recommendation],
            "canonical_templates": ["scatter", "polar_curve"],
            "advanced_templates": [],
            "recommendation_confidence": float(semantics.get("confidence") or 0.0),
            "recommendation_summary": str(semantics.get("reason") or ""),
            "warnings": [],
            "inspection_resolution": {
                "status": "ready_rule_authoritative",
                "authoritative_source": "sciplot_material_rule",
                "rule_id": rule_id,
                "generic_inspection_status": "unsupported_explicit_shape",
            },
            "inspection_warning_provenance": [
                {
                    "message": warning,
                    "source": "generic_table_inspection",
                    "disposition": "superseded_by_ready_rule",
                    "resolved_by": f"sciplot_material_rule:{rule_id}",
                }
            ],
            # Historical payload key retained for consumers of inspection JSON.
            "vendor_inspection_error": str(inspection_error),
            "sciplot_semantics": semantics,
        }
    candidate = _material_rule_recommendation(semantics)
    candidate.update(
        {
            "score": 0.0,
            "recommended_action": "inspect_source",
            "lifecycle_policy": "candidate_only",
            "recommendation_source": "sciplot_material_rule_candidate",
            "suitability_hint": (
                "Unverified SciPlot material-rule candidate; not eligible for "
                "automatic rendering."
            ),
        }
    )
    semantic_family = str(semantics.get("semantic_family") or "unknown")
    reason = str(
        semantics.get("reason") or f"Matched SciPlot material rule `{semantic_family}`."
    )
    rule_id = str(semantics.get("rule_id") or semantic_family)
    warning = (
        "Generic table inspection could not read this source, so SciPlot cannot "
        f"treat material rule `{rule_id}` as authoritative: {inspection_error}"
    )
    return {
        "source": str(source),
        "model": semantic_family,
        "model_label": f"{semantic_family} ({rule_id}; unverified candidate)",
        # Keep executable recommendation surfaces empty.  Consumers such as
        # ``render --auto`` intentionally select only from this list.
        "recommendations": [],
        "canonical_templates": [],
        "advanced_templates": [],
        "unverified_candidate": candidate,
        "recommendation_confidence": 0.0,
        "recommendation_summary": f"Unverified candidate only. {reason}",
        "warnings": [f"[generic_table_inspection] {warning}"],
        "inspection_resolution": {
            "status": "generic_inspection_failed",
            "authoritative_source": None,
            "candidate_source": "sciplot_material_rule",
            "candidate_rule_id": rule_id,
            "candidate_model": semantic_family,
            "candidate_template": semantics.get("template"),
            "generic_inspection_status": "failed",
        },
        "inspection_warning_provenance": [
            {
                "message": warning,
                "source": "generic_table_inspection",
                "disposition": "preserved_for_review",
                "resolved_by": "",
            }
        ],
        "vendor_inspection_error": str(inspection_error),
        "sciplot_semantics": semantics,
    }


def inspect_payload(
    input_path: Path,
    *,
    sheet: str | int = 0,
    inspect_source: Callable[[Path, str | int], Any] = inspect_input_file,
    classify: Callable[..., dict[str, Any]] = classify_source,
) -> dict[str, Any]:
    with normalized_source(input_path) as source:
        if source.is_file() and source.stat().st_size <= 0:
            raise ValueError(f"Input file is empty: {source}")
        try:
            payload = json_safe(inspect_source(source, sheet))
        except (IsADirectoryError, TypeError, ValueError) as exc:
            # A non-empty file that the generic reader cannot parse must fail
            # closed.  Classifying it after the failure lets path keywords such
            # as ``dma`` or ``ftir`` turn arbitrary bytes into an apparently
            # authoritative ready-rule result.
            semantics = json_safe(classify(source, sheet=sheet))
            if semantics.get("production_status") != "ready" or not semantics.get(
                "rule_id"
            ):
                raise
            if (
                source.is_file()
                and semantics.get("rule_id") != "performance_comparison"
            ):
                raise
            return _semantic_only_inspection_payload(
                source, semantics, inspection_error=exc
            )
        semantics = json_safe(classify(source, sheet=sheet, vendor_inspection=payload))
        payload["sciplot_semantics"] = semantics
        inspected_model = str(payload.get("model") or "")
        semantic_family = str(semantics.get("semantic_family") or "")
        rule_id = str(semantics.get("rule_id") or "")
        inspected_recommendations = (
            payload.get("recommendations")
            if isinstance(payload.get("recommendations"), list)
            else []
        )
        inspected_template = (
            str(inspected_recommendations[0].get("template_id") or "")
            if inspected_recommendations
            else ""
        )
        semantic_template = str(semantics.get("template") or "")
        ready_rule_authority = semantics.get("production_status") == "ready" and bool(
            rule_id
        )
        semantic_override = ready_rule_authority and (
            inspected_model != semantic_family
            or inspected_template != semantic_template
        )
        if semantic_override:
            inspected_advanced = (
                payload.get("advanced_templates")
                if isinstance(payload.get("advanced_templates"), list)
                else []
            )
            confidence = float(semantics.get("confidence") or 0.0)
            reason = str(
                semantics.get("reason")
                or f"Matched SciPlot material rule `{semantic_family}`."
            )
            recommendation = _material_rule_recommendation(semantics)
            # These three keys are part of the established inspection payload.
            payload["vendor_inspection_model"] = inspected_model
            payload["vendor_recommendations"] = inspected_recommendations
            payload["vendor_advanced_templates"] = inspected_advanced
            payload["model"] = semantic_family
            payload["model_label"] = (
                f"{semantic_family} ({semantics.get('rule_id') or semantic_family})"
            )
            payload["recommendations"] = [recommendation]
            payload["canonical_templates"] = [recommendation]
            payload["advanced_templates"] = []
            payload["recommendation_confidence"] = confidence
            payload["recommendation_summary"] = reason
        if ready_rule_authority:
            warnings = (
                payload.get("warnings")
                if isinstance(payload.get("warnings"), list)
                else []
            )
            user_warnings, warning_provenance = _resolve_ready_rule_inspection_warnings(
                warnings,
                rule_id=rule_id,
            )
            payload["warnings"] = user_warnings
            payload["inspection_resolution"] = {
                "status": "ready_rule_authoritative",
                "authoritative_source": "sciplot_material_rule",
                "rule_id": rule_id,
                "selected_model": semantic_family,
                "selected_template": semantic_template,
                "generic_inspection_status": (
                    "superseded" if semantic_override else "confirmed"
                ),
                "generic_model": inspected_model or "unknown",
                "generic_template": inspected_template or "unknown",
            }
            payload["inspection_warning_provenance"] = warning_provenance
    return payload
