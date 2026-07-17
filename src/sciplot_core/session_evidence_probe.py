from __future__ import annotations

import copy
import hashlib
import json
import os
import shutil
import tempfile
import traceback
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Callable
from uuid import uuid4

from sciplot_core._utils import file_sha256, json_safe
from sciplot_core.canvas.persistence import atomic_write_json
from sciplot_core.session_evidence import (
    ACCEPTANCE_LANES,
    CANONICAL_MODEL_TASKS,
    EXPECTED_EVIDENCE,
    SESSION_EVIDENCE_EVENT_KIND,
    SESSION_EVIDENCE_EVENT_VERSION,
    _canonical_bytes,
    _completion_evidence_checks,
    _head_path,
    _m3_round_summary,
    _m6_round_summary,
    _pending_path,
    _pending_record,
    _read_events_unlocked,
    _select_m6_round,
    _validate_preregistration,
    _write_head_unlocked,
    canonical_sha256,
    complete_session,
    preregister_session,
    recover_session_ledger,
    session_ledger_status,
    witness_session_reopen,
)
from sciplot_core.session_evidence_artifacts import verify_regular_production_qa

SESSION_EVIDENCE_PROBE_KIND = "sciplot_session_evidence_probe"
SESSION_EVIDENCE_PROBE_VERSION = 3


def _check(
    check_id: str,
    label: str,
    passed: bool,
    *,
    detail: Any = None,
) -> dict[str, Any]:
    return {
        "id": check_id,
        "label": label,
        "status": "passed" if passed else "failed",
        "detail": json_safe(detail),
    }


def _expect_failure(
    operation: Callable[[], object],
    *,
    contains: str | None = None,
) -> tuple[bool, str]:
    try:
        operation()
    except Exception as exc:
        message = f"{type(exc).__name__}: {exc}"
        return (
            contains is None or contains.casefold() in message.casefold(),
            message,
        )
    return False, "operation unexpectedly succeeded"


def _copy_ledger(source: Path, destination: Path) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(source, destination)
    head = json.loads(_head_path(source).read_text(encoding="utf-8"))
    head["ledger"] = str(destination.resolve())
    atomic_write_json(_head_path(destination), head)


