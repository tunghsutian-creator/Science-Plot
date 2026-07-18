from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from sciplot_core._utils import json_safe, slug
from sciplot_core.policy import LayoutPolicy, layout_policy_payload
from sciplot_core.readiness import (
    HIGH_CONFIDENCE_THRESHOLD,
    INSIDE_VALIDATED_ENVELOPE,
    MEDIUM_CONFIDENCE_THRESHOLD,
    evaluate_validated_envelope,
    validated_envelope_evaluation_ready,
)
from sciplot_core.split import DEFAULT_STACK_SPLIT_POLICY, STACKED_TALL_FIGURE_HEIGHT_MM

ONE_STEP_MODEL_KIND = "sciplot_one_step_project"
ONE_STEP_MODEL_VERSION = 2

READY_STATE = "ready"
HUMAN_CONFIRMATION_STATE = "needs_human_confirmation"
RULE_REPAIR_STATE = "needs_rule_repair"

QUALITY_ACTION_LINE_WIDTH_PT = 1.2

_LEGEND_INLINE_STRATEGY = {
    "object": "legend",
    "fallback_order": ["inside_auto_legend", "inline_labels"],
    "reject_if": [
        "legend_overlap",
        "legend_footprint",
        "legend_axes_too_small",
        "legend_outside_bounds",
    ],
}

_LEGEND_AUTO_STRATEGY = {
    "object": "legend",
    "fallback_order": ["inside_auto_legend", "inline_labels"],
    "reject_if": [
        "label_collision",
        "label_out_of_bounds",
        "stacked_label_collision",
        "stacked_label_bounds",
    ],
}

_STACK_SPLIT_POLICY = DEFAULT_STACK_SPLIT_POLICY


