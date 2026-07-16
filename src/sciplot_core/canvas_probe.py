from __future__ import annotations

import json
import os
import shutil
import tempfile
from collections.abc import Callable
from contextlib import ExitStack
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from sciplot_core._utils import file_sha256, json_safe
from sciplot_core.canvas.annotations import ReviewAnnotation
from sciplot_core.canvas.assistant_contract import (
    DataMappingProposal,
    DeclarativeTransformation,
)
from sciplot_core.canvas.model import CanvasSession
from sciplot_core.canvas.operations import CanvasOperation, CanvasOperationBatch
from sciplot_core.canvas.persistence import (
    append_operation_journal,
    load_canvas_session,
    load_review_annotations,
    read_operation_journal,
    save_canvas_session,
    save_review_annotations,
)

CANVAS_CHARACTERIZATION_KIND = "sciplot_canvas_characterization"
CANVAS_CHARACTERIZATION_VERSION = 1


def _now() -> str:
    return datetime.now(UTC).isoformat()


def _check(
    check_id: str, label: str, passed: bool, detail: Any = None
) -> dict[str, Any]:
    return {
        "id": check_id,
        "label": label,
        "status": "passed" if passed else "failed",
        "detail": json_safe(detail),
    }


def _raises_value_error(callback: Callable[[], Any]) -> bool:
    try:
        callback()
    except ValueError:
        return True
    return False


def _resolve_persisted_path(value: str, *, root: Path) -> Path:
    path = Path(value).expanduser()
    if not path.is_absolute():
        path = root / path
    return path.resolve()


