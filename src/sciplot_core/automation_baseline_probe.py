"""Run the development-only R0 AI-efficient automation benchmark matrix."""

from __future__ import annotations

import base64
import builtins
import gc
import io
import os
import platform
import secrets
import shutil
import subprocess
import sys
import tempfile
import time
import tracemalloc
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Callable, Iterator

from sciplot_core._paths import REPO_ROOT
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
from sciplot_core.automation_baseline_validation import validate_baseline_report
from sciplot_core.automation_baseline_schema import (
    BASELINE_LIMITATIONS,
    BASELINE_RULE_ID,
    BASELINE_TEMPLATE,
    SCENARIO_DESCRIPTIONS,
)
from sciplot_core.automation_states import (
    HUMAN_CONFIRMATION_STATE,
    READY_STATE,
    RULE_REPAIR_STATE,
)
from sciplot_core.autoplot import run_autoplot
from sciplot_core.doctor import doctor_payload
from sciplot_core.foundation.file_hashing import file_sha256
from sciplot_core.foundation.iso_timestamps import utc_now_iso
from sciplot_core.foundation.json_io import atomic_write_json
from sciplot_core.foundation.json_hashing import canonical_json_sha256
from sciplot_core.foundation.json_values import json_safe
from sciplot_core.materials_rules import (
    get_rule,
    list_rules_payload,
    semantic_payload_from_rule,
    show_rule_payload,
)
from sciplot_core.one_step import (
    build_mapping_package,
    build_render_request_package,
    build_source_package,
)
from sciplot_core.plan_preview import build_plan_preview
from sciplot_core.policy import AUTOPLOT_RENDER_OPTIONS, DEFAULT_EXPORT_FORMATS_POLICY
from sciplot_core.readiness import evaluate_validated_envelope
from sciplot_core.readiness.registry_io import load_validated_envelope_registry
from sciplot_core.readiness.registry_model import ValidatedEnvelopeRegistry
from sciplot_core.readiness.rule_certification import (
    current_rule_invocation_contract_payload,
)
from sciplot_core.readiness.rule_contract import rule_contract_hashes
from sciplot_core.request_contract import normalize_render_options
from sciplot_core.render.target_paths import (
    validated_terminal_worker_environment_base,
)
from sciplot_core.source_inspection import clear_inspection_cache
from sciplot_core.veusz_runtime import veusz_worker_environment


_RULE_ID = BASELINE_RULE_ID
_TEMPLATE = BASELINE_TEMPLATE
_SOURCE = REPO_ROOT / "tests/fixtures/performance_comparison/material_performance_long.csv"
_MEDIUM_CONFIDENCE = 75.0


