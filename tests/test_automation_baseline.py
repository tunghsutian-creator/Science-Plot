from __future__ import annotations

import builtins
import io
import os
import subprocess
import sys
from copy import deepcopy
from pathlib import Path
from typing import Any

import pytest

from sciplot_core.automation_baseline import (
    AUTOMATION_BASELINE_KIND,
    AUTOMATION_BASELINE_SCENARIOS,
    AUTOMATION_BASELINE_VERSION,
    canonical_json_bytes,
    figure_plan_evidence_identity,
    figure_plan_fact_identity,
    metric_distribution,
    payload_measurement_projection,
)
from sciplot_core.automation_baseline_probe import (
    _confirmation_sample,
    _copy_exact_current_document,
    _external_model_call_guard,
    _markdown_report,
    _repair_sample,
    _ready_write_guard,
    _ready_sample,
    _scenario_record,
    _source_parent_snapshot,
    _source_reads,
    _visual_sample,
    run_automation_baseline_probe,
)
from sciplot_core.automation_baseline_schema import (
    BASELINE_LIMITATIONS,
    SCENARIO_CHECKS,
    SCENARIO_DESCRIPTIONS,
    SCENARIO_REASON_CODES,
)
from sciplot_core.automation_baseline_validation import validate_baseline_report
from sciplot_core.cli.parsers import build_parser
from sciplot_core.foundation.file_hashing import file_sha256
from sciplot_core.foundation.json_hashing import canonical_json_sha256
from sciplot_core.readiness.registry_io import load_validated_envelope_registry
from sciplot_core.veusz_runtime import veusz_worker_environment


_FIXTURE_SHA256 = "a" * 64
_RULE_CONTRACT_SHA256 = "b" * 64
_SEMANTIC_CONTRACT_SHA256 = "c" * 64
_PLAN_SHA256 = "d" * 64
_DOCTOR_PAYLOAD_SHA256 = "2" * 64
_CATALOG_PAYLOAD_SHA256 = "3" * 64
_READY_RULE_PAYLOAD_SHA256 = "5" * 64
_SOURCE_TREE_SHA256 = canonical_json_sha256(
    {"kind": "file", "content_sha256": _FIXTURE_SHA256},
    allow_nan=False,
)


def _metrics(scenario_id: str) -> dict[str, int | float | None]:
    ready = scenario_id == "ready_zero_ai"
    visual = scenario_id == "selected_object_visual_edit"
    metrics: dict[str, int | float | None] = {
        "wall_time_ms": 1.0,
        "peak_python_memory_bytes": 2,
        "raw_source_read_opens": 1 if ready else 0,
        "full_decision_payload_bytes": 1,
        "provider_payload_bytes": 100 if visual else 0,
        "provider_context_bytes": 40 if visual else 0,
        "image_bytes": 20 if visual else 0,
        "provider_requests": 1 if visual else 0,
        "model_calls": 0,
        "submit_to_proposal_ms": 5.0 if visual else None,
        "proposal_to_applied_ms": 2.0 if visual else None,
    }
    return metrics


def _sample_hash(index: int) -> str:
    return format(index % 16, "x") * 64


def _component_sha256(scenario_id: str, component: str) -> str:
    if scenario_id == "ready_zero_ai" and component == "rule_show":
        return _READY_RULE_PAYLOAD_SHA256
    return canonical_json_sha256(
        {"scenario_id": scenario_id, "component": component},
        allow_nan=False,
    )


def _evidence_identity(index: int, scenario_id: str) -> dict[str, Any]:
    if scenario_id == "ready_zero_ai":
        return {
            "stable": {
                "rule_id": "performance_comparison",
                "rule_contract_sha256": _RULE_CONTRACT_SHA256,
                "rule_semantic_contract_sha256": _SEMANTIC_CONTRACT_SHA256,
                "plan_id": f"rfp_{_PLAN_SHA256[:16]}",
                "plan_sha256": _PLAN_SHA256,
                "selection_policy": "explicit_supported_template",
                "primary_figure_id": "performance_scatter",
                "template": "scatter",
                "source_sha256": _SOURCE_TREE_SHA256,
                "selected_figure_ids": ["performance_scatter"],
                "tasks_sha256": "6" * 64,
                "fixture_sha256": _FIXTURE_SHA256,
            },
            "sample": {
                "request_sha256": "f" * 64,
                "delivered_vsz_sha256": _sample_hash(index),
            },
        }
    if scenario_id == "scientific_confirmation":
        return {
            "stable": {
                "rule_id": "performance_comparison",
                "current_contract_sha256": _RULE_CONTRACT_SHA256,
                "current_semantic_contract_sha256": _SEMANTIC_CONTRACT_SHA256,
                "fixture_sha256": _FIXTURE_SHA256,
                "controlled_confidence": 75.0,
                "question_payload_present": False,
            },
            "sample": {},
        }
    if scenario_id == "rule_repair":
        return {
            "stable": {
                "rule_id": "performance_comparison",
                "current_contract_sha256": _RULE_CONTRACT_SHA256,
                "current_semantic_contract_sha256": _SEMANTIC_CONTRACT_SHA256,
                "certified_contract_sha256": "0" * 64,
                "certified_semantic_contract_sha256": "1" * 64,
                "invocation_reason_codes": list(
                    SCENARIO_REASON_CODES["rule_repair"]
                ),
            },
            "sample": {"filesystem_write_opens": 0},
        }
    return {
        "stable": {
            "provider_id": "studio_assistant_probe",
            "selected_widget_type": "axis",
            "setting_suffix": "/label",
            "history_statuses": [
                "submitted",
                "proposal_ready",
                "apply_started",
                "applied",
            ],
            "upstream_plan_sha256": _PLAN_SHA256,
        },
        "sample": {
            "source_document_sha256": _sample_hash(index),
            "request_sha256": "9" * 64,
            "context_sha256": _component_sha256(
                "selected_object_visual_edit", "context"
            ),
            "provider_payload_sha256": "9" * 64,
            "base_revision": 1,
            "before_render_sha256": "7" * 64,
            "applied_render_sha256": "8" * 64,
            "undo_render_sha256": "7" * 64,
        },
    }


