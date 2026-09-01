"""Cross-scenario identity checks for the R0 automation baseline."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from sciplot_core.automation_baseline import canonical_json_bytes
from sciplot_core.automation_baseline_schema import (
    BASELINE_PRIMARY_FIGURE_ID,
    BASELINE_RULE_ID,
    BASELINE_SELECTION_POLICY,
    BASELINE_TEMPLATE,
    BASELINE_VISUAL_PROVIDER_ID,
    BASELINE_VISUAL_SETTING_SUFFIX,
    BASELINE_VISUAL_WIDGET_TYPE,
    EVIDENCE_IDENTITY_FIELDS,
    SCENARIO_EVIDENCE_FIELDS,
    SCENARIO_REASON_CODES,
    TEXT_EVIDENCE_FIELDS,
)
from sciplot_core.automation_baseline_validation_utils import (
    require_sha256,
    validate_fixed_mapping,
)
from sciplot_core.foundation.json_hashing import canonical_json_sha256


def validate_scenario_evidence(
    payload: object, *, scenario_id: str, fixture_sha256: str
) -> None:
    evidence = validate_fixed_mapping(
        payload, EVIDENCE_IDENTITY_FIELDS, "evidence identity"
    )
    fields = SCENARIO_EVIDENCE_FIELDS[scenario_id]
    stable = validate_fixed_mapping(
        evidence["stable"], fields["stable"], "stable identity"
    )
    sample = validate_fixed_mapping(
        evidence["sample"], fields["sample"], "sample identity"
    )
    for field, value in {**stable, **sample}.items():
        if field.endswith("sha256"):
            require_sha256(value, label=field)
        if field in TEXT_EVIDENCE_FIELDS and (
            not isinstance(value, str) or not value
        ):
            raise ValueError("Automation baseline evidence identifiers must be text.")
    if "fixture_sha256" in stable and stable["fixture_sha256"] != fixture_sha256:
        raise ValueError("Automation baseline scenario fixture identity is inconsistent.")
    if scenario_id == "ready_zero_ai":
        selected = stable["selected_figure_ids"]
        if (
            not isinstance(selected, list)
            or not selected
            or any(not isinstance(value, str) or not value for value in selected)
            or len(set(selected)) != len(selected)
        ):
            raise ValueError("Automation baseline ready plan identity is invalid.")
        expected_source_sha256 = canonical_json_sha256(
            {"kind": "file", "content_sha256": fixture_sha256}, allow_nan=False
        )
        if stable["source_sha256"] != expected_source_sha256:
            raise ValueError("Automation baseline ready source identity is invalid.")
        if stable["plan_id"] != f"rfp_{stable['plan_sha256'][:16]}":
            raise ValueError("Automation baseline ready plan identity is invalid.")
        if (
            stable["rule_id"],
            stable["template"],
            stable["selection_policy"],
            stable["primary_figure_id"],
            stable["selected_figure_ids"],
        ) != (
            BASELINE_RULE_ID,
            BASELINE_TEMPLATE,
            BASELINE_SELECTION_POLICY,
            BASELINE_PRIMARY_FIGURE_ID,
            [BASELINE_PRIMARY_FIGURE_ID],
        ):
            raise ValueError("Automation baseline ready benchmark identity is invalid.")
    elif scenario_id == "scientific_confirmation":
        if stable["controlled_confidence"] != 75.0 or (
            stable["question_payload_present"] is not False
        ):
            raise ValueError("Automation baseline confirmation identity is invalid.")
    elif scenario_id == "rule_repair":
        if (
            stable["invocation_reason_codes"]
            != list(SCENARIO_REASON_CODES[scenario_id])
            or type(sample["filesystem_write_opens"]) is not int
            or sample["filesystem_write_opens"] != 0
            or stable["certified_contract_sha256"]
            == stable["current_contract_sha256"]
            or stable["certified_semantic_contract_sha256"]
            == stable["current_semantic_contract_sha256"]
        ):
            raise ValueError("Automation baseline repair identity is invalid.")
    else:
        if (
            stable["provider_id"],
            stable["selected_widget_type"],
            stable["setting_suffix"],
        ) != (
            BASELINE_VISUAL_PROVIDER_ID,
            BASELINE_VISUAL_WIDGET_TYPE,
            BASELINE_VISUAL_SETTING_SUFFIX,
        ):
            raise ValueError("Automation baseline visual benchmark identity is invalid.")
        if stable["history_statuses"] != [
            "submitted",
            "proposal_ready",
            "apply_started",
            "applied",
        ] or type(sample["base_revision"]) is not int or sample["base_revision"] < 0:
            raise ValueError("Automation baseline visual history identity is invalid.")
        if sample["before_render_sha256"] != sample["undo_render_sha256"] or (
            sample["before_render_sha256"] == sample["applied_render_sha256"]
        ):
            raise ValueError("Automation baseline visual render identity is invalid.")


def validate_cross_scenario_identity(
    scenarios: list[Mapping[str, Any]], *, session: Mapping[str, Any]
) -> None:
    ready, confirmation, repair, visual = scenarios
    ready_stable = ready["samples"][0]["evidence_identity"]["stable"]
    confirmation_stable = confirmation["samples"][0]["evidence_identity"]["stable"]
    repair_stable = repair["samples"][0]["evidence_identity"]["stable"]
    if not (
        ready_stable["rule_id"]
        == confirmation_stable["rule_id"]
        == repair_stable["rule_id"]
        and ready_stable["rule_contract_sha256"]
        == confirmation_stable["current_contract_sha256"]
        == repair_stable["current_contract_sha256"]
        and ready_stable["rule_semantic_contract_sha256"]
        == confirmation_stable["current_semantic_contract_sha256"]
        == repair_stable["current_semantic_contract_sha256"]
    ):
        raise ValueError("Automation baseline scientific owner identity is inconsistent.")
    for ready_sample, visual_sample in zip(
        ready["samples"], visual["samples"], strict=True
    ):
        ready_rule = ready_sample["payload_components"]["rule_show"]
        if (
            ready_rule["bytes"] != session["selected_rule_payload_bytes"]
            or ready_rule["sha256"] != session["selected_rule_payload_sha256"]
        ):
            raise ValueError("Automation baseline ready rule payload size is inconsistent.")
        visual_context = visual_sample["payload_components"]["context"]
        if (
            visual_context["bytes"]
            != visual_sample["metrics"]["provider_context_bytes"]
            or visual_context["sha256"]
            != visual_sample["evidence_identity"]["sample"]["context_sha256"]
        ):
            raise ValueError("Automation baseline visual context size is inconsistent.")
        base_revision = visual_sample["evidence_identity"]["sample"]["base_revision"]
        revision_component = visual_sample["payload_components"]["base_revision"]
        if revision_component != {
            "bytes": canonical_json_bytes(base_revision),
            "sha256": canonical_json_sha256(base_revision, allow_nan=False),
        }:
            raise ValueError(
                "Automation baseline visual revision payload size is inconsistent."
            )
        if visual_sample["evidence_identity"]["sample"]["request_sha256"] != (
            visual_sample["evidence_identity"]["sample"]["provider_payload_sha256"]
        ):
            raise ValueError(
                "Automation baseline visual provider request identity is inconsistent."
            )
        if ready_sample["evidence_identity"]["sample"]["delivered_vsz_sha256"] != (
            visual_sample["evidence_identity"]["sample"]["source_document_sha256"]
        ):
            raise ValueError("Automation baseline visual source identity is inconsistent.")
        if visual_sample["evidence_identity"]["stable"]["upstream_plan_sha256"] != (
            ready_sample["evidence_identity"]["stable"]["plan_sha256"]
        ):
            raise ValueError("Automation baseline visual plan identity is inconsistent.")


__all__ = ["validate_cross_scenario_identity", "validate_scenario_evidence"]
