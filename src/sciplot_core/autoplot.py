from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from sciplot_core._utils import json_safe
from sciplot_core.delivery import verify_delivery_package
from sciplot_core.policy import DELIVERY_DIR
from sciplot_core.publish_state import build_publish_state
from sciplot_core.readiness import validated_envelope_evaluation_ready
from sciplot_core.study_model import verify_output_package_contract
from sciplot_core.workflow import run_one_step

AUTOPLOT_MODEL_KIND = "sciplot_autoplot_result"
AUTOPLOT_MODEL_VERSION = 2
_VALID_STATES = {"ready", "needs_human_confirmation", "needs_rule_repair"}


def _read_json_if_exists(path: Path) -> dict[str, Any]:
    if not path.exists() or not path.is_file():
        return {}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {}
    return payload if isinstance(payload, dict) else {}


def _truthy_path(value: object) -> Path | None:
    if not isinstance(value, str) or not value.strip():
        return None
    return Path(value).expanduser()


def _manifest_path(run_output: Path) -> Path:
    return run_output / "manifest.json"


def _one_step_status_path(run_output: Path) -> Path:
    return run_output / "one_step_status.json"


def _delivery_package(
    one_step: dict[str, Any], manifest: dict[str, Any]
) -> dict[str, Any]:
    for payload in (one_step.get("delivery_package"), manifest.get("delivery_package")):
        if isinstance(payload, dict):
            return payload
    return {}


def _figure_qa(one_step: dict[str, Any], manifest: dict[str, Any]) -> dict[str, Any]:
    figure_qa = (
        one_step.get("figure_qa_report")
        if isinstance(one_step.get("figure_qa_report"), dict)
        else {}
    )
    if figure_qa:
        return figure_qa
    manifest_one_step = (
        manifest.get("one_step") if isinstance(manifest.get("one_step"), dict) else {}
    )
    figure_qa = (
        manifest_one_step.get("figure_qa_report")
        if isinstance(manifest_one_step.get("figure_qa_report"), dict)
        else {}
    )
    return figure_qa


def _intervention_package(
    one_step: dict[str, Any], manifest: dict[str, Any]
) -> dict[str, Any]:
    intervention = (
        one_step.get("intervention_package")
        if isinstance(one_step.get("intervention_package"), dict)
        else {}
    )
    if intervention:
        return intervention
    manifest_one_step = (
        manifest.get("one_step") if isinstance(manifest.get("one_step"), dict) else {}
    )
    intervention = (
        manifest_one_step.get("intervention_package")
        if isinstance(manifest_one_step.get("intervention_package"), dict)
        else {}
    )
    return intervention


def _validated_envelope(
    one_step: dict[str, Any],
    manifest: dict[str, Any],
) -> dict[str, Any]:
    envelope = (
        one_step.get("validated_envelope")
        if isinstance(one_step.get("validated_envelope"), dict)
        else {}
    )
    if envelope:
        return envelope
    manifest_one_step = (
        manifest.get("one_step") if isinstance(manifest.get("one_step"), dict) else {}
    )
    envelope = manifest_one_step.get("validated_envelope")
    return envelope if isinstance(envelope, dict) else {}


def _route_package(
    one_step: dict[str, Any], manifest: dict[str, Any]
) -> dict[str, Any]:
    source = (
        one_step.get("source_package")
        if isinstance(one_step.get("source_package"), dict)
        else {}
    )
    mapping = (
        one_step.get("mapping_package")
        if isinstance(one_step.get("mapping_package"), dict)
        else {}
    )
    render_request = (
        one_step.get("render_request")
        if isinstance(one_step.get("render_request"), dict)
        else {}
    )
    semantic = (
        manifest.get("semantic") if isinstance(manifest.get("semantic"), dict) else {}
    )
    return {
        "mode": "one_step",
        "source_kind": source.get("source_kind") or "unknown",
        "semantic_family": mapping.get("semantic_family")
        or semantic.get("semantic_family")
        or "unknown",
        "rule_id": mapping.get("rule_id") or semantic.get("rule_id"),
        "confidence_band": source.get("confidence_band")
        or mapping.get("confidence_band")
        or "unknown",
        "recipe": render_request.get("recipe"),
        "template": render_request.get("template")
        or manifest.get("result", {}).get("template"),
        "figure_size": render_request.get("figure_size"),
        "exports": render_request.get("exports") or [],
    }


