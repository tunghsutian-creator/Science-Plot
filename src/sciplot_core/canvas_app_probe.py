from __future__ import annotations

import json
import os
import shutil
import sys
import tempfile
import traceback
from contextlib import ExitStack
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from PIL import Image

from sciplot_core._utils import file_sha256, json_safe
from sciplot_core.canvas.persistence import read_operation_journal

CANVAS_APP_PROBE_KIND = "sciplot_canvas_app_probe"
CANVAS_APP_PROBE_VERSION = 3


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
    expected_mode: str = "light",
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
        paper_crop = rgb.crop(
            (
                round(width * 0.18),
                round(height * 0.12),
                round(width * 0.68),
                round(height * 0.90),
            )
        )
        paper_luma = paper_crop.convert("L")
        paper_mean_luminance = sum(
            paper_luma.histogram()[index] * index for index in range(256)
        ) / (paper_luma.width * paper_luma.height)
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
        "paper_mean_luminance": round(paper_mean_luminance, 3),
        "paper_surface_ready": paper_mean_luminance >= 180.0,
        "inspector_mean_luminance": round(inspector_mean_luminance, 3),
        "inspector_surface_ready": (
            inspector_mean_luminance <= 110.0
            if expected_mode == "dark"
            else inspector_mean_luminance >= 160.0
        ),
        "expected_mode": expected_mode,
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
    dark_screenshot_path = run_root / "canvas_dark.png"
    high_contrast_screenshot_path = run_root / "canvas_high_contrast.png"
    recovery_screenshot_path = run_root / "canvas_recovered.png"
    stderr_log = run_root / "logs" / "canvas_app_stderr.log"
    checks: list[dict[str, Any]] = []
    evidence: dict[str, Any] = {}
    error: dict[str, str] | None = None
    windows: list[Any] = []
    stderr_stack = ExitStack()

    try:
        os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
        from PyQt6 import QtCore, QtGui, QtTest, QtWidgets

        from sciplot_core.studio import _capture_process_stderr
        from sciplot_gui.main_window import SciPlotCanvasWindow
        from sciplot_gui.theme import build_canvas_theme
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

        baseline_theme = (
            window.theme_tokens.to_dict() if window.theme_tokens is not None else {}
        )
        original_palette = QtGui.QPalette(application.palette())
        dark_palette = QtGui.QPalette(original_palette)
        dark_palette.setColor(
            QtGui.QPalette.ColorRole.Window, QtGui.QColor("#202327")
        )
        dark_palette.setColor(
            QtGui.QPalette.ColorRole.WindowText, QtGui.QColor("#f4f6f8")
        )
        dark_palette.setColor(
            QtGui.QPalette.ColorRole.Base, QtGui.QColor("#151719")
        )
        dark_palette.setColor(
            QtGui.QPalette.ColorRole.Text, QtGui.QColor("#f4f6f8")
        )
        dark_palette.setColor(
            QtGui.QPalette.ColorRole.Highlight, QtGui.QColor("#74b9ff")
        )
        dark_palette.setColor(
            QtGui.QPalette.ColorRole.HighlightedText, QtGui.QColor("#101214")
        )
        dark_theme = build_canvas_theme(dark_palette)
        high_contrast_theme = build_canvas_theme(
            application.palette(), high_contrast=True
        )
        theme_contract = {
            "baseline": baseline_theme,
            "dark": dark_theme.to_dict(),
            "high_contrast": high_contrast_theme.to_dict(),
        }

        accessibility_actions = (
            window.save_action,
            window.undo_action,
            window.redo_action,
            window.previous_page_action,
            window.next_page_action,
            window.zoom_out_action,
            window.zoom_in_action,
            window.zoom_page_action,
            window.zoom_100_action,
            window.export_action,
        )
        toolbar_accessibility = {
            action.objectName(): (
                window.toolbar.widgetForAction(action).accessibleName()
                if window.toolbar.widgetForAction(action) is not None
                else ""
            )
            for action in accessibility_actions
        }
        control_accessibility = {
            "more": window.more_button.accessibleName(),
            "object_navigator": window.inspector_panel.object_combo.accessibleName(),
            "point_picker": window.inspector_panel.point_pick_button.accessibleName(),
            "apply": window.inspector_panel.apply_button.accessibleName(),
            "revert": window.inspector_panel.revert_button.accessibleName(),
            "inspector": window.inspector_dock.accessibleName(),
        }
        menu_actions = {
            action
            for menu in (
                window.file_menu,
                window.edit_menu,
                window.view_menu,
                window.document_menu,
                window.more_menu,
            )
            for action in menu.actions()
        }
        primary_actions = (
            *accessibility_actions,
            window.inspector_action,
            window.point_pick_action,
            window.canvas_only_action,
            window.high_contrast_action,
            window.advanced_action,
            window.close_action,
        )
        action_routes = {
            action.objectName(): {
                "shortcut": action.shortcut().toString(),
                "menu_route": action in menu_actions,
            }
            for action in primary_actions
        }

        window.resize(900, 700)
        window._apply_adaptive_layout()
        QtTest.QTest.qWait(30)
        application.processEvents()
        adaptive_narrow = {
            "window_width": window.width(),
            "inspector_visible": window.inspector_dock.isVisible(),
            "inspector_floating": window.inspector_dock.isFloating(),
            "canvas_width": window.plot_window.width(),
            "status_detail_hidden": not window.selection_status.isVisible()
            and not window.coordinate_status.isVisible(),
        }
        window.resize(1380, 860)
        window._apply_adaptive_layout()
        QtTest.QTest.qWait(30)
        application.processEvents()
        adaptive_wide = {
            "window_width": window.width(),
            "inspector_visible": window.inspector_dock.isVisible(),
            "inspector_floating": window.inspector_dock.isFloating(),
            "status_detail_visible": window.selection_status.isVisible()
            and window.coordinate_status.isVisible(),
        }

        focus_control = window.inspector_panel.object_combo
        focus_control.setFocus(QtCore.Qt.FocusReason.TabFocusReason)
        application.processEvents()
        focus_before_tab = application.focusWidget()
        navigation_event = QtGui.QKeyEvent(
            QtCore.QEvent.Type.KeyPress,
            QtCore.Qt.Key.Key_Tab,
            QtCore.Qt.KeyboardModifier.NoModifier,
        )
        tab_navigation_handled = window.eventFilter(
            focus_control,
            navigation_event,
        )
        application.processEvents()
        focus_after_tab = application.focusWidget()
        tab_focus_navigation = (
            tab_navigation_handled is True
            and window._canvas_only is False
            and (
                focus_before_tab is None
                or focus_after_tab is not focus_before_tab
            )
        )
        window.plot_window.setFocus(QtCore.Qt.FocusReason.ShortcutFocusReason)
        application.processEvents()
        QtTest.QTest.keyClick(window.plot_window, QtCore.Qt.Key.Key_Tab)
        application.processEvents()
        canvas_only_enabled = {
            "active": window._canvas_only,
            "toolbar_hidden": not window.toolbar.isVisible(),
            "menu_hidden": not window.menuBar().isVisible(),
            "status_hidden": not window.statusBar().isVisible(),
            "inspector_hidden": not window.inspector_dock.isVisible(),
            "canvas_visible": window.plot_window.isVisible(),
        }
        QtTest.QTest.keyClick(window, QtCore.Qt.Key.Key_Tab)
        application.processEvents()
        canvas_only_restored = {
            "active": window._canvas_only,
            "toolbar_visible": window.toolbar.isVisible(),
            "menu_visible": window.menuBar().isVisible(),
            "status_visible": window.statusBar().isVisible(),
            "inspector_visible": window.inspector_dock.isVisible(),
        }

        window.controller.set_zoom_factor(1.0)
        theme_render_reference = window.controller.adapter.force_redraw()
        window.high_contrast_action.trigger()
        application.processEvents()
        high_contrast_enabled = (
            window.controller.session.interface.high_contrast is True
            and window.theme_tokens is not None
            and window.theme_tokens.high_contrast is True
        )
        high_contrast_screenshot = _capture_window(
            window,
            high_contrast_screenshot_path,
            application=application,
        )
        window.controller.set_zoom_factor(1.0)
        high_contrast_render = window.controller.adapter.force_redraw()
        window.high_contrast_action.trigger()
        application.processEvents()
        high_contrast_restored = (
            window.controller.session.interface.high_contrast is False
            and window.theme_tokens is not None
            and window.theme_tokens.high_contrast is False
        )
        application.setPalette(dark_palette)
        application.processEvents()
        window._apply_theme()
        dark_runtime_enabled = (
            window.theme_tokens is not None and window.theme_tokens.mode == "dark"
        )
        dark_screenshot = _capture_window(
            window,
            dark_screenshot_path,
            application=application,
            expected_mode="dark",
        )
        window.controller.set_zoom_factor(1.0)
        dark_render = window.controller.adapter.force_redraw()
        application.setPalette(original_palette)
        application.processEvents()
        window._apply_theme()
        window.controller.set_zoom_factor(1.0)
        restored_theme_render = window.controller.adapter.force_redraw()
        system_theme_restored = (
            window.theme_tokens is not None
            and window.theme_tokens.mode == baseline_theme.get("mode")
        )
        theme_render_invariant = (
            bool(theme_render_reference)
            and high_contrast_render == theme_render_reference
            and dark_render == theme_render_reference
            and restored_theme_render == theme_render_reference
        )

        target_info = next(
            target
            for target in window.controller.visible_text_targets()
            if target.get("object_type") == "axis"
        )
        selected_target = window.select_text_target(str(target_info["object_id"]))
        inspector_model = window.controller.contextual_inspector()
        inspector_object_count = window.inspector_panel.object_combo.count()
        field_ids = {field.field_id for field in inspector_model.fields}
        selection_visual = {
            "overlay_visible": window.controller.adapter.selection_overlay_visible,
            "direct_manipulation": (
                window.controller.adapter.direct_manipulation_supported
            ),
        }
        xy_object = next(
            item
            for item in inspector_model.related_objects
            if item.object_type == "xy"
        )
        window.controller.select_object_id(xy_object.object_id)
        xy_model = window.controller.contextual_inspector()
        dataset_fields = [
            field.to_dict()
            for field in xy_model.fields
            if field.editor == "dataset"
        ]
        window.select_text_target(str(target_info["object_id"]))
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
        value_a = f"{original_value} [Canvas A]"
        value_b = f"{original_value} [Canvas B]"
        staged_value = f"{original_value} [Staged only]"
        staged_widget = window.inspector_panel.field_widgets["axis_label"]
        staged_widget.setText(staged_value)
        application.processEvents()
        staged_revision = window.controller.session.revision
        staged_apply_enabled = window.inspector_panel.apply_button.isEnabled()
        staged_save_blocked = False
        staged_navigation_blocked = False
        try:
            window.save_document()
        except RuntimeError:
            staged_save_blocked = True
        try:
            window._inspector_object_selected(xy_object.object_id)
        except RuntimeError:
            staged_navigation_blocked = True
        staged_selection_preserved = (
            window.controller.session.selection.primary_object_id
            == target_info["object_id"]
        )
        window.inspector_panel.revert_staged()
        application.processEvents()
        staged_reverted_value = window.controller.adapter.setting_value(
            str(selected_target["setting_path"])
        )

        immediate_widget = window.inspector_panel.field_widgets["axis_label_bold"]
        immediate_before = bool(immediate_widget.isChecked())
        immediate_revision_before = window.controller.session.revision
        immediate_render_before = window.controller.adapter.render_fingerprint()
        immediate_widget.setChecked(not immediate_before)
        application.processEvents()
        immediate_revision_after = window.controller.session.revision
        immediate_render_after = window.controller.adapter.render_fingerprint()
        immediate_value_after = bool(
            window.controller.adapter.setting_value(
                next(
                    field.setting_path
                    for field in window.controller.contextual_inspector().fields
                    if field.field_id == "axis_label_bold"
                )
            )
        )

        render_hashes = [window.controller.adapter.render_fingerprint()]
        applied_values: list[str] = []
        for index in range(operation_count):
            value = value_a if index % 2 == 0 else value_b
            if index == 0:
                label_widget = window.inspector_panel.field_widgets["axis_label"]
                label_widget.setText(value)
                window.inspector_panel._apply_clicked()
            else:
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
        pre_export_structural = window.controller.run_structural_qa()
        window.inspector_panel.set_structural_qa(pre_export_structural)
        pickinfo = window.controller.adapter.first_data_point_pick()
        window._set_point_pick_active(True)
        window._on_point_picked(pickinfo)
        application.processEvents()
        selected_point = (
            window.controller.session.selection.data_point.to_dict()
            if window.controller.session.selection.data_point is not None
            else None
        )
        point_marker_visible = window.plot_window.pickeritem.isVisible()
        window.save_document()
        application.processEvents()
        export_payload = window.export_current()
        post_export_structural = dict(
            window.controller.session.structural_qa_summary
        )
        normal_screenshot = _capture_window(
            window,
            screenshot_path,
            application=application,
        )
        window.high_contrast_action.trigger()
        application.processEvents()
        high_contrast_persisted_before_close = (
            window.controller.session.interface.high_contrast is True
            and window.theme_tokens is not None
            and window.theme_tokens.high_contrast is True
        )
        window_class = type(window).__name__
        exported_revision = window.controller.session.exported_revision
        interface_before_close = window.controller.session.interface.to_dict()
        saved_hash = file_sha256(workspace.document_path)
        window.close()
        application.processEvents()

        reopened = SciPlotCanvasWindow(workspace, interactive=False)
        windows.append(reopened)
        reopened.show()
        application.processEvents()
        reopened_point = (
            reopened.controller.session.selection.data_point.to_dict()
            if reopened.controller.session.selection.data_point is not None
            else None
        )
        reopened_point_marker_visible = reopened.plot_window.pickeritem.isVisible()
        reopened_target = reopened.select_text_target(str(target_info["object_id"]))
        reopened_value = reopened.controller.adapter.setting_value(
            str(reopened_target["setting_path"])
        )
        reopened_render = reopened.controller.adapter.render_fingerprint()
        reopened_revision = reopened.controller.session.revision
        reopened_exported_revision = reopened.controller.session.exported_revision
        reopened_state = reopened.controller.session.state
        reopened_interface = reopened.controller.session.interface.to_dict()
        reopened_theme_high_contrast = (
            reopened.theme_tokens is not None
            and reopened.theme_tokens.high_contrast is True
        )

        recovery_value = f"{original_value} [Canvas Recovery]"
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
            and dark_screenshot_path.is_file()
            and dark_screenshot_path.stat().st_size > 0
            and high_contrast_screenshot_path.is_file()
            and high_contrast_screenshot_path.stat().st_size > 0
            and recovery_screenshot_path.is_file()
            and recovery_screenshot_path.stat().st_size > 0
            and normal_screenshot["width"] >= 900
            and normal_screenshot["height"] >= 600
            and normal_screenshot["has_tonal_range"] is True
            and dark_screenshot["has_tonal_range"] is True
            and high_contrast_screenshot["has_tonal_range"] is True
            and recovery_screenshot["has_tonal_range"] is True
            and normal_screenshot["canvas_surface_ready"] is True
            and dark_screenshot["canvas_surface_ready"] is True
            and high_contrast_screenshot["canvas_surface_ready"] is True
            and recovery_screenshot["canvas_surface_ready"] is True
            and normal_screenshot["paper_surface_ready"] is True
            and dark_screenshot["paper_surface_ready"] is True
            and high_contrast_screenshot["paper_surface_ready"] is True
            and recovery_screenshot["paper_surface_ready"] is True
            and normal_screenshot["inspector_surface_ready"] is True
            and dark_screenshot["inspector_surface_ready"] is True
            and high_contrast_screenshot["inspector_surface_ready"] is True
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
            "theme_contract": theme_contract,
            "toolbar_accessibility": toolbar_accessibility,
            "control_accessibility": control_accessibility,
            "action_routes": action_routes,
            "adaptive_layout": {
                "narrow": adaptive_narrow,
                "wide": adaptive_wide,
            },
            "canvas_only": {
                "enabled": canvas_only_enabled,
                "restored": canvas_only_restored,
                "tab_focus_navigation": tab_focus_navigation,
            },
            "high_contrast_enabled": high_contrast_enabled,
            "high_contrast_restored": high_contrast_restored,
            "high_contrast_persisted_before_close": (
                high_contrast_persisted_before_close
            ),
            "reopened_theme_high_contrast": reopened_theme_high_contrast,
            "dark_runtime_enabled": dark_runtime_enabled,
            "system_theme_restored": system_theme_restored,
            "contextual_inspector": {
                "target": inspector_model.target.to_dict(),
                "field_ids": sorted(field_ids),
                "object_count": inspector_object_count,
                "dataset_fields": dataset_fields,
                "selection_visual": selection_visual,
                "staged_revision": staged_revision,
                "staged_apply_enabled": staged_apply_enabled,
                "staged_save_blocked": staged_save_blocked,
                "staged_navigation_blocked": staged_navigation_blocked,
                "staged_selection_preserved": staged_selection_preserved,
                "staged_reverted_value": staged_reverted_value,
                "immediate_before": immediate_before,
                "immediate_value_after": immediate_value_after,
                "immediate_revision_before": immediate_revision_before,
                "immediate_revision_after": immediate_revision_after,
                "immediate_render_before": immediate_render_before,
                "immediate_render_after": immediate_render_after,
            },
            "text_target": target_info,
            "data_point_selection": {
                "selected": selected_point,
                "marker_visible": point_marker_visible,
                "reopened": reopened_point,
                "reopened_marker_visible": reopened_point_marker_visible,
            },
            "structural_qa": {
                "before_export": pre_export_structural,
                "after_export": post_export_structural,
            },
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
            "immediate_operation_count": 1,
            "revision_after_operations": revision_after_operations,
            "reopened_revision": reopened_revision,
            "reopened_state": reopened_state,
            "interface_before_close": interface_before_close,
            "reopened_interface": reopened_interface,
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
            "dark_screenshot": dark_screenshot,
            "high_contrast_screenshot": high_contrast_screenshot,
            "recovery_screenshot": recovery_screenshot,
            "theme_render": {
                "reference": theme_render_reference,
                "high_contrast": high_contrast_render,
                "dark": dark_render,
                "restored": restored_theme_render,
                "invariant": theme_render_invariant,
            },
        }
        checks.extend(
            [
                _check(
                    "native_sciplot_window",
                    "The SciPlot shell is native-owned and never imports Veusz MainWindow",
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
                    "palette_backed_theme",
                    "System, dark, and increased-contrast themes meet the M2 token contract",
                    baseline_theme.get("mode") in {"light", "dark"}
                    and float(baseline_theme.get("text_contrast") or 0.0) >= 4.5
                    and float(baseline_theme.get("accent_contrast") or 0.0) >= 4.5
                    and dark_theme.mode == "dark"
                    and dark_theme.text_contrast >= 4.5
                    and dark_theme.accent_contrast >= 4.5
                    and high_contrast_theme.high_contrast is True
                    and high_contrast_theme.text_contrast >= 7.0
                    and high_contrast_theme.accent_contrast >= 7.0
                    and high_contrast_enabled
                    and high_contrast_restored
                    and dark_runtime_enabled
                    and system_theme_restored,
                    {
                        **theme_contract,
                        "dark_runtime_enabled": dark_runtime_enabled,
                        "system_theme_restored": system_theme_restored,
                    },
                ),
                _check(
                    "theme_preserves_figure_render",
                    "Application theme changes never alter the exact-current figure pixmap",
                    theme_render_invariant,
                    {
                        "reference": theme_render_reference,
                        "high_contrast": high_contrast_render,
                        "dark": dark_render,
                        "restored": restored_theme_render,
                    },
                ),
                _check(
                    "adaptive_canvas_layout",
                    "The inspector floats at narrow width and redocks without squeezing the Canvas",
                    adaptive_narrow["inspector_visible"] is True
                    and adaptive_narrow["inspector_floating"] is True
                    and int(adaptive_narrow["canvas_width"]) >= 700
                    and adaptive_narrow["status_detail_hidden"] is True
                    and adaptive_wide["inspector_visible"] is True
                    and adaptive_wide["inspector_floating"] is False
                    and adaptive_wide["status_detail_visible"] is True,
                    {
                        "narrow": adaptive_narrow,
                        "wide": adaptive_wide,
                    },
                ),
                _check(
                    "canvas_only_mode",
                    "Tab enters and exits a trustworthy Canvas-only view",
                    all(
                        canvas_only_enabled.get(key) is True
                        for key in (
                            "active",
                            "toolbar_hidden",
                            "menu_hidden",
                            "status_hidden",
                            "inspector_hidden",
                            "canvas_visible",
                        )
                    )
                    and tab_focus_navigation
                    and canvas_only_restored.get("active") is False
                    and all(
                        canvas_only_restored.get(key) is True
                        for key in (
                            "toolbar_visible",
                            "menu_visible",
                            "status_visible",
                            "inspector_visible",
                        )
                    ),
                    {
                        "enabled": canvas_only_enabled,
                        "restored": canvas_only_restored,
                        "tab_focus_navigation": tab_focus_navigation,
                    },
                ),
                _check(
                    "accessible_control_names",
                    "Toolbar symbols and primary inspector controls expose accessible names",
                    all(toolbar_accessibility.values())
                    and all(control_accessibility.values()),
                    {
                        "toolbar": toolbar_accessibility,
                        "controls": control_accessibility,
                    },
                ),
                _check(
                    "menu_shortcut_parity",
                    "Every primary Canvas command has a shortcut or menu route",
                    all(
                        bool(item["shortcut"]) or item["menu_route"] is True
                        for item in action_routes.values()
                    ),
                    action_routes,
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
                    "bounded_contextual_inspector",
                    "Selection opens a finite scientific editor instead of a raw Veusz property tree",
                    selected_target.get("object_id") == target_info.get("object_id")
                    and inspector_object_count > 0
                    and {"axis_label", "axis_min", "axis_max", "axis_label_bold"}
                    <= field_ids
                    and dataset_fields
                    and all(field.get("read_only") is True for field in dataset_fields)
                    and selection_visual["overlay_visible"] is True
                    and inspector_initially_visible
                    and inspector_hides
                    and inspector_restores
                    and advanced_editor_in_more,
                    {
                        "selection": selected_target,
                        "target": inspector_model.target.to_dict(),
                        "field_ids": sorted(field_ids),
                        "object_count": inspector_object_count,
                        "dataset_fields": dataset_fields,
                        "selection_visual": selection_visual,
                        "inspector_toggle": {
                            "initially_visible": inspector_initially_visible,
                            "hides": inspector_hides,
                            "restores": inspector_restores,
                        },
                        "advanced_editor_in_more": advanced_editor_in_more,
                    },
                ),
                _check(
                    "inspector_staging_and_revert",
                    "Staged fields do not mutate the document until Apply and can be reverted",
                    staged_revision == 0
                    and staged_apply_enabled is True
                    and staged_save_blocked is True
                    and staged_navigation_blocked is True
                    and staged_selection_preserved is True
                    and staged_reverted_value == original_value,
                    {
                        "revision": staged_revision,
                        "apply_enabled": staged_apply_enabled,
                        "save_blocked": staged_save_blocked,
                        "navigation_blocked": staged_navigation_blocked,
                        "selection_preserved": staged_selection_preserved,
                        "reverted_value": staged_reverted_value,
                    },
                ),
                _check(
                    "immediate_inspector_operation",
                    "A safe immediate field uses the typed gateway and redraws live",
                    immediate_revision_after == immediate_revision_before + 1
                    and immediate_value_after == (not immediate_before)
                    and immediate_render_after != immediate_render_before,
                    {
                        "revision_before": immediate_revision_before,
                        "revision_after": immediate_revision_after,
                        "value_before": immediate_before,
                        "value_after": immediate_value_after,
                        "render_before": immediate_render_before,
                        "render_after": immediate_render_after,
                    },
                ),
                _check(
                    "sequential_typed_operations",
                    f"{operation_count} sequential user-path operations complete",
                    revision_after_operations == operation_count + 1
                    and len(applied_values) == operation_count,
                    {
                        "revision": revision_after_operations,
                        "operation_count": operation_count,
                        "immediate_operation_count": 1,
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
                    "data_point_selection_persists",
                    "A picked data point is persisted and restored on the exact-current Canvas",
                    selected_point is not None
                    and selected_point == reopened_point
                    and point_marker_visible is True
                    and reopened_point_marker_visible is True,
                    {
                        "selected": selected_point,
                        "reopened": reopened_point,
                        "marker_visible": point_marker_visible,
                        "reopened_marker_visible": reopened_point_marker_visible,
                    },
                ),
                _check(
                    "debounced_structural_qa_boundary",
                    "Structural QA passes before export while honestly marking artifact QA stale",
                    pre_export_structural.get("status") == "warning"
                    and pre_export_structural.get("ready_for_artifact_qa") is True
                    and (
                        pre_export_structural.get("summary", {}).get("warning_ids")
                        == ["artifact_qa_current"]
                    )
                    and post_export_structural.get("status") == "passed",
                    {
                        "before_export": pre_export_structural,
                        "after_export": post_export_structural,
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
                    "interface_state_reopens",
                    "Inspector geometry and contrast preferences survive close and reopen",
                    reopened_interface.get("inspector_visible")
                    == interface_before_close.get("inspector_visible")
                    and abs(
                        int(reopened_interface.get("inspector_width") or 0)
                        - int(interface_before_close.get("inspector_width") or 0)
                    )
                    <= 3
                    and reopened_interface.get("high_contrast")
                    == interface_before_close.get("high_contrast")
                    and reopened_interface.get("inspector_visible") is True
                    and reopened_interface.get("high_contrast") is True
                    and high_contrast_persisted_before_close
                    and reopened_theme_high_contrast,
                    {
                        "before_close": interface_before_close,
                        "reopened": reopened_interface,
                        "theme_high_contrast": reopened_theme_high_contrast,
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
                        "dark": dark_screenshot,
                        "high_contrast": high_contrast_screenshot,
                        "recovered": recovery_screenshot,
                    },
                ),
                _check(
                    "source_document_immutable",
                    "The native Canvas probe mutates only its copied project or VSZ",
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
        error = {
            "type": type(exc).__name__,
            "message": str(exc),
            "traceback": traceback.format_exc(),
        }
        checks.append(
            _check(
                "canvas_app_probe_exception",
                "The native Canvas application probe completes without an exception",
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
            "dark_screenshot": (
                str(dark_screenshot_path) if dark_screenshot_path.is_file() else None
            ),
            "high_contrast_screenshot": (
                str(high_contrast_screenshot_path)
                if high_contrast_screenshot_path.is_file()
                else None
            ),
            "recovery_screenshot": str(recovery_screenshot_path)
            if recovery_screenshot_path.is_file()
            else None,
            "stderr_log": str(stderr_log) if stderr_log.is_file() else None,
        },
        "error": error,
        "limitations": [
            "This probe covers the M2 contextual editing core; native annotation "
            "dragging is exercised by a dedicated label-bearing project probe.",
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