_ISSUE_QUALITY_ACTIONS: dict[str, dict[str, Any]] = {
    "stroke_weight_out_of_band": {
        "id": "normalize_line_width",
        "label": "Normalize line width",
        "reason": "Curve strokes fall outside the publication-style line-weight contract.",
        "series_style_patch": {
            "target": "visible_series",
            "line_width": QUALITY_ACTION_LINE_WIDTH_PT,
        },
    },
    "line_tick_hierarchy": {
        "id": "normalize_line_width",
        "label": "Normalize line width",
        "reason": "Curve strokes are visually weaker than the tick hierarchy.",
        "series_style_patch": {
            "target": "visible_series",
            "line_width": QUALITY_ACTION_LINE_WIDTH_PT,
        },
    },
    "stroke_hierarchy": {
        "id": "normalize_line_width",
        "label": "Normalize line width",
        "reason": "The plotted stroke hierarchy is outside the visual QA contract.",
        "series_style_patch": {
            "target": "visible_series",
            "line_width": QUALITY_ACTION_LINE_WIDTH_PT,
        },
    },
    "tick_label_overlap": {
        "id": "use_sparse_ticks",
        "label": "Use sparse ticks",
        "reason": "Major tick labels overlap in the rendered frame.",
        "render_options_patch": {
            "x_tick_density": "sparse",
            "y_tick_density": "sparse",
        },
    },
    "axis_label_crowding": {
        "id": "use_sparse_ticks",
        "label": "Use sparse ticks",
        "reason": "Axis tick labels are too crowded for the current figure size.",
        "render_options_patch": {
            "x_tick_density": "sparse",
            "y_tick_density": "sparse",
        },
    },
    "category_crowding": {
        "id": "use_sparse_ticks",
        "label": "Use sparse ticks",
        "reason": "Categorical labels are crowded in the rendered frame.",
        "render_options_patch": {"x_tick_density": "sparse"},
    },
    "legend_overlap": {
        "id": "use_inline_labels",
        "label": "Use inline labels",
        "reason": "The legend overlaps data, ticks, axis labels, or direct labels.",
        "render_options_patch": {
            "legend_position": "auto",
            "series_label_mode": "inline",
        },
        "layout_strategy": _LEGEND_INLINE_STRATEGY,
    },
    "legend_footprint": {
        "id": "use_inline_labels",
        "label": "Use inline labels",
        "reason": "The legend footprint leaves too little useful plotting area.",
        "render_options_patch": {
            "legend_position": "auto",
            "series_label_mode": "inline",
        },
        "layout_strategy": _LEGEND_INLINE_STRATEGY,
    },
    "legend_axes_too_small": {
        "id": "use_inline_labels",
        "label": "Use inline labels",
        "reason": "Legend avoidance makes the data axes too small.",
        "render_options_patch": {
            "legend_position": "auto",
            "series_label_mode": "inline",
        },
        "layout_strategy": _LEGEND_INLINE_STRATEGY,
    },
    "legend_outside_bounds": {
        "id": "use_inside_or_inline_labels",
        "label": "Keep labels inside",
        "reason": "The legend extends outside the rendered canvas.",
        "render_options_patch": {
            "legend_position": "auto",
            "series_label_mode": "inline",
        },
        "layout_strategy": _LEGEND_INLINE_STRATEGY,
    },
    "legend_crowded_inside": {
        "id": "use_inside_or_inline_labels",
        "label": "Keep labels inside",
        "reason": "The visible legend is too crowded for the fixed publication frame.",
        "render_options_patch": {
            "legend_position": "auto",
            "series_label_mode": "inline",
        },
        "layout_strategy": _LEGEND_INLINE_STRATEGY,
    },
    "label_collision": {
        "id": "use_auto_legend",
        "label": "Use auto legend",
        "reason": "Direct labels collide; let the renderer choose a safer legend/label mode.",
        "render_options_patch": {
            "legend_position": "auto",
            "series_label_mode": "legend",
        },
        "layout_strategy": _LEGEND_AUTO_STRATEGY,
    },
    "label_out_of_bounds": {
        "id": "use_auto_legend",
        "label": "Use auto legend",
        "reason": "At least one direct label falls outside the plotting axes.",
        "render_options_patch": {
            "legend_position": "auto",
            "series_label_mode": "legend",
        },
        "layout_strategy": _LEGEND_AUTO_STRATEGY,
    },
    "ftir_wavenumber_bounds_missing": {
        "id": "restore_ftir_wavenumber_axis",
        "label": "Restore FTIR axis",
        "reason": "FTIR/wavenumber plots must show 4000 to 400 cm^-1 with endpoint ticks.",
        "render_options_patch": {
            "x_min": 400.0,
            "x_max": 4000.0,
            "reverse_x": True,
            "x_tick_density": "auto",
        },
    },
    "stacked_top_blank_excess": {
        "id": "tighten_stacked_y_axis",
        "label": "Tighten stacked y-axis",
        "reason": "Stacked curves leave excessive blank area above the data.",
        "clear_render_options": ["y_min", "y_max"],
    },
    "data_vertical_occupancy_low": {
        "id": "tighten_stacked_y_axis",
        "label": "Tighten stacked y-axis",
        "reason": "The data occupy too little vertical space in the plotted frame.",
        "clear_render_options": ["y_min", "y_max"],
    },
    "stack_curve_overlap": {
        "id": "increase_stack_spacing",
        "label": "Increase stack spacing",
        "reason": "Manual stacked-curve spacing causes curve overlap.",
        "clear_render_options": ["stack_spacing_scale"],
    },
    "stack_spacing_too_loose": {
        "id": "tighten_stacked_y_axis",
        "label": "Tighten stacked y-axis",
        "reason": "Manual stacked-curve spacing is too loose for the current figure.",
        "clear_render_options": ["stack_spacing_scale", "y_min", "y_max"],
    },
    "stack_peak_too_small": {
        "id": "increase_figure_height_or_split",
        "label": "Increase height or split",
        "reason": "Stacked peaks are below the minimum readable pixel height.",
        "figure_size_patch": {
            "mode": "increase_height",
            "fallback_size": "60x110",
            "split_if_unavailable": True,
        },
        "split_policy": _STACK_SPLIT_POLICY,
        "requires_human_confirmation": True,
    },
    "stacked_label_collision": {
        "id": "use_auto_legend",
        "label": "Use auto legend",
        "reason": "Stacked direct labels collide.",
        "render_options_patch": {
            "legend_position": "auto",
            "series_label_mode": "legend",
        },
        "layout_strategy": _LEGEND_AUTO_STRATEGY,
    },
    "stacked_label_bounds": {
        "id": "use_auto_legend",
        "label": "Use auto legend",
        "reason": "At least one stacked direct label is outside the plotting axes.",
        "render_options_patch": {
            "legend_position": "auto",
            "series_label_mode": "legend",
        },
        "layout_strategy": _LEGEND_AUTO_STRATEGY,
    },
}

