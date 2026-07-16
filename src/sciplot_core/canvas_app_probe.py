from __future__ import annotations

import json
import os
import shutil
import sys
import tempfile
from contextlib import ExitStack
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from PIL import Image

from sciplot_core._utils import file_sha256, json_safe
from sciplot_core.canvas.persistence import read_operation_journal

CANVAS_APP_PROBE_KIND = "sciplot_canvas_app_probe"
CANVAS_APP_PROBE_VERSION = 1


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


def _source_document(target: Path) -> Path | None:
    if target.is_file() and target.suffix.casefold() == ".vsz":
        return target
    if target.is_file() and target.name == "plot_request.json":
        candidate = target.parent / "studio" / "document.vsz"
        return candidate if candidate.is_file() else None
    if target.is_dir():
        candidate = target / "studio" / "document.vsz"
        if candidate.is_file():
            return candidate
        candidates = sorted(target.glob("**/studio/document.vsz"))
        if len(candidates) == 1:
            return candidates[0]
    return None


def _copy_probe_target(source: Path, run_root: Path) -> Path:
    if source.is_dir():
        copied = run_root / "project"
        shutil.copytree(
            source,
            copied,
            ignore=shutil.ignore_patterns(
                ".sciplot_canvas",
                "runs",
                "delivery",
                "*.zip",
                "__pycache__",
            ),
        )
        return copied
    if source.is_file() and source.name == "plot_request.json":
        copied = run_root / "project"
        shutil.copytree(
            source.parent,
            copied,
            ignore=shutil.ignore_patterns(
                ".sciplot_canvas",
                "runs",
                "delivery",
                "*.zip",
                "__pycache__",
            ),
        )
        return copied / "plot_request.json"
    if source.is_file() and source.suffix.casefold() == ".vsz":
        copied = run_root / source.name
        shutil.copy2(source, copied)
        return copied
    raise ValueError(
        "Canvas app probe accepts an existing SciPlot project, plot_request.json, "
        "or VSZ document."
    )


def _capture_window(
    window: Any,
    path: Path,
    *,
    application: Any,
) -> dict[str, Any]:
    from PyQt6 import QtCore, QtGui, QtTest, QtWidgets

    window.controller.zoom_to_page()
    window.controller.adapter.force_redraw()
    window._sync_ui()
    window.ensurePolished()
    for widget in window.findChildren(QtWidgets.QWidget):
        widget.ensurePolished()
        widget.update()
    window.update()
    QtTest.QTest.qWait(150)
    for _ in range(8):
        application.sendPostedEvents()
        application.processEvents(
            QtCore.QEventLoop.ProcessEventsFlag.AllEvents,
            50,
        )
    opaque_image = (
        window.grab().toImage().convertToFormat(QtGui.QImage.Format.Format_RGB888)
    )
    if not opaque_image.save(str(path)):
        raise RuntimeError(f"Could not save Canvas screenshot: {path}")
    with Image.open(path) as image:
        rgb = image.convert("RGB")
        extrema = rgb.getextrema()
        width, height = rgb.size
        canvas_crop = rgb.crop((0, 40, round(width * 0.75), height - 25))
        canvas_luma = canvas_crop.convert("L")
        canvas_mean_luminance = sum(
            canvas_luma.histogram()[index] * index for index in range(256)
        ) / (canvas_luma.width * canvas_luma.height)
        inspector_crop = rgb.crop((round(width * 0.75), 40, width, height - 25))
        inspector_luma = inspector_crop.convert("L")
        inspector_mean_luminance = sum(
            inspector_luma.histogram()[index] * index for index in range(256)
        ) / (inspector_luma.width * inspector_luma.height)
    return {
        "path": str(path),
        "width": width,
        "height": height,
        "channel_extrema": extrema,
        "has_tonal_range": all(high - low >= 80 for low, high in extrema),
        "canvas_mean_luminance": round(canvas_mean_luminance, 3),
        "canvas_surface_ready": canvas_mean_luminance >= 90.0,
        "inspector_mean_luminance": round(inspector_mean_luminance, 3),
        "inspector_surface_ready": inspector_mean_luminance >= 160.0,
    }