def _real_canvas_case(
    run_root: Path,
    *,
    fixture_project: Path,
    frozen_build_artifact: Path | None = None,
    repo_root: Path | None = None,
    veusz_root: Path | None = None,
) -> dict[str, Any]:
    from sciplot_core.canvas_review_probe import run_canvas_review_probe

    if frozen_build_artifact is None:
        if repo_root is not None or veusz_root is not None:
            raise ValueError("repo_root and veusz_root require frozen_build_artifact.")
        build_artifact = run_root / "build" / "synthetic_canvas_probe_build.whl"
        build_artifact.parent.mkdir(parents=True, exist_ok=True)
        build_artifact.write_bytes(b"SciPlot E0 synthetic build identity probe\n")
        scope = "synthetic_probe"
        round_id = None
        task = "E0 real Veusz Canvas review promotion lifecycle"
    else:
        if repo_root is None or veusz_root is None:
            raise ValueError(
                "The frozen-build contract probe requires explicit repo_root "
                "and veusz_root."
            )
        build_artifact = frozen_build_artifact.expanduser().resolve()
        scope = "formal_contract_probe"
        round_id = "e0_frozen_build_contract"
        task = "E0 installed frozen-build Veusz Canvas review promotion contract probe"
    registration: dict[str, Any] = {}

    def preregister_before_actions(
        workspace: Any,
        _copied_target: Path,
        _probe_root: Path,
    ) -> dict[str, Any]:
        project = Path(str(workspace.project_dir)).expanduser().resolve()
        source = project / "source"
        ledger = project / ".sciplot_evidence" / "session_evidence.jsonl"
        preregistration = preregister_session(
            ledger,
            project_path=project,
            source_paths=[source],
            lane="scalar_review_composition",
            scope=scope,
            source_class="synthetic_contract_fixture",
            task=task,
            round_id=round_id,
            owner="e0_probe_owner",
            entry_route="canvas",
            build_artifact=build_artifact,
            repo_root=repo_root,
            veusz_root=veusz_root,
            expected_evidence=[
                "canvas_lifecycle",
                "provider_disabled",
                "review_sidecar",
                "review_promotion",
            ],
            journal_path=Path(str(workspace.journal_path)),
            session_id="e0_canvas_review",
        )
        registration.update(
            {
                "ledger": ledger,
                "session_id": preregistration["session_id"],
                "project": project,
                "source": source,
                "journal": Path(str(workspace.journal_path)),
                "session": Path(str(workspace.session_path)),
                "review": Path(str(workspace.annotations_path)),
                "document": Path(str(workspace.document_path)),
                "scope": scope,
                "formal_evidence_eligible": preregistration["formal_evidence_eligible"],
                "frozen_build_contract": preregistration["frozen_build_contract"],
            }
        )
        return {
            key: str(value) if isinstance(value, Path) else value
            for key, value in registration.items()
        }

    probe = run_canvas_review_probe(
        fixture_project,
        output_root=run_root / "canvas_review",
        before_actions=preregister_before_actions,
    )
    if probe.get("status") != "passed":
        raise RuntimeError(
            "Real Canvas review probe failed: "
            f"{probe.get('summary') or probe.get('error')}"
        )
    evidence = probe.get("evidence")
    if not isinstance(evidence, dict):
        raise ValueError("Canvas review probe returned no evidence.")
    export = evidence.get("promoted_export")
    export = export if isinstance(export, dict) else {}
    studio_run = export.get("studio_run")
    studio_run = studio_run if isinstance(studio_run, dict) else {}
    manifest = Path(str(studio_run.get("manifest") or "")).expanduser().resolve()
    witness = witness_session_reopen(
        registration["ledger"],
        registration["session_id"],
        owner="e0_probe_owner",
        journal_path=registration["journal"],
        canvas_session_path=registration["session"],
        document_path=registration["document"],
        review_path=registration["review"],
    )
    completion = complete_session(
        registration["ledger"],
        registration["session_id"],
        owner="e0_probe_owner",
        outcome="pass",
        active_seconds=31.0,
        manifest_path=manifest,
    )
    status = session_ledger_status(registration["ledger"])
    return {
        "probe": probe,
        "registration": {
            key: str(value) if isinstance(value, Path) else value
            for key, value in registration.items()
        },
        "manifest": str(manifest),
        "witness": witness,
        "completion": completion,
        "status": status,
        "build_artifact": str(build_artifact),
    }