def run_canvas_contract_probe(*, output_root: Path) -> dict[str, Any]:
    root = output_root.expanduser().resolve()
    root.mkdir(parents=True, exist_ok=True)
    session_path = root / "canvas_session.json"
    annotations_path = root / "review_annotations.json"
    journal_path = root / "operation_journal.jsonl"

    session = CanvasSession(
        project_id="canvas_contract_probe",
        document_id="document-contract-probe",
        document_path=str(root / "document.vsz"),
        state="canvas_ready",
    )
    axis = session.object_registry.bind(
        structural_key="root/page[0]/graph[0]/axis[0]",
        current_path="/page/graph/x",
        object_type="axis",
        revision=session.revision,
    )
    operation = CanvasOperation.set_setting(
        target_id=axis.object_id,
        setting_path="/page/graph/x/label",
        value="Frequency",
        expected_value="",
        require_expected_value=True,
    )
    batch = CanvasOperationBatch(
        base_revision=0,
        provider="contract_probe",
        rationale="Verify the version 1 typed setting contract.",
        operations=(operation,),
    )
    annotation = ReviewAnnotation(
        page_index=0,
        shape="arrow",
        coordinate_space="object",
        geometry={"start": [0.2, 0.2], "end": [0.4, 0.5]},
        text="Review only",
        target_object_id=axis.object_id,
    )
    proposal = DataMappingProposal(
        source_hashes={"raw/example.csv": "a" * 64},
        column_roles={"Frequency": "x", "Storage modulus": "y"},
        transformations=(
            DeclarativeTransformation(
                transformation_type="unit_convert",
                parameters={"column": "Frequency", "from": "rad/s", "to": "Hz"},
            ),
        ),
        confidence=0.91,
        requires_confirmation=True,
        human_confirmed=False,
        rationale="Contract-only proposal; no data are executed.",
    )

    save_canvas_session(session_path, session)
    save_review_annotations(annotations_path, [annotation])
    append_operation_journal(
        journal_path,
        {
            "kind": "sciplot_canvas_journal_entry",
            "version": 1,
            "event": "contract_probe",
            "batch": batch.to_dict(),
        },
    )

    loaded = load_canvas_session(session_path)
    loaded_annotations = load_review_annotations(annotations_path)
    journal = read_operation_journal(journal_path)
    rebound = loaded.object_registry.bind(
        structural_key="root/page[0]/graph[0]/axis[0]",
        current_path="/renamed_page/renamed_graph/renamed_axis",
        object_type="axis",
        revision=1,
    )
    restored_batch = CanvasOperationBatch.from_dict(batch.to_dict())
    restored_proposal = DataMappingProposal.from_dict(proposal.to_dict())
    operation_schema_rejected = _raises_value_error(
        lambda: CanvasOperation(
            operation_type="set_setting",
            target_id=axis.object_id,
            arguments={
                "setting_path": "/page/graph/x/label",
                "value": "Frequency",
                "python": "print('unsafe')",
            },
        )
    )
    executable_mapping_rejected = _raises_value_error(
        lambda: DeclarativeTransformation(
            transformation_type="rename",
            parameters={"mapping": {"x": "Frequency"}, "nested": {"script": "unsafe"}},
        )
    )
    operation_top_level_rejected = _raises_value_error(
        lambda: CanvasOperation.from_dict(
            {
                **operation.to_dict(),
                "python": "print('unsafe')",
            }
        )
    )
    boolean_coercion_rejected = _raises_value_error(
        lambda: CanvasOperationBatch.from_dict(
            {
                **batch.to_dict(),
                "atomic": "false",
            }
        )
    )
    mapping_top_level_rejected = _raises_value_error(
        lambda: DataMappingProposal.from_dict(
            {
                **proposal.to_dict(),
                "script": "unsafe",
            }
        )
    )
    session_integrity_rejected = _raises_value_error(
        lambda: CanvasSession.from_dict(
            {
                **session.to_dict(),
                "dirty": True,
            }
        )
    )
    checks = [
        _check(
            "session_roundtrip",
            "CanvasSession version 1 persists and reloads without Qt",
            loaded.session_id == session.session_id and loaded.state == "canvas_ready",
        ),
        _check(
            "stable_object_identity",
            "Stable object IDs survive display-path changes",
            rebound.object_id == axis.object_id
            and rebound.current_path == "/renamed_page/renamed_graph/renamed_axis",
        ),
        _check(
            "typed_operation_roundtrip",
            "CanvasOperationBatch version 1 roundtrips with its base revision",
            restored_batch.to_dict() == batch.to_dict(),
        ),
        _check(
            "review_annotation_is_non_exported",
            "ReviewAnnotation defaults to review-only state",
            len(loaded_annotations) == 1
            and loaded_annotations[0].state == "review_only",
        ),
        _check(
            "mapping_proposal_is_declarative",
            "DataMappingProposal carries source hashes and cannot execute before confirmation",
            restored_proposal.source_hashes == proposal.source_hashes
            and restored_proposal.executable is False,
        ),
        _check(
            "journal_is_append_only_jsonl",
            "The operation journal records a typed batch as JSONL",
            len(journal) == 1
            and (journal[0].get("batch") or {}).get("batch_id") == batch.batch_id,
        ),
        _check(
            "operation_schema_is_closed",
            "Typed setting operations reject undeclared executable arguments",
            operation_schema_rejected,
        ),
        _check(
            "mapping_schema_rejects_executable_content",
            "Declarative data mappings reject nested executable content",
            executable_mapping_rejected,
        ),
        _check(
            "operation_payload_schema_is_closed",
            "Typed operation payloads reject undeclared top-level fields",
            operation_top_level_rejected,
        ),
        _check(
            "boolean_types_are_not_coerced",
            "Typed batches reject string values masquerading as booleans",
            boolean_coercion_rejected,
        ),
        _check(
            "mapping_payload_schema_is_closed",
            "Data mapping payloads reject undeclared top-level fields",
            mapping_top_level_rejected,
        ),
        _check(
            "session_computed_state_is_verified",
            "CanvasSession rejects persisted dirty state that conflicts with revisions",
            session_integrity_rejected,
        ),
    ]
    return {
        "kind": "sciplot_canvas_contract_probe",
        "version": 1,
        "status": "passed"
        if all(item["status"] == "passed" for item in checks)
        else "failed",
        "checks": checks,
        "artifacts": {
            "session": str(session_path),
            "annotations": str(annotations_path),
            "journal": str(journal_path),
        },
    }