_STACK_SPLIT_QUALITY_ACTION = {
    "id": "split_stacked_figure",
    "label": "Split stacked figure",
    "reason": "Stacked peaks remain below readable pixel height even on a tall figure.",
    "split_policy": _STACK_SPLIT_POLICY,
    "requires_human_confirmation": True,
}

_AUTOFIX_QUALITY_ACTIONS: dict[str, dict[str, Any]] = {
    "stroke_weight_autorepaired": {
        "id": "normalize_line_width",
        "label": "Normalized line width",
        "reason": "Default strokes were raised to the publication-style line-weight floor.",
        "series_style_patch": {
            "target": "visible_series",
            "line_width": QUALITY_ACTION_LINE_WIDTH_PT,
        },
    },
    "stacked_y_axis_compacted": {
        "id": "tighten_stacked_y_axis",
        "label": "Tightened stacked y-axis",
        "reason": "The renderer compacted stacked y-limits after visual occupancy QA.",
    },
    "legend_auto_inline_labels": {
        "id": "use_inline_labels",
        "label": "Switched to inline labels",
        "reason": "The renderer used inline labels because the legend would hurt data readability.",
        "render_options_patch": {
            "legend_position": "auto",
            "series_label_mode": "inline",
        },
    },
    "direct_series_labels": {
        "id": "use_inline_labels",
        "label": "Used inline labels",
        "reason": "Direct labels were selected by the automatic layout pass.",
        "render_options_patch": {
            "legend_position": "auto",
            "series_label_mode": "inline",
        },
    },
    "legend_auto_widened_inside": {
        "id": "widen_for_inside_legend",
        "label": "Widened for inside legend",
        "reason": "The renderer widened an unlocked canvas while preserving the fixed graph margins.",
        "render_options_patch": {
            "legend_position": "auto",
            "series_label_mode": "legend",
        },
    },
    "legend_outside_removed": {
        "id": "keep_legend_inside",
        "label": "Kept legend inside",
        "reason": "A retired outside-legend request was normalized to the fixed inside-frame policy.",
        "render_options_patch": {
            "legend_position": "auto",
            "series_label_mode": "legend",
        },
    },
    "legend_auto_upper_right": {
        "id": "move_legend_upper_right",
        "label": "Moved legend upper right",
        "reason": "The legend was moved away from the lower data region.",
        "render_options_patch": {
            "legend_position": "upper_right",
            "series_label_mode": "legend",
        },
    },
    "direct_label_offset": {
        "id": "offset_direct_labels",
        "label": "Offset direct labels",
        "reason": "Inline labels were offset from their curve anchors to reduce label-on-curve collisions.",
        "render_options_patch": {
            "series_label_offset_fraction": 0.018,
            "series_label_vertical_align": "bottom",
        },
    },
    "tick_density_sparse": {
        "id": "use_sparse_ticks",
        "label": "Used sparse ticks",
        "reason": "Dense ticks were downgraded to keep labels readable.",
        "render_options_patch": {
            "x_tick_density": "sparse",
            "y_tick_density": "sparse",
        },
    },
    "split_stacked_figure_auto": {
        "id": "split_stacked_figure",
        "label": "Split stacked figure",
        "reason": "A tall unreadable stacked figure was split into series chunks.",
        "split_policy": _STACK_SPLIT_POLICY,
        "requires_human_confirmation": False,
    },
}