def _real_composition_case(
    run_root: Path,
    *,
    document: Path,
) -> dict[str, Any]:
    from sciplot_core.composition_probe import run_composition_probe

    build_artifact = run_root / "build" / "synthetic_composition_probe_build.whl"
    build_artifact.parent.mkdir(parents=True, exist_ok=True)
    build_artifact.write_bytes(b"SciPlot E0 synthetic build identity probe\n")
    registration: dict[str, Any] = {}

    def preregister_before_actions(
        workspace: Any,
        source_documents: list[Path],
        _probe_root: Path,
    ) -> dict[str, Any]:
        ledger = workspace.root / ".sciplot_evidence" / "session_evidence.jsonl"
        preregistration = preregister_session(
            ledger,
            project_path=workspace.root,
            source_paths=source_documents,
            lane="scalar_review_composition",
            scope="synthetic_probe",
            source_class="synthetic_contract_fixture",
            task="E0 real native 183 mm Composition lifecycle",
            owner="e0_probe_owner",
            entry_route="compose",
            build_artifact=build_artifact,
            expected_evidence=["composition_lifecycle"],
            journal_path=workspace.journal_path,
            session_id="e0_native_composition",
        )
        registration.update(
            {
                "ledger": ledger,
                "session_id": preregistration["session_id"],
                "project": workspace.root,
                "journal": workspace.journal_path,
                "composition": workspace.composition_path,
                "sources": list(source_documents),
            }
        )
        return {
            key: (
                [str(item) for item in value]
                if isinstance(value, list)
                else str(value)
                if isinstance(value, Path)
                else value
            )
            for key, value in registration.items()
        }

    probe = run_composition_probe(
        [document],
        output_root=run_root / "composition",
        before_actions=preregister_before_actions,
    )
    if probe.get("status") != "passed":
        raise RuntimeError(f"Real Composition probe failed: {probe.get('checks')}")
    evidence = probe.get("evidence")
    if not isinstance(evidence, dict):
        raise ValueError("Composition probe returned no evidence.")
    delivery = evidence.get("delivery")
    delivery = delivery if isinstance(delivery, dict) else {}
    delivery_manifest = (
        Path(str(delivery.get("delivery_manifest") or "")).expanduser().resolve()
    )
    witness = witness_session_reopen(
        registration["ledger"],
        registration["session_id"],
        owner="e0_probe_owner",
        journal_path=registration["journal"],
        composition_path=registration["composition"],
        composition_delivery_path=delivery_manifest,
    )
    completion = complete_session(
        registration["ledger"],
        registration["session_id"],
        owner="e0_probe_owner",
        outcome="pass",
        active_seconds=25.0,
        manifest_path=delivery_manifest,
    )
    status = session_ledger_status(registration["ledger"])
    return {
        "probe": probe,
        "registration": {
            key: (
                [str(item) for item in value]
                if isinstance(value, list)
                else str(value)
                if isinstance(value, Path)
                else value
            )
            for key, value in registration.items()
        },
        "manifest": str(delivery_manifest),
        "witness": witness,
        "completion": completion,
        "status": status,
    }


def _m3_probe_rows() -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    planning_index = 0
    for canonical_task in CANONICAL_MODEL_TASKS:
        for attempt in (1, 2):
            cancellation = canonical_task == "cancellation_rollback"
            score = "not_applicable" if cancellation else "correct"
            if not cancellation:
                planning_index += 1
                if planning_index == 10:
                    score = "incorrect"
            rows.append(
                {
                    "session_id": f"m3_{canonical_task}_{attempt}",
                    "canonical_task": canonical_task,
                    "attempt": attempt,
                    "provider": "provider",
                    "model": "model",
                    "candidate_identity": "candidate_a",
                    "completed": True,
                    "outcome": "pass",
                    "score": score,
                    "lifecycle_passed": True,
                    "fallback_free": True,
                    "advanced_editor_free": True,
                }
            )
    return rows


def _m6_probe_rows(*, per_lane: int = 3) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for lane_index, lane in enumerate(ACCEPTANCE_LANES):
        for lane_attempt in range(per_lane):
            checks = {evidence_id: False for evidence_id in EXPECTED_EVIDENCE}
            expected = ["canvas_lifecycle"]
            checks["canvas_lifecycle"] = True
            if lane_attempt == 0:
                expected.append("provider_disabled")
                checks["provider_disabled"] = True
            if lane_attempt == 1 and lane_index < 3:
                expected.append("ai_operation")
                checks["ai_operation"] = True
            if lane_index == 0 and lane_attempt == 2:
                expected.append("data_mapping")
                checks["data_mapping"] = True
            if lane_index == 4 and lane_attempt == 1:
                expected.extend(["review_sidecar", "review_promotion"])
                checks["review_sidecar"] = True
                checks["review_promotion"] = True
            if lane_index == 4 and lane_attempt == 2:
                expected = ["composition_lifecycle"]
                checks["canvas_lifecycle"] = False
                checks["composition_lifecycle"] = True
            rows.append(
                {
                    "session_id": f"m6_{lane_index}_{lane_attempt}",
                    "lane": lane,
                    "candidate_identity": "candidate_a",
                    "completed": True,
                    "qualifying_m6": True,
                    "evidence_checks": checks,
                    "expected_evidence": sorted(expected),
                }
            )
    return rows


