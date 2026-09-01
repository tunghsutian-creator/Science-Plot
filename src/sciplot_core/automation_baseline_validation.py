"""Fail-closed validation for the R0 automation baseline report."""

from __future__ import annotations

import math
import re
from collections.abc import Mapping
from pathlib import PurePosixPath
from typing import Any

from sciplot_core.automation_baseline import metric_distribution
from sciplot_core.automation_baseline_identity_validation import (
    validate_cross_scenario_identity,
    validate_scenario_evidence,
)
from sciplot_core.automation_baseline_schema import (
    ARTIFACT_FIELDS,
    AUTOMATION_BASELINE_KIND,
    AUTOMATION_BASELINE_SCENARIOS,
    AUTOMATION_BASELINE_VERSION,
    BASELINE_LIMITATIONS,
    BASELINE_READY_RULE_FLOOR,
    DISTRIBUTION_FIELDS,
    INTEGER_METRIC_FIELDS,
    METRIC_FIELDS,
    NULLABLE_METRIC_FIELDS,
    PAYLOAD_COMPONENT_FIELDS,
    PLATFORM_FIELDS,
    REPORT_FIELDS,
    SAMPLE_FIELDS,
    SCENARIO_ACTIONS,
    SCENARIO_CHECKS,
    SCENARIO_DESCRIPTIONS,
    SCENARIO_FIELDS,
    SCENARIO_PAYLOAD_COMPONENTS,
    SCENARIO_REASON_CODES,
    SCENARIO_STATES,
    SESSION_FIELDS,
    STABLE_EVIDENCE_FIELDS,
    SUMMARY_FIELDS,
    TOKEN_USAGE_FIELDS,
)
from sciplot_core.automation_states import is_automation_state
from sciplot_core.foundation.iso_timestamps import require_zoned_iso_timestamp
from sciplot_core.automation_baseline_validation_utils import (
    require_fields as _require_fields,
    require_sha256 as _require_sha256,
    same_typed_json_value as _same_typed_json_value,
    validate_fixed_mapping as _validate_fixed_mapping,
)