def _sample(index: int, scenario_id: str, state: str) -> dict[str, Any]:
    selected_object = scenario_id == "selected_object_visual_edit"
    next_action = {
        "ready_zero_ai": "handoff_ready",
        "scientific_confirmation": "ask_human",
        "rule_repair": "handoff_rule_repair",
        "selected_object_visual_edit": "handoff_ready",
    }[scenario_id]
    metrics = _metrics(scenario_id)
    payload_components = {
        key: {
            "bytes": 1,
            "sha256": _component_sha256(scenario_id, key),
        }
        for key in {
            "ready_zero_ai": {
                "rule_show",
                "plan_preview",
                "autoplot_result",
            },
            "scientific_confirmation": {
                "semantic",
                "source_package",
                "mapping_package",
                "render_request",
                "evaluation",
            },
            "rule_repair": {"rule_show"},
            "selected_object_visual_edit": {
                "intent",
                "base_revision",
                "context",
                "visual_preview_metadata",
                "provider_response",
                "apply_result",
                "transaction_history",
                "undo_evidence",
            },
        }[scenario_id]
    }
    if selected_object:
        payload_components["context"]["bytes"] = 40
        payload_components["base_revision"] = {
            "bytes": canonical_json_bytes(1),
            "sha256": canonical_json_sha256(1, allow_nan=False),
        }
    metrics["full_decision_payload_bytes"] = sum(
        component["bytes"] for component in payload_components.values()
    )
    return {
        "sample_index": index,
        "status": "passed",
        "observed_state": state,
        "next_action": next_action,
        "provider_mode": "offline_fixture" if selected_object else "none",
        "provider_outcome": "completed" if selected_object else "not_used",
        "metrics": metrics,
        "payload_components": payload_components,
        "token_usage": {
            "input_tokens": None,
            "output_tokens": None,
            "basis": "offline_replay_no_token_usage",
        },
        "evidence_identity": _evidence_identity(index, scenario_id),
        "reason_codes": list(SCENARIO_REASON_CODES[scenario_id]),
        "checks": {key: True for key in SCENARIO_CHECKS[scenario_id]},
    }


def _report() -> dict[str, Any]:
    states = (
        "ready",
        "needs_human_confirmation",
        "needs_rule_repair",
        "ready",
    )
    scenarios = []
    for scenario_id, state in zip(
        AUTOMATION_BASELINE_SCENARIOS,
        states,
        strict=True,
    ):
        sample = _sample(1, scenario_id, state)
        scenarios.append(
            {
                "scenario_id": scenario_id,
                "description": SCENARIO_DESCRIPTIONS[scenario_id],
                "expected_state": state,
                "status": "passed",
                "samples": [sample],
                "metrics": metric_distribution([sample["metrics"]]),
                "stable_evidence": {
                    "identical_across_samples": True,
                    "first": sample["evidence_identity"]["stable"],
                },
            }
        )
    return {
        "kind": AUTOMATION_BASELINE_KIND,
        "version": AUTOMATION_BASELINE_VERSION,
        "generated_at": "2026-08-31T00:00:00+00:00",
        "status": "passed",
        "platform": {
            "python": "3.14.7",
            "system": "Darwin",
            "release": "test",
            "machine": "arm64",
        },
        "repetitions": 1,
        "session_payloads": {
            "doctor_status": "ready",
            "doctor_payload_bytes": 1,
            "doctor_payload_sha256": _DOCTOR_PAYLOAD_SHA256,
            "ready_rule_count": 24,
            "fixture_sha256": _FIXTURE_SHA256,
            "fixture_sha256_after": _FIXTURE_SHA256,
            "fixture_integrity_reads_outside_measurements": 3,
            "rule_catalog_payload_bytes": 2,
            "rule_catalog_payload_sha256": _CATALOG_PAYLOAD_SHA256,
            "selected_rule_payload_bytes": 1,
            "selected_rule_payload_sha256": _READY_RULE_PAYLOAD_SHA256,
        },
        "scenario_order": list(AUTOMATION_BASELINE_SCENARIOS),
        "scenarios": scenarios,
        "summary": {
            "scenario_count": 4,
            "passed_count": 4,
            "model_calls": 0,
            "provider_requests": 1,
            "raw_dataset_arrays_sent": False,
            "user_delivery_created": False,
        },
        "artifacts": {
            "root": (
                ".tmp_verify/r0_automation_baseline/automation_r0_0123456789abcdef"
            ),
            "json": (
                ".tmp_verify/r0_automation_baseline/automation_r0_0123456789abcdef/"
                "automation_r0_baseline.json"
            ),
            "markdown": (
                ".tmp_verify/r0_automation_baseline/automation_r0_0123456789abcdef/"
                "automation_r0_baseline.md"
            ),
        },
        "limitations": list(BASELINE_LIMITATIONS),
    }


def _brief_feasibility_payloads() -> dict[str, dict[str, Any]]:
    digest = "a" * 64
    base: dict[str, Any] = {
        "kind": "sciplot_automation_brief",
        "version": 1,
        "phase": "executed",
        "subject": {"kind": "source", "opaque_id": "benchmark-subject"},
        "decision": {
            "automation_state": "ready",
            "next_action": "handoff_ready",
            "decision_code": "ready_handoff",
            "owner_reason_refs": [],
            "question": None,
            "maintenance_owner": None,
        },
        "candidates": [],
        "invocation": {
            "preview_operation": "plan",
            "execute_operation": "autoplot",
            "rule_id": "performance_comparison",
            "selected_template": "scatter",
            "required_argument_names": ["source"],
        },
        "identities": {
            "rule_contract_sha256": digest,
            "request_sha256": digest,
            "figure_plan_sha256": digest,
            "document_revision": None,
            "render_sha256": None,
        },
        "provider": {
            "mode": "none",
            "outcome": "not_used",
            "call_budget": 0,
            "calls_used": 0,
        },
        "completion": {
            "ready_to_use": True,
            "qa_status": "passed",
            "delivery_complete": True,
            "artifact_count": 4,
        },
    }
    confirmation = deepcopy(base)
    confirmation["phase"] = "preflight"
    confirmation["decision"].update(
        automation_state="needs_human_confirmation",
        next_action="ask_human",
        decision_code="human_confirmation_required",
        owner_reason_refs=[
            {
                "owner": "validated_envelope",
                "code": "mapping_requires_confirmation",
                "detail_id": None,
            },
            {
                "owner": "validated_envelope",
                "code": "semantic_match_requires_confirmation",
                "detail_id": None,
            },
        ],
        question="Which supported mapping matches this source?",
    )
    confirmation["invocation"].update(
        preview_operation=None,
        execute_operation=None,
        rule_id=None,
        selected_template=None,
        required_argument_names=[],
    )
    confirmation["identities"].update(
        request_sha256=None,
        figure_plan_sha256=None,
    )
    confirmation["completion"].update(
        ready_to_use=False,
        qa_status=None,
        delivery_complete=False,
        artifact_count=0,
    )
    repair = deepcopy(base)
    repair["phase"] = "preflight"
    repair["decision"].update(
        automation_state="needs_rule_repair",
        next_action="handoff_rule_repair",
        decision_code="rule_repair_required",
        owner_reason_refs=[
            {
                "owner": "rule_certification",
                "code": "certified_rule_contract_sha256_mismatch",
                "detail_id": "performance_comparison",
            },
            {
                "owner": "rule_certification",
                "code": "certified_rule_semantic_contract_sha256_mismatch",
                "detail_id": "performance_comparison",
            },
        ],
        maintenance_owner="rule_certification",
    )
    repair["invocation"].update(
        preview_operation=None,
        execute_operation=None,
        selected_template=None,
        required_argument_names=[],
    )
    repair["identities"].update(
        request_sha256=None,
        figure_plan_sha256=None,
    )
    repair["completion"].update(
        ready_to_use=False,
        qa_status=None,
        delivery_complete=False,
        artifact_count=0,
    )
    visual = deepcopy(base)
    visual["phase"] = "selected_object"
    visual["subject"] = {
        "kind": "selected_object",
        "opaque_id": "benchmark-object",
    }
    visual["invocation"].update(
        preview_operation=None,
        execute_operation=None,
        rule_id=None,
        selected_template=None,
        required_argument_names=[],
    )
    visual["identities"].update(
        document_revision=514,
        render_sha256=digest,
    )
    visual["provider"].update(
        mode="offline_fixture",
        outcome="completed",
        call_budget=1,
        calls_used=1,
    )
    visual["completion"].update(
        artifact_count=1,
    )
    return {
        "ready_zero_ai": base,
        "scientific_confirmation": confirmation,
        "rule_repair": repair,
        "selected_object_visual_edit": visual,
    }


