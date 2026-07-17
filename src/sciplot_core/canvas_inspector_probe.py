from __future__ import annotations

import json
import os
import shutil
import tempfile
import traceback
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from uuid import uuid4

from sciplot_core._utils import file_sha256, json_safe
from sciplot_core.canvas.inspector import (
    INSPECTOR_EDITORS,
    SUPPORTED_INSPECTOR_TYPES,
)
from sciplot_core.canvas.persistence import read_operation_journal
from sciplot_core.canvas.provider import AssistantRequest

CANVAS_INSPECTOR_PROBE_KIND = "sciplot_canvas_inspector_matrix"
CANVAS_INSPECTOR_PROBE_VERSION = 1


def _now() -> str:
    return datetime.now(UTC).isoformat()


def _check(
    check_id: str,
    label: str,
    passed: bool,
    detail: Any = None,
) -> dict[str, Any]:
    return {
        "id": check_id,
        "label": label,
        "status": "passed" if passed else "failed",
        "detail": json_safe(detail),
    }


def _safe_name(path: Path, index: int) -> str:
    stem = path.stem or f"document_{index + 1}"
    cleaned = "".join(
        character if character.isalnum() or character in {"-", "_"} else "_"
        for character in stem
    ).strip("_")
    return f"{index + 1:02d}_{cleaned or 'document'}"