def _manifest_publish_integrity(manifest: dict[str, Any]) -> dict[str, Any]:
    manifest_one_step = (
        manifest.get("one_step") if isinstance(manifest.get("one_step"), dict) else {}
    )
    qa = manifest.get("qa") if isinstance(manifest.get("qa"), dict) else {}
    package_contract = (
        manifest.get("package_contract")
        if isinstance(manifest.get("package_contract"), dict)
        else {}
    )
    delivery_package = (
        manifest.get("delivery_package")
        if isinstance(manifest.get("delivery_package"), dict)
        else {}
    )
    expected = build_publish_state(
        qa=qa,
        package_contract=package_contract,
        delivery_package=delivery_package,
        prerequisite_state=manifest_one_step.get("state"),
    )
    recorded_gates = (
        manifest.get("publish_gates")
        if isinstance(manifest.get("publish_gates"), dict)
        else {}
    )
    recorded_state = str(manifest.get("state") or "").strip()
    recorded_ready = manifest.get("ready_to_use")
    checks = {
        "state_recorded": recorded_state in _VALID_STATES,
        "ready_to_use_recorded": type(recorded_ready) is bool,
        "state_matches_gates": recorded_state == expected["state"],
        "ready_to_use_matches_gates": (
            type(recorded_ready) is bool
            and recorded_ready is expected["ready_to_use"]
        ),
        "publish_gates_match": recorded_gates == expected["publish_gates"],
    }
    return {
        "valid": all(checks.values()),
        "checks": checks,
        "recorded_state": recorded_state,
        "recorded_ready_to_use": recorded_ready,
        "recorded_publish_gates": json_safe(recorded_gates),
        "expected": json_safe(expected),
        "package_contract_complete": package_contract.get("complete") is True,
    }


