"""Run one-step and persist its autoplot summary."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from sciplot_core.automation_states import READY_STATE, RULE_REPAIR_STATE
from sciplot_core.foundation.json_io import atomic_write_json
from sciplot_core.foundation.json_values import json_safe
from sciplot_core.materials_rules.catalog import get_rule
from sciplot_core.materials_rules.models import SemanticRule
from sciplot_core.readiness.registry_io import load_validated_envelope_registry
from sciplot_core.readiness.rule_certification import (
    current_rule_invocation_contract_payload,
)
from sciplot_core.workflow import run_one_step

from sciplot_core.autoplot.summary import (
    _autoplot_result_payload,
    build_autoplot_summary,
)


def _rule_preflight_summary(
    *,
    rule: SemanticRule,
    template: str | None,
    reason_codes: list[str],
) -> dict[str, Any]:
    selected_template = str(template).strip() if template is not None else ""
    reasons = list(reason_codes)
    return _autoplot_result_payload(
        state=RULE_REPAIR_STATE,
        ready_to_use=False,
        project_dir=None,
        run_output=None,
        request_path=None,
        manifest=None,
        one_step_status=None,
        delivery=None,
        delivery_complete=False,
        delivery_recorded_complete=False,
        review_html=None,
        revision_brief=None,
        route={
            "mode": "one_step",
            "source_kind": "unknown",
            "semantic_family": rule.semantic_family,
            "rule_id": rule.rule_id,
            "confidence_band": "unknown",
            "recipe": "auto",
            "template": selected_template or rule.template,
            "figure_size": None,
            "exports": [],
        },
        figure_plan={"complete": False, "status": RULE_REPAIR_STATE},
        figure_plan_gate={
            "valid": False,
            "complete": False,
            "status": RULE_REPAIR_STATE,
        },
        quality={
            "status": None,
            "qa_status": None,
            "layout_review_mode": "structured_qa_only",
            "issue_ids": [],
            "quality_actions": [],
            "image_review_required": False,
        },
        validated_envelope={
            "state": RULE_REPAIR_STATE,
            "rule_id": rule.rule_id,
            "ready_without_ai": False,
            "contract_current": False,
            "evidence": None,
            "repair_reasons": reasons,
            "confirmation_reasons": [],
        },
        integrity={
            "state_consistent": False,
            "preparation_state_consistent": False,
            "publish_state_consistent": False,
            "qa_ready": False,
            "validated_envelope_ready": False,
            "manifest_exists": False,
            "manifest_valid": False,
            "one_step_status_exists": False,
            "one_step_status_valid": False,
            "one_step_manifest_consistent": False,
            "figure_plan_projection_consistent": False,
            "delivery_path_exists": False,
            "delivery_path_canonical": False,
            "delivery_package_consistent": False,
            "delivery_verification": {},
            "publish_state_valid": False,
            "publish_state": {},
            "package_contract_verification": {},
            "reasons": reasons,
        },
        token_policy={
            "default_codex_context": "structured_qa_summary",
            "codex_reads_images_by_default": False,
            "image_review_required": False,
            "image_review_allowed_only_when": [
                "qa_failure",
                "low_confidence_semantics",
                "explicit_user_request",
            ],
            "codex_role": "rule_repair_or_user_requested_visual_refinement",
        },
        codex_handoff={
            "required": True,
            "read_first": [],
            "image_review_required": False,
            "intervention_package": {},
        },
    )


def run_autoplot(
    input_path: Path,
    *,
    output_root: Path,
    project_name: str | None = None,
    delivery_root: Path | None = None,
    rule_id: str | None = None,
    template: str | None = None,
) -> dict[str, Any]:
    if rule_id is not None:
        rule = get_rule(rule_id)
        invocation = current_rule_invocation_contract_payload(
            rule=rule,
            registry=load_validated_envelope_registry(),
        )
        if invocation["availability"] != READY_STATE:
            summary = _rule_preflight_summary(
                rule=rule,
                template=template,
                reason_codes=list(invocation["reason_codes"]),
            )
            summary["summary_path"] = None
            return summary
        if not input_path.exists():
            raise ValueError(f"Input not found: {input_path}")

    result = run_one_step(
        input_path,
        output_root=output_root,
        project_name=project_name,
        delivery_root=delivery_root,
        rule_id=rule_id,
        template=template,
    )
    summary = build_autoplot_summary(result)
    run_output = Path(str(summary["run_output"]))
    summary_path = run_output / "autoplot_summary.json"
    summary["summary_path"] = str(summary_path)
    atomic_write_json(summary_path, json_safe(summary))
    return summary