def validate_baseline_report(payload: Mapping[str, Any]) -> None:
    """Reject incomplete, internally inconsistent, or open-ended R0 evidence."""

    _require_fields(payload, REPORT_FIELDS, label="automation baseline report")
    if payload.get("kind") != AUTOMATION_BASELINE_KIND:
        raise ValueError("Automation baseline kind is invalid.")
    if type(payload.get("version")) is not int or (
        payload["version"] != AUTOMATION_BASELINE_VERSION
    ):
        raise ValueError("Automation baseline version is invalid.")
    repetitions = payload.get("repetitions")
    if type(repetitions) is not int or repetitions < 1:
        raise ValueError("Automation baseline repetitions must be a positive integer.")
    if payload.get("scenario_order") != list(AUTOMATION_BASELINE_SCENARIOS):
        raise ValueError("Automation baseline scenario order is invalid.")
    require_zoned_iso_timestamp(
        payload.get("generated_at"),
        "Automation baseline generated_at",
    )
    session = _validate_session(payload, repetitions=repetitions)
    _validate_fixed_mapping(payload.get("summary"), SUMMARY_FIELDS, "summary")
    artifacts = _validate_fixed_mapping(
        payload.get("artifacts"), ARTIFACT_FIELDS, "artifacts"
    )
    if any(not isinstance(value, str) or not value for value in artifacts.values()):
        raise ValueError("Automation baseline artifact paths must be non-empty text.")
    artifact_paths = {key: PurePosixPath(value) for key, value in artifacts.items()}
    if any(
        path.is_absolute() or ".." in path.parts for path in artifact_paths.values()
    ):
        raise ValueError("Automation baseline artifact paths must be repository-relative.")
    root = artifact_paths["root"]
    root_text = root.as_posix()
    if (
        re.fullmatch(
            r"\.tmp_verify/r0_automation_baseline/automation_r0_[0-9a-f]{16}",
            root_text,
        )
        is None
        or artifact_paths["json"].parent != root
        or artifact_paths["markdown"].parent != root
        or artifact_paths["json"].name != "automation_r0_baseline.json"
        or artifact_paths["markdown"].name != "automation_r0_baseline.md"
    ):
        raise ValueError("Automation baseline artifact locators are invalid.")
    limitations = payload.get("limitations")
    if limitations != list(BASELINE_LIMITATIONS):
        raise ValueError("Automation baseline limitations are invalid.")
    scenarios = payload.get("scenarios")
    if not isinstance(scenarios, list) or len(scenarios) != len(
        AUTOMATION_BASELINE_SCENARIOS
    ):
        raise ValueError("Automation baseline scenarios are incomplete.")
    for expected_id, scenario in zip(
        AUTOMATION_BASELINE_SCENARIOS, scenarios, strict=True
    ):
        if not isinstance(scenario, Mapping):
            raise ValueError("Automation baseline scenario must be an object.")
        _validate_scenario(
            scenario,
            expected_id=expected_id,
            repetitions=repetitions,
            fixture_sha256=session["fixture_sha256"],
        )
    validate_cross_scenario_identity(scenarios, session=session)
    expected_status = (
        "passed" if all(item["status"] == "passed" for item in scenarios) else "failed"
    )
    if payload.get("status") != expected_status:
        raise ValueError("Automation baseline report status is inconsistent.")
    expected_summary = {
        "scenario_count": len(scenarios),
        "passed_count": sum(item["status"] == "passed" for item in scenarios),
        "model_calls": sum(
            sample["metrics"]["model_calls"]
            for scenario in scenarios
            for sample in scenario["samples"]
        ),
        "provider_requests": sum(
            sample["metrics"]["provider_requests"]
            for scenario in scenarios
            for sample in scenario["samples"]
        ),
        "raw_dataset_arrays_sent": any(
            not sample["checks"]["raw_dataset_arrays_absent"]
            for sample in scenarios[-1]["samples"]
        ),
        "user_delivery_created": any(
            not sample["checks"]["source_parent_unchanged"]
            for sample in scenarios[0]["samples"]
        ),
    }
    if not _same_typed_json_value(payload["summary"], expected_summary):
        raise ValueError("Automation baseline summary is inconsistent.")


def _validate_session(
    payload: Mapping[str, Any], *, repetitions: int
) -> Mapping[str, Any]:
    platform = _validate_fixed_mapping(payload.get("platform"), PLATFORM_FIELDS, "platform")
    if any(
        not isinstance(value, str)
        or not value
        or len(value) > 128
        or "/" in value
        or "\\" in value
        or "\n" in value
        for value in platform.values()
    ):
        raise ValueError("Automation baseline platform values must be non-empty text.")
    session = _validate_fixed_mapping(
        payload.get("session_payloads"), SESSION_FIELDS, "session payloads"
    )
    if session["doctor_status"] != "ready":
        raise ValueError("Automation baseline requires doctor status=ready.")
    for field in (
        "doctor_payload_bytes",
        "ready_rule_count",
        "fixture_integrity_reads_outside_measurements",
        "rule_catalog_payload_bytes",
        "selected_rule_payload_bytes",
    ):
        if type(session[field]) is not int or session[field] <= 0:
            raise ValueError("Automation baseline session counts must be positive integers.")
    if session["ready_rule_count"] < BASELINE_READY_RULE_FLOOR:
        raise ValueError("Automation baseline ready-rule inventory has regressed.")
    _require_sha256(session["fixture_sha256"], label="fixture_sha256")
    _require_sha256(session["fixture_sha256_after"], label="fixture_sha256_after")
    for field in (
        "doctor_payload_sha256",
        "rule_catalog_payload_sha256",
        "selected_rule_payload_sha256",
    ):
        _require_sha256(session[field], label=field)
    if session["fixture_sha256_after"] != session["fixture_sha256"]:
        raise ValueError("Automation baseline fixture bytes changed during the run.")
    if session["fixture_integrity_reads_outside_measurements"] != repetitions + 2:
        raise ValueError("Automation baseline fixture integrity read count is inconsistent.")
    return session


