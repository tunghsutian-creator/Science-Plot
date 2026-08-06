"""Build the user-facing autoplot summary."""

from __future__ import annotations

from typing import Any
from sciplot_core.automation_states import (
    READY_STATE,
    RULE_REPAIR_STATE,
    fail_closed_automation_state,
)
from sciplot_core.foundation.json_values import json_safe
from sciplot_core.figure_plan import figure_plan_manifest_gate
from sciplot_core.delivery import verify_delivery_package
from sciplot_core.output_contract import requested_delivery_root
from sciplot_core.readiness import validated_envelope_evaluation_ready
from sciplot_core.study_model import verify_output_package_contract

from sciplot_core.autoplot.contracts import (
    AUTOPLOT_MODEL_KIND,
    AUTOPLOT_MODEL_VERSION,
)

from sciplot_core.autoplot.evidence import (
    AutoplotRunEvidence,
    _truthy_path,
)

from sciplot_core.autoplot.publish_integrity import (
    _manifest_publish_integrity,
)


def build_autoplot_summary(
    one_step_result: dict[str, Any],
    *,
    _validated_envelope_ready=validated_envelope_evaluation_ready,
) -> dict[str, Any]:
    evidence = AutoplotRunEvidence.load(one_step_result)
    run_output = evidence.run_output
    project_dir = evidence.project_dir
    status_path = evidence.status_path
    manifest_path = evidence.manifest_path
    manifest = evidence.manifest
    figure_plan = figure_plan_manifest_gate(manifest)
    manifest_publish = _manifest_publish_integrity(manifest)
    package_verification = verify_output_package_contract(
        manifest.get("package_contract"),
        output_dir=run_output,
        manifest=manifest,
    )
    status_valid = evidence.status_valid
    manifest_valid = evidence.manifest_valid
    preparation_state_consistent = len(set(evidence.preparation_state_claims)) <= 1
    publish_state_consistent = len(set(evidence.publish_state_claims)) <= 1
    state_consistent = preparation_state_consistent and publish_state_consistent
    state = fail_closed_automation_state(
        evidence.manifest_state
        or evidence.reported_state
        or evidence.persisted_state
        or evidence.reported_payload_state
    )
    if not state_consistent or manifest_publish["valid"] is not True:
        state = RULE_REPAIR_STATE
    delivery = evidence.delivery_package
    figure_qa = evidence.figure_qa
    intervention = evidence.intervention
    validated_envelope = evidence.validated_envelope
    render_request = evidence.render_request
    delivery_path = _truthy_path(delivery.get("path"))
    manifest_exists = manifest_path.is_file()
    status_exists = status_path.is_file()
    delivery_path_exists = bool(delivery_path is not None and delivery_path.is_dir())
    expected_delivery_path = requested_delivery_root(
        manifest,
        run_output=run_output,
    )
    delivery_path_canonical = bool(
        delivery_path is not None
        and delivery_path_exists
        and delivery_path.resolve() == expected_delivery_path
    )
    delivery_recorded_complete = delivery.get("complete") is True
    delivery_verification = verify_delivery_package(
        delivery,
        expected_root=expected_delivery_path,
        expected_manifest=manifest,
    )
    delivery_complete = bool(
        delivery_recorded_complete
        and delivery_path_exists
        and delivery_verification["passed"] is True
    )
    manifest_delivery = evidence.manifest_delivery_package
    delivery_record_consistent = bool(delivery and delivery == manifest_delivery)
    one_step_payload_consistent = bool(
        status_valid
        and manifest_valid
        and evidence.persisted_status == evidence.manifest_one_step
    )
    image_review_required = bool(figure_qa.get("image_review_required"))
    envelope_ready = _validated_envelope_ready(
        validated_envelope,
        render_request=render_request,
    )
    qa_ready = bool(
        figure_qa.get("status") == "passed"
        and figure_qa.get("qa_status") == "passed"
        and figure_qa.get("needs_ai_intervention") is not True
    )
    integrity_reasons = []
    if not state_consistent:
        integrity_reasons.append("one_step_state_mismatch")
    if not manifest_exists:
        integrity_reasons.append("manifest_missing")
    elif not manifest_valid:
        integrity_reasons.append("manifest_invalid")
    if not status_exists:
        integrity_reasons.append("one_step_status_missing")
    elif not status_valid:
        integrity_reasons.append("one_step_status_invalid")
    if not one_step_payload_consistent:
        integrity_reasons.append("one_step_manifest_mismatch")
    if manifest_publish["valid"] is not True:
        integrity_reasons.append("publish_state_missing_or_mismatch")
    if manifest_publish["package_contract_complete"] is not True:
        integrity_reasons.append("package_contract_incomplete")
    if package_verification["passed"] is not True:
        integrity_reasons.append("package_contract_verification_failed")
    if not delivery_record_consistent:
        integrity_reasons.append("delivery_package_mismatch")
    if not delivery_path_exists:
        integrity_reasons.append("delivery_path_missing")
    elif not delivery_path_canonical:
        integrity_reasons.append("delivery_path_noncanonical")
    if not delivery_recorded_complete:
        integrity_reasons.append("delivery_package_incomplete")
    if delivery_verification["passed"] is not True:
        integrity_reasons.append("delivery_package_verification_failed")
    if not envelope_ready:
        integrity_reasons.append("validated_envelope_invalid")
    if not qa_ready:
        integrity_reasons.append("figure_qa_not_passed")
    if figure_plan is not None and figure_plan["complete"] is not True:
        integrity_reasons.append("resolved_figure_plan_incomplete")
    artifact_integrity_ready = bool(
        manifest_exists
        and manifest_valid
        and status_exists
        and status_valid
        and delivery_complete
        and delivery_path_canonical
        and one_step_payload_consistent
        and delivery_record_consistent
        and manifest_publish["valid"] is True
        and package_verification["passed"] is True
        and (figure_plan is None or figure_plan["complete"] is True)
    )
    codex_required = bool(intervention.get("required")) or (
        state == RULE_REPAIR_STATE
        or not envelope_ready
        or not qa_ready
        or not artifact_integrity_ready
    )

    summary = {
        "kind": AUTOPLOT_MODEL_KIND,
        "version": AUTOPLOT_MODEL_VERSION,
        "state": state,
        "ready_to_use": (
            state == READY_STATE
            and delivery_complete
            and envelope_ready
            and qa_ready
            and state_consistent
            and artifact_integrity_ready
            and manifest_publish["expected"]["ready_to_use"] is True
        ),
        "project_dir": str(project_dir),
        "run_output": str(run_output),
        "request_path": evidence.reported_result.get("request_path"),
        "manifest": str(manifest_path) if manifest_exists else None,
        "one_step_status": str(status_path) if status_exists else None,
        "delivery": str(delivery_path) if delivery_path is not None else None,
        "delivery_complete": delivery_complete,
        "delivery_recorded_complete": delivery_recorded_complete,
        "review_html": str(run_output / "review.html")
        if (run_output / "review.html").exists()
        else None,
        "revision_brief": str(run_output / "revision_brief.md")
        if (run_output / "revision_brief.md").exists()
        else None,
        "route": evidence.route_package(),
        "figure_plan": json_safe(
            figure_plan
            or {
                "valid": True,
                "complete": True,
                "status": "not_applicable_legacy_or_single_figure",
            }
        ),
        "quality": {
            "status": figure_qa.get("status"),
            "qa_status": figure_qa.get("qa_status"),
            "layout_review_mode": figure_qa.get("layout_review_mode")
            or "structured_qa_only",
            "issue_ids": figure_qa.get("issue_ids") or [],
            "quality_actions": figure_qa.get("quality_actions") or [],
            "image_review_required": image_review_required,
        },
        "validated_envelope": {
            "state": validated_envelope.get("state") or "missing",
            "rule_id": validated_envelope.get("rule_id"),
            "ready_without_ai": envelope_ready,
            "contract_current": validated_envelope.get("contract_current") is True,
            "evidence": json_safe(validated_envelope.get("accepted_evidence")),
            "repair_reasons": list(
                validated_envelope.get("repair_reasons")
                if isinstance(validated_envelope.get("repair_reasons"), list)
                else []
            ),
            "confirmation_reasons": list(
                validated_envelope.get("confirmation_reasons")
                if isinstance(
                    validated_envelope.get("confirmation_reasons"),
                    list,
                )
                else []
            ),
        },
        "integrity": {
            "state_consistent": state_consistent,
            "preparation_state_consistent": preparation_state_consistent,
            "publish_state_consistent": publish_state_consistent,
            "qa_ready": qa_ready,
            "validated_envelope_ready": envelope_ready,
            "manifest_exists": manifest_exists,
            "manifest_valid": manifest_valid,
            "one_step_status_exists": status_exists,
            "one_step_status_valid": status_valid,
            "one_step_manifest_consistent": one_step_payload_consistent,
            "delivery_path_exists": delivery_path_exists,
            "delivery_path_canonical": delivery_path_canonical,
            "delivery_package_consistent": delivery_record_consistent,
            "delivery_verification": json_safe(delivery_verification),
            "publish_state_valid": manifest_publish["valid"],
            "publish_state": json_safe(manifest_publish),
            "package_contract_verification": json_safe(package_verification),
            "reasons": integrity_reasons,
        },
        "token_policy": {
            "default_codex_context": "structured_qa_summary",
            "codex_reads_images_by_default": False,
            "image_review_required": image_review_required,
            "image_review_allowed_only_when": [
                "qa_failure",
                "low_confidence_semantics",
                "explicit_user_request",
            ],
            "codex_role": "rule_repair_or_user_requested_visual_refinement",
        },
        "codex_handoff": {
            "required": codex_required,
            "read_first": [
                path
                for path in (
                    str(status_path) if status_path.exists() else None,
                    str(manifest_path) if manifest_path.exists() else None,
                    str(run_output / "revision_brief.md")
                    if (run_output / "revision_brief.md").exists()
                    else None,
                )
                if path
            ],
            "image_review_required": image_review_required,
            "intervention_package": json_safe(intervention),
        },
    }
    return summary