def _summarize_export(payload: dict[str, Any]) -> dict[str, Any]:
    exports = payload.get("exports")
    exports = exports if isinstance(exports, list) else []
    export_items = [
        {
            "format": item.get("format"),
            "path": item.get("path"),
            "exists": item.get("exists") is True,
            "size_bytes": int(item.get("size_bytes") or 0),
        }
        for item in exports
        if isinstance(item, dict)
    ]
    summary: dict[str, Any] = {
        "scope": payload.get("scope"),
        "status": payload.get("status"),
        "state": payload.get("state"),
        "ready_to_use": payload.get("ready_to_use") is True,
        "exports": export_items,
    }
    if payload.get("scope") == "project_delivery":
        run = payload.get("studio_run")
        run = run if isinstance(run, dict) else {}
        delivery = run.get("delivery_package")
        delivery = delivery if isinstance(delivery, dict) else {}
        qa = run.get("qa")
        qa = qa if isinstance(qa, dict) else {}
        summary["project_delivery"] = {
            "manifest": run.get("manifest"),
            "review_html": run.get("review_html"),
            "revision_brief": run.get("revision_brief"),
            "delivery_path": delivery.get("path"),
            "delivery_complete": delivery.get("complete") is True,
            "qa_status": qa.get("status"),
        }
    else:
        receipt = payload.get("standalone_export")
        receipt = receipt if isinstance(receipt, dict) else {}
        summary["standalone_export"] = {
            "receipt": receipt.get("receipt_path"),
            "qa_report": receipt.get("artifact_qa_path"),
            "export_ready": receipt.get("export_ready") is True,
            "project_delivery_complete": receipt.get("project_delivery_complete")
            is True,
            "provenance_complete": receipt.get("provenance_complete") is True,
        }
    return summary


