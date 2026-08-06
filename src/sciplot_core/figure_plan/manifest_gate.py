"""Validate durable manifest projections of one resolved figure plan."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from sciplot_core.figure_plan.constants import SUPPORTED_FIGURE_PLAN_RULE_IDS
from sciplot_core.figure_plan.execution import figure_plan_gate
from sciplot_core.figure_plan.payload_types import (
    FigurePlanManifestGatePayload,
    FigurePlanManifestGateValidPayload,
    FigurePlanProjectionConsistencyPayload,
)
from sciplot_core.figure_plan.plan import resolved_figure_plan_from_payload


def figure_plan_manifest_gate(
    manifest: dict[str, Any],
) -> FigurePlanManifestGatePayload | None:
    """Verify that every durable manifest projection carries one completed plan."""

    declared_rule_ids = _manifest_rule_ids(manifest)
    applicable_rule_ids = declared_rule_ids & SUPPORTED_FIGURE_PLAN_RULE_IDS
    gate = figure_plan_gate(manifest.get("resolved_figure_plan"))
    if gate is None:
        if applicable_rule_ids:
            return {
                "valid": False,
                "complete": False,
                "plan_id": None,
                "plan_sha256": None,
                "selected_figure_ids": [],
                "ready_figure_ids": [],
                "incomplete_figure_ids": [],
                "reason": "resolved_figure_plan_required_for_supported_rule",
            }
        return None
    if gate["valid"] is not True:
        return gate
    plan = resolved_figure_plan_from_payload(manifest["resolved_figure_plan"])
    assert plan is not None
    expected_outcomes = [outcome.to_payload() for outcome in plan.outcomes]
    result_value = manifest.get("result")
    if isinstance(result_value, dict):
        result = result_value
    else:
        result = {}
    study_model_value = manifest.get("study_model")
    if isinstance(study_model_value, dict):
        study_model = study_model_value
    else:
        study_model = {}
    study_run_value = study_model.get("run")
    if isinstance(study_run_value, dict):
        study_run = study_run_value
    else:
        study_run = {}
    consistency: FigurePlanProjectionConsistencyPayload = {
        "manifest_rule_matches": not declared_rule_ids
        or declared_rule_ids == {plan.rule_id},
        "manifest_outcomes_match": manifest.get("figure_outcomes") == expected_outcomes,
        "result_plan_matches": result.get("resolved_figure_plan") == plan.to_payload(),
        "result_outcomes_match": result.get("figure_outcomes") == expected_outcomes,
        "study_plan_id_matches": study_run.get("resolved_figure_plan_id")
        == plan.plan_id,
        "study_outcomes_match": study_run.get("figure_outcomes") == expected_outcomes,
        "outcome_artifacts_exist": all(
            Path(path).expanduser().is_file()
            for outcome in plan.outcomes
            for path in outcome.artifacts
        ),
    }
    manifest_gate: FigurePlanManifestGateValidPayload = {
        "valid": True,
        "complete": bool(gate["complete"] and all(consistency.values())),
        "plan_id": gate["plan_id"],
        "plan_sha256": gate["plan_sha256"],
        "source_sha256": gate["source_sha256"],
        "selected_figure_ids": gate["selected_figure_ids"],
        "ready_figure_ids": gate["ready_figure_ids"],
        "incomplete_figure_ids": gate["incomplete_figure_ids"],
        "reason": gate["reason"],
        "projection_consistency": consistency,
    }
    if not manifest_gate["complete"]:
        manifest_gate["reason"] = (
            "resolved_figure_plan_projection_mismatch"
            if not all(consistency.values())
            else "resolved_figure_plan_incomplete"
        )
    return manifest_gate


def _manifest_rule_ids(manifest: dict[str, Any]) -> set[str]:
    values: set[str] = set()
    for key in ("semantic", "request"):
        payload = manifest.get(key)
        if not isinstance(payload, dict):
            continue
        rule_id = str(payload.get("rule_id") or "").strip()
        if rule_id:
            values.add(rule_id)
    return values


__all__ = ["figure_plan_manifest_gate"]