def _exercise_document(
    source: Path,
    *,
    run_root: Path,
    index: int,
    application: Any,
) -> dict[str, Any]:
    from sciplot_gui.main_window import SciPlotCanvasWindow
    from sciplot_gui.workspace import resolve_canvas_workspace

    name = _safe_name(source, index)
    document_root = run_root / name
    document_root.mkdir(parents=True, exist_ok=True)
    copied_document = document_root / source.name
    shutil.copy2(source, copied_document)
    source_hash = file_sha256(source)
    workspace = resolve_canvas_workspace(copied_document)
    window = SciPlotCanvasWindow(workspace, interactive=False)
    object_reports: list[dict[str, Any]] = []
    qa_reports: list[dict[str, Any]] = []
    direct_drag: dict[str, Any] | None = None
    try:
        window.show()
        application.processEvents()
        for page_index in range(window.controller.adapter.page_count):
            window.controller.set_page(page_index)
            page_path = window.controller.adapter.current_page_path
            window.controller.inventory = (
                window.controller.adapter.bind_object_registry(
                    window.controller.session
                )
            )
            page_items = [
                item
                for item in window.controller.inventory
                if item.get("object_type") in SUPPORTED_INSPECTOR_TYPES
                and (
                    str(item.get("path")) == page_path
                    or str(item.get("path")).startswith(f"{page_path}/")
                )
            ]
            for item in page_items:
                window.controller.select_object_id(str(item["object_id"]))
                model = window.controller.contextual_inspector()
                field_paths_valid = all(
                    field.setting_path.startswith(f"{model.target.path}/")
                    for field in model.fields
                )
                choice_fields_valid = all(
                    field.editor != "choice" or bool(field.choices)
                    for field in model.fields
                )
                dataset_fields_read_only = all(
                    field.editor != "dataset" or field.read_only
                    for field in model.fields
                )
                editor_types_valid = all(
                    field.editor in INSPECTOR_EDITORS for field in model.fields
                )
                assistant_context_valid = False
                assistant_context_error: str | None = None
                assistant_capability_count = 0
                try:
                    assistant_request = AssistantRequest(
                        transaction_id=str(uuid4()),
                        provider_id="inspector_matrix",
                        intent="Validate this selected object's bounded catalog.",
                        base_revision=window.controller.session.revision,
                        context=window.assistant.context_summary(),
                        allowed_proposal_kinds=("canvas_operation_batch",),
                    )
                    allowed_operations = assistant_request.context[
                        "editing_capabilities"
                    ]["allowed_operations"]
                    editable_fields = [
                        field for field in model.fields if not field.read_only
                    ]
                    assistant_capability_count = len(allowed_operations)
                    assistant_context_valid = (
                        assistant_capability_count == len(editable_fields)
                        and {item["field_id"] for item in allowed_operations}
                        == {field.field_id for field in editable_fields}
                        and {
                            item["setting_path"] for item in allowed_operations
                        }
                        == {field.setting_path for field in editable_fields}
                        and all(
                            item["editor"] not in {"dataset", "read_only"}
                            for item in allowed_operations
                        )
                    )
                    if not assistant_context_valid:
                        assistant_context_error = (
                            "Capability catalog does not exactly match editable "
                            "Inspector fields."
                        )
                except (KeyError, TypeError, ValueError) as exc:
                    assistant_context_error = str(exc)
                coercion_errors: list[dict[str, str]] = []
                for field in model.fields:
                    if field.read_only:
                        continue
                    try:
                        field.coerce_input(field.value)
                    except ValueError as exc:
                        coercion_errors.append(
                            {
                                "field_id": field.field_id,
                                "error": str(exc),
                            }
                        )
                window.inspector_panel.set_model(model)
                editor_roundtrip_changes: list[dict[str, Any]] = []
                editor_roundtrip_error: str | None = None
                try:
                    editor_roundtrip_changes = (
                        window.inspector_panel.collect_changes()
                    )
                except ValueError as exc:
                    editor_roundtrip_error = str(exc)
                object_reports.append(
                    {
                        "page_index": page_index,
                        "object_id": model.target.object_id,
                        "path": model.target.path,
                        "object_type": model.target.object_type,
                        "field_count": len(model.fields),
                        "field_ids": [
                            field.field_id for field in model.fields
                        ],
                        "field_paths_valid": field_paths_valid,
                        "choice_fields_valid": choice_fields_valid,
                        "dataset_fields_read_only": dataset_fields_read_only,
                        "editor_types_valid": editor_types_valid,
                        "assistant_context_valid": assistant_context_valid,
                        "assistant_capability_count": assistant_capability_count,
                        "assistant_context_error": assistant_context_error,
                        "current_values_coercible": not coercion_errors,
                        "coercion_errors": coercion_errors,
                        "editor_roundtrip_clean": (
                            not window.inspector_panel.has_staged_changes
                            and not editor_roundtrip_changes
                            and editor_roundtrip_error is None
                        ),
                        "editor_roundtrip_changes": editor_roundtrip_changes,
                        "editor_roundtrip_error": editor_roundtrip_error,
                        "model_json": model.to_dict(),
                    }
                )
            qa_reports.append(window.controller.run_structural_qa())

        label_item = next(
            (
                item
                for item in window.controller.inventory
                if item.get("object_type") == "label"
            ),
            None,
        )
        if label_item is not None:
            label_path = str(label_item["path"])
            page_path = f"/{label_path.strip('/').split('/')[0]}"
            pages = [
                child
                for child in window.controller.adapter.document.basewidget.children
                if child.typename == "page"
            ]
            label_page = next(
                (
                    page_index
                    for page_index, page in enumerate(pages)
                    if str(page.path) == page_path
                ),
                0,
            )
            window.controller.set_page(label_page)
            window.controller.select_object_id(str(label_item["object_id"]))
            window._refresh_contextual_inspector()
            application.processEvents()
            widget = window.controller.adapter._widget(label_path)
            controls = (
                window.plot_window.painthelper.getControlGraph(widget)
                if window.plot_window.painthelper is not None
                else []
            )
            if controls:
                control = controls[0]
                revision_before = window.controller.session.revision
                render_before = (
                    window.controller.adapter.render_fingerprint()
                )
                x_before = list(widget.settings.xPos)
                y_before = list(widget.settings.yPos)
                control.posn[0] += 4.0
                control.posn[1] += 3.0
                control.posn[2] += 4.0
                control.posn[3] += 3.0
                widget.updateControlItem(control)
                application.processEvents()
                x_after = list(widget.settings.xPos)
                y_after = list(widget.settings.yPos)
                staged_after_drag = (
                    window.inspector_panel.has_staged_changes
                )
                staged_changes_after_drag: list[dict[str, Any]] = []
                staged_error_after_drag: str | None = None
                try:
                    staged_changes_after_drag = (
                        window.inspector_panel.collect_changes()
                    )
                except ValueError as exc:
                    staged_error_after_drag = str(exc)
                direct_drag = {
                    "path": label_path,
                    "revision_before": revision_before,
                    "revision_after": window.controller.session.revision,
                    "render_before": render_before,
                    "render_after": (
                        window.controller.adapter.render_fingerprint()
                    ),
                    "x_before": x_before,
                    "x_after": x_after,
                    "y_before": y_before,
                    "y_after": y_after,
                    "direct_manipulation_supported": (
                        window.controller.adapter.direct_manipulation_supported
                    ),
                    "staged_after_drag": staged_after_drag,
                    "staged_changes_after_drag": staged_changes_after_drag,
                    "staged_error_after_drag": staged_error_after_drag,
                }
                window.save_document()
        journal = read_operation_journal(workspace.journal_path)
        direct_entries = [
            entry
            for entry in journal
            if (
                entry.get("event") == "operation_batch_applied"
                and (entry.get("batch") or {}).get("provider")
                == "user_direct_manipulation"
            )
        ]
        if direct_drag is not None:
            direct_drag["journal_entry_count"] = len(direct_entries)
        source_immutable = (
            source.is_file() and file_sha256(source) == source_hash
        )
        return {
            "name": name,
            "source": str(source),
            "copied_document": str(copied_document),
            "source_immutable": source_immutable,
            "object_reports": object_reports,
            "structural_qa": qa_reports,
            "direct_drag": direct_drag,
        }
    finally:
        if not window._closed:
            if window.inspector_panel.has_staged_changes:
                window.inspector_panel.revert_staged()
            if (
                window.controller.session.dirty
                and not window.inspector_panel.has_staged_changes
            ):
                window.save_document()
            window.close()
            application.processEvents()