def _recovery_probe(
    run_root: Path,
    *,
    source_ledger: Path,
) -> list[dict[str, Any]]:
    base_events = _read_events_unlocked(source_ledger)
    payload = copy.deepcopy(base_events[0]["payload"])
    payload["task"] = "E0 crash-recovery append"
    payload["task_fingerprint"] = canonical_sha256(
        {"task": "e0 crash recovery", "source": str(uuid4())}
    )
    event = {
        "kind": SESSION_EVIDENCE_EVENT_KIND,
        "version": SESSION_EVIDENCE_EVENT_VERSION,
        "sequence": len(base_events) + 1,
        "event_id": str(uuid4()),
        "event_type": "preregistered",
        "session_id": "e0_recovered_append",
        "recorded_at": datetime.now(UTC).isoformat(),
        "previous_event_sha256": base_events[-1]["event_sha256"],
        "payload": payload,
    }
    event["event_sha256"] = canonical_sha256(event)
    results: list[dict[str, Any]] = []
    for phase in ("pending_only", "tail_only", "head_done"):
        ledger = run_root / "ledger_recovery" / phase / "session_evidence.jsonl"
        _copy_ledger(source_ledger, ledger)
        pending = _pending_record(ledger, events=base_events, event=event)
        atomic_write_json(_pending_path(ledger), pending)
        if phase in {"tail_only", "head_done"}:
            with ledger.open("ab") as handle:
                handle.write(_canonical_bytes(event) + b"\n")
        if phase == "head_done":
            _write_head_unlocked(ledger, [*base_events, event])
        blocked = session_ledger_status(ledger)
        recovery = recover_session_ledger(ledger)
        final = session_ledger_status(ledger)
        results.append(
            {
                "phase": phase,
                "blocked_before_recovery": blocked.get("status") == "failed",
                "action": recovery.get("action"),
                "final_status": final.get("status"),
                "final_session_count": final.get("summary", {}).get("session_count"),
                "pending_removed": not _pending_path(ledger).exists(),
            }
        )
    return results