def _validate_scenario(
    scenario: Mapping[str, Any],
    *,
    expected_id: str,
    repetitions: int,
    fixture_sha256: str,
) -> None:
    _require_fields(scenario, SCENARIO_FIELDS, label="automation scenario")
    if scenario.get("scenario_id") != expected_id:
        raise ValueError("Automation baseline scenario identity is invalid.")
    if scenario.get("expected_state") != SCENARIO_STATES[expected_id]:
        raise ValueError("Automation baseline expected state is invalid.")
    if scenario.get("description") != SCENARIO_DESCRIPTIONS[expected_id]:
        raise ValueError("Automation baseline scenario description is invalid.")
    samples = scenario.get("samples")
    if not isinstance(samples, list) or len(samples) != repetitions:
        raise ValueError(f"Automation scenario `{expected_id}` sample count is invalid.")
    for index, sample in enumerate(samples, start=1):
        _validate_sample(
            sample,
            index=index,
            scenario_id=expected_id,
            fixture_sha256=fixture_sha256,
        )
    stable_values = [sample["evidence_identity"]["stable"] for sample in samples]
    stable_identical = all(value == stable_values[0] for value in stable_values)
    expected_status = (
        "passed"
        if stable_identical
        and all(
            sample["status"] == "passed"
            and sample["observed_state"] == scenario["expected_state"]
            for sample in samples
        )
        else "failed"
    )
    if scenario.get("status") != expected_status:
        raise ValueError("Automation baseline scenario status is inconsistent.")
    expected_metrics = metric_distribution([sample["metrics"] for sample in samples])
    metrics_summary = _validate_fixed_mapping(
        scenario.get("metrics"), METRIC_FIELDS, "scenario metrics"
    )
    for distribution in metrics_summary.values():
        _validate_fixed_mapping(distribution, DISTRIBUTION_FIELDS, "metric distribution")
    if not _same_typed_json_value(metrics_summary, expected_metrics):
        raise ValueError("Automation baseline scenario metrics are inconsistent.")
    expected_stable = {
        "identical_across_samples": stable_identical,
        "first": stable_values[0],
    }
    stable_evidence = _validate_fixed_mapping(
        scenario.get("stable_evidence"), STABLE_EVIDENCE_FIELDS, "stable evidence"
    )
    if not _same_typed_json_value(stable_evidence, expected_stable):
        raise ValueError("Automation baseline stable evidence is inconsistent.")


def _validate_sample(
    sample: object,
    *,
    index: int,
    scenario_id: str,
    fixture_sha256: str,
) -> None:
    if not isinstance(sample, Mapping):
        raise ValueError("Automation baseline sample must be an object.")
    _require_fields(sample, SAMPLE_FIELDS, label="automation sample")
    if type(sample.get("sample_index")) is not int or sample["sample_index"] != index:
        raise ValueError("Automation baseline sample order is invalid.")
    if not is_automation_state(sample.get("observed_state")):
        raise ValueError("Automation baseline observed state is invalid.")
    if sample.get("next_action") != SCENARIO_ACTIONS[scenario_id]:
        raise ValueError("Automation baseline next action is invalid.")
    metrics = _validate_metrics(sample.get("metrics"), scenario_id=scenario_id)
    _validate_token_usage(sample.get("token_usage"))
    components = _validate_fixed_mapping(
        sample.get("payload_components"),
        SCENARIO_PAYLOAD_COMPONENTS[scenario_id],
        "payload components",
    )
    component_manifests = {
        key: _validate_fixed_mapping(
            value,
            PAYLOAD_COMPONENT_FIELDS,
            f"payload component `{key}`",
        )
        for key, value in components.items()
    }
    for key, component in component_manifests.items():
        if type(component["bytes"]) is not int or component["bytes"] <= 0:
            raise ValueError(
                "Automation baseline payload component sizes must be positive integers."
            )
        _require_sha256(component["sha256"], label=f"{key} payload sha256")
    if metrics["full_decision_payload_bytes"] != sum(
        component["bytes"] for component in component_manifests.values()
    ):
        raise ValueError("Automation baseline full decision payload size is inconsistent.")
    expected_provider = (
        ("offline_fixture", "completed")
        if scenario_id == "selected_object_visual_edit"
        else ("none", "not_used")
    )
    if (sample.get("provider_mode"), sample.get("provider_outcome")) != expected_provider:
        raise ValueError("Automation baseline provider state is invalid.")
    validate_scenario_evidence(
        sample.get("evidence_identity"),
        scenario_id=scenario_id,
        fixture_sha256=fixture_sha256,
    )
    if sample.get("reason_codes") != list(SCENARIO_REASON_CODES[scenario_id]):
        raise ValueError("Automation baseline reason codes are invalid.")
    checks = _validate_fixed_mapping(
        sample.get("checks"), SCENARIO_CHECKS[scenario_id], "scenario checks"
    )
    if any(not isinstance(value, bool) for value in checks.values()):
        raise ValueError("Automation baseline checks must be boolean.")
    expected_status = "passed" if all(checks.values()) else "failed"
    if sample.get("status") != expected_status:
        raise ValueError("Automation baseline sample status is inconsistent.")