def test_canonical_json_bytes_counts_compact_utf8_and_rejects_nan() -> None:
    assert canonical_json_bytes({"é": 1}) == len('{"é":1}'.encode())
    with pytest.raises(ValueError, match="Out of range float"):
        canonical_json_bytes({"value": float("nan")})


def test_payload_measurement_projection_is_independent_of_local_path_length() -> None:
    short = payload_measurement_projection(
        {
            "delivery": "/tmp/r0/run",
            "nested": [".tmp_verify/a"],
            "setting_path": "/page/x/label",
        }
    )
    long = payload_measurement_projection(
        {
            "delivery": "/Users/private/a/much/longer/local/run",
            "nested": [".tmp_verify/a/much/longer/run"],
            "setting_path": "/page/x/label",
        }
    )

    assert short == long == {
        "delivery": "<absolute-path>",
        "nested": ["<development-evidence-path>"],
        "setting_path": "/page/x/label",
    }


def test_frozen_brief_shape_has_reachable_per_scenario_size_gates() -> None:
    denominators = {
        "ready_zero_ai": 15_700,
        "scientific_confirmation": 4_877,
        "rule_repair": 2_677,
        "selected_object_visual_edit": 15_951,
    }
    payloads = _brief_feasibility_payloads()
    assert payloads["ready_zero_ai"]["phase"] == "executed"
    assert payloads["ready_zero_ai"]["decision"] == {
        "automation_state": "ready",
        "next_action": "handoff_ready",
        "decision_code": "ready_handoff",
        "owner_reason_refs": [],
        "question": None,
        "maintenance_owner": None,
    }
    assert payloads["selected_object_visual_edit"]["decision"]["next_action"] == (
        "handoff_ready"
    )
    assert payloads["selected_object_visual_edit"]["provider"]["outcome"] == (
        "completed"
    )
    assert payloads["selected_object_visual_edit"]["completion"]["ready_to_use"]
    sizes = {
        scenario_id: canonical_json_bytes(payload)
        for scenario_id, payload in payloads.items()
    }

    assert sizes == {
        "ready_zero_ai": 985,
        "scientific_confirmation": 1_070,
        "rule_repair": 1_122,
        "selected_object_visual_edit": 1_032,
    }
    assert all(size <= 8 * 1024 for size in sizes.values())
    for scenario_id in (
        "ready_zero_ai",
        "scientific_confirmation",
        "selected_object_visual_edit",
    ):
        assert sizes[scenario_id] / denominators[scenario_id] <= 0.30
    assert sizes["rule_repair"] <= 1_280
    assert sizes["rule_repair"] / denominators["rule_repair"] <= 0.45


def test_figure_plan_fact_identity_ignores_outcomes_but_binds_tasks() -> None:
    payload = {
        "plan_id": "rfp_123",
        "plan_sha256": "a" * 64,
        "rule_id": "performance_comparison",
        "selection_policy": "explicit_template",
        "primary_figure_id": "performance_scatter",
        "source_sha256": "b" * 64,
        "selected_figure_ids": ["performance_scatter"],
        "tasks": [{"figure_id": "performance_scatter", "order": 1}],
        "outcomes": [{"status": "completed"}],
    }
    completed = deepcopy(payload)
    completed["outcomes"] = [{"status": "failed"}]

    assert figure_plan_fact_identity(payload) == figure_plan_fact_identity(completed)
    completed["tasks"][0]["order"] = 2
    assert figure_plan_fact_identity(payload) != figure_plan_fact_identity(completed)


def test_figure_plan_persisted_identity_hashes_source_derived_task_details() -> None:
    payload = {
        "plan_id": "rfp_123",
        "plan_sha256": "a" * 64,
        "rule_id": "performance_comparison",
        "selection_policy": "explicit_template",
        "primary_figure_id": "performance_scatter",
        "source_sha256": "b" * 64,
        "selected_figure_ids": ["performance_scatter"],
        "tasks": [{"sample_order": ["PRIVATE_SAMPLE_LABEL"]}],
    }

    evidence = figure_plan_evidence_identity(payload)

    assert "tasks" not in evidence
    assert "PRIVATE_SAMPLE_LABEL" not in repr(evidence)
    assert len(evidence["tasks_sha256"]) == 64