def run_canvas_app_probe(
    target: Path,
    *,
    output_root: Path,
    operation_count: int = 50,
) -> dict[str, Any]:
    if operation_count < 1:
        raise ValueError("operation_count must be positive.")
    source = target.expanduser().resolve()
    if not source.exists():
        raise FileNotFoundError(source)
    source_document = _source_document(source)
    source_hash = file_sha256(source_document) if source_document else None
    resolved_output = output_root.expanduser().resolve()
    resolved_output.mkdir(parents=True, exist_ok=True)
    run_root = Path(tempfile.mkdtemp(prefix="canvas_app_probe_", dir=resolved_output))
    copied_target = _copy_probe_target(source, run_root)
    summary_path = run_root / "canvas_app_probe.json"
    screenshot_path = run_root / "canvas_window.png"
    recovery_screenshot_path = run_root / "canvas_recovered.png"
    stderr_log = run_root / "logs" / "canvas_app_stderr.log"
    checks: list[dict[str, Any]] = []
    evidence: dict[str, Any] = {}
    error: dict[str, str] | None = None
    windows: list[Any] = []
    stderr_stack = ExitStack()

    try:
        os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
        from PyQt6 import QtWidgets

        from sciplot_core.studio import _capture_process_stderr
        from sciplot_gui.main_window import SciPlotCanvasWindow
        from sciplot_gui.workspace import resolve_canvas_workspace

        stderr_stack.enter_context(_capture_process_stderr(stderr_log))
        application = QtWidgets.QApplication.instance()
        owns_application = application is None
        if application is None:
            application = QtWidgets.QApplication([])
        application.setApplicationName("SciPlot Canvas Probe")
        application.setQuitOnLastWindowClosed(False)

        workspace = resolve_canvas_workspace(copied_target)
        window = SciPlotCanvasWindow(workspace, interactive=False)
        windows.append(window)
        window.show()
        application.processEvents()
        application.processEvents()

        initial_render = window.controller.adapter.render_fingerprint()
        interaction = window.controller.adapter.interaction_characterization()
        application.processEvents()
        clicked_selection = window.controller.selected_object

        target_info = window.controller.visible_text_targets()[0]
        selected_target = window.select_text_target(str(target_info["object_id"]))
        text_target_count = window.text_target_combo.count()
        inspector_initially_visible = window.inspector.isVisible()
        window.inspector_action.trigger()
        application.processEvents()
        inspector_hides = not window.inspector.isVisible()
        window.inspector_action.trigger()
        application.processEvents()
        inspector_restores = window.inspector.isVisible()
        advanced_editor_in_more = (
            window.advanced_action in window.more_menu.actions()
            and window.advanced_action not in window.toolbar.actions()
        )
        original_value = window.controller.adapter.setting_value(
            str(selected_target["setting_path"])
        )
        value_a = f"{original_value} [M1 A]"
        value_b = f"{original_value} [M1 B]"
        render_hashes = [window.controller.adapter.render_fingerprint()]
        applied_values: list[str] = []
        for index in range(operation_count):
            value = value_a if index % 2 == 0 else value_b
            window.apply_selected_text(value)
            application.processEvents()
            applied_values.append(value)
            render_hashes.append(window.controller.adapter.render_fingerprint())
        final_value = applied_values[-1]
        revision_after_operations = window.controller.session.revision
        render_changes = sum(
            previous != current
            for previous, current in zip(
                render_hashes[:-1],
                render_hashes[1:],
                strict=True,
            )
        )
        window.save_document()
        application.processEvents()
        export_payload = window.export_current()
        normal_screenshot = _capture_window(
            window,
            screenshot_path,
            application=application,
        )
        window_class = type(window).__name__
        exported_revision = window.controller.session.exported_revision
        saved_hash = file_sha256(workspace.document_path)
        window.close()
        application.processEvents()

        reopened = SciPlotCanvasWindow(workspace, interactive=False)
        windows.append(reopened)
        reopened.show()
        application.processEvents()
        reopened_target = reopened.select_text_target(str(target_info["object_id"]))
        reopened_value = reopened.controller.adapter.setting_value(
            str(reopened_target["setting_path"])
        )
        reopened_render = reopened.controller.adapter.render_fingerprint()
        reopened_revision = reopened.controller.session.revision
        reopened_exported_revision = reopened.controller.session.exported_revision
        reopened_state = reopened.controller.session.state

        recovery_value = f"{original_value} [M1 Recovery]"
        reopened.apply_selected_text(recovery_value)
        application.processEvents()
        recovery_revision = reopened.controller.session.revision
        recovery_render = reopened.controller.adapter.render_fingerprint()
        reopened.set_close_policy_for_test("keep_recovery")
        reopened.close()
        application.processEvents()

        recovered = SciPlotCanvasWindow(workspace, interactive=False)
        windows.append(recovered)
        recovered.show()
        application.processEvents()
        recovered_target = recovered.select_text_target(str(target_info["object_id"]))
        recovered_value = recovered.controller.adapter.setting_value(
            str(recovered_target["setting_path"])
        )
        recovered_render = recovered.controller.adapter.render_fingerprint()
        recovered_from_snapshot = recovered.controller.recovered_from_snapshot
        recovered_state = recovered.controller.session.state
        recovery_banner_visible = recovered.recovery_banner.isVisible()
        recovery_undo_available = recovered.controller.adapter.can_undo
        recovery_screenshot = _capture_window(
            recovered,
            recovery_screenshot_path,
            application=application,
        )
        recovered.save_document()
        final_document_hash = file_sha256(workspace.document_path)
        recovered.close()
        application.processEvents()

        journal = read_operation_journal(workspace.journal_path)
        journal_events = [str(item.get("event")) for item in journal]
        source_immutable = source_document is None or (
            source_hash is not None
            and source_document.is_file()
            and file_sha256(source_document) == source_hash
        )
        screenshot_ready = (
            screenshot_path.is_file()
            and screenshot_path.stat().st_size > 0
            and recovery_screenshot_path.is_file()
            and recovery_screenshot_path.stat().st_size > 0
            and normal_screenshot["width"] >= 900
            and normal_screenshot["height"] >= 600
            and normal_screenshot["has_tonal_range"] is True
            and recovery_screenshot["has_tonal_range"] is True
            and normal_screenshot["canvas_surface_ready"] is True
            and recovery_screenshot["canvas_surface_ready"] is True
            and normal_screenshot["inspector_surface_ready"] is True
            and recovery_screenshot["inspector_surface_ready"] is True
        )
        exports = export_payload.get("exports")
        exported_formats = {
            str(item.get("format"))
            for item in exports
            if isinstance(item, dict)
            and item.get("exists") is True
            and int(item.get("size_bytes") or 0) > 0
        }
        export_evidence = _summarize_export(export_payload)
        if export_payload.get("scope") == "project_delivery":
            project_delivery = export_evidence.get("project_delivery")
            project_delivery = (
                project_delivery if isinstance(project_delivery, dict) else {}
            )
            delivery_boundary_honest = (
                export_payload.get("ready_to_use") is True
                and project_delivery.get("delivery_complete") is True
                and project_delivery.get("qa_status") == "passed"
            )
        else:
            standalone_export = export_evidence.get("standalone_export")
            standalone_export = (
                standalone_export if isinstance(standalone_export, dict) else {}
            )
            delivery_boundary_honest = (
                export_payload.get("scope") == "standalone_exact_current_export"
                and standalone_export.get("project_delivery_complete") is False
                and standalone_export.get("provenance_complete") is False
            )
        no_veusz_mainwindow = (
            "veusz.windows.mainwindow" not in sys.modules
            and window_class == "SciPlotCanvasWindow"
        )
        evidence = {
            "source": str(source),
            "copied_target": str(copied_target),
            "workspace": workspace.to_dict(),
            "window_class": window_class,
            "initial_render": initial_render,
            "interaction": interaction,
            "clicked_selection": clicked_selection,
            "text_target": target_info,
            "inspector_toggle": {
                "initially_visible": inspector_initially_visible,
                "hides": inspector_hides,
                "restores": inspector_restores,
            },
            "advanced_editor_in_more": advanced_editor_in_more,
            "original_value": original_value,
            "final_value": final_value,
            "reopened_value": reopened_value,
            "recovery_value": recovery_value,
            "recovered_value": recovered_value,
            "operation_count": operation_count,
            "revision_after_operations": revision_after_operations,
            "reopened_revision": reopened_revision,
            "reopened_state": reopened_state,
            "recovery_revision": recovery_revision,
            "recovered_state": recovered_state,
            "render_changes": render_changes,
            "render_hash_count": len(render_hashes),
            "reopened_render": reopened_render,
            "recovery_render": recovery_render,
            "recovered_render": recovered_render,
            "saved_hash": saved_hash,
            "final_document_hash": final_document_hash,
            "exported_revision": exported_revision,
            "reopened_exported_revision": reopened_exported_revision,
            "export": export_evidence,
            "journal_events": journal_events,
            "recovered_from_snapshot": recovered_from_snapshot,
            "recovery_banner_visible": recovery_banner_visible,
            "recovery_undo_available": recovery_undo_available,
            "source_immutable": source_immutable,
            "owns_application": owns_application,
            "normal_screenshot": normal_screenshot,
            "recovery_screenshot": recovery_screenshot,
        }
        checks.extend(
            [
                _check(
                    "native_sciplot_window",
                    "The M1 shell is SciPlot-owned and never imports Veusz MainWindow",
                    no_veusz_mainwindow,
                    {
                        "window_class": window_class,
                        "mainwindow_module_loaded": "veusz.windows.mainwindow"
                        in sys.modules,
                    },
                ),
                _check(
                    "embedded_plotwindow_renders",
                    "The native shell renders the exact-current VSZ in its embedded PlotWindow",
                    bool(initial_render),
                    {"render_sha256": initial_render},
                ),
                _check(
                    "canvas_click_updates_selection",
                    "A PlotWindow click updates the SciPlot selection state",
                    interaction.get("selection_signal_received") is True
                    and clicked_selection is not None,
                    {
                        "interaction": interaction,
                        "selection": clicked_selection,
                    },
                ),
                _check(
                    "bounded_text_inspector",
                    "The focused visible-text inspector selects a stable Canvas object",
                    selected_target.get("object_id") == target_info.get("object_id")
                    and text_target_count > 0
                    and inspector_initially_visible
                    and inspector_hides
                    and inspector_restores
                    and advanced_editor_in_more,
                    {
                        "selection": selected_target,
                        "target_count": text_target_count,
                        "inspector_toggle": {
                            "initially_visible": inspector_initially_visible,
                            "hides": inspector_hides,
                            "restores": inspector_restores,
                        },
                        "advanced_editor_in_more": advanced_editor_in_more,
                    },
                ),
                _check(
                    "sequential_typed_operations",
                    f"{operation_count} sequential user-path operations complete",
                    revision_after_operations == operation_count
                    and len(applied_values) == operation_count,
                    {
                        "revision": revision_after_operations,
                        "operation_count": operation_count,
                    },
                ),
                _check(
                    "every_operation_redraws",
                    "Every sequential operation changes the visible live render without reload",
                    render_changes == operation_count,
                    {
                        "render_changes": render_changes,
                        "operation_count": operation_count,
                    },
                ),
                _check(
                    "save_reopen_preserves_state",
                    "Saving and reopening preserves the final accepted value and revision",
                    reopened_value == final_value
                    and reopened_revision == revision_after_operations
                    and reopened_state == "ready"
                    and bool(reopened_render),
                    {
                        "expected_value": final_value,
                        "reopened_value": reopened_value,
                        "revision": reopened_revision,
                        "state": reopened_state,
                    },
                ),
                _check(
                    "exact_current_export_and_qa",
                    "The saved document exports a non-empty PDF/TIFF pair through deterministic QA",
                    {"pdf", "tiff_300"} <= exported_formats
                    and export_payload.get("ready_to_use") is True,
                    export_evidence,
                ),
                _check(
                    "project_delivery_gate",
                    "Project Canvas exports require delivery while standalone VSZ "
                    "exports make no project-provenance claim",
                    delivery_boundary_honest,
                    export_evidence,
                ),
                _check(
                    "export_revision_persists",
                    "The exported Canvas revision survives close and reopen",
                    exported_revision == revision_after_operations
                    and reopened_exported_revision == exported_revision,
                    {
                        "exported_revision": exported_revision,
                        "reopened_exported_revision": reopened_exported_revision,
                    },
                ),
                _check(
                    "explicit_recovery_close",
                    "Closing dirty work with Keep Recovery records an explicit journal event",
                    "close_with_recovery" in journal_events,
                    {"events": journal_events},
                ),
                _check(
                    "dirty_session_reopens_in_canvas",
                    "The SciPlot shell reopens the exact accepted unsaved state from recovery",
                    recovered_from_snapshot is not None
                    and recovered_value == recovery_value
                    and recovered_render == recovery_render
                    and recovered_state == "editing"
                    and recovery_banner_visible,
                    {
                        "snapshot": recovered_from_snapshot,
                        "expected_value": recovery_value,
                        "recovered_value": recovered_value,
                        "state": recovered_state,
                        "banner_visible": recovery_banner_visible,
                    },
                ),
                _check(
                    "recovery_history_boundary_is_explicit",
                    "Cross-process recovery starts a new in-memory undo history boundary",
                    recovery_undo_available is False,
                    {"can_undo_after_recovery": recovery_undo_available},
                ),
                _check(
                    "window_screenshots_exist",
                    "Normal and recovered native Canvas windows produce visual QA screenshots",
                    screenshot_ready,
                    {
                        "normal": normal_screenshot,
                        "recovered": recovery_screenshot,
                    },
                ),
                _check(
                    "source_document_immutable",
                    "The M1 probe mutates only its copied project or VSZ",
                    source_immutable,
                    {
                        "source_document": str(source_document)
                        if source_document
                        else None,
                        "source_sha256": source_hash,
                    },
                ),
            ]
        )
        if owns_application:
            application.quit()
    except Exception as exc:
        error = {"type": type(exc).__name__, "message": str(exc)}
        checks.append(
            _check(
                "canvas_app_probe_exception",
                "The M1 Canvas application probe completes without an exception",
                False,
                error,
            )
        )
    finally:
        for window in reversed(windows):
            if getattr(window, "_closed", True):
                continue
            try:
                window.set_close_policy_for_test("keep_recovery")
                window.close()
            except Exception:
                pass
        stderr_stack.close()

    status = (
        "passed"
        if checks and all(item["status"] == "passed" for item in checks)
        else "failed"
    )
    payload = {
        "kind": CANVAS_APP_PROBE_KIND,
        "version": CANVAS_APP_PROBE_VERSION,
        "generated_at": _now(),
        "status": status,
        "state": "ready" if status == "passed" else "needs_rule_repair",
        "summary": {
            "check_count": len(checks),
            "passed_count": sum(item["status"] == "passed" for item in checks),
            "failed_ids": [item["id"] for item in checks if item["status"] != "passed"],
        },
        "checks": checks,
        "evidence": evidence,
        "artifacts": {
            "run_root": str(run_root),
            "summary": str(summary_path),
            "screenshot": str(screenshot_path) if screenshot_path.is_file() else None,
            "recovery_screenshot": str(recovery_screenshot_path)
            if recovery_screenshot_path.is_file()
            else None,
            "stderr_log": str(stderr_log) if stderr_log.is_file() else None,
        },
        "error": error,
        "limitations": [
            "This is the M1 live Canvas kernel, not the M2 review overlay or "
            "bounded scientific inspector suite.",
            "Cross-process recovery restores the exact accepted visual state "
            "but intentionally starts a new Veusz in-memory undo boundary.",
        ],
    }
    summary_path.write_text(
        json.dumps(json_safe(payload), indent=2, ensure_ascii=False),
        encoding="utf-8",
    )
    return payload


__all__ = [
    "CANVAS_APP_PROBE_KIND",
    "CANVAS_APP_PROBE_VERSION",
    "run_canvas_app_probe",
]