def _now() -> str:
    return datetime.now(UTC).isoformat()


def _source_counts(path: Path) -> dict[str, int]:
    if path.is_file():
        return {"file_count": 1, "folder_count": 0}
    if path.is_dir():
        file_count = sum(1 for item in path.rglob("*") if item.is_file())
        folder_count = sum(1 for item in path.rglob("*") if item.is_dir())
        return {"file_count": file_count, "folder_count": folder_count}
    return {"file_count": 0, "folder_count": 0}


def _semantic_confidence(semantic: dict[str, Any]) -> float:
    try:
        return float(semantic.get("confidence") or 0.0)
    except (TypeError, ValueError):
        return 0.0


def confidence_band(semantic: dict[str, Any]) -> str:
    confidence = _semantic_confidence(semantic)
    if bool(semantic.get("needs_ai_intervention")):
        return "low"
    if confidence >= HIGH_CONFIDENCE_THRESHOLD:
        return "high"
    if confidence >= MEDIUM_CONFIDENCE_THRESHOLD:
        return "medium"
    return "low"


def _quality_action(
    template: dict[str, Any], *, status: str, evidence_id: str
) -> dict[str, Any]:
    action = {
        "id": str(template["id"]),
        "status": status,
        "label": str(template["label"]),
        "reason": str(template["reason"]),
        "evidence_id": evidence_id,
    }
    for key in (
        "render_options_patch",
        "clear_render_options",
        "figure_size_patch",
        "layout_strategy",
        "split_policy",
        "series_style_patch",
        "requires_rule_repair",
        "requires_human_confirmation",
    ):
        if key in template:
            action[key] = json_safe(template[key])
    action["can_apply_as_refine_draft"] = bool(
        action.get("render_options_patch")
        or action.get("clear_render_options")
        or action.get("figure_size_patch")
        or action.get("split_policy")
        or action.get("series_style_patch")
    )
    return action


def _layout_summary_height_mm(
    layout_summaries: list[dict[str, Any]] | None,
) -> float | None:
    heights: list[float] = []
    for summary in layout_summaries or []:
        if not isinstance(summary, dict):
            continue
        for key in ("requested_size_mm", "figure_size_mm"):
            value = summary.get(key)
            if not isinstance(value, list | tuple) or len(value) < 2:
                continue
            try:
                heights.append(float(value[1]))
            except (TypeError, ValueError):
                continue
    return max(heights) if heights else None


def _template_for_issue(
    issue_id: str,
    *,
    layout_summaries: list[dict[str, Any]] | None,
) -> dict[str, Any] | None:
    if issue_id == "stack_peak_too_small":
        height_mm = _layout_summary_height_mm(layout_summaries)
        if height_mm is not None and height_mm >= STACKED_TALL_FIGURE_HEIGHT_MM:
            return _STACK_SPLIT_QUALITY_ACTION
    return _ISSUE_QUALITY_ACTIONS.get(issue_id)


def build_quality_actions(
    *,
    issue_ids: list[str],
    autofixes_applied: list[str],
    layout_summaries: list[dict[str, Any]] | None = None,
) -> list[dict[str, Any]]:
    actions: list[dict[str, Any]] = []
    handled: set[str] = set()
    for autofix in autofixes_applied:
        template = _AUTOFIX_QUALITY_ACTIONS.get(str(autofix))
        if not template:
            continue
        action = _quality_action(template, status="applied", evidence_id=str(autofix))
        actions.append(action)
        handled.add(str(action["id"]))
    for issue_id in issue_ids:
        template = _template_for_issue(str(issue_id), layout_summaries=layout_summaries)
        if not template:
            continue
        if str(template["id"]) in handled:
            continue
        actions.append(
            _quality_action(template, status="suggested", evidence_id=str(issue_id))
        )
        handled.add(str(template["id"]))
    return actions