def run_canvas_inspector_matrix_probe(
    documents: list[Path],
    *,
    output_root: Path,
) -> dict[str, Any]:
    if not documents:
        raise ValueError("At least one VSZ document is required.")
    sources = [path.expanduser().resolve() for path in documents]
    for source in sources:
        if not source.is_file() or source.suffix.casefold() != ".vsz":
            raise FileNotFoundError(f"Canvas inspector probe needs a VSZ: {source}")

    resolved_output = output_root.expanduser().resolve()
    resolved_output.mkdir(parents=True, exist_ok=True)
    run_root = Path(
        tempfile.mkdtemp(prefix="canvas_inspector_matrix_", dir=resolved_output)
    )
    summary_path = run_root / "canvas_inspector_matrix.json"
    checks: list[dict[str, Any]] = []
    reports: list[dict[str, Any]] = []
    errors: list[dict[str, str]] = []

    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PyQt6 import QtWidgets

    application = QtWidgets.QApplication.instance()
    owns_application = application is None
    if application is None:
        application = QtWidgets.QApplication([])
    application.setApplicationName("SciPlot Canvas Inspector Matrix")
    application.setQuitOnLastWindowClosed(False)

    for index, source in enumerate(sources):
        try:
            reports.append(
                _exercise_document(
                    source,
                    run_root=run_root,
                    index=index,
                    application=application,
                )
            )
        except Exception as exc:
            errors.append(
                {
                    "source": str(source),
                    "type": type(exc).__name__,
                    "message": str(exc),
                    "traceback": traceback.format_exc(),
                }
            )

    object_reports = [
        item
        for report in reports
        for item in report.get("object_reports", [])
        if isinstance(item, dict)
    ]
    seen_types = {
        str(item.get("object_type")) for item in object_reports
    }
    required_types = set(SUPPORTED_INSPECTOR_TYPES)
    invalid_objects = [
        item
        for item in object_reports
        if (
            int(item.get("field_count") or 0) < 1
            or item.get("field_paths_valid") is not True
            or item.get("choice_fields_valid") is not True
            or item.get("dataset_fields_read_only") is not True
            or item.get("editor_types_valid") is not True
            or item.get("assistant_context_valid") is not True
            or item.get("current_values_coercible") is not True
        )
    ]
    editor_roundtrip_failures = [
        item
        for item in object_reports
        if item.get("editor_roundtrip_clean") is not True
    ]
    qa_reports = [
        qa
        for report in reports
        for qa in report.get("structural_qa", [])
        if isinstance(qa, dict)
    ]
    direct_reports = [
        report["direct_drag"]
        for report in reports
        if isinstance(report.get("direct_drag"), dict)
    ]
    direct_passed = any(
        int(report.get("revision_after") or 0)
        == int(report.get("revision_before") or 0) + 1
        and report.get("render_after") != report.get("render_before")
        and (
            report.get("x_after") != report.get("x_before")
            or report.get("y_after") != report.get("y_before")
        )
        and report.get("staged_after_drag") is False
        and not report.get("staged_changes_after_drag")
        and report.get("staged_error_after_drag") is None
        and int(report.get("journal_entry_count") or 0) == 1
        for report in direct_reports
    )

    checks.extend(
        [
            _check(
                "every_document_loaded",
                "Every representative VSZ opens in the native Canvas",
                len(reports) == len(sources) and not errors,
                {"reports": len(reports), "sources": len(sources), "errors": errors},
            ),
            _check(
                "full_supported_object_matrix",
                "The representative set covers every bounded M2 object editor",
                required_types <= seen_types,
                {
                    "required_types": sorted(required_types),
                    "seen_types": sorted(seen_types),
                    "missing_types": sorted(required_types - seen_types),
                },
            ),
            _check(
                "all_contextual_models_valid",
                "Every supported object builds a finite, scoped manual and Assistant context model",
                bool(object_reports) and not invalid_objects,
                {
                    "object_count": len(object_reports),
                    "invalid_objects": invalid_objects,
                },
            ),
            _check(
                "all_editor_roundtrips_clean",
                "Every contextual editor loads without inventing staged changes",
                bool(object_reports) and not editor_roundtrip_failures,
                {
                    "object_count": len(object_reports),
                    "failures": editor_roundtrip_failures,
                },
            ),
            _check(
                "all_dataset_fields_read_only",
                "No contextual inspector exposes dataset mapping as a visual mutation",
                all(
                    item.get("dataset_fields_read_only") is True
                    for item in object_reports
                ),
                {"object_count": len(object_reports)},
            ),
            _check(
                "structural_qa_ready",
                "Fast structural QA reaches the artifact-QA boundary on every representative document",
                len(qa_reports) >= len(sources)
                and all(
                    qa.get("ready_for_artifact_qa") is True
                    and qa.get("status") in {"warning", "passed"}
                    for qa in qa_reports
                ),
                qa_reports,
            ),
            _check(
                "native_label_drag_is_typed",
                "A native annotation drag becomes one typed, journaled Canvas batch",
                direct_passed,
                direct_reports,
            ),
            _check(
                "representative_sources_immutable",
                "Matrix validation mutates only copied VSZ documents",
                reports
                and all(
                    report.get("source_immutable") is True for report in reports
                ),
                [
                    {
                        "source": report.get("source"),
                        "source_immutable": report.get("source_immutable"),
                    }
                    for report in reports
                ],
            ),
        ]
    )
    if owns_application:
        application.quit()

    status = (
        "passed"
        if checks and all(check["status"] == "passed" for check in checks)
        else "failed"
    )
    payload = {
        "kind": CANVAS_INSPECTOR_PROBE_KIND,
        "version": CANVAS_INSPECTOR_PROBE_VERSION,
        "generated_at": _now(),
        "status": status,
        "state": "ready" if status == "passed" else "needs_rule_repair",
        "summary": {
            "document_count": len(sources),
            "object_count": len(object_reports),
            "supported_types": sorted(seen_types),
            "check_count": len(checks),
            "passed_count": sum(
                check["status"] == "passed" for check in checks
            ),
            "failed_ids": [
                check["id"]
                for check in checks
                if check["status"] != "passed"
            ],
        },
        "checks": checks,
        "reports": reports,
        "errors": errors,
        "artifacts": {
            "run_root": str(run_root),
            "summary": str(summary_path),
        },
    }
    summary_path.write_text(
        json.dumps(json_safe(payload), indent=2, ensure_ascii=False),
        encoding="utf-8",
    )
    return payload


__all__ = [
    "CANVAS_INSPECTOR_PROBE_KIND",
    "CANVAS_INSPECTOR_PROBE_VERSION",
    "run_canvas_inspector_matrix_probe",
]
