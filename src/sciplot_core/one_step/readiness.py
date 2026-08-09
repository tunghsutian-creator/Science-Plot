"""Determine the one-step lifecycle state from evidence."""

from __future__ import annotations

from typing import Any

from sciplot_core.automation_states import (
    AutomationState,
    HUMAN_CONFIRMATION_STATE,
    READY_STATE,
    RULE_REPAIR_STATE,
)
from sciplot_core.figure_plan import ResolvedFigurePlan
from sciplot_core.readiness import (
    INSIDE_VALIDATED_ENVELOPE,
    validated_envelope_evaluation_ready,
)


def _readiness(
    *,
    source_package: dict[str, Any],
    mapping_package: dict[str, Any],
    render_request: dict[str, Any],
    figure_qa_report: dict[str, Any],
    validated_envelope: dict[str, Any],
    resolved_figure_plan: ResolvedFigurePlan | None = None,
) -> tuple[AutomationState, list[str]]:
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
    if resolved_figure_plan is not None and not resolved_figure_plan.complete:
        reasons.append("resolved_figure_plan_incomplete")
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
            or "resolved_figure_plan_incomplete" in reasons
            or "validated_envelope_rule_repair_required" in reasons
            or "validated_envelope_invalid" in reasons
        ):
            return RULE_REPAIR_STATE, reasons
        return HUMAN_CONFIRMATION_STATE, reasons
    return READY_STATE, ["all_programmatic_gates_passed"]