def build_autoplot_summary(one_step_result: dict[str, Any]) -> dict[str, Any]:
    run_output = _truthy_path(one_step_result.get("run_output")) or Path(".")
    project_dir = _truthy_path(one_step_result.get("project_dir")) or run_output.parent
    status_path = _one_step_status_path(run_output)
    manifest_path = _manifest_path(run_output)
    reported_one_step = (
        one_step_result.get("one_step")
        if isinstance(one_step_result.get("one_step"), dict)
        else {}
    )
    persisted_status = _read_json_if_exists(status_path)
    manifest = _read_json_if_exists(manifest_path)
    manifest_one_step = (
        manifest.get("one_step")
        if isinstance(manifest.get("one_step"), dict)
        else {}
    )

    persisted_state = str(persisted_status.get("state") or "").strip()
    manifest_one_step_state = str(manifest_one_step.get("state") or "").strip()
    manifest_publish = _manifest_publish_integrity(manifest)
    package_verification = verify_output_package_contract(
        manifest.get("package_contract"),
        output_dir=run_output,
        manifest=manifest,
    )
    manifest_state = str(manifest_publish["recorded_state"] or "").strip()
    status_valid = persisted_state in _VALID_STATES
    manifest_valid = bool(
        manifest.get("kind") == "sciplot_run"
        and manifest_one_step_state in _VALID_STATES
        and manifest_state in _VALID_STATES
    )
    one_step = (
        persisted_status
        if status_valid
        else reported_one_step or manifest_one_step
    )

    reported_state = str(one_step_result.get("status") or "").strip()
    reported_payload_state = str(reported_one_step.get("state") or "").strip()
    preparation_state_claims = [
        state
        for state in (
            reported_payload_state,
            persisted_state,
            manifest_one_step_state,
        )
        if state
    ]
    publish_state_claims = [
        state for state in (reported_state, manifest_state) if state
    ]
    preparation_state_consistent = len(set(preparation_state_claims)) <= 1
    publish_state_consistent = len(set(publish_state_claims)) <= 1
    state_consistent = preparation_state_consistent and publish_state_consistent
    state = manifest_state or reported_state or persisted_state or reported_payload_state
    if state not in _VALID_STATES:
        state = "needs_rule_repair"
    if not state_consistent or manifest_publish["valid"] is not True:
        state = "needs_rule_repair"
    delivery = _delivery_package(one_step, manifest)
    figure_qa = _figure_qa(one_step, manifest)
    intervention = _intervention_package(one_step, manifest)
    validated_envelope = _validated_envelope(one_step, manifest)
    render_request = (
        one_step.get("render_request")
        if isinstance(one_step.get("render_request"), dict)
        else {}
    )
    delivery_path = _truthy_path(delivery.get("path"))
    manifest_exists = manifest_path.is_file()
    status_exists = status_path.is_file()
    delivery_path_exists = bool(
        delivery_path is not None and delivery_path.is_dir()
    )
    expected_delivery_path = (run_output / DELIVERY_DIR).resolve()
    delivery_path_canonical = bool(
        delivery_path is not None
        and delivery_path_exists
        and delivery_path.resolve() == expected_delivery_path
    )
    delivery_recorded_complete = delivery.get("complete") is True
    delivery_verification = verify_delivery_package(
        delivery,
        expected_root=expected_delivery_path,
    )
    delivery_complete = bool(
        delivery_recorded_complete
        and delivery_path_exists
        and delivery_verification["passed"] is True
    )
    manifest_delivery = (
        manifest.get("delivery_package")
        if isinstance(manifest.get("delivery_package"), dict)
        else {}
    )
    delivery_record_consistent = bool(delivery and delivery == manifest_delivery)
    one_step_payload_consistent = bool(
        status_valid and manifest_valid and persisted_status == manifest_one_step
    )
    image_review_required = bool(figure_qa.get("image_review_required"))
    envelope_ready = validated_envelope_evaluation_ready(
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
    )
    codex_required = bool(intervention.get("required")) or (
        state == "needs_rule_repair"
        or not envelope_ready
        or not qa_ready
        or not artifact_integrity_ready
    )

    summary = {
        "kind": AUTOPLOT_MODEL_KIND,
        "version": AUTOPLOT_MODEL_VERSION,
        "state": state,
        "ready_to_use": (
            state == "ready"
            and delivery_complete
            and envelope_ready
            and qa_ready
            and state_consistent
            and artifact_integrity_ready
            and manifest_publish["expected"]["ready_to_use"] is True
        ),
        "project_dir": str(project_dir),
        "run_output": str(run_output),
        "request_path": one_step_result.get("request_path"),
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
        "route": _route_package(one_step, manifest),
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


def run_autoplot(
    input_path: Path,
    *,
    output_root: Path,
    project_name: str | None = None,
) -> dict[str, Any]:
    result = run_one_step(
        input_path, output_root=output_root, project_name=project_name
    )
    summary = build_autoplot_summary(result)
    run_output = Path(str(summary["run_output"]))
    run_output.mkdir(parents=True, exist_ok=True)
    summary_path = run_output / "autoplot_summary.json"
    summary["summary_path"] = str(summary_path)
    summary_path.write_text(
        json.dumps(json_safe(summary), indent=2, ensure_ascii=False), encoding="utf-8"
    )
    return summary


__all__ = [
    "AUTOPLOT_MODEL_KIND",
    "AUTOPLOT_MODEL_VERSION",
    "build_autoplot_summary",
    "run_autoplot",
]