def run_automation_baseline_probe(
    *,
    output_root: Path,
    repetitions: int = 3,
) -> dict[str, Any]:
    """Measure four current routes without using a model or user delivery path."""

    if isinstance(repetitions, bool) or not isinstance(repetitions, int):
        raise ValueError("Automation baseline repetitions must be an integer.")
    if repetitions < 1:
        raise ValueError("Automation baseline repetitions must be positive.")
    resolved_output = output_root.expanduser().resolve()
    development_root = (
        REPO_ROOT / ".tmp_verify" / "r0_automation_baseline"
    ).resolve()
    if resolved_output != development_root:
        raise ValueError(
            "R0 automation baseline output must be the repository's fixed "
            "`.tmp_verify/r0_automation_baseline/` evidence root."
        )
    resolved_output.mkdir(parents=True, exist_ok=True)
    for _attempt in range(10):
        run_root = resolved_output / f"automation_r0_{secrets.token_hex(8)}"
        try:
            run_root.mkdir(mode=0o700)
        except FileExistsError:
            continue
        break
    else:
        raise RuntimeError("Could not allocate a unique R0 evidence root.")
    rule = get_rule(_RULE_ID)
    source = _SOURCE.resolve()
    if not source.is_file():
        raise FileNotFoundError(source)
    registry = load_validated_envelope_registry()
    doctor = doctor_payload()
    if doctor.get("status") != "ready":
        raise RuntimeError("R0 automation baseline requires doctor status=ready.")

    def projector(candidate: Any) -> dict[str, Any]:
        return current_rule_invocation_contract_payload(
            rule=candidate,
            registry=registry,
        )

    catalog = list_rules_payload(invocation_projector=projector)
    rule_payload = show_rule_payload(
        rule.rule_id,
        invocation_projector=projector,
    )

    source_sha256 = file_sha256(source)
    scenarios = _collect_scenarios(
        run_root=run_root,
        source=source,
        source_sha256=source_sha256,
        rule_payload=rule_payload,
        registry=registry,
        repetitions=repetitions,
    )
    passed = all(scenario["status"] == "passed" for scenario in scenarios)
    summary_path = run_root / "automation_r0_baseline.json"
    markdown_path = run_root / "automation_r0_baseline.md"
    report: dict[str, Any] = {
        "kind": AUTOMATION_BASELINE_KIND,
        "version": AUTOMATION_BASELINE_VERSION,
        "generated_at": utc_now_iso(),
        "status": "passed" if passed else "failed",
        "platform": {
            "python": platform.python_version(),
            "system": platform.system(),
            "release": platform.release(),
            "machine": platform.machine(),
        },
        "repetitions": repetitions,
        "session_payloads": {
            "doctor_status": doctor["status"],
            "doctor_payload_bytes": canonical_json_bytes(doctor),
            "doctor_payload_sha256": canonical_json_sha256(
                doctor, allow_nan=False
            ),
            "ready_rule_count": doctor["rule_summary"]["ready"],
            "fixture_sha256": source_sha256,
            "fixture_sha256_after": file_sha256(source),
            "fixture_integrity_reads_outside_measurements": repetitions + 2,
            "rule_catalog_payload_bytes": canonical_json_bytes(catalog),
            "rule_catalog_payload_sha256": canonical_json_sha256(
                catalog, allow_nan=False
            ),
            "selected_rule_payload_bytes": canonical_json_bytes(rule_payload),
            "selected_rule_payload_sha256": canonical_json_sha256(
                rule_payload, allow_nan=False
            ),
        },
        "scenario_order": list(AUTOMATION_BASELINE_SCENARIOS),
        "scenarios": scenarios,
        "summary": {
            "scenario_count": len(scenarios),
            "passed_count": sum(item["status"] == "passed" for item in scenarios),
            "model_calls": sum(
                int(sample["metrics"]["model_calls"])
                for scenario in scenarios
                for sample in scenario["samples"]
            ),
            "provider_requests": sum(
                int(sample["metrics"]["provider_requests"])
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
        },
        "artifacts": {
            "root": run_root.relative_to(REPO_ROOT).as_posix(),
            "json": summary_path.relative_to(REPO_ROOT).as_posix(),
            "markdown": markdown_path.relative_to(REPO_ROOT).as_posix(),
        },
        "limitations": list(BASELINE_LIMITATIONS),
    }
    validate_baseline_report(report)
    atomic_write_json(summary_path, json_safe(report))
    markdown_path.write_text(_markdown_report(report), encoding="utf-8")
    return report


def _collect_scenarios(
    *,
    run_root: Path,
    source: Path,
    source_sha256: str,
    rule_payload: dict[str, Any],
    registry: ValidatedEnvelopeRegistry,
    repetitions: int,
) -> list[dict[str, Any]]:
    work_root = Path(
        tempfile.mkdtemp(prefix="ephemeral_work_", dir=str(run_root))
    ).resolve()
    try:
        ready_samples: list[dict[str, Any]] = []
        documents: list[Path] = []
        for index in range(1, repetitions + 1):
            sample, document = _ready_sample(
                source,
                source_sha256=source_sha256,
                rule_payload=rule_payload,
                sample_root=work_root / "ready" / f"sample_{index:02d}",
                sample_index=index,
            )
            ready_samples.append(sample)
            documents.append(document)
        confirmation_samples = [
            _confirmation_sample(
                source,
                source_sha256=source_sha256,
                registry=registry,
                sample_root=work_root / "confirmation" / f"sample_{index:02d}",
                sample_index=index,
            )
            for index in range(1, repetitions + 1)
        ]
        repair_samples = [
            _repair_sample(
                source=source,
                registry=registry,
                sample_root=work_root / "repair" / f"sample_{index:02d}",
                sample_index=index,
            )
            for index in range(1, repetitions + 1)
        ]
        visual_samples = [
            _visual_sample(
                source,
                document=documents[index - 1],
                upstream_ready_sample=ready_samples[index - 1],
                sample_root=work_root / "visual" / f"sample_{index:02d}",
                sample_index=index,
            )
            for index in range(1, repetitions + 1)
        ]
        specs = (
            (
                "ready_zero_ai",
                SCENARIO_DESCRIPTIONS["ready_zero_ai"],
                READY_STATE,
                ready_samples,
            ),
            (
                "scientific_confirmation",
                SCENARIO_DESCRIPTIONS["scientific_confirmation"],
                HUMAN_CONFIRMATION_STATE,
                confirmation_samples,
            ),
            (
                "rule_repair",
                SCENARIO_DESCRIPTIONS["rule_repair"],
                RULE_REPAIR_STATE,
                repair_samples,
            ),
            (
                "selected_object_visual_edit",
                SCENARIO_DESCRIPTIONS["selected_object_visual_edit"],
                READY_STATE,
                visual_samples,
            ),
        )
        return [_scenario_record(*spec) for spec in specs]
    finally:
        if work_root.exists():
            shutil.rmtree(work_root)


def _ready_sample(
    source: Path,
    *,
    source_sha256: str,
    rule_payload: dict[str, Any],
    sample_root: Path,
    sample_index: int,
) -> tuple[dict[str, Any], Path]:
    sample_root.mkdir(parents=True, exist_ok=True)
    clear_inspection_cache()
    source_parent_before = _source_parent_snapshot(
        source,
        excluded_root=sample_root,
    )

    def execute() -> tuple[dict[str, Any], int]:
        operation_tmp = sample_root / "tmp"
        operation_tmp.mkdir(parents=True, exist_ok=True)
        with (
            _temporary_workspace(operation_tmp),
            _source_reads(source) as source_reads,
            _ready_write_guard(
                source=source,
                allowed_root=sample_root,
            ) as outside_writes,
            _external_model_call_guard() as model_calls,
        ):
            preview = build_plan_preview(
                source,
                request={
                    "rule_id": _RULE_ID,
                    "template": _TEMPLATE,
                    "explicit_template_selection": True,
                },
            )
            result = run_autoplot(
                source,
                output_root=sample_root / "runtime",
                project_name="performance_r0_baseline",
                delivery_root=sample_root / "delivery",
                rule_id=_RULE_ID,
                template=_TEMPLATE,
            )
        return {
            "preview": preview,
            "result": result,
            "outside_write_attempts": outside_writes(),
            "model_calls": model_calls(),
        }, source_reads()

    bundle, measured = _measure(execute)
    source_parent_after = _source_parent_snapshot(
        source,
        excluded_root=sample_root,
    )
    bundle["source_parent_unchanged"] = (
        source_parent_after == source_parent_before
    )
    preview = bundle["preview"]
    result = bundle["result"]
    planned = preview.get("resolved_figure_plan")
    completed = result.get("figure_plan")
    planned_identity = (
        figure_plan_fact_identity(planned) if isinstance(planned, dict) else {}
    )
    completed_identity = (
        figure_plan_fact_identity(completed) if isinstance(completed, dict) else {}
    )
    persisted_plan_identity = (
        figure_plan_evidence_identity(planned) if isinstance(planned, dict) else {}
    )
    delivery = Path(str(result.get("delivery") or ""))
    documents = sorted((delivery / "project").glob("*.vsz"))
    document = documents[0] if len(documents) == 1 else delivery / "missing.vsz"
    outcome_vsz = _outcome_vsz(completed)
    hashes = rule_contract_hashes(get_rule(_RULE_ID))
    checks = {
        "plan_is_planned": preview.get("status") == "planned",
        "autoplot_is_ready": result.get("state") == READY_STATE
        and result.get("ready_to_use") is True,
        "direct_and_planned_facts_match": planned_identity == completed_identity,
        "validated_envelope_is_current": result.get("validated_envelope", {}).get(
            "contract_current"
        )
        is True,
        "delivery_is_complete": result.get("delivery_complete") is True,
        "one_delivered_vsz_exists": len(documents) == 1 and document.is_file(),
        "raw_source_bytes_unchanged": file_sha256(source) == source_sha256,
        "current_and_delivered_vsz_match": bool(
            outcome_vsz is not None
            and outcome_vsz.is_file()
            and document.is_file()
            and file_sha256(outcome_vsz) == file_sha256(document)
        ),
        "instrumented_writes_confined_to_sample_root": (
            bundle["outside_write_attempts"] == 0
        ),
        "source_parent_unchanged": bundle["source_parent_unchanged"],
    }
    evidence = {
        "stable": {
            "rule_id": _RULE_ID,
            "rule_contract_sha256": hashes.contract_sha256,
            "rule_semantic_contract_sha256": hashes.semantic_contract_sha256,
            **persisted_plan_identity,
            "template": _TEMPLATE,
            "fixture_sha256": source_sha256,
        },
        "sample": {
            "request_sha256": file_sha256(Path(str(result["request_path"]))),
            "delivered_vsz_sha256": (
                file_sha256(document) if document.is_file() else None
            ),
        },
    }
    sample = _sample_record(
        sample_index=sample_index,
        observed_state=str(result.get("state") or RULE_REPAIR_STATE),
        next_action="handoff_ready",
        provider_mode="none",
        provider_outcome="not_used",
        measured=measured,
        raw_source_read_opens=bundle["raw_source_read_opens"],
        model_calls=bundle["model_calls"],
        decision_payload_components={
            "rule_show": rule_payload,
            "plan_preview": preview,
            "autoplot_result": result,
        },
        evidence_identity=evidence,
        reason_codes=list(result.get("integrity", {}).get("reasons") or []),
        checks=checks,
    )
    return sample, document


def _confirmation_sample(
    source: Path,
    *,
    source_sha256: str,
    registry: ValidatedEnvelopeRegistry,
    sample_root: Path,
    sample_index: int,
) -> dict[str, Any]:
    sample_root.mkdir(parents=True, exist_ok=True)

    def execute() -> tuple[dict[str, Any], int]:
        with (
            _temporary_workspace(sample_root / "tmp"),
            _source_reads(source) as source_reads,
            _ready_write_guard(source=source, allowed_root=sample_root) as writes,
            _external_model_call_guard() as model_calls,
        ):
            bundle = _evaluation_bundle(
                source,
                registry=registry,
                explicit_rule=False,
                confidence=_MEDIUM_CONFIDENCE,
            )
            bundle["model_calls"] = model_calls()
            bundle["outside_write_attempts"] = writes()
        return bundle, source_reads()

    bundle, measured = _measure(execute)
    evaluation = bundle["evaluation"]
    reasons = list(evaluation.get("confirmation_reasons") or [])
    checks = {
        "state_requires_human_confirmation": evaluation.get("state")
        == HUMAN_CONFIRMATION_STATE,
        "ready_without_ai_is_false": evaluation.get("ready_without_ai") is False,
        "no_rule_repair_reason": not evaluation.get("repair_reasons"),
        "one_state_reason_exists": bool(reasons),
        "current_runtime_has_no_question_payload": "question" not in evaluation,
        "instrumented_writes_confined_to_sample_root": (
            bundle["outside_write_attempts"] == 0
        ),
    }
    return _sample_record(
        sample_index=sample_index,
        observed_state=str(evaluation.get("state") or RULE_REPAIR_STATE),
        next_action="ask_human",
        provider_mode="none",
        provider_outcome="not_used",
        measured=measured,
        raw_source_read_opens=bundle["raw_source_read_opens"],
        model_calls=bundle["model_calls"],
        decision_payload_components={
            key: bundle[key]
            for key in (
                "semantic",
                "source_package",
                "mapping_package",
                "render_request",
                "evaluation",
            )
        },
        evidence_identity={
            "stable": {
                "rule_id": evaluation.get("rule_id"),
                "current_contract_sha256": evaluation.get(
                    "current_contract_sha256"
                ),
                "current_semantic_contract_sha256": evaluation.get(
                    "current_semantic_contract_sha256"
                ),
                "fixture_sha256": source_sha256,
                "controlled_confidence": _MEDIUM_CONFIDENCE,
                "question_payload_present": False,
            },
            "sample": {},
        },
        reason_codes=reasons,
        checks=checks,
    )


def _repair_sample(
    *,
    source: Path = _SOURCE,
    registry: ValidatedEnvelopeRegistry,
    sample_root: Path,
    sample_index: int,
) -> dict[str, Any]:
    sample_root.mkdir(parents=True, exist_ok=True)
    stale_registry = _stale_registry(registry, rule_id=_RULE_ID)

    def execute() -> tuple[dict[str, Any], int]:
        with (
            _source_reads(source) as source_reads,
            _filesystem_write_opens() as writes,
            _ready_write_guard(source=source, allowed_root=sample_root) as outside_writes,
            _external_model_call_guard() as model_calls,
        ):
            rule = get_rule(_RULE_ID)
            hashes = rule_contract_hashes(rule)
            entry = stale_registry.entry(rule.rule_id)
            invocation = current_rule_invocation_contract_payload(
                rule=rule,
                registry=stale_registry,
            )
            shown = show_rule_payload(
                rule.rule_id,
                invocation_projector=lambda _rule: invocation,
            )
        return {
            "invocation": invocation,
            "shown": shown,
            "current_contract_sha256": hashes.contract_sha256,
            "current_semantic_contract_sha256": hashes.semantic_contract_sha256,
            "certified_contract_sha256": (
                entry.contract_sha256 if entry is not None else None
            ),
            "certified_semantic_contract_sha256": (
                entry.semantic_contract_sha256 if entry is not None else None
            ),
            "filesystem_write_opens": writes(),
            "outside_write_attempts": outside_writes(),
            "model_calls": model_calls(),
        }, source_reads()

    bundle, measured = _measure(execute)
    invocation = bundle["invocation"]
    reasons = list(invocation.get("reason_codes") or [])
    checks = {
        "state_requires_rule_repair": invocation.get("availability")
        == RULE_REPAIR_STATE,
        "stale_registry_is_reported": (
            "certified_rule_contract_sha256_mismatch" in reasons
            and "certified_rule_semantic_contract_sha256_mismatch" in reasons
        ),
        "invocation_stops_before_execution": invocation.get("availability")
        == RULE_REPAIR_STATE,
        "raw_source_was_not_opened": bundle["raw_source_read_opens"] == 0,
        "filesystem_was_not_opened_for_write": bundle["filesystem_write_opens"]
        == 0,
        "show_reuses_same_invocation": bundle["shown"].get("invocation")
        == invocation,
        "instrumented_writes_confined_to_sample_root": (
            bundle["outside_write_attempts"] == 0
        ),
    }
    return _sample_record(
        sample_index=sample_index,
        observed_state=RULE_REPAIR_STATE,
        next_action="handoff_rule_repair",
        provider_mode="none",
        provider_outcome="not_used",
        measured=measured,
        raw_source_read_opens=bundle["raw_source_read_opens"],
        model_calls=bundle["model_calls"],
        decision_payload_components={"rule_show": bundle["shown"]},
        evidence_identity={
            "stable": {
                "rule_id": _RULE_ID,
                "current_contract_sha256": bundle["current_contract_sha256"],
                "current_semantic_contract_sha256": bundle[
                    "current_semantic_contract_sha256"
                ],
                "certified_contract_sha256": bundle["certified_contract_sha256"],
                "certified_semantic_contract_sha256": bundle[
                    "certified_semantic_contract_sha256"
                ],
                "invocation_reason_codes": reasons,
            },
            "sample": {
                "filesystem_write_opens": bundle["filesystem_write_opens"]
            },
        },
        reason_codes=reasons,
        checks=checks,
    )


def _visual_sample(
    source: Path,
    *,
    document: Path,
    upstream_ready_sample: dict[str, Any],
    sample_root: Path,
    sample_index: int,
) -> dict[str, Any]:
    sample_root.mkdir(parents=True, exist_ok=True)
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

    def execute() -> tuple[dict[str, Any], int]:
        with (
            _temporary_workspace(sample_root / "tmp"),
            _source_reads(source) as source_reads,
            _ready_write_guard(source=source, allowed_root=sample_root) as writes,
            _external_model_call_guard() as model_calls,
        ):
            result = _run_selected_object_cycle(
                document,
                output_root=sample_root,
            )
            result["model_calls"] = model_calls()
            result["outside_write_attempts"] = writes()
        return result, source_reads()

    result, measured = _measure(execute)
    checks = dict(result["checks"])
    upstream_checks = upstream_ready_sample.get("checks")
    upstream_evidence = upstream_ready_sample.get("evidence_identity")
    upstream_evidence = (
        upstream_evidence if isinstance(upstream_evidence, dict) else {}
    )
    upstream_sample_evidence = upstream_evidence.get("sample")
    upstream_sample_evidence = (
        upstream_sample_evidence
        if isinstance(upstream_sample_evidence, dict)
        else {}
    )
    checks["upstream_ready_document_is_bound"] = (
        upstream_ready_sample.get("status") == "passed"
        and upstream_ready_sample.get("observed_state") == READY_STATE
        and isinstance(upstream_checks, dict)
        and bool(upstream_checks)
        and all(value is True for value in upstream_checks.values())
        and upstream_sample_evidence.get("delivered_vsz_sha256")
        == file_sha256(document)
        == result["evidence_identity"]["sample"]["source_document_sha256"]
    )
    checks["source_data_was_not_read"] = result["raw_source_read_opens"] == 0
    checks["instrumented_writes_confined_to_sample_root"] = (
        result["outside_write_attempts"] == 0
    )
    stable_upstream = upstream_evidence.get("stable")
    stable_upstream = stable_upstream if isinstance(stable_upstream, dict) else {}
    result["evidence_identity"]["stable"]["upstream_plan_sha256"] = (
        stable_upstream.get("plan_sha256")
    )
    return _sample_record(
        sample_index=sample_index,
        observed_state=str(upstream_ready_sample.get("observed_state")),
        next_action="handoff_ready",
        provider_mode="offline_fixture",
        provider_outcome="completed",
        measured=measured,
        raw_source_read_opens=result["raw_source_read_opens"],
        model_calls=result["model_calls"],
        decision_payload_components=result["decision_payload_components"],
        provider_payload_bytes=result["request_metrics"]["payload_bytes"],
        provider_context_bytes=result["request_metrics"]["context_bytes"],
        image_bytes=result["request_metrics"]["image_bytes"],
        provider_requests=result["provider_request_count"],
        submit_to_proposal_ms=result["timings_ms"]["submit_to_proposal"],
        proposal_to_applied_ms=result["timings_ms"]["proposal_to_applied"],
        evidence_identity=result["evidence_identity"],
        reason_codes=[],
        checks=checks,
    )


def _run_selected_object_cycle(
    document: Path,
    *,
    output_root: Path,
) -> dict[str, Any]:
    """Run one offline submit/proposal/accept/Undo cycle in one Veusz document."""

    from sciplot_core import studio_assistant_probe as assistant_probe
    from sciplot_gui.studio_assistant_history import read_assistant_history

    source_document = document.expanduser().resolve()
    copied_document = output_root / "document.vsz"
    source_document_sha256 = _copy_exact_current_document(
        source_document,
        copied_document,
    )
    before_png = output_root / "before.png"
    applied_png = output_root / "applied.png"
    undo_png = output_root / "undo.png"
    window: Any | None = None
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

    try:
        from PyQt6 import QtWidgets

        from sciplot_core.studio import _ensure_veusz_on_path

        _ensure_veusz_on_path()
        application = QtWidgets.QApplication.instance()
        if application is None:
            application = QtWidgets.QApplication([])
        application.setApplicationName("SciPlot R0 Selected-object Baseline")
        application.setQuitOnLastWindowClosed(False)

        provider = assistant_probe.DeterministicStudioAssistantProvider()
        window, bridge = assistant_probe._create_window(
            copied_document,
            provider=provider,
        )
        window.resize(1200, 820)
        window.show()
        assistant_probe._wait_until(
            application,
            lambda: bool(window.isVisible()),
            timeout_ms=2000,
        )
        axis = assistant_probe._axis_widget(window.document)
        bridge.set_selected_widget(axis)
        setting_path = f"{axis.path}/label"
        label_setting = window.document.resolveSettingPath(None, setting_path)
        original_label = json_safe(label_setting.get())
        next_label = (
            f"{original_label} · R0"
            if str(original_label).strip()
            else "Selected axis · R0"
        )
        before = assistant_probe._capture_plot(bridge, before_png)
        applied_events: list[dict[str, Any]] = []
        bridge.proposalApplied.connect(lambda value: applied_events.append(dict(value)))

        provider.configure(next_value=next_label)
        submit_started = time.perf_counter_ns()
        request = bridge.submit_intent(
            "Make the selected axis label visibly clearer in one bounded edit."
        )
        proposal_ready = assistant_probe._wait_until(
            application,
            lambda: bridge.pending_batch is not None and not bridge.runner.active,
        )
        proposal_ready_at = time.perf_counter_ns()
        if not proposal_ready:
            raise RuntimeError("The offline selected-object proposal did not complete.")
        pending_response = bridge._pending_response
        if pending_response is None:
            raise RuntimeError("The offline selected-object response was not retained.")
        provider_response_payload = pending_response.to_dict()
        apply_result = bridge.accept_pending()
        applied = assistant_probe._wait_until(
            application,
            lambda: bool(applied_events),
        )
        applied_at = time.perf_counter_ns()
        if not applied or apply_result is None:
            raise RuntimeError("The offline selected-object proposal was not applied.")

        applied_capture = assistant_probe._capture_plot(bridge, applied_png)
        provider_request = next(
            item for item in provider.requests if item.request_id == request.request_id
        )
        request_payload = provider_request.to_dict()
        request_metrics = _assistant_request_metrics(request_payload)
        input_payload_components = {
            "intent": request.intent,
            "base_revision": request.base_revision,
            "context": request.context,
            "visual_preview_metadata": assistant_probe._visual_preview_metadata(
                request.visual_preview
            ),
        }
        history = [
            event
            for event in read_assistant_history(bridge.history_path)
            if event.get("request_id") == request.request_id
        ]
        applied_value = json_safe(label_setting.get())
        window.slotEditUndo()
        undo_capture = assistant_probe._capture_plot(bridge, undo_png)
        undo_value = json_safe(label_setting.get())
        undo_evidence = {
            "original_value": original_label,
            "applied_value": applied_value,
            "undo_value": undo_value,
            "before_render_sha256": before["sha256"],
            "applied_render_sha256": applied_capture["sha256"],
            "undo_render_sha256": undo_capture["sha256"],
            "source_document_sha256": source_document_sha256,
            "copied_document_sha256": file_sha256(copied_document),
        }
        decision_payload_components = {
            **input_payload_components,
            "provider_response": provider_response_payload,
            "apply_result": apply_result,
            "transaction_history": history,
            "undo_evidence": undo_evidence,
        }
        context = request_payload.get("context")
        context = context if isinstance(context, dict) else {}
        raw_arrays_absent = (
            context.get("raw_dataset_arrays_included") is False
            and "datasets" not in context
        )
        statuses = [str(event.get("status")) for event in history]
        checks = {
            "one_offline_provider_request": len(provider.requests) == 1,
            "proposal_completed_before_apply": proposal_ready,
            "manual_accept_applied_one_batch": (
                applied_value == next_label
                and len(applied_events) == 1
                and apply_result["verification_status"] == "applied"
            ),
            "exact_current_preview_was_bound": (
                request.base_revision == before["revision"]
                and request.visual_preview is not None
                and request.visual_preview["sha256"] == before["sha256"]
                and request.payload_sha256 == provider_request.payload_sha256
            ),
            "raw_dataset_arrays_absent": raw_arrays_absent,
            "render_changed_after_apply": applied_capture["sha256"] != before["sha256"],
            "history_has_one_complete_transaction": statuses
            == ["submitted", "proposal_ready", "apply_started", "applied"],
            "native_undo_restores_prior_state": (
                undo_value == original_label
                and undo_capture["sha256"] == before["sha256"]
            ),
            "source_and_copy_bytes_remain_unchanged": (
                file_sha256(source_document) == source_document_sha256
                and file_sha256(copied_document) == source_document_sha256
            ),
        }
        return {
            "assistant_terminal_status": "applied",
            "provider_request_count": len(provider.requests),
            "request_metrics": request_metrics,
            "decision_payload_components": decision_payload_components,
            "timings_ms": {
                "submit_to_proposal": round(
                    (proposal_ready_at - submit_started) / 1_000_000,
                    3,
                ),
                "proposal_to_applied": round(
                    (applied_at - proposal_ready_at) / 1_000_000,
                    3,
                ),
            },
            "evidence_identity": {
                "stable": {
                    "provider_id": provider.descriptor.provider_id,
                    "selected_widget_type": str(axis.typename),
                    "setting_suffix": "/label",
                    "history_statuses": statuses,
                },
                "sample": {
                    "source_document_sha256": source_document_sha256,
                    "request_sha256": request.payload_sha256,
                    "context_sha256": request.context_sha256,
                    "provider_payload_sha256": canonical_json_sha256(
                        request_payload, allow_nan=False
                    ),
                    "base_revision": request.base_revision,
                    "before_render_sha256": before["sha256"],
                    "applied_render_sha256": applied_capture["sha256"],
                    "undo_render_sha256": undo_capture["sha256"],
                },
            },
            "checks": checks,
        }
    finally:
        assistant_probe._close_window(window)


def _copy_exact_current_document(source: Path, destination: Path) -> str:
    """Copy one VSZ only when source and copied bytes share one stable identity."""

    source_sha256_before = file_sha256(source)
    shutil.copy2(source, destination)
    source_sha256_after = file_sha256(source)
    copied_sha256 = file_sha256(destination)
    if not (
        source_sha256_before == source_sha256_after == copied_sha256
    ):
        raise RuntimeError(
            "Selected-object baseline copy is not the exact-current source document."
        )
    return source_sha256_before


def _evaluation_bundle(
    source: Path,
    *,
    registry: ValidatedEnvelopeRegistry,
    explicit_rule: bool,
    confidence: float | None,
) -> dict[str, Any]:
    rule = get_rule(_RULE_ID)
    semantic = semantic_payload_from_rule(
        rule,
        confidence=(confidence if confidence is not None else 95.0),
        reason="R0 controlled replay of the current source-bound rule contract.",
    )
    request: dict[str, Any] = {
        "recipe": "auto",
        "rule_id": _RULE_ID,
        "template": _TEMPLATE,
        "input": "redacted",
        "output": "redacted",
        "exports": list(DEFAULT_EXPORT_FORMATS_POLICY),
        "render_options": normalize_render_options(AUTOPLOT_RENDER_OPTIONS),
        "explicit_render_option_keys": [],
    }
    mapping_request = request if explicit_rule else {
        key: value
        for key, value in request.items()
        if key not in {"rule_id", "template"}
    }
    source_package = build_source_package(input_path=source, semantic=semantic)
    mapping_package = build_mapping_package(
        request=mapping_request,
        semantic=semantic,
    )
    render_request = build_render_request_package(
        request_path=Path("redacted_plot_request.json"),
        request=request,
    )
    evaluation = evaluate_validated_envelope(
        semantic=semantic,
        source_package=source_package,
        mapping_package=mapping_package,
        render_request=render_request,
        registry=registry,
    )
    return {
        "semantic": semantic,
        "source_package": source_package,
        "mapping_package": mapping_package,
        "render_request": render_request,
        "evaluation": evaluation,
    }


def _sample_record(
    *,
    sample_index: int,
    observed_state: str,
    next_action: str,
    provider_mode: str,
    provider_outcome: str,
    measured: dict[str, Any],
    raw_source_read_opens: int,
    model_calls: int,
    decision_payload_components: dict[str, Any],
    evidence_identity: dict[str, Any],
    reason_codes: list[str],
    checks: dict[str, bool],
    provider_payload_bytes: int = 0,
    provider_context_bytes: int = 0,
    image_bytes: int = 0,
    provider_requests: int = 0,
    submit_to_proposal_ms: float | None = None,
    proposal_to_applied_ms: float | None = None,
) -> dict[str, Any]:
    projected_components = {
        key: payload_measurement_projection(value)
        for key, value in decision_payload_components.items()
    }
    payload_components = {
        key: {
            "bytes": canonical_json_bytes(value),
            "sha256": canonical_json_sha256(value, allow_nan=False),
        }
        for key, value in projected_components.items()
    }
    metrics = {
        **measured,
        "raw_source_read_opens": raw_source_read_opens,
        "full_decision_payload_bytes": sum(
            component["bytes"] for component in payload_components.values()
        ),
        "provider_payload_bytes": provider_payload_bytes,
        "provider_context_bytes": provider_context_bytes,
        "image_bytes": image_bytes,
        "provider_requests": provider_requests,
        "model_calls": model_calls,
        "submit_to_proposal_ms": submit_to_proposal_ms,
        "proposal_to_applied_ms": proposal_to_applied_ms,
    }
    return {
        "sample_index": sample_index,
        "status": "passed" if checks and all(checks.values()) else "failed",
        "observed_state": observed_state,
        "next_action": next_action,
        "provider_mode": provider_mode,
        "provider_outcome": provider_outcome,
        "metrics": metrics,
        "payload_components": payload_components,
        "token_usage": {
            "input_tokens": None,
            "output_tokens": None,
            "basis": "offline_replay_no_token_usage",
        },
        "evidence_identity": json_safe(evidence_identity),
        "reason_codes": reason_codes,
        "checks": checks,
    }


def _scenario_record(
    scenario_id: str,
    description: str,
    expected_state: str,
    samples: list[dict[str, Any]],
) -> dict[str, Any]:
    evidence = [sample["evidence_identity"] for sample in samples]
    stable = [
        item.get("stable") if isinstance(item, dict) else None for item in evidence
    ]
    stable_identical = all(item == stable[0] for item in stable)
    return {
        "scenario_id": scenario_id,
        "description": description,
        "expected_state": expected_state,
        "status": "passed"
        if samples
        and stable_identical
        and all(
            sample["status"] == "passed"
            and sample["observed_state"] == expected_state
            for sample in samples
        )
        else "failed",
        "samples": samples,
        "metrics": metric_distribution([sample["metrics"] for sample in samples]),
        "stable_evidence": {
            "identical_across_samples": stable_identical,
            "first": stable[0],
        },
    }


def _measure(
    callback: Callable[[], tuple[dict[str, Any], int]],
) -> tuple[dict[str, Any], dict[str, Any]]:
    gc.collect()
    tracemalloc.start()
    started = time.perf_counter_ns()
    try:
        value, raw_source_read_opens = callback()
        wall_time_ms = (time.perf_counter_ns() - started) / 1_000_000
        _current, peak = tracemalloc.get_traced_memory()
    finally:
        if tracemalloc.is_tracing():
            tracemalloc.stop()
    value["raw_source_read_opens"] = raw_source_read_opens
    return value, {
        "wall_time_ms": round(wall_time_ms, 3),
        "peak_python_memory_bytes": peak,
    }


@contextmanager
def _source_reads(source: Path) -> Iterator[Callable[[], int]]:
    resolved = source.expanduser().resolve()
    original_open = builtins.open
    original_io_open = io.open
    count = 0

    def matches(file: Any, args: tuple[Any, ...], kwargs: dict[str, Any]) -> bool:
        if isinstance(file, int):
            return False
        try:
            candidate = Path(file).expanduser().resolve()
        except (OSError, TypeError, ValueError):
            return False
        mode = str(args[0] if args else kwargs.get("mode", "r"))
        return candidate == resolved and not any(flag in mode for flag in "wax+")

    def tracked_open(file: Any, *args: Any, **kwargs: Any) -> Any:
        nonlocal count
        if matches(file, args, kwargs):
            count += 1
        return original_open(file, *args, **kwargs)

    def tracked_io_open(file: Any, *args: Any, **kwargs: Any) -> Any:
        nonlocal count
        if matches(file, args, kwargs):
            count += 1
        return original_io_open(file, *args, **kwargs)

    builtins.open = tracked_open
    io.open = tracked_io_open
    try:
        yield lambda: count
    finally:
        builtins.open = original_open
        io.open = original_io_open


@contextmanager
def _filesystem_write_opens() -> Iterator[Callable[[], int]]:
    original_open = builtins.open
    original_io_open = io.open
    count = 0

    def is_write(args: tuple[Any, ...], kwargs: dict[str, Any]) -> bool:
        mode = str(args[0] if args else kwargs.get("mode", "r"))
        return any(flag in mode for flag in "wax+")

    def tracked_open(file: Any, *args: Any, **kwargs: Any) -> Any:
        nonlocal count
        if not isinstance(file, int) and is_write(args, kwargs):
            count += 1
            raise RuntimeError(
                "R0 repair preflight attempted a forbidden filesystem write."
            )
        return original_open(file, *args, **kwargs)

    def tracked_io_open(file: Any, *args: Any, **kwargs: Any) -> Any:
        nonlocal count
        if not isinstance(file, int) and is_write(args, kwargs):
            count += 1
            raise RuntimeError(
                "R0 repair preflight attempted a forbidden filesystem write."
            )
        return original_io_open(file, *args, **kwargs)

    builtins.open = tracked_open
    io.open = tracked_io_open
    try:
        yield lambda: count
    finally:
        builtins.open = original_open
        io.open = original_io_open


@contextmanager
def _ready_write_guard(
    *, source: Path, allowed_root: Path
) -> Iterator[Callable[[], int]]:
    """Reject instrumented path mutations and unapproved child launches."""

    resolved_source = source.expanduser().resolve()
    resolved_allowed = allowed_root.expanduser().resolve()
    original_open = builtins.open
    original_io_open = io.open
    original_os_open = os.open
    original_mkdir = os.mkdir
    original_makedirs = os.makedirs
    original_rename = os.rename
    original_replace = os.replace
    original_remove = os.remove
    original_unlink = os.unlink
    original_rmdir = os.rmdir
    original_symlink = os.symlink
    original_link = os.link
    original_chmod = os.chmod
    original_utime = os.utime
    original_truncate = os.truncate
    original_mkfifo = os.mkfifo
    original_mknod = os.mknod
    original_chdir = os.chdir
    original_fchdir = os.fchdir
    original_popen = subprocess.Popen
    original_system = os.system
    original_spawn_functions = {
        name: getattr(os, name)
        for name in (
            "spawnl",
            "spawnle",
            "spawnlp",
            "spawnlpe",
            "spawnv",
            "spawnve",
            "spawnvp",
            "spawnvpe",
            "posix_spawn",
            "posix_spawnp",
            "fork",
            "forkpty",
        )
        if hasattr(os, name)
    }
    outside_attempts = 0
    approved_popen_depth = 0
    trusted_cwd = REPO_ROOT.resolve()
    if Path.cwd().resolve() != trusted_cwd:
        raise RuntimeError(
            "R0 automation baseline must run from the repository root."
        )
    trusted_process_environment = dict(os.environ)
    trusted_worker_environment = validated_terminal_worker_environment_base(
        veusz_worker_environment()
    )

    def fd_path(fd: int) -> Path | None:
        try:
            return Path(os.readlink(f"/proc/self/fd/{fd}"))
        except OSError:
            try:
                import fcntl

                raw = fcntl.fcntl(fd, 50, b"\0" * 1024)
                return Path(raw.split(b"\0", 1)[0].decode())
            except (ImportError, OSError, UnicodeDecodeError, ValueError):
                return None

    def resolve_target(
        file: Any,
        *,
        dir_fd: int | None = None,
    ) -> tuple[Path, Path] | None:
        if isinstance(file, int):
            candidate = fd_path(file)
            if candidate is None:
                return None
        else:
            try:
                candidate = Path(file).expanduser()
            except (OSError, TypeError, ValueError):
                return None
        try:
            if dir_fd is not None and not candidate.is_absolute():
                base = fd_path(dir_fd)
                if base is None:
                    return None
                candidate = base / candidate
            lexical = Path(os.path.abspath(os.fspath(candidate)))
            return lexical, candidate.resolve(strict=False)
        except (OSError, TypeError, ValueError):
            return None

    def require_allowed(file: Any, *, dir_fd: int | None = None) -> None:
        nonlocal outside_attempts
        locations = resolve_target(file, dir_fd=dir_fd)
        if locations is not None and all(
            candidate == Path("/dev/null") for candidate in locations
        ):
            return
        if locations is not None and all(
            candidate.is_relative_to(resolved_allowed) for candidate in locations
        ):
            return
        outside_attempts += 1
        if locations is not None and resolved_source in locations:
            raise RuntimeError(
                "R0 ready baseline attempted a forbidden raw-source write."
            )
        raise RuntimeError(
            "R0 ready baseline attempted a write outside its evidence root."
        )

    def is_write_mode(args: tuple[Any, ...], kwargs: dict[str, Any]) -> bool:
        mode = str(args[0] if args else kwargs.get("mode", "r"))
        return any(flag in mode for flag in "wax+")

    def guarded_open(file: Any, *args: Any, **kwargs: Any) -> Any:
        if is_write_mode(args, kwargs):
            require_allowed(file)
        return original_open(file, *args, **kwargs)

    def guarded_io_open(file: Any, *args: Any, **kwargs: Any) -> Any:
        if is_write_mode(args, kwargs):
            require_allowed(file)
        return original_io_open(file, *args, **kwargs)

    def guarded_os_open(
        file: Any,
        flags: int,
        mode: int = 0o777,
        *,
        dir_fd: int | None = None,
    ) -> int:
        write_flags = os.O_WRONLY | os.O_RDWR | os.O_CREAT | os.O_TRUNC | os.O_APPEND
        if flags & write_flags:
            require_allowed(file, dir_fd=dir_fd)
        return original_os_open(file, flags, mode, dir_fd=dir_fd)

    def guarded_mkdir(
        path: Any,
        mode: int = 0o777,
        *,
        dir_fd: int | None = None,
    ) -> None:
        require_allowed(path, dir_fd=dir_fd)
        original_mkdir(path, mode, dir_fd=dir_fd)

    def guarded_makedirs(
        name: Any,
        mode: int = 0o777,
        exist_ok: bool = False,
    ) -> None:
        require_allowed(name)
        original_makedirs(name, mode=mode, exist_ok=exist_ok)

    def guarded_rename(
        src: Any,
        dst: Any,
        *,
        src_dir_fd: int | None = None,
        dst_dir_fd: int | None = None,
    ) -> None:
        require_allowed(src, dir_fd=src_dir_fd)
        require_allowed(dst, dir_fd=dst_dir_fd)
        original_rename(
            src,
            dst,
            src_dir_fd=src_dir_fd,
            dst_dir_fd=dst_dir_fd,
        )

    def guarded_replace(
        src: Any,
        dst: Any,
        *,
        src_dir_fd: int | None = None,
        dst_dir_fd: int | None = None,
    ) -> None:
        require_allowed(src, dir_fd=src_dir_fd)
        require_allowed(dst, dir_fd=dst_dir_fd)
        original_replace(
            src,
            dst,
            src_dir_fd=src_dir_fd,
            dst_dir_fd=dst_dir_fd,
        )

    def guarded_remove(path: Any, *, dir_fd: int | None = None) -> None:
        require_allowed(path, dir_fd=dir_fd)
        original_remove(path, dir_fd=dir_fd)

    def guarded_unlink(path: Any, *, dir_fd: int | None = None) -> None:
        require_allowed(path, dir_fd=dir_fd)
        original_unlink(path, dir_fd=dir_fd)

    def guarded_rmdir(path: Any, *, dir_fd: int | None = None) -> None:
        require_allowed(path, dir_fd=dir_fd)
        original_rmdir(path, dir_fd=dir_fd)

    def guarded_symlink(
        src: Any,
        dst: Any,
        target_is_directory: bool = False,
        *,
        dir_fd: int | None = None,
    ) -> None:
        require_allowed(dst, dir_fd=dir_fd)
        destination = resolve_target(dst, dir_fd=dir_fd)
        if destination is None:
            require_allowed(dst, dir_fd=dir_fd)
        else:
            link_target = Path(src).expanduser()
            if not link_target.is_absolute():
                link_target = destination[0].parent / link_target
            require_allowed(link_target)
        original_symlink(
            src,
            dst,
            target_is_directory=target_is_directory,
            dir_fd=dir_fd,
        )

    def guarded_link(
        src: Any,
        dst: Any,
        *,
        src_dir_fd: int | None = None,
        dst_dir_fd: int | None = None,
        follow_symlinks: bool = True,
    ) -> None:
        require_allowed(src, dir_fd=src_dir_fd)
        require_allowed(dst, dir_fd=dst_dir_fd)
        original_link(
            src,
            dst,
            src_dir_fd=src_dir_fd,
            dst_dir_fd=dst_dir_fd,
            follow_symlinks=follow_symlinks,
        )

    def guarded_path_mutation(
        original: Callable[..., Any],
    ) -> Callable[..., Any]:
        def guarded(path: Any, *args: Any, **kwargs: Any) -> Any:
            require_allowed(path, dir_fd=kwargs.get("dir_fd"))
            return original(path, *args, **kwargs)

        return guarded

    def allowlisted_worker_command(command: object) -> bool:
        if not isinstance(command, (list, tuple)) or len(command) < 4:
            return False
        argv = [os.fspath(value) for value in command]
        try:
            executable_matches = Path(argv[0]).resolve() == Path(sys.executable).resolve()
        except (OSError, ValueError):
            return False
        if not executable_matches or argv[1:3] != ["-m", "sciplot_core.veusz_worker"]:
            return False
        operation = argv[3]
        if operation == "export":
            paths = argv[4:5]
        elif operation == "audit-documents":
            paths = argv[4:]
        else:
            return False
        if not paths:
            return False
        try:
            for path in paths:
                require_allowed(path)
        except RuntimeError:
            return False
        return True

    def trusted_popen_request(
        command: object,
        kwargs: dict[str, Any],
    ) -> bool:
        stdin = kwargs.get("stdin")
        stdout = kwargs.get("stdout")
        stderr = kwargs.get("stderr")
        if (
            stdin is not None
            or kwargs.get("pass_fds", ()) != ()
            or kwargs.get("close_fds", True) is not True
        ):
            return False
        if (
            kwargs.get("shell")
            or kwargs.get("executable") is not None
            or kwargs.get("preexec_fn") is not None
            or kwargs.get("cwd") is not None
            or Path.cwd().resolve() != trusted_cwd
        ):
            return False
        if command in (["uname", "-p"], ("uname", "-p")):
            resolved_uname = shutil.which("uname")
            return (
                stdout == subprocess.PIPE
                and stderr == subprocess.DEVNULL
                and kwargs.get("env") is None
                and dict(os.environ) == trusted_process_environment
                and resolved_uname is not None
                and Path(resolved_uname).resolve()
                in {Path("/usr/bin/uname"), Path("/bin/uname")}
            )
        if not allowlisted_worker_command(command):
            return False
        environment = kwargs.get("env")
        if not isinstance(environment, dict):
            return False
        python_path = environment.get("PYTHONPATH")
        if not isinstance(python_path, str):
            return False
        try:
            source_root = Path(
                environment.get("SCIPLOT_SOURCE_ROOT", REPO_ROOT / "src")
            ).resolve()
            python_roots = [
                Path(value).expanduser().resolve()
                for value in python_path.split(os.pathsep)
                if value
            ]
        except (OSError, TypeError, ValueError):
            return False
        if (
            source_root != (REPO_ROOT / "src").resolve()
            or not python_roots
            or any(root != source_root for root in python_roots)
            or stdout != subprocess.PIPE
            or stderr != subprocess.PIPE
        ):
            return False
        try:
            candidate_environment = validated_terminal_worker_environment_base(
                environment
            )
        except ValueError:
            return False
        return candidate_environment == trusted_worker_environment

    def guarded_popen(*args: Any, **kwargs: Any) -> Any:
        nonlocal approved_popen_depth, outside_attempts
        if len(args) > 1 or (args and "args" in kwargs):
            outside_attempts += 1
            raise RuntimeError(
                "R0 ready baseline attempted an unapproved child-process launch."
            )
        command = kwargs.get("args", args[0] if args else None)
        if not trusted_popen_request(command, kwargs):
            outside_attempts += 1
            raise RuntimeError(
                "R0 ready baseline attempted an unapproved child-process launch."
            )
        approved_popen_depth += 1
        try:
            return original_popen(*args, **kwargs)
        finally:
            approved_popen_depth -= 1

    def blocked_process_launch(*args: Any, **kwargs: Any) -> Any:
        del args, kwargs
        nonlocal outside_attempts
        outside_attempts += 1
        raise RuntimeError(
            "R0 ready baseline attempted an unapproved child-process launch."
        )

    def blocked_chdir(*args: Any, **kwargs: Any) -> Any:
        del args, kwargs
        nonlocal outside_attempts
        outside_attempts += 1
        raise RuntimeError(
            "R0 ready baseline attempted to change the trusted working directory."
        )

    def guarded_low_level_spawn(
        original: Callable[..., Any],
    ) -> Callable[..., Any]:
        def guarded(*args: Any, **kwargs: Any) -> Any:
            if approved_popen_depth:
                return original(*args, **kwargs)
            return blocked_process_launch(*args, **kwargs)

        return guarded

    builtins.open = guarded_open
    io.open = guarded_io_open
    os.open = guarded_os_open
    os.mkdir = guarded_mkdir
    os.makedirs = guarded_makedirs
    os.rename = guarded_rename
    os.replace = guarded_replace
    os.remove = guarded_remove
    os.unlink = guarded_unlink
    os.rmdir = guarded_rmdir
    os.symlink = guarded_symlink
    os.link = guarded_link
    os.chmod = guarded_path_mutation(original_chmod)
    os.utime = guarded_path_mutation(original_utime)
    os.truncate = guarded_path_mutation(original_truncate)
    os.mkfifo = guarded_path_mutation(original_mkfifo)
    os.mknod = guarded_path_mutation(original_mknod)
    os.chdir = blocked_chdir
    os.fchdir = blocked_chdir
    subprocess.Popen = guarded_popen
    os.system = blocked_process_launch
    for name, original in original_spawn_functions.items():
        setattr(os, name, guarded_low_level_spawn(original))
    try:
        yield lambda: outside_attempts
    finally:
        builtins.open = original_open
        io.open = original_io_open
        os.open = original_os_open
        os.mkdir = original_mkdir
        os.makedirs = original_makedirs
        os.rename = original_rename
        os.replace = original_replace
        os.remove = original_remove
        os.unlink = original_unlink
        os.rmdir = original_rmdir
        os.symlink = original_symlink
        os.link = original_link
        os.chmod = original_chmod
        os.utime = original_utime
        os.truncate = original_truncate
        os.mkfifo = original_mkfifo
        os.mknod = original_mknod
        os.chdir = original_chdir
        os.fchdir = original_fchdir
        subprocess.Popen = original_popen
        os.system = original_system
        for name, original in original_spawn_functions.items():
            setattr(os, name, original)


def _source_parent_snapshot(
    source: Path,
    *,
    excluded_root: Path,
) -> dict[str, tuple[str, int, str | None]]:
    """Fingerprint persistent source-adjacent paths without rereading source."""

    parent = source.expanduser().resolve().parent
    excluded_source = source.expanduser().resolve()
    excluded = excluded_root.expanduser().resolve()
    snapshot: dict[str, tuple[str, int, str | None]] = {}
    stack = [parent]
    while stack:
        current = stack.pop()
        with os.scandir(current) as entries:
            for entry in entries:
                path = Path(entry.path)
                try:
                    lexical = Path(os.path.abspath(os.fspath(path)))
                    if lexical == excluded_source or lexical.is_relative_to(excluded):
                        continue
                    relative = path.relative_to(parent).as_posix()
                    metadata = entry.stat(follow_symlinks=False)
                    mode = metadata.st_mode
                    if entry.is_symlink():
                        snapshot[relative] = ("symlink", mode, os.readlink(path))
                    elif entry.is_dir(follow_symlinks=False):
                        snapshot[relative] = ("directory", mode, None)
                        stack.append(path)
                    elif entry.is_file(follow_symlinks=False):
                        snapshot[relative] = ("file", mode, file_sha256(path))
                    else:
                        snapshot[relative] = ("other", mode, None)
                except FileNotFoundError:
                    snapshot[entry.name] = ("race", 0, None)
    return snapshot


@contextmanager
def _temporary_workspace(root: Path) -> Iterator[None]:
    """Direct Python and child-process temporary files into one allowed root."""

    root.mkdir(parents=True, exist_ok=True)
    original_tempdir = tempfile.tempdir
    original_environment = {
        key: os.environ.get(key) for key in ("TMPDIR", "TEMP", "TMP")
    }
    tempfile.tempdir = str(root)
    for key in original_environment:
        os.environ[key] = str(root)
    try:
        yield
    finally:
        tempfile.tempdir = original_tempdir
        for key, value in original_environment.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value


@contextmanager
def _external_model_call_guard() -> Iterator[Callable[[], int]]:
    """Block the current production model adapter and count attempted calls."""

    from sciplot_core.openai_provider.provider import OpenAIResponsesProvider
    from sciplot_core.openai_provider.sse_client import _ResponsesSSEClient

    original_generate = OpenAIResponsesProvider.generate
    original_stream = _ResponsesSSEClient.stream
    count = 0

    def blocked(*_args: Any, **_kwargs: Any) -> Any:
        nonlocal count
        count += 1
        raise RuntimeError("R0 automation baseline attempted an external model call.")

    OpenAIResponsesProvider.generate = blocked
    _ResponsesSSEClient.stream = blocked
    try:
        yield lambda: count
    finally:
        OpenAIResponsesProvider.generate = original_generate
        _ResponsesSSEClient.stream = original_stream


def _assistant_request_metrics(payload: dict[str, Any]) -> dict[str, int]:
    visual = payload.get("visual_preview")
    encoded = visual.get("base64") if isinstance(visual, dict) else None
    image_bytes = (
        len(base64.b64decode(encoded.encode("ascii"), validate=True))
        if isinstance(encoded, str) and encoded
        else 0
    )
    return {
        "payload_bytes": canonical_json_bytes(payload),
        "context_bytes": canonical_json_bytes(payload.get("context") or {}),
        "image_bytes": image_bytes,
    }


def _outcome_vsz(plan: object) -> Path | None:
    if not isinstance(plan, dict):
        return None
    outcomes = plan.get("outcomes")
    if not isinstance(outcomes, list):
        return None
    candidates = [
        Path(str(path))
        for outcome in outcomes
        if isinstance(outcome, dict)
        for path in outcome.get("artifacts", [])
        if isinstance(path, str) and path.casefold().endswith(".vsz")
    ]
    return candidates[0] if len(candidates) == 1 else None


def _stale_registry(
    registry: ValidatedEnvelopeRegistry,
    *,
    rule_id: str,
) -> ValidatedEnvelopeRegistry:
    payload = registry.to_dict()
    entry = next(item for item in payload["entries"] if item["rule_id"] == rule_id)
    entry["contract_sha256"] = "0" * 64
    entry["semantic_contract_sha256"] = "1" * 64
    return ValidatedEnvelopeRegistry.from_dict(payload)


def _markdown_report(report: dict[str, Any]) -> str:
    rows = []
    for scenario in report["scenarios"]:
        metrics = scenario["metrics"]
        rows.append(
            "| {scenario_id} | {status} | {state} | {wall:.3f} | {memory:.0f} | "
            "{reads:.1f} | {payload:.0f} | {context:.0f} | {calls:.1f} |".format(
                scenario_id=scenario["scenario_id"],
                status=scenario["status"],
                state=scenario["expected_state"],
                wall=metrics["wall_time_ms"]["p95"],
                memory=metrics["peak_python_memory_bytes"]["p95"],
                reads=metrics["raw_source_read_opens"]["p95"],
                payload=metrics["full_decision_payload_bytes"]["p95"],
                context=metrics["provider_context_bytes"]["p95"],
                calls=metrics["model_calls"]["p95"],
            )
        )
    delivery_statement = (
        "A source-parent change was detected; this failed evidence does not "
        "claim that user delivery was avoided."
        if report["summary"]["user_delivery_created"]
        else "No user delivery was created."
    )
    return "\n".join(
        [
            "# SciPlot R0 automation baseline",
            "",
            f"Status: **{report['status']}**; repetitions: {report['repetitions']}.",
            "",
            "| Scenario | Status | State | Wall p95 ms | Python peak p95 B | "
            "Raw-source opens p95 | Full decision payload p95 B | Provider context p95 B | "
            "Model calls p95 |",
            "| --- | --- | --- | ---: | ---: | ---: | ---: | ---: | ---: |",
            *rows,
            "",
            "All measurements are local development evidence. "
            f"{delivery_statement} The offline provider made no model call.",
            "",
        ]
    )


__all__ = ["run_automation_baseline_probe"]