def build_source_package(
    *,
    input_path: Path,
    raw_archive: dict[str, Any] | None = None,
    semantic: dict[str, Any] | None = None,
) -> dict[str, Any]:
    semantic = semantic if isinstance(semantic, dict) else {}
    counts = _source_counts(input_path)
    return {
        "kind": "sciplot_source_package",
        "version": 1,
        "source": str(input_path),
        "source_kind": "directory" if input_path.is_dir() else "file",
        "file_count": counts["file_count"],
        "folder_count": counts["folder_count"],
        "instrument_family": semantic.get("semantic_family") or "unknown",
        "rule_id": semantic.get("rule_id"),
        "confidence": _semantic_confidence(semantic),
        "confidence_band": confidence_band(semantic),
        "raw_archive": json_safe(raw_archive or {}),
    }


def build_mapping_package(
    *,
    request: dict[str, Any],
    semantic: dict[str, Any],
    study_model: dict[str, Any] | None = None,
) -> dict[str, Any]:
    study_model = study_model if isinstance(study_model, dict) else {}
    confidence = _semantic_confidence(semantic)
    requested_rule_id = request.get("rule_id")
    explicit_rule_confirmation = (
        isinstance(requested_rule_id, str)
        and requested_rule_id.strip() == str(semantic.get("rule_id") or "").strip()
    )
    has_confirmations = bool(request.get("column_confirmations"))
    sample_order = request.get("series_order")
    if not isinstance(sample_order, list):
        sample_order = (
            study_model.get("sample_order")
            if isinstance(study_model.get("sample_order"), list)
            else []
        )
    status = "confirmed" if has_confirmations or explicit_rule_confirmation else "auto"
    if (
        bool(semantic.get("needs_ai_intervention"))
        or confidence < MEDIUM_CONFIDENCE_THRESHOLD
    ):
        status = "needs_rule_repair"
    elif confidence < HIGH_CONFIDENCE_THRESHOLD and not (
        has_confirmations or explicit_rule_confirmation
    ):
        status = "needs_human_confirmation"
    return {
        "kind": "sciplot_mapping_package",
        "version": 1,
        "status": status,
        "experiment_type": semantic.get("rule_id")
        or semantic.get("semantic_family")
        or "unknown",
        "semantic_family": semantic.get("semantic_family") or "unknown",
        "rule_id": semantic.get("rule_id"),
        "confidence": confidence,
        "confidence_band": confidence_band(semantic),
        "reason": semantic.get("reason") or "",
        "sample_order": [str(item) for item in sample_order],
        "column_confirmations": json_safe(request.get("column_confirmations") or []),
    }


def build_render_request_package(
    *, request_path: Path, request: dict[str, Any]
) -> dict[str, Any]:
    render_options = request.get("render_options", {})
    figure_size = (
        render_options.get("size") if isinstance(render_options, dict) else None
    ) or "60x55"
    return {
        "kind": "sciplot_render_request",
        "version": 1,
        "path": str(request_path),
        "rule_id": request.get("rule_id"),
        "recipe": request.get("recipe"),
        "template": request.get("template"),
        "exports": json_safe(request.get("exports", ["pdf", "tiff_300"])),
        "render_engine": "veusz",
        "figure_size": figure_size,
        "render_options": json_safe(render_options),
        "split_policy": json_safe(request.get("split_policy", {})),
        "series_order": json_safe(request.get("series_order", [])),
        "explicit_render_option_keys": json_safe(
            request.get("explicit_render_option_keys", [])
        ),
    }


