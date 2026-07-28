"""Build a rule-repair intervention package."""

from __future__ import annotations

from typing import Any
from sciplot_core.automation_states import RULE_REPAIR_STATE
from sciplot_core.foundation.json_values import json_safe


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