def test_baseline_report_rejects_unknown_nested_fields_and_fake_tokens() -> None:
    report = _report()
    validate_baseline_report(report)

    unknown = deepcopy(report)
    unknown["scenarios"][0]["samples"][0]["metrics"]["mystery"] = 1
    with pytest.raises(ValueError, match=r"unknown=\['mystery'\]"):
        validate_baseline_report(unknown)

    fake_tokens = deepcopy(report)
    fake_tokens["scenarios"][0]["samples"][0]["token_usage"]["input_tokens"] = 1.5
    with pytest.raises(ValueError, match="offline token usage"):
        validate_baseline_report(fake_tokens)

    mutated_source = deepcopy(report)
    mutated_source["session_payloads"]["fixture_sha256_after"] = "b" * 64
    with pytest.raises(ValueError, match="fixture bytes changed"):
        validate_baseline_report(mutated_source)

    wrong_integrity_count = deepcopy(report)
    wrong_integrity_count["session_payloads"][
        "fixture_integrity_reads_outside_measurements"
    ] = 1
    with pytest.raises(ValueError, match="integrity read count is inconsistent"):
        validate_baseline_report(wrong_integrity_count)

    incomplete_checks = deepcopy(report)
    incomplete_checks["scenarios"][0]["samples"][0]["checks"] = {
        "anything": True
    }
    with pytest.raises(ValueError, match="scenario checks fields are invalid"):
        validate_baseline_report(incomplete_checks)

    incomplete_visual_metrics = deepcopy(report)
    incomplete_visual_metrics["scenarios"][3]["samples"][0]["metrics"][
        "image_bytes"
    ] = 0
    with pytest.raises(ValueError, match="visual transport metrics are incomplete"):
        validate_baseline_report(incomplete_visual_metrics)

    missing_identity = deepcopy(report)
    missing_identity["scenarios"][0]["samples"][0]["evidence_identity"] = {
        "stable": {},
        "sample": {},
    }
    with pytest.raises(ValueError, match="stable identity fields are invalid"):
        validate_baseline_report(missing_identity)

    invalid_session = deepcopy(report)
    invalid_session["session_payloads"]["doctor_status"] = "broken"
    with pytest.raises(ValueError, match="doctor status=ready"):
        validate_baseline_report(invalid_session)

    shrunken_ready_inventory = deepcopy(report)
    shrunken_ready_inventory["session_payloads"]["ready_rule_count"] = 23
    with pytest.raises(ValueError, match="ready-rule inventory has regressed"):
        validate_baseline_report(shrunken_ready_inventory)

    contradictory_repair = deepcopy(report)
    repair_identity = contradictory_repair["scenarios"][2]["samples"][0][
        "evidence_identity"
    ]["stable"]
    repair_identity["certified_contract_sha256"] = repair_identity[
        "current_contract_sha256"
    ]
    repair_identity["certified_semantic_contract_sha256"] = repair_identity[
        "current_semantic_contract_sha256"
    ]
    with pytest.raises(ValueError, match="repair identity is invalid"):
        validate_baseline_report(contradictory_repair)

    detached_ready_source = deepcopy(report)
    detached_ready_source["scenarios"][0]["samples"][0]["evidence_identity"][
        "stable"
    ]["source_sha256"] = "0" * 64
    with pytest.raises(ValueError, match="ready source identity is invalid"):
        validate_baseline_report(detached_ready_source)

    detached_plan_id = deepcopy(report)
    detached_plan_id["scenarios"][0]["samples"][0]["evidence_identity"][
        "stable"
    ]["plan_id"] = "rfp_0000000000000000"
    with pytest.raises(ValueError, match="ready plan identity is invalid"):
        validate_baseline_report(detached_plan_id)

    absolute_artifact = deepcopy(report)
    absolute_artifact["artifacts"]["root"] = "/Users/name/private/r0"
    with pytest.raises(ValueError, match="repository-relative"):
        validate_baseline_report(absolute_artifact)

    impossible_visual_payload = deepcopy(report)
    impossible_visual_payload["scenarios"][3]["samples"][0]["metrics"][
        "provider_payload_bytes"
    ] = 1
    with pytest.raises(ValueError, match="visual payload size is inconsistent"):
        validate_baseline_report(impossible_visual_payload)

    detached_context_size = deepcopy(report)
    visual_sample = detached_context_size["scenarios"][3]["samples"][0]
    visual_sample["payload_components"]["context"]["bytes"] -= 1
    visual_sample["metrics"]["full_decision_payload_bytes"] -= 1
    detached_context_size["scenarios"][3]["metrics"] = metric_distribution(
        [visual_sample["metrics"]]
    )
    with pytest.raises(ValueError, match="visual context size is inconsistent"):
        validate_baseline_report(detached_context_size)

    detached_revision_size = deepcopy(report)
    detached_revision_size["scenarios"][3]["samples"][0]["evidence_identity"][
        "sample"
    ]["base_revision"] = 514
    with pytest.raises(ValueError, match="revision payload size is inconsistent"):
        validate_baseline_report(detached_revision_size)

    detached_request_identity = deepcopy(report)
    detached_request_identity["scenarios"][3]["samples"][0][
        "evidence_identity"
    ]["sample"]["provider_payload_sha256"] = "8" * 64
    with pytest.raises(ValueError, match="provider request identity is inconsistent"):
        validate_baseline_report(detached_request_identity)

    changed_benchmark = deepcopy(report)
    for scenario in changed_benchmark["scenarios"][:3]:
        scenario["samples"][0]["evidence_identity"]["stable"]["rule_id"] = (
            "other_rule"
        )
    with pytest.raises(ValueError, match="ready benchmark identity is invalid"):
        validate_baseline_report(changed_benchmark)

    leaking_description = deepcopy(report)
    leaking_description["scenarios"][0]["description"] = (
        "/Users/private/material_performance_long.csv"
    )
    with pytest.raises(ValueError, match="scenario description is invalid"):
        validate_baseline_report(leaking_description)

    leaking_limitation = deepcopy(report)
    leaking_limitation["limitations"][0] = (
        "/Users/private/material_performance_long.csv"
    )
    with pytest.raises(ValueError, match="limitations are invalid"):
        validate_baseline_report(leaking_limitation)

    leaking_platform = deepcopy(report)
    leaking_platform["platform"]["release"] = "/Users/private/source.csv"
    with pytest.raises(ValueError, match="platform values"):
        validate_baseline_report(leaking_platform)

    naive_generated_at = deepcopy(report)
    naive_generated_at["generated_at"] = "2026-08-31T00:00:00"
    with pytest.raises(ValueError, match="must include a timezone offset"):
        validate_baseline_report(naive_generated_at)

    leaking_locator = deepcopy(report)
    leaking_locator["artifacts"] = {
        "root": (
            ".tmp_verify/r0_automation_baseline/automation_r0_private_sample"
        ),
        "json": (
            ".tmp_verify/r0_automation_baseline/automation_r0_private_sample/"
            "automation_r0_baseline.json"
        ),
        "markdown": (
            ".tmp_verify/r0_automation_baseline/automation_r0_private_sample/"
            "automation_r0_baseline.md"
        ),
    }
    with pytest.raises(ValueError, match="artifact locators are invalid"):
        validate_baseline_report(leaking_locator)

    impossible_visual_envelope = deepcopy(report)
    impossible_sample = impossible_visual_envelope["scenarios"][3]["samples"][0]
    impossible_sample["metrics"]["provider_payload_bytes"] = 68
    with pytest.raises(ValueError, match="visual payload size is inconsistent"):
        validate_baseline_report(impossible_visual_envelope)