def build_figure_qa_report(
    *,
    qa: dict[str, Any] | None,
    layout_quality: dict[str, Any] | None,
    delivery_package: dict[str, Any] | None = None,
) -> dict[str, Any]:
    qa = qa if isinstance(qa, dict) else {}
    layout_quality = layout_quality if isinstance(layout_quality, dict) else {}
    issue_ids = (
        layout_quality.get("issue_ids")
        if isinstance(layout_quality.get("issue_ids"), list)
        else []
    )
    layout_needs_ai = bool(layout_quality.get("needs_ai_intervention"))
    qa_status = str(qa.get("status") or "unknown")
    delivery_complete = (
        bool(delivery_package.get("complete"))
        if isinstance(delivery_package, dict)
        else False
    )
    pdfs = qa.get("pdfs") if isinstance(qa.get("pdfs"), list) else []
    normalized_issue_ids = [str(item) for item in issue_ids]
    raw_autofixes = layout_quality.get("autofixes_applied")
    autofixes_applied = (
        [str(item) for item in raw_autofixes] if isinstance(raw_autofixes, list) else []
    )
    export_visual_qa = [
        {"path": item.get("path"), "visual_qa": item.get("visual_qa")}
        for item in pdfs
        if isinstance(item, dict) and isinstance(item.get("visual_qa"), dict)
    ]
    layout_summaries = layout_quality.get("summaries")
    if not isinstance(layout_summaries, list):
        layout_summaries = []
    split_plan = layout_quality.get("split_plan")
    if not isinstance(split_plan, dict):
        split_plan = {}
    return {
        "kind": "sciplot_figure_qa_report",
        "version": 1,
        "status": "passed"
        if qa_status == "passed" and not layout_needs_ai
        else "failed",
        "qa_status": qa_status,
        "layout_review_mode": layout_quality.get("review_mode") or "structured_qa_only",
        "needs_ai_intervention": layout_needs_ai,
        "issue_ids": normalized_issue_ids,
        "autofixes_applied": autofixes_applied,
        "quality_actions": build_quality_actions(
            issue_ids=normalized_issue_ids,
            autofixes_applied=autofixes_applied,
            layout_summaries=layout_summaries,
        ),
        "summary_count": len(layout_summaries),
        "split_plan": json_safe(split_plan),
        "delivery_complete": delivery_complete,
        "export_visual_qa": export_visual_qa,
        "image_review_required": layout_needs_ai
        or qa_status not in {"passed", "unknown"},
        "image_review_triggers": [
            "qa_failure",
            "low_confidence_semantics",
            "explicit_user_request",
        ],
    }


def _readiness(
    *,
    source_package: dict[str, Any],
    mapping_package: dict[str, Any],
    render_request: dict[str, Any],
    figure_qa_report: dict[str, Any],
    validated_envelope: dict[str, Any],
) -> tuple[str, list[str]]:
    reasons: list[str] = []
    if (
        figure_qa_report.get("needs_ai_intervention")
        or figure_qa_report.get("status") != "passed"
        or figure_qa_report.get("qa_status") != "passed"
    ):
        reasons.append("figure_qa_failed")
    if figure_qa_report.get("delivery_complete") is False:
        reasons.append("delivery_package_incomplete")
    if (
        source_package.get("confidence_band") == "low"
        or mapping_package.get("status") == "needs_rule_repair"
    ):
        reasons.append("semantic_rule_repair_required")
    if mapping_package.get("status") == "needs_human_confirmation":
        reasons.append("mapping_confirmation_required")
    envelope_state = validated_envelope.get("state")
    if envelope_state == "needs_rule_repair":
        reasons.append("validated_envelope_rule_repair_required")
    elif envelope_state == "needs_human_confirmation":
        reasons.append("validated_envelope_confirmation_required")
    elif envelope_state != INSIDE_VALIDATED_ENVELOPE:
        reasons.append("validated_envelope_invalid")
    elif not validated_envelope_evaluation_ready(
        validated_envelope,
        render_request=render_request,
    ):
        reasons.append("validated_envelope_invalid")
    if reasons:
        if (
            "semantic_rule_repair_required" in reasons
            or "figure_qa_failed" in reasons
            or "delivery_package_incomplete" in reasons
            or "validated_envelope_rule_repair_required" in reasons
            or "validated_envelope_invalid" in reasons
        ):
            return RULE_REPAIR_STATE, reasons
        return HUMAN_CONFIRMATION_STATE, reasons
    return READY_STATE, ["all_programmatic_gates_passed"]