def _tampered_evaluation_status(
    run_root: Path,
    *,
    source_ledger: Path,
) -> dict[str, Any]:
    ledger = run_root / "tamper" / "self_reported_evaluation.jsonl"
    _copy_ledger(source_ledger, ledger)
    events = [
        json.loads(line)
        for line in ledger.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    completion = events[-1]
    completion["payload"]["evaluation"]["qualifying_m6"] = True
    completion["event_sha256"] = canonical_sha256(
        {key: value for key, value in completion.items() if key != "event_sha256"}
    )
    ledger.write_bytes(b"".join(_canonical_bytes(event) + b"\n" for event in events))
    head = json.loads(_head_path(ledger).read_text(encoding="utf-8"))
    data = ledger.read_bytes()
    head.update(
        {
            "event_count": len(events),
            "last_event_sha256": completion["event_sha256"],
            "ledger_size_bytes": len(data),
            "ledger_sha256": hashlib.sha256(data).hexdigest(),
            "updated_at": datetime.now(UTC).isoformat(),
        }
    )
    atomic_write_json(_head_path(ledger), head)
    return session_ledger_status(ledger)


def _compact_runtime_probe(
    probe: dict[str, Any],
    *,
    evidence_fields: tuple[str, ...] = (),
) -> dict[str, Any]:
    evidence = probe.get("evidence")
    evidence = evidence if isinstance(evidence, dict) else {}
    summary = probe.get("summary")
    summary = summary if isinstance(summary, dict) else {}
    return {
        "kind": probe.get("kind"),
        "version": probe.get("version"),
        "status": probe.get("status"),
        "summary": summary,
        "check_count": probe.get("check_count") or summary.get("check_count"),
        "passed_count": probe.get("passed_count") or summary.get("passed_count"),
        "evidence": {
            field: evidence.get(field) for field in evidence_fields if field in evidence
        },
        "artifacts": probe.get("artifacts"),
        "error": probe.get("error"),
    }


def run_session_evidence_probe(
    *,
    output_root: Path,
    frozen_build_artifact: Path | None = None,
    repo_root: Path | None = None,
    veusz_root: Path | None = None,
) -> dict[str, Any]:
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    output = output_root.expanduser().resolve()
    output.mkdir(parents=True, exist_ok=True)
    run_root = Path(
        tempfile.mkdtemp(prefix="session_evidence_probe_", dir=output)
    ).resolve()
    summary_path = run_root / "session_evidence_probe.json"
    checks: list[dict[str, Any]] = []
    runtime_probes: dict[str, Any] = {}
    artifacts: dict[str, Any] = {"run_root": str(run_root)}

    try:
        from sciplot_core.smoke import _write_synthetic_ftir
        from sciplot_core.studio import prepare_studio_document

        fixture_path = run_root / "fixture" / "ftir_e0.csv"
        _write_synthetic_ftir(fixture_path)
        prepared = prepare_studio_document(
            fixture_path,
            output_root=run_root / "fixture_projects",
            project_name="E0 real artifact fixture",
        )
        fixture_project = Path(str(prepared["project_dir"]))
        canvas = _real_canvas_case(
            run_root,
            fixture_project=fixture_project,
            frozen_build_artifact=frozen_build_artifact,
            repo_root=repo_root,
            veusz_root=veusz_root,
        )
        runtime_probes["canvas_review"] = _compact_runtime_probe(
            canvas["probe"],
            evidence_fields=(
                "annotation_count",
                "promotion_count",
                "final_revision",
                "final_promoted_count",
                "final_active_count",
                "journal_event_count",
            ),
        )
        artifacts["canvas_ledger"] = canvas["registration"]["ledger"]
        artifacts["canvas_manifest"] = canvas["manifest"]
        canvas_completion = canvas["completion"]
        canvas_status = canvas["status"]
        checks.append(
            _check(
                "real_canvas_closed_chain",
                "A real Veusz Canvas review/promotion session closes through "
                "PDF/TIFF production QA, VSZ authority, delivery, witness, and completion",
                canvas_completion.get("outcome") == "pass"
                and canvas_status.get("status") == "passed"
                and canvas_status.get("summary", {}).get("completed_count") == 1
                and canvas_completion.get("qualifying_m6") is False,
                detail={
                    "manifest": canvas["manifest"],
                    "summary": canvas_status.get("summary"),
                    "evidence_checks": canvas_completion.get("event", {})
                    .get("payload", {})
                    .get("evidence_checks"),
                },
            )
        )
        canvas_checks = (
            canvas_completion.get("event", {})
            .get("payload", {})
            .get("evidence_checks", {})
        )
        checks.append(
            _check(
                "real_provider_disabled_and_review_bound",
                "Provider-disabled state and review sidecar promotion come from "
                "the reopened native Canvas journal and object registry",
                canvas_checks.get("provider_disabled") is True
                and canvas_checks.get("review_sidecar") is True
                and canvas_checks.get("review_promotion") is True,
                detail=canvas_checks,
            )
        )
        if frozen_build_artifact is not None:
            checks.append(
                _check(
                    "frozen_build_contract_probe_is_verified_and_non_counting",
                    "An installed frozen wheel can preregister, witness, and "
                    "complete a real-artifact synthetic contract probe without "
                    "entering M3 or M6 counts",
                    canvas["registration"].get("scope") == "formal_contract_probe"
                    and canvas["registration"].get("frozen_build_contract") is True
                    and canvas["registration"].get("formal_evidence_eligible") is False
                    and canvas_status.get("scope_counts", {}).get(
                        "formal_contract_probe"
                    )
                    == 1
                    and canvas_status.get("m3", {}).get("gate_passed") is False
                    and canvas_status.get("m6", {}).get("gate_passed") is False
                    and canvas_completion.get("qualifying_m6") is False
                    and canvas_completion.get("m3_scored") is False,
                    detail={
                        "registration": canvas["registration"],
                        "scope_counts": canvas_status.get("scope_counts"),
                        "m3": canvas_status.get("m3"),
                        "m6": canvas_status.get("m6"),
                    },
                )
            )

        document = Path(str(prepared["document"])).expanduser().resolve()
        composition = _real_composition_case(run_root, document=document)
        runtime_probes["composition"] = _compact_runtime_probe(
            composition["probe"],
        )
        artifacts["composition_ledger"] = composition["registration"]["ledger"]
        artifacts["composition_manifest"] = composition["manifest"]
        composition_completion = composition["completion"]
        composition_status = composition["status"]
        checks.append(
            _check(
                "real_native_composition_closed_chain",
                "A real 183 mm native Veusz composition closes through source "
                "snapshot verification, native audit, physical QA, delivery, witness, and completion",
                composition_completion.get("outcome") == "pass"
                and composition_status.get("status") == "passed"
                and composition_completion.get("event", {})
                .get("payload", {})
                .get("evidence_checks", {})
                .get("composition_lifecycle")
                is True,
                detail={
                    "manifest": composition["manifest"],
                    "summary": composition_status.get("summary"),
                },
            )
        )

        fake_root = run_root / "negative_fake_artifacts"
        fake_root.mkdir(parents=True, exist_ok=True)
        fake_pdf = fake_root / "fake.pdf"
        fake_tiff = fake_root / "fake_300dpi.tiff"
        fake_vsz = fake_root / "fake.vsz"
        fake_pdf.write_bytes(b"%PDF-1.4\\nnot a rendered scientific figure\\n")
        fake_tiff.write_bytes(b"not a TIFF")
        fake_vsz.write_text("not a Veusz document\n", encoding="utf-8")
        fake_qa_ok, fake_qa_detail = _expect_failure(
            lambda: verify_regular_production_qa(
                {
                    "output": str(fake_root),
                    "journal_profile": {},
                    "request": {},
                },
                document=fake_vsz,
                witnessed_exports={
                    "pdf": [
                        {
                            "format": "pdf",
                            "path": str(fake_pdf),
                            "size_bytes": fake_pdf.stat().st_size,
                            "sha256": file_sha256(fake_pdf),
                        }
                    ],
                    "tiff_300": [
                        {
                            "format": "tiff_300",
                            "path": str(fake_tiff),
                            "size_bytes": fake_tiff.stat().st_size,
                            "sha256": file_sha256(fake_tiff),
                        }
                    ],
                },
            )
        )
        checks.append(
            _check(
                "fake_artifact_self_qa_rejected",
                "Handwritten PDF/TIFF/VSZ bytes cannot become positive E0 evidence",
                fake_qa_ok,
                detail=fake_qa_detail,
            )
        )

        tampered = _tampered_evaluation_status(
            run_root,
            source_ledger=Path(canvas["registration"]["ledger"]),
        )
        checks.append(
            _check(
                "self_reported_classification_rejected",
                "Status rejects a fully rehashed ledger whose completion "
                "self-reports a classification not derivable from raw evidence",
                tampered.get("status") == "failed"
                and "stored evaluation"
                in str(tampered.get("integrity", {}).get("error", "")),
                detail=tampered.get("integrity"),
            )
        )

        prereg_event = _read_events_unlocked(Path(canvas["registration"]["ledger"]))[0]
        nested_unknown = copy.deepcopy(prereg_event["payload"])
        nested_unknown["build"]["git"]["covert_field"] = True
        nested_ok, nested_detail = _expect_failure(
            lambda: _validate_preregistration(nested_unknown),
            contains="unknown fields",
        )
        checks.append(
            _check(
                "nested_unknown_fields_rejected",
                "Closed nested schemas reject covert build/runtime evidence fields",
                nested_ok,
                detail=nested_detail,
            )
        )
        unverified_frozen_probe = copy.deepcopy(prereg_event["payload"])
        unverified_frozen_probe["scope"] = "formal_contract_probe"
        unverified_frozen_probe["round_id"] = "unverified_frozen_probe"
        unverified_frozen_ok, unverified_frozen_detail = _expect_failure(
            lambda: _validate_preregistration(unverified_frozen_probe),
            contains="Frozen-build sessions require",
        )
        checks.append(
            _check(
                "formal_contract_probe_rejects_unverified_build",
                "The non-counting installed-lifecycle scope still rejects a "
                "dirty, uncommitted, or wheel-unverified runtime",
                unverified_frozen_ok,
                detail=unverified_frozen_detail,
            )
        )

        duplicate_root = run_root / "duplicate_natural_task"
        duplicate_project = duplicate_root / "project"
        duplicate_project.mkdir(parents=True)
        source_a = duplicate_root / "a.csv"
        source_b = duplicate_root / "b.csv"
        source_a.write_text("x,y\n1,2\n", encoding="utf-8")
        source_b.write_text("x,y\n3,4\n", encoding="utf-8")
        duplicate_artifact = duplicate_root / "probe.whl"
        duplicate_artifact.write_bytes(b"duplicate probe")
        duplicate_journal = duplicate_project / "journal.jsonl"
        duplicate_ledger = duplicate_root / "ledger.jsonl"
        preregister_session(
            duplicate_ledger,
            project_path=duplicate_project,
            source_paths=[source_a, source_b],
            lane=ACCEPTANCE_LANES[0],
            scope="synthetic_probe",
            source_class="synthetic_contract_fixture",
            task="same natural task",
            round_id="round_a",
            owner="owner",
            entry_route="canvas",
            build_artifact=duplicate_artifact,
            expected_evidence=["canvas_lifecycle"],
            journal_path=duplicate_journal,
            session_id="natural_task_a",
        )
        duplicate_ok, duplicate_detail = _expect_failure(
            lambda: preregister_session(
                duplicate_ledger,
                project_path=duplicate_project,
                source_paths=[source_b, source_a],
                lane=ACCEPTANCE_LANES[1],
                scope="synthetic_probe",
                source_class="synthetic_contract_fixture",
                task="same natural task",
                round_id="round_b",
                owner="owner",
                entry_route="canvas",
                build_artifact=duplicate_artifact,
                expected_evidence=["canvas_lifecycle"],
                journal_path=duplicate_journal,
                session_id="natural_task_b",
            ),
            contains="already preregistered",
        )
        checks.append(
            _check(
                "natural_task_fingerprint_is_order_lane_round_invariant",
                "Source order, lane, and round cannot inflate one natural task",
                duplicate_ok,
                detail=duplicate_detail,
            )
        )

        cross_transaction_prereg = {
            "expected_evidence": ["ai_operation", "canvas_lifecycle"],
            "provider": "provider",
            "model": "model",
        }
        cross_transaction_witness = {
            "authority_mode": "canvas",
            "authority": {"ready_to_use": True},
            "optional_evidence": {},
            "journal": {
                "event_types": {
                    "assistant_request_submitted": 1,
                    "assistant_batch_proposed": 1,
                    "assistant_transaction_committed": 1,
                },
                "references": [
                    {
                        "event": "assistant_request_submitted",
                        "provider": "provider",
                        "model": "model",
                        "transaction_id": "transaction_a",
                        "request_id": "request_a",
                        "index": 0,
                    },
                    {
                        "event": "assistant_batch_proposed",
                        "provider": "provider",
                        "transaction_id": "transaction_b",
                        "request_id": "request_a",
                        "batch_id": "batch_a",
                        "response_status": "proposal",
                        "proposal_kind": "canvas_operation_batch",
                        "response_sha256": "a" * 64,
                        "index": 1,
                    },
                    {
                        "event": "assistant_transaction_committed",
                        "provider": "provider",
                        "transaction_id": "transaction_a",
                        "active_batch_ids": ["batch_b"],
                        "verification": {
                            "structural_qa_passed": True,
                            "canonical_vsz_unchanged_before_save": True,
                            "raw_inputs_mutated": False,
                        },
                        "index": 2,
                    },
                ],
            },
        }
        cross_ok, cross_detail = _expect_failure(
            lambda: _completion_evidence_checks(
                cross_transaction_prereg,
                cross_transaction_witness,
            ),
            contains="ai_operation",
        )
        checks.append(
            _check(
                "cross_transaction_and_batch_ai_rejected",
                "AI proposal and commit must share request, transaction, and active batch",
                cross_ok,
                detail=cross_detail,
            )
        )

        m3_rows = _m3_probe_rows()
        coherent_m3 = _m3_round_summary("m3_pass", m3_rows)
        fallback_m3 = copy.deepcopy(m3_rows)
        fallback_m3[0]["fallback_free"] = False
        checks.append(
            _check(
                "m3_fixed_cohort_gate",
                "M3 passes exactly 12 coherent fallback-free and editor-free "
                "attempts, with 12/12 authority, 2/2 rollback, and 9/10 planning",
                coherent_m3.get("gate_passed") is True
                and _m3_round_summary("m3_fallback", fallback_m3).get("gate_passed")
                is False,
                detail=coherent_m3,
            )
        )

        exact_m6 = _m6_round_summary("exact_15", _m6_probe_rows())
        overfilled_m6 = _m6_round_summary(
            "overfilled_20",
            _m6_probe_rows(per_lane=4),
        )
        mixed_m6_rows = _m6_probe_rows()
        mixed_m6_rows[-1]["candidate_identity"] = "candidate_b"
        mixed_m6 = _m6_round_summary("mixed", mixed_m6_rows)
        selected, passing_ids = _select_m6_round(
            {
                "exact_15": exact_m6,
                "overfilled_20": overfilled_m6,
            }
        )
        checks.append(
            _check(
                "m6_fixed_candidate_cohort_and_round_projection",
                "M6 selects one passing 15-session round and cannot combine it "
                "with a larger failed round or mixed candidate",
                exact_m6.get("gate_passed") is True
                and overfilled_m6.get("gate_passed") is False
                and mixed_m6.get("gate_passed") is False
                and passing_ids == ["exact_15"]
                and selected.get("round_id") == "exact_15"
                and selected.get("qualifying_count") == 15,
                detail={
                    "exact": exact_m6,
                    "overfilled": overfilled_m6,
                    "mixed": mixed_m6,
                    "selected": selected.get("round_id"),
                },
            )
        )

        recovery = _recovery_probe(
            run_root,
            source_ledger=Path(canvas["registration"]["ledger"]),
        )
        checks.append(
            _check(
                "ledger_crash_recovery_three_phases",
                "Pending-only, appended-before-head, and head-before-clear crashes "
                "all block status and recover without duplicate or lost events",
                len(recovery) == 3
                and all(
                    item["blocked_before_recovery"]
                    and item["final_status"] == "passed"
                    and item["final_session_count"] == 2
                    and item["pending_removed"]
                    for item in recovery
                ),
                detail=recovery,
            )
        )
    except Exception as exc:
        checks.append(
            _check(
                "session_evidence_probe_runtime",
                "The real session evidence lifecycle completes without an exception",
                False,
                detail={
                    "type": type(exc).__name__,
                    "message": str(exc),
                    "traceback": traceback.format_exc(),
                },
            )
        )

    passed_count = sum(check["status"] == "passed" for check in checks)
    failed_ids = [str(check["id"]) for check in checks if check["status"] != "passed"]
    payload = {
        "kind": SESSION_EVIDENCE_PROBE_KIND,
        "version": SESSION_EVIDENCE_PROBE_VERSION,
        "status": "passed" if not failed_ids else "failed",
        "synthetic_contract_fixture": True,
        "counts_as_real_session_evidence": False,
        "real_production_artifacts_required_for_positive_path": True,
        "checks": checks,
        "summary": {
            "check_count": len(checks),
            "passed_count": passed_count,
            "failed_ids": failed_ids,
        },
        "runtime_probes": runtime_probes,
        "artifacts": artifacts,
        "limitations": [
            "The source data are explicitly synthetic and never count toward M3 or M6.",
            "Positive evidence nevertheless uses real Veusz VSZ, PDF, 300 dpi TIFF, native Canvas/Composition authority, recomputed production QA, and delivery files.",
            "Fake artifact bytes appear only in a negative rejection test.",
            "The local ledger is tamper-evident and crash-recoverable, not signed or remotely anchored.",
        ],
    }
    payload["artifacts"]["summary"] = str(summary_path)
    atomic_write_json(summary_path, payload)
    return payload


__all__ = [
    "SESSION_EVIDENCE_PROBE_KIND",
    "SESSION_EVIDENCE_PROBE_VERSION",
    "run_session_evidence_probe",
]
