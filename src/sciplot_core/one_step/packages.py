"""Build source, mapping, render-request, and figure-QA packages."""

from __future__ import annotations

from pathlib import Path
from typing import Any
from sciplot_core.foundation.json_values import json_safe
from sciplot_core.readiness import (
    HIGH_CONFIDENCE_THRESHOLD,
    MEDIUM_CONFIDENCE_THRESHOLD,
)

from sciplot_core.one_step.confidence import (
    _source_counts,
    _semantic_confidence,
    confidence_band,
)

from sciplot_core.one_step.quality_actions import (
    build_quality_actions,
)


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