def build_intervention_package(
    *,
    intervention_request: dict[str, Any] | None = None,
    state: str,
    figure_qa_report: dict[str, Any] | None = None,
) -> dict[str, Any]:
    figure_qa_report = figure_qa_report if isinstance(figure_qa_report, dict) else {}
    return {
        "kind": "sciplot_intervention_package",
        "version": 1,
        "required": state == RULE_REPAIR_STATE,
        "reason": "rule_or_layout_repair_required"
        if state == RULE_REPAIR_STATE
        else "",
        "request": json_safe(intervention_request or {}),
        "codex_review_policy": {
            "default": "structured_qa_summary",
            "image_review_required": bool(
                figure_qa_report.get("image_review_required")
            ),
            "image_review_triggers": figure_qa_report.get("image_review_triggers")
            or ["qa_failure", "low_confidence_semantics", "explicit_user_request"],
        },
    }


def build_one_step_project(
    *,
    input_path: Path,
    request_path: Path,
    request: dict[str, Any],
    semantic: dict[str, Any],
    raw_archive: dict[str, Any] | None,
    study_model: dict[str, Any] | None,
    layout_policy: LayoutPolicy,
    layout_quality: dict[str, Any] | None,
    qa: dict[str, Any] | None,
    delivery_package: dict[str, Any] | None = None,
    intervention_request: dict[str, Any] | None = None,
) -> dict[str, Any]:
    source_package = build_source_package(
        input_path=input_path, raw_archive=raw_archive, semantic=semantic
    )
    mapping_package = build_mapping_package(
        request=request, semantic=semantic, study_model=study_model
    )
    render_request = build_render_request_package(
        request_path=request_path, request=request
    )
    figure_qa_report = build_figure_qa_report(
        qa=qa,
        layout_quality=layout_quality,
        delivery_package=delivery_package,
    )
    validated_envelope = evaluate_validated_envelope(
        semantic=semantic,
        source_package=source_package,
        mapping_package=mapping_package,
        render_request=render_request,
    )
    state, reasons = _readiness(
        source_package=source_package,
        mapping_package=mapping_package,
        render_request=render_request,
        figure_qa_report=figure_qa_report,
        validated_envelope=validated_envelope,
    )
    return {
        "kind": ONE_STEP_MODEL_KIND,
        "version": ONE_STEP_MODEL_VERSION,
        "created_at": _now(),
        "project": slug(Path(request_path).parent.name or Path(input_path).stem),
        "state": state,
        "state_reasons": reasons,
        "source_package": source_package,
        "mapping_package": mapping_package,
        "render_request": render_request,
        "layout_policy": layout_policy_payload(layout_policy),
        "figure_qa_report": figure_qa_report,
        "validated_envelope": validated_envelope,
        "intervention_package": build_intervention_package(
            intervention_request=intervention_request,
            state=state,
            figure_qa_report=figure_qa_report,
        ),
        "delivery_package": json_safe(delivery_package or {}),
    }


__all__ = [
    "HIGH_CONFIDENCE_THRESHOLD",
    "HUMAN_CONFIRMATION_STATE",
    "MEDIUM_CONFIDENCE_THRESHOLD",
    "ONE_STEP_MODEL_KIND",
    "ONE_STEP_MODEL_VERSION",
    "READY_STATE",
    "RULE_REPAIR_STATE",
    "build_figure_qa_report",
    "build_intervention_package",
    "build_mapping_package",
    "build_one_step_project",
    "build_quality_actions",
    "build_render_request_package",
    "build_source_package",
    "confidence_band",
]