def test_failed_visual_report_truthfully_records_raw_array_egress() -> None:
    report = _report()
    visual = report["scenarios"][3]
    visual["samples"][0]["checks"]["raw_dataset_arrays_absent"] = False
    visual["samples"][0]["status"] = "failed"
    visual["status"] = "failed"
    report["status"] = "failed"
    report["summary"]["passed_count"] = 3
    report["summary"]["raw_dataset_arrays_sent"] = True

    validate_baseline_report(report)


def test_failed_markdown_does_not_claim_source_adjacent_delivery_was_avoided() -> None:
    report = _report()
    ready = report["scenarios"][0]
    ready["samples"][0]["checks"]["source_parent_unchanged"] = False
    ready["samples"][0]["status"] = "failed"
    ready["status"] = "failed"
    report["status"] = "failed"
    report["summary"]["passed_count"] = 3
    report["summary"]["user_delivery_created"] = True
    validate_baseline_report(report)

    markdown = _markdown_report(report)

    assert "No user delivery was created" not in markdown
    assert "A source-parent change was detected" in markdown


def test_baseline_report_recomputes_status_metrics_and_stable_evidence() -> None:
    report = _report()

    false_pass = deepcopy(report)
    false_pass["scenarios"][0]["samples"][0]["checks"][
        "direct_and_planned_facts_match"
    ] = False
    with pytest.raises(ValueError, match="sample status is inconsistent"):
        validate_baseline_report(false_pass)

    wrong_state = deepcopy(report)
    wrong_state["scenarios"][0]["samples"][0]["observed_state"] = (
        "needs_rule_repair"
    )
    with pytest.raises(ValueError, match="scenario status is inconsistent"):
        validate_baseline_report(wrong_state)

    forged_metrics = deepcopy(report)
    forged_metrics["scenarios"][0]["metrics"]["wall_time_ms"]["p95"] = 0
    with pytest.raises(ValueError, match="scenario metrics are inconsistent"):
        validate_baseline_report(forged_metrics)

    forged_stable = deepcopy(report)
    forged_stable["scenarios"][0]["stable_evidence"]["first"] = {"forged": True}
    with pytest.raises(ValueError, match="stable evidence is inconsistent"):
        validate_baseline_report(forged_stable)

    boolean_distribution = deepcopy(report)
    distribution = boolean_distribution["scenarios"][0]["metrics"]["wall_time_ms"]
    distribution.update({"values": [True], "p50": True, "p95": True})
    with pytest.raises(ValueError, match="scenario metrics are inconsistent"):
        validate_baseline_report(boolean_distribution)

    boolean_summary = deepcopy(report)
    boolean_summary["summary"]["model_calls"] = False
    boolean_summary["summary"]["provider_requests"] = True
    with pytest.raises(ValueError, match="summary is inconsistent"):
        validate_baseline_report(boolean_summary)

    boolean_stability = deepcopy(report)
    boolean_stability["scenarios"][0]["stable_evidence"][
        "identical_across_samples"
    ] = 1
    with pytest.raises(ValueError, match="stable evidence is inconsistent"):
        validate_baseline_report(boolean_stability)

    forged_denominator = deepcopy(report)
    forged_denominator["scenarios"][0]["samples"][0]["metrics"][
        "full_decision_payload_bytes"
    ] += 1
    with pytest.raises(ValueError, match="payload size is inconsistent"):
        validate_baseline_report(forged_denominator)


def test_scenario_and_validator_fail_when_repetition_identity_drifts() -> None:
    first = _sample(1, "ready_zero_ai", "ready")
    second = _sample(2, "ready_zero_ai", "ready")
    second["evidence_identity"]["stable"]["plan_sha256"] = "e" * 64
    second["evidence_identity"]["stable"]["plan_id"] = "rfp_eeeeeeeeeeeeeeee"

    scenario = _scenario_record(
        "ready_zero_ai",
        "identity drift replay",
        "ready",
        [first, second],
    )
    assert scenario["status"] == "failed"
    assert scenario["stable_evidence"]["identical_across_samples"] is False

    report = _report()
    report["repetitions"] = 2
    report["session_payloads"]["fixture_integrity_reads_outside_measurements"] = 4
    for item in report["scenarios"]:
        duplicate = deepcopy(item["samples"][0])
        duplicate["sample_index"] = 2
        item["samples"].append(duplicate)
        item["metrics"] = metric_distribution(
            [sample["metrics"] for sample in item["samples"]]
        )
    report["summary"]["provider_requests"] = 2
    drifted = report["scenarios"][0]
    drifted["samples"][1]["evidence_identity"]["stable"]["plan_sha256"] = (
        "e" * 64
    )
    drifted["samples"][1]["evidence_identity"]["stable"]["plan_id"] = (
        "rfp_eeeeeeeeeeeeeeee"
    )
    drifted["stable_evidence"] = {
        "identical_across_samples": False,
        "first": drifted["samples"][0]["evidence_identity"]["stable"],
    }

    with pytest.raises(ValueError, match="scenario status is inconsistent"):
        validate_baseline_report(report)


def test_source_open_instrumentation_restores_global_openers(tmp_path: Path) -> None:
    source = tmp_path / "source.csv"
    source.write_text("x,y\n1,2\n", encoding="utf-8")
    original_builtin = builtins.open
    original_io = io.open

    with pytest.raises(RuntimeError, match="controlled"):
        with _source_reads(source) as source_reads:
            source.read_text(encoding="utf-8")
            assert source_reads() == 1
            raise RuntimeError("controlled")

    assert builtins.open is original_builtin
    assert io.open is original_io