def run_canvas_characterization(
    document_path: Path,
    *,
    output_root: Path,
) -> dict[str, Any]:
    """Characterize the pinned embedded Veusz lifecycle on a copied VSZ."""

    source = document_path.expanduser().resolve()
    if not source.is_file():
        raise FileNotFoundError(source)
    resolved_output = output_root.expanduser().resolve()
    resolved_output.mkdir(parents=True, exist_ok=True)
    run_root = Path(
        tempfile.mkdtemp(prefix="canvas_characterization_", dir=resolved_output)
    )
    summary_path = run_root / "canvas_characterization.json"
    copied_document = run_root / "document.vsz"
    shutil.copy2(source, copied_document)
    source_hash = file_sha256(source)

    session_path = run_root / "canvas_session.json"
    journal_path = run_root / "operation_journal.jsonl"
    export_root = run_root / "exact_current_export"
    recovery_root = run_root / "crash_recovery"
    checks: list[dict[str, Any]] = []
    controller: Any = None
    stderr_stack = ExitStack()
    stderr_log = run_root / "logs" / "canvas_qt_stderr.log"
    error: dict[str, str] | None = None
    evidence: dict[str, Any] = {}

    try:
        os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
        from sciplot_core.studio import _capture_process_stderr, export_studio_document
        from sciplot_gui.document_controller import DocumentController

        stderr_stack.enter_context(_capture_process_stderr(stderr_log))
        controller = DocumentController(
            document_path=copied_document,
            session_path=session_path,
            journal_path=journal_path,
            project_id=source.stem,
        )
        initial_render = controller.adapter.render_fingerprint()
        embedded_window_class = type(controller.adapter.plot_window).__name__
        embedded_document_class = type(controller.adapter.document).__name__
        target = controller.adapter.first_visible_text_target(controller.session)
        original_value = target["value"]
        new_value = (
            f"{original_value} [M0 Canvas]"
            if str(original_value).strip()
            else "M0 Canvas axis"
        )
        stable_ids_before = {
            item["structural_key"]: item["object_id"] for item in controller.inventory
        }

        batch = CanvasOperationBatch(
            base_revision=controller.session.revision,
            provider="m0_characterization",
            rationale="M0 live text-setting redraw characterization",
            operations=(
                CanvasOperation.set_setting(
                    target_id=target["object_id"],
                    setting_path=target["setting_path"],
                    value=new_value,
                    expected_value=original_value,
                    require_expected_value=True,
                ),
            ),
        )
        apply_entry = controller.apply_batch(batch)
        applied_render = controller.adapter.render_fingerprint()
        recovered_after_apply = load_canvas_session(session_path)
        applied_value = controller.adapter.setting_value(target["setting_path"])

        undo_entry = controller.undo(provider="m0_characterization")
        undo_render = controller.adapter.render_fingerprint()
        undo_value = controller.adapter.setting_value(target["setting_path"])

        redo_entry = controller.redo(provider="m0_characterization")
        redo_render = controller.adapter.render_fingerprint()
        redo_value = controller.adapter.setting_value(target["setting_path"])
        interactions = controller.adapter.interaction_characterization()
        saved_document = controller.save()
        saved_hash = file_sha256(saved_document)
        saved_revision = controller.session.saved_revision
        controller.close()
        controller = None

        reopened = DocumentController(
            document_path=copied_document,
            session_path=session_path,
            journal_path=journal_path,
            project_id=source.stem,
        )
        controller = reopened
        reopened_render = reopened.adapter.render_fingerprint()
        reopened_target = reopened.adapter.first_visible_text_target(reopened.session)
        reopened_value = reopened.adapter.setting_value(reopened_target["setting_path"])
        stable_ids_after = {
            item["structural_key"]: item["object_id"] for item in reopened.inventory
        }
        export_payload = export_studio_document(
            copied_document,
            formats=["pdf", "tiff_300"],
            output_dir=export_root,
        )
        exports = (
            export_payload.get("exports")
            if isinstance(export_payload.get("exports"), list)
            else []
        )
        reopened.mark_exported(exports)
        reopened.close()
        controller = None

        recovery_root.mkdir(parents=True, exist_ok=True)
        recovery_document = recovery_root / "document.vsz"
        recovery_session_path = recovery_root / "canvas_session.json"
        recovery_journal_path = recovery_root / "operation_journal.jsonl"
        shutil.copy2(source, recovery_document)
        recovery_controller = DocumentController(
            document_path=recovery_document,
            session_path=recovery_session_path,
            journal_path=recovery_journal_path,
            project_id=f"{source.stem}_recovery",
        )
        controller = recovery_controller
        recovery_target = recovery_controller.adapter.first_visible_text_target(
            recovery_controller.session
        )
        recovery_original_value = recovery_target["value"]
        recovery_new_value = (
            f"{recovery_original_value} [M0 Recovery]"
            if str(recovery_original_value).strip()
            else "M0 Recovery"
        )
        recovery_controller.apply_batch(
            CanvasOperationBatch(
                base_revision=recovery_controller.session.revision,
                provider="m0_crash_recovery",
                rationale="Persist an accepted unsaved edit as a recovery VSZ.",
                operations=(
                    CanvasOperation.set_setting(
                        target_id=recovery_target["object_id"],
                        setting_path=recovery_target["setting_path"],
                        value=recovery_new_value,
                        expected_value=recovery_original_value,
                        require_expected_value=True,
                    ),
                ),
            )
        )
        recovery_expected_render = recovery_controller.adapter.render_fingerprint()
        recovery_snapshot = _resolve_persisted_path(
            recovery_controller.session.recovery_snapshots[-1],
            root=recovery_session_path.parent,
        )
        recovery_controller.close()
        controller = None

        escaped_root = run_root / "escaped_recovery"
        shutil.copytree(recovery_root, escaped_root)
        escaped_session_path = escaped_root / "canvas_session.json"
        escaped_journal_path = escaped_root / "operation_journal.jsonl"
        escaped_document = escaped_root / "document.vsz"
        outside_snapshot = run_root / "outside_recovery.vsz"
        shutil.copy2(recovery_snapshot, outside_snapshot)
        escaped_session = load_canvas_session(escaped_session_path)
        escaped_reference = "../outside_recovery.vsz"
        escaped_session.recovery_snapshots = [escaped_reference]
        escaped_session.recovery_snapshot_hashes = {
            escaped_reference: file_sha256(outside_snapshot)
        }
        save_canvas_session(escaped_session_path, escaped_session)
        escaped_recovery_rejected = False
        escaped_recovery_error = ""
        try:
            escaped_controller = DocumentController(
                document_path=escaped_document,
                session_path=escaped_session_path,
                journal_path=escaped_journal_path,
                project_id=f"{source.stem}_escaped_recovery",
            )
        except RuntimeError as exc:
            escaped_recovery_rejected = "outside" in str(exc)
            escaped_recovery_error = str(exc)
        else:
            controller = escaped_controller
            escaped_controller.close()
            controller = None

        tampered_root = run_root / "tampered_recovery"
        shutil.copytree(recovery_root, tampered_root)
        tampered_session_path = tampered_root / "canvas_session.json"
        tampered_journal_path = tampered_root / "operation_journal.jsonl"
        tampered_document = tampered_root / "document.vsz"
        tampered_session = load_canvas_session(tampered_session_path)
        tampered_snapshot = _resolve_persisted_path(
            tampered_session.recovery_snapshots[-1],
            root=tampered_session_path.parent,
        )
        with tampered_snapshot.open("a", encoding="utf-8") as handle:
            handle.write("\n# M0 tampered recovery probe\n")
        tampered_recovery_rejected = False
        tampered_recovery_error = ""
        try:
            tampered_controller = DocumentController(
                document_path=tampered_document,
                session_path=tampered_session_path,
                journal_path=tampered_journal_path,
                project_id=f"{source.stem}_tampered_recovery",
            )
        except RuntimeError as exc:
            tampered_recovery_rejected = "integrity" in str(exc)
            tampered_recovery_error = str(exc)
        else:
            controller = tampered_controller
            tampered_controller.close()
            controller = None

        recovered_controller = DocumentController(
            document_path=recovery_document,
            session_path=recovery_session_path,
            journal_path=recovery_journal_path,
            project_id=f"{source.stem}_recovery",
        )
        controller = recovered_controller
        recovery_reopened_target = (
            recovered_controller.adapter.first_visible_text_target(
                recovered_controller.session
            )
        )
        recovery_reopened_value = recovered_controller.adapter.setting_value(
            recovery_reopened_target["setting_path"]
        )
        recovery_reopened_render = recovered_controller.adapter.render_fingerprint()
        recovered_from_snapshot = recovered_controller.recovered_from_snapshot
        recovered_controller.save()
        recovered_controller.close()
        controller = None

        with recovery_document.open("a", encoding="utf-8") as handle:
            handle.write("\n# M0 external conflict probe\n")
        external_conflict_rejected = False
        external_conflict_error = ""
        try:
            conflict_controller = DocumentController(
                document_path=recovery_document,
                session_path=recovery_session_path,
                journal_path=recovery_journal_path,
                project_id=f"{source.stem}_recovery",
            )
        except RuntimeError as exc:
            external_conflict_rejected = "changed outside" in str(exc)
            external_conflict_error = str(exc)
        else:
            controller = conflict_controller
            conflict_controller.close()
            controller = None

        journal = read_operation_journal(journal_path)
        recovery_journal = read_operation_journal(recovery_journal_path)
        exports_ready = {
            str(item.get("format"))
            for item in exports
            if isinstance(item, dict)
            and item.get("exists") is True
            and int(item.get("size_bytes") or 0) > 0
        }
        evidence = {
            "source": str(source),
            "copied_document": str(copied_document),
            "target": target,
            "original_value": original_value,
            "new_value": new_value,
            "initial_render": initial_render,
            "embedded_window_class": embedded_window_class,
            "embedded_document_class": embedded_document_class,
            "applied_render": applied_render,
            "undo_render": undo_render,
            "redo_render": redo_render,
            "reopened_render": reopened_render,
            "apply_entry": apply_entry,
            "undo_entry": undo_entry,
            "redo_entry": redo_entry,
            "interactions": interactions,
            "saved_hash": saved_hash,
            "saved_revision": saved_revision,
            "exports": exports,
            "journal_entries": len(journal),
            "crash_recovery": {
                "snapshot": str(recovery_snapshot),
                "snapshot_exists": recovery_snapshot.is_file(),
                "expected_value": recovery_new_value,
                "reopened_value": recovery_reopened_value,
                "expected_render": recovery_expected_render,
                "reopened_render": recovery_reopened_render,
                "recovered_from_snapshot": recovered_from_snapshot,
                "journal_events": [item.get("event") for item in recovery_journal],
                "external_conflict_rejected": external_conflict_rejected,
                "external_conflict_error": external_conflict_error,
                "tampered_recovery_rejected": tampered_recovery_rejected,
                "tampered_recovery_error": tampered_recovery_error,
                "escaped_recovery_rejected": escaped_recovery_rejected,
                "escaped_recovery_error": escaped_recovery_error,
            },
        }
        checks.extend(
            [
                _check(
                    "embedded_document_renders",
                    "Veusz Document renders through an embedded PlotWindow without MainWindow",
                    bool(initial_render)
                    and embedded_window_class == "PlotWindow"
                    and embedded_document_class == "Document",
                    {
                        "render_sha256": initial_render,
                        "window_class": embedded_window_class,
                        "document_class": embedded_document_class,
                    },
                ),
                _check(
                    "typed_setting_redraws_live",
                    "One typed visible-text operation changes the live canvas",
                    applied_value == new_value and applied_render != initial_render,
                    {
                        "setting_path": target["setting_path"],
                        "before": original_value,
                        "after": applied_value,
                        "render_changed": applied_render != initial_render,
                    },
                ),
                _check(
                    "recovery_snapshot_checkpoint",
                    "Accepted operation state is serialized as a recovery VSZ before close",
                    recovered_after_apply.revision == 1
                    and recovered_after_apply.last_render_sha256 == applied_render
                    and bool(recovered_after_apply.recovery_snapshots)
                    and _resolve_persisted_path(
                        recovered_after_apply.recovery_snapshots[-1],
                        root=session_path.parent,
                    ).is_file(),
                    recovered_after_apply.to_dict(),
                ),
                _check(
                    "dirty_session_auto_recovers",
                    "A dirty session reopens from its latest recovery VSZ without changing the canonical source",
                    recovery_snapshot.is_file()
                    and recovered_from_snapshot == str(recovery_snapshot.resolve())
                    and recovery_reopened_value == recovery_new_value
                    and recovery_reopened_render == recovery_expected_render
                    and "recovered_from_snapshot"
                    in {str(item.get("event")) for item in recovery_journal},
                    evidence["crash_recovery"],
                ),
                _check(
                    "external_vsz_conflict_blocks",
                    "A clean session refuses a canonical VSZ changed outside its revision history",
                    external_conflict_rejected,
                    evidence["crash_recovery"],
                ),
                _check(
                    "tampered_recovery_snapshot_blocks",
                    "A dirty session rejects a recovery VSZ whose recorded hash no longer matches",
                    tampered_recovery_rejected,
                    evidence["crash_recovery"],
                ),
                _check(
                    "recovery_path_escape_blocks",
                    "A dirty session rejects recovery references outside its project recovery root",
                    escaped_recovery_rejected,
                    evidence["crash_recovery"],
                ),
                _check(
                    "atomic_undo",
                    "The typed batch undoes as one Veusz history operation",
                    undo_value == original_value and undo_render == initial_render,
                    {
                        "value": undo_value,
                        "render_restored": undo_render == initial_render,
                    },
                ),
                _check(
                    "atomic_redo",
                    "The typed batch redoes and restores the edited render",
                    redo_value == new_value and redo_render == applied_render,
                    {
                        "value": redo_value,
                        "render_restored": redo_render == applied_render,
                    },
                ),
                _check(
                    "plotwindow_object_click",
                    "Embedded PlotWindow emits an object-selection signal",
                    interactions.get("selection_signal_received") is True,
                    interactions,
                ),
                _check(
                    "plotwindow_axis_coordinates",
                    "Embedded PlotWindow reports axis coordinates for a canvas point",
                    interactions.get("axis_coordinates_reported") is True,
                    interactions,
                ),
                _check(
                    "save_reopen_exact_state",
                    "The edited VSZ saves and reopens with the accepted value",
                    reopened_value == new_value
                    and saved_hash == file_sha256(copied_document)
                    and saved_revision == 3
                    and bool(reopened_render),
                    {
                        "reopened_value": reopened_value,
                        "saved_revision": saved_revision,
                        "render_sha256": reopened_render,
                    },
                ),
                _check(
                    "stable_object_ids_after_reopen",
                    "SciPlot object IDs remain stable across save and reopen",
                    stable_ids_before == stable_ids_after,
                    {
                        "object_count_before": len(stable_ids_before),
                        "object_count_after": len(stable_ids_after),
                    },
                ),
                _check(
                    "exact_current_export",
                    "The exact edited VSZ exports the canonical PDF/TIFF pair",
                    {"pdf", "tiff_300"} <= exports_ready,
                    {"formats": sorted(exports_ready), "exports": exports},
                ),
                _check(
                    "source_document_immutable",
                    "Characterization modifies only its copied VSZ",
                    file_sha256(source) == source_hash and source != copied_document,
                    {"source_sha256": source_hash},
                ),
                _check(
                    "typed_operation_journal",
                    "Apply, undo, redo, save, and export events are auditable",
                    {
                        "operation_batch_applied",
                        "undo",
                        "redo",
                        "save",
                        "exact_current_export",
                    }
                    <= {str(item.get("event")) for item in journal},
                    {"events": [item.get("event") for item in journal]},
                ),
            ]
        )
    except Exception as exc:
        error = {"type": type(exc).__name__, "message": str(exc)}
        checks.append(
            _check(
                "canvas_characterization_exception",
                "Canvas characterization completes without an exception",
                False,
                error,
            )
        )
    finally:
        if controller is not None:
            try:
                controller.close()
            except Exception:
                pass
        stderr_stack.close()

    status = (
        "passed"
        if checks and all(item["status"] == "passed" for item in checks)
        else "failed"
    )
    payload = {
        "kind": CANVAS_CHARACTERIZATION_KIND,
        "version": CANVAS_CHARACTERIZATION_VERSION,
        "generated_at": _now(),
        "status": status,
        "state": "ready" if status == "passed" else "needs_rule_repair",
        "checks": checks,
        "summary": {
            "check_count": len(checks),
            "passed_count": sum(item["status"] == "passed" for item in checks),
            "failed_ids": [item["id"] for item in checks if item["status"] != "passed"],
        },
        "evidence": evidence,
        "artifacts": {
            "run_root": str(run_root),
            "copied_document": str(copied_document),
            "session": str(session_path),
            "journal": str(journal_path),
            "exports": str(export_root),
            "recovery_root": str(recovery_root),
            "stderr_log": str(stderr_log) if stderr_log.is_file() else None,
            "summary": str(summary_path),
        },
        "error": error,
        "limitations": [
            "This probe characterizes the pinned Veusz adapter and typed setting path; "
            "it is not the M1 user-facing Canvas shell.",
            "The probe works on a copied VSZ and does not count as real-data acceptance "
            "unless the supplied source VSZ itself came from authorized real data.",
        ],
    }
    summary_path.write_text(
        json.dumps(json_safe(payload), indent=2, ensure_ascii=False),
        encoding="utf-8",
    )
    return payload


__all__ = [
    "CANVAS_CHARACTERIZATION_KIND",
    "CANVAS_CHARACTERIZATION_VERSION",
    "run_canvas_characterization",
    "run_canvas_contract_probe",
]