def _validate_metrics(payload: object, *, scenario_id: str) -> Mapping[str, Any]:
    metrics = _validate_fixed_mapping(payload, METRIC_FIELDS, "metrics")
    for field, value in metrics.items():
        if value is None and field in NULLABLE_METRIC_FIELDS:
            continue
        if (
            isinstance(value, bool)
            or not isinstance(value, (int, float))
            or not math.isfinite(float(value))
            or value < 0
        ):
            raise ValueError("Automation baseline metrics must be finite and non-negative.")
        if field in INTEGER_METRIC_FIELDS and type(value) is not int:
            raise ValueError("Automation baseline count and byte metrics must be integers.")
    if metrics["wall_time_ms"] <= 0 or metrics["peak_python_memory_bytes"] <= 0:
        raise ValueError("Automation baseline time and memory metrics must be positive.")
    if metrics["model_calls"] != 0:
        raise ValueError("Automation baseline replay cannot report model calls.")
    visual = scenario_id == "selected_object_visual_edit"
    expected_requests = 1 if visual else 0
    if metrics["provider_requests"] != expected_requests:
        raise ValueError("Automation baseline provider request count is invalid.")
    expected_source_reads = None if scenario_id == "ready_zero_ai" else 0
    if expected_source_reads is None:
        if metrics["raw_source_read_opens"] <= 0:
            raise ValueError("Automation baseline ready source-read count is invalid.")
    elif metrics["raw_source_read_opens"] != expected_source_reads:
        raise ValueError("Automation baseline source-read count is invalid.")
    transport_fields = ("provider_payload_bytes", "provider_context_bytes", "image_bytes")
    timing_fields = ("submit_to_proposal_ms", "proposal_to_applied_ms")
    if visual:
        if any(metrics[field] <= 0 for field in transport_fields) or any(
            metrics[field] is None for field in timing_fields
        ):
            raise ValueError("Automation baseline visual transport metrics are incomplete.")
        encoded_image_bytes = 4 * ((metrics["image_bytes"] + 2) // 3)
        if metrics["provider_payload_bytes"] <= (
            metrics["provider_context_bytes"] + encoded_image_bytes
        ):
            raise ValueError("Automation baseline visual payload size is inconsistent.")
    elif any(metrics[field] != 0 for field in transport_fields) or any(
        metrics[field] is not None for field in timing_fields
    ):
        raise ValueError("Automation baseline unused provider metrics must be zero or null.")
    return metrics


def _validate_token_usage(payload: object) -> None:
    token_usage = _validate_fixed_mapping(payload, TOKEN_USAGE_FIELDS, "token usage")
    expected = {
        "input_tokens": None,
        "output_tokens": None,
        "basis": "offline_replay_no_token_usage",
    }
    if token_usage != expected:
        raise ValueError("Automation baseline offline token usage is inconsistent.")


__all__ = ["validate_baseline_report"]