def test_rule_repair_replay_stops_before_source_or_filesystem_write(
    tmp_path: Path,
) -> None:
    sample = _repair_sample(
        registry=load_validated_envelope_registry(),
        sample_root=tmp_path / "repair",
        sample_index=1,
    )

    assert sample["status"] == "passed"
    assert sample["observed_state"] == "needs_rule_repair"
    assert sample["metrics"]["raw_source_read_opens"] == 0
    assert sample["evidence_identity"]["sample"]["filesystem_write_opens"] == 0
    assert sample["metrics"]["model_calls"] == 0
    assert sample["token_usage"] == {
        "input_tokens": None,
        "output_tokens": None,
        "basis": "offline_replay_no_token_usage",
    }


def test_ready_replay_blocks_raw_source_write_before_it_reaches_disk(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source = tmp_path / "source.csv"
    source.write_text("x,y\n1,2\n", encoding="utf-8")
    original_bytes = source.read_bytes()
    original_builtin = builtins.open
    original_io = io.open

    def mutating_preview(_source: Path, *, request: dict[str, Any]) -> dict[str, Any]:
        assert request["rule_id"] == "performance_comparison"
        source.write_text("TRANSIENT_MUTATION", encoding="utf-8")
        source.write_bytes(original_bytes)
        return {}

    monkeypatch.setattr(
        "sciplot_core.automation_baseline_probe.build_plan_preview",
        mutating_preview,
    )

    with pytest.raises(RuntimeError, match="forbidden raw-source write"):
        _ready_sample(
            source,
            source_sha256=file_sha256(source),
            rule_payload={},
            sample_root=tmp_path / "sample",
            sample_index=1,
        )

    assert source.read_bytes() == original_bytes
    assert builtins.open is original_builtin
    assert io.open is original_io


def test_ready_replay_blocks_source_adjacent_delivery_before_creation(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source = tmp_path / "source.csv"
    escaped = tmp_path / "source_SciPlot"
    source.write_text("x,y\n1,2\n", encoding="utf-8")
    original_mkdir = os.mkdir

    def escaping_preview(_source: Path, *, request: dict[str, Any]) -> dict[str, Any]:
        assert request["template"] == "scatter"
        escaped.mkdir()
        return {}

    monkeypatch.setattr(
        "sciplot_core.automation_baseline_probe.build_plan_preview",
        escaping_preview,
    )

    with pytest.raises(RuntimeError, match="outside its evidence root"):
        _ready_sample(
            source,
            source_sha256=file_sha256(source),
            rule_payload={},
            sample_root=tmp_path / "sample",
            sample_index=1,
        )

    assert not escaped.exists()
    assert os.mkdir is original_mkdir


def test_ready_replay_blocks_source_adjacent_symlink_before_creation(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source = tmp_path / "source.csv"
    sample_root = tmp_path / "sample"
    escaped = tmp_path / "source_SciPlot"
    source.write_text("x,y\n1,2\n", encoding="utf-8")

    def escaping_preview(_source: Path, *, request: dict[str, Any]) -> dict[str, Any]:
        assert request["rule_id"] == "performance_comparison"
        escaped.symlink_to(sample_root, target_is_directory=True)
        return {}

    monkeypatch.setattr(
        "sciplot_core.automation_baseline_probe.build_plan_preview",
        escaping_preview,
    )

    with pytest.raises(RuntimeError, match="outside its evidence root"):
        _ready_sample(
            source,
            source_sha256=file_sha256(source),
            rule_payload={},
            sample_root=sample_root,
            sample_index=1,
        )

    assert not escaped.exists()


def test_ready_replay_blocks_unapproved_child_delivery_before_creation(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source = tmp_path / "source.csv"
    sample_root = tmp_path / "sample"
    escaped = tmp_path / "source_SciPlot"
    source.write_text("x,y\n1,2\n", encoding="utf-8")
    original_popen = subprocess.Popen

    def escaping_preview(_source: Path, *, request: dict[str, Any]) -> dict[str, Any]:
        assert request["template"] == "scatter"
        subprocess.run(["/bin/mkdir", str(escaped)], check=True)
        return {}

    monkeypatch.setattr(
        "sciplot_core.automation_baseline_probe.build_plan_preview",
        escaping_preview,
    )

    with pytest.raises(RuntimeError, match="unapproved child-process launch"):
        _ready_sample(
            source,
            source_sha256=file_sha256(source),
            rule_payload={},
            sample_root=sample_root,
            sample_index=1,
        )

    assert not escaped.exists()
    assert subprocess.Popen is original_popen


def test_ready_guard_binds_the_complete_worker_execution_context(
    tmp_path: Path,
) -> None:
    source = tmp_path / "source.csv"
    allowed = tmp_path / "sample"
    document = allowed / "document.vsz"
    source.write_text("x,y\n1,2\n", encoding="utf-8")
    allowed.mkdir()
    document.write_text("# Veusz saved document\n", encoding="utf-8")
    escaped = tmp_path / "escaped.txt"
    replacement = tmp_path / "replacement"
    replacement.write_text(
        f"#!/bin/sh\nprintf escaped > '{escaped}'\n",
        encoding="utf-8",
    )
    replacement.chmod(0o700)
    shadow = tmp_path / "shadow"
    worker_package = shadow / "sciplot_core" / "veusz_worker"
    worker_package.mkdir(parents=True)
    (shadow / "sciplot_core" / "__init__.py").write_text("", encoding="utf-8")
    (worker_package / "__init__.py").write_text("", encoding="utf-8")
    (worker_package / "__main__.py").write_text(
        "from pathlib import Path\n"
        f"Path({str(escaped)!r}).write_text('escaped', encoding='utf-8')\n",
        encoding="utf-8",
    )
    command = [
        sys.executable,
        "-m",
        "sciplot_core.veusz_worker",
        "audit-documents",
        str(document),
    ]
    trusted_environment = veusz_worker_environment()
    bad_environment = dict(trusted_environment)
    bad_environment["PYTHONPATH"] = str(shadow)
    bad_terminal_environment = dict(trusted_environment)
    bad_terminal_environment[
        "SCIPLOT_INTERNAL_TERMINAL_SOURCE_PREPARED"
    ] = "invalid"
    overrides = (
        {"executable": str(replacement), "env": trusted_environment},
        {"cwd": str(shadow), "env": trusted_environment},
        {"env": bad_environment},
        {"env": bad_terminal_environment},
        {"shell": True, "env": trusted_environment},
    )
    outside_stream = tmp_path / "outside-stream.txt"
    outside_fd = os.open(
        outside_stream,
        os.O_WRONLY | os.O_CREAT | os.O_TRUNC,
        0o600,
    )

    try:
        with _ready_write_guard(source=source, allowed_root=allowed) as attempts:
            for override in overrides:
                with pytest.raises(
                    RuntimeError,
                    match="unapproved child-process launch",
                ):
                    subprocess.run(command, check=True, **override)
            with pytest.raises(
                RuntimeError,
                match="unapproved child-process launch",
            ):
                subprocess.run(
                    ["uname", "-p"],
                    check=True,
                    stdout=outside_fd,
                    stderr=subprocess.DEVNULL,
                    text=True,
                    encoding="utf8",
                )
            for descriptor_override in (
                {"pass_fds": (outside_fd,)},
                {"close_fds": False},
            ):
                with pytest.raises(
                    RuntimeError,
                    match="unapproved child-process launch",
                ):
                    subprocess.run(
                        command,
                        check=True,
                        capture_output=True,
                        env=trusted_environment,
                        **descriptor_override,
                    )
            with pytest.raises(
                RuntimeError,
                match="unapproved child-process launch",
            ):
                subprocess.Popen(
                    command,
                    -1,
                    str(replacement),
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    env=trusted_environment,
                )
            with pytest.raises(RuntimeError, match="trusted working directory"):
                os.chdir(shadow)
            assert attempts() == len(overrides) + 5
    finally:
        os.close(outside_fd)

    assert not escaped.exists()
    assert outside_stream.read_bytes() == b""


def test_ready_guard_requires_the_repository_working_directory(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source = tmp_path / "source.csv"
    allowed = tmp_path / "sample"
    source.write_text("x,y\n1,2\n", encoding="utf-8")
    allowed.mkdir()
    monkeypatch.chdir(tmp_path)

    with pytest.raises(RuntimeError, match="repository root"):
        with _ready_write_guard(source=source, allowed_root=allowed):
            pass


def test_ready_guard_rejects_inherited_python_path_shadowing(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source = tmp_path / "source.csv"
    allowed = tmp_path / "sample"
    document = allowed / "document.vsz"
    shadow = tmp_path / "shadow"
    source.write_text("x,y\n1,2\n", encoding="utf-8")
    allowed.mkdir()
    document.write_text("# Veusz saved document\n", encoding="utf-8")
    shadow.mkdir()
    monkeypatch.setenv("PYTHONPATH", str(shadow))
    command = [
        sys.executable,
        "-m",
        "sciplot_core.veusz_worker",
        "audit-documents",
        str(document),
    ]

    with _ready_write_guard(source=source, allowed_root=allowed) as attempts:
        with pytest.raises(
            RuntimeError,
            match="unapproved child-process launch",
        ):
            subprocess.run(
                command,
                check=True,
                capture_output=True,
                env=veusz_worker_environment(),
            )
        assert attempts() == 1


def test_source_parent_snapshot_records_symlink_location_not_resolved_target(
    tmp_path: Path,
) -> None:
    source = tmp_path / "source.csv"
    allowed = tmp_path / "sample"
    escaped = tmp_path / "source_SciPlot"
    source.write_text("x,y\n1,2\n", encoding="utf-8")
    allowed.mkdir()
    before = _source_parent_snapshot(source, excluded_root=allowed)

    escaped.symlink_to(allowed, target_is_directory=True)

    after = _source_parent_snapshot(source, excluded_root=allowed)
    assert before != after
    assert after["source_SciPlot"][0] == "symlink"


def test_confirmation_replay_blocks_transient_raw_source_write(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import sciplot_core.automation_baseline_probe as baseline_probe

    source = tmp_path / "source.csv"
    source.write_text("x,y\n1,2\n", encoding="utf-8")
    original_bytes = source.read_bytes()
    original = baseline_probe._evaluation_bundle

    def mutating_bundle(*args: Any, **kwargs: Any) -> dict[str, Any]:
        source.write_text("TRANSIENT", encoding="utf-8")
        source.write_bytes(original_bytes)
        return original(*args, **kwargs)

    monkeypatch.setattr(baseline_probe, "_evaluation_bundle", mutating_bundle)

    with pytest.raises(RuntimeError, match="forbidden raw-source write"):
        _confirmation_sample(
            source,
            source_sha256=file_sha256(source),
            registry=load_validated_envelope_registry(),
            sample_root=tmp_path / "confirmation",
            sample_index=1,
        )

    assert source.read_bytes() == original_bytes


def test_external_model_call_guard_counts_and_blocks_the_production_adapter() -> None:
    from sciplot_core.openai_provider.provider import OpenAIResponsesProvider

    original_generate = OpenAIResponsesProvider.generate
    with _external_model_call_guard() as calls:
        with pytest.raises(RuntimeError, match="external model call"):
            OpenAIResponsesProvider.generate(None, None)  # type: ignore[arg-type]
        assert calls() == 1

    assert OpenAIResponsesProvider.generate is original_generate


def test_rule_repair_replay_detects_an_injected_source_read(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source = tmp_path / "source.csv"
    source.write_text("x,y\n1,2\n", encoding="utf-8")
    import sciplot_core.automation_baseline_probe as baseline_probe

    original = baseline_probe.current_rule_invocation_contract_payload

    def leaking_owner(**kwargs: Any) -> dict[str, Any]:
        source.read_text(encoding="utf-8")
        return original(**kwargs)

    monkeypatch.setattr(
        baseline_probe,
        "current_rule_invocation_contract_payload",
        leaking_owner,
    )

    sample = _repair_sample(
        source=source,
        registry=load_validated_envelope_registry(),
        sample_root=tmp_path / "repair",
        sample_index=1,
    )

    assert sample["status"] == "failed"
    assert sample["metrics"]["raw_source_read_opens"] == 1
    assert sample["checks"]["raw_source_was_not_opened"] is False


def test_rule_repair_replay_blocks_injected_write_before_it_reaches_disk(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source = tmp_path / "source.csv"
    marker = tmp_path / "unexpected.txt"
    source.write_text("x,y\n1,2\n", encoding="utf-8")
    original_builtin = builtins.open
    original_io = io.open
    import sciplot_core.automation_baseline_probe as baseline_probe

    original = baseline_probe.current_rule_invocation_contract_payload

    def leaking_owner(**kwargs: Any) -> dict[str, Any]:
        marker.write_text("unexpected", encoding="utf-8")
        return original(**kwargs)

    monkeypatch.setattr(
        baseline_probe,
        "current_rule_invocation_contract_payload",
        leaking_owner,
    )

    with pytest.raises(RuntimeError, match="outside its evidence root"):
        _repair_sample(
            source=source,
            registry=load_validated_envelope_registry(),
            sample_root=tmp_path / "repair",
            sample_index=1,
        )

    assert not marker.exists()
    assert builtins.open is original_builtin
    assert io.open is original_io


def test_visual_sample_keeps_replay_provider_separate_from_model_calls(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source = tmp_path / "source.csv"
    document = tmp_path / "document.vsz"
    source.write_text("x,y\n1,2\n", encoding="utf-8")
    document.write_text("# Veusz saved document\n", encoding="utf-8")

    monkeypatch.setattr(
        "sciplot_core.automation_baseline_probe._run_selected_object_cycle",
        lambda *_args, **_kwargs: {
            "assistant_terminal_status": "applied",
            "provider_request_count": 1,
            "outside_write_attempts": 0,
            "request_metrics": {
                "payload_bytes": 100,
                "context_bytes": 40,
                "image_bytes": 20,
            },
            "decision_payload_components": {
                "intent": "bounded edit",
                "base_revision": 1,
                "context": {},
                "visual_preview_metadata": {"sha256": "a" * 64},
            },
            "timings_ms": {
                "submit_to_proposal": 5.0,
                "proposal_to_applied": 2.0,
            },
            "evidence_identity": {
                "stable": {},
                "sample": {"source_document_sha256": file_sha256(document)},
            },
            "checks": {
                key: True
                for key in SCENARIO_CHECKS["selected_object_visual_edit"]
                if key
                not in {"upstream_ready_document_is_bound", "source_data_was_not_read"}
            },
        },
    )

    sample = _visual_sample(
        source,
        document=document,
        upstream_ready_sample={
            **_sample(1, "ready_zero_ai", "ready"),
            "evidence_identity": {
                "stable": {"plan_sha256": "a" * 64},
                "sample": {"delivered_vsz_sha256": file_sha256(document)},
            },
        },
        sample_root=tmp_path / "visual",
        sample_index=1,
    )

    assert sample["status"] == "passed"
    assert sample["metrics"]["provider_requests"] == 1
    assert sample["metrics"]["model_calls"] == 0
    assert sample["metrics"]["raw_source_read_opens"] == 0
    assert sample["metrics"]["submit_to_proposal_ms"] == 5.0
    assert sample["token_usage"]["input_tokens"] is None


def test_visual_replay_blocks_transient_raw_source_write(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source = tmp_path / "source.csv"
    document = tmp_path / "document.vsz"
    source.write_text("x,y\n1,2\n", encoding="utf-8")
    document.write_text("# Veusz saved document\n", encoding="utf-8")
    original_bytes = source.read_bytes()

    def mutating_cycle(*_args: Any, **_kwargs: Any) -> dict[str, Any]:
        source.write_text("TRANSIENT", encoding="utf-8")
        source.write_bytes(original_bytes)
        return {}

    monkeypatch.setattr(
        "sciplot_core.automation_baseline_probe._run_selected_object_cycle",
        mutating_cycle,
    )

    with pytest.raises(RuntimeError, match="forbidden raw-source write"):
        _visual_sample(
            source,
            document=document,
            upstream_ready_sample=_sample(1, "ready_zero_ai", "ready"),
            sample_root=tmp_path / "visual",
            sample_index=1,
        )

    assert source.read_bytes() == original_bytes


def test_visual_copy_rejects_a_nonidentical_document_before_open(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source = tmp_path / "source.vsz"
    copied = tmp_path / "copied.vsz"
    source.write_text("# exact-current", encoding="utf-8")

    def tampered_copy(_source: Path, destination: Path) -> None:
        destination.write_text("# different document", encoding="utf-8")

    monkeypatch.setattr(
        "sciplot_core.automation_baseline_probe.shutil.copy2",
        tampered_copy,
    )

    with pytest.raises(RuntimeError, match="not the exact-current source document"):
        _copy_exact_current_document(source, copied)

    assert source.read_text(encoding="utf-8") == "# exact-current"
    assert copied.read_text(encoding="utf-8") == "# different document"


def test_automation_baseline_is_one_hidden_diagnostics_command() -> None:
    parser = build_parser()
    args = parser.parse_args(
        ["automation-baseline", "--out", ".tmp_verify/r0", "--repetitions", "2"]
    )
    help_text = parser.format_help()

    assert args.command == "automation-baseline"
    assert args.repetitions == 2
    assert "automation-baseline" not in help_text


def test_probe_rejects_output_outside_development_evidence_root(
    tmp_path: Path,
) -> None:
    output = tmp_path / "not-repository-evidence"

    with pytest.raises(ValueError, match="fixed.*evidence root"):
        run_automation_baseline_probe(output_root=output, repetitions=1)

    assert not output.exists()


def test_scenario_collection_removes_source_derived_work_artifacts(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import sciplot_core.automation_baseline_probe as baseline_probe

    source = tmp_path / "source.csv"
    source.write_text("x,y\n1,2\n", encoding="utf-8")

    def ready_sample(
        _source: Path,
        *,
        sample_root: Path,
        sample_index: int,
        **_kwargs: Any,
    ) -> tuple[dict[str, Any], Path]:
        sample_root.mkdir(parents=True)
        document = sample_root / "source-derived.vsz"
        document.write_text("# temporary", encoding="utf-8")
        return {"sample_index": sample_index}, document

    def visual_sample(
        _source: Path,
        *,
        sample_root: Path,
        sample_index: int,
        **_kwargs: Any,
    ) -> dict[str, Any]:
        sample_root.mkdir(parents=True)
        (sample_root / "sensitive.png").write_bytes(b"temporary")
        return {"sample_index": sample_index}

    monkeypatch.setattr(baseline_probe, "_ready_sample", ready_sample)
    monkeypatch.setattr(
        baseline_probe,
        "_confirmation_sample",
        lambda *_args, sample_index, **_kwargs: {"sample_index": sample_index},
    )
    monkeypatch.setattr(
        baseline_probe,
        "_repair_sample",
        lambda *_args, sample_index, **_kwargs: {"sample_index": sample_index},
    )
    monkeypatch.setattr(baseline_probe, "_visual_sample", visual_sample)
    monkeypatch.setattr(
        baseline_probe,
        "_scenario_record",
        lambda scenario_id, *_args: {"scenario_id": scenario_id},
    )

    scenarios = baseline_probe._collect_scenarios(
        run_root=tmp_path,
        source=source,
        source_sha256="a" * 64,
        rule_payload={},
        registry=load_validated_envelope_registry(),
        repetitions=1,
    )

    assert [scenario["scenario_id"] for scenario in scenarios] == list(
        AUTOMATION_BASELINE_SCENARIOS
    )
    assert list(tmp_path.iterdir()) == [source]
