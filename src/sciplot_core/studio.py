from __future__ import annotations

import json
import math
import os
import re
import shlex
import shutil
import subprocess
import sys
import tempfile
from contextlib import contextmanager
from copy import deepcopy
from dataclasses import dataclass, replace
from datetime import UTC, datetime
from html import escape
from io import StringIO
from pathlib import Path
from typing import Any

import pandas as pd

from sciplot_core._paths import VEUSZ_ROOT, VEUSZ_UPSTREAM_COMMIT
from sciplot_core._utils import decode_text, existing_file_sha256, json_safe
from sciplot_core.data_mapping import resolve_data_mapping_request
from sciplot_core.delivery import build_delivery_package
from sciplot_core.launchers import portable_sciplot_prelude, portable_vsz_finder
from sciplot_core.materials_rules import compute_analysis_metrics, get_rule, semantic_payload_from_rule
from sciplot_core.operation_modes import normal_mode_payload
from sciplot_core.policy import (
    AUTO_LOG_BOUND_PADDING_FACTOR,
    CATEGORICAL_BOX_FILL_FRACTION,
    CATEGORICAL_BOX_FILL_TRANSPARENCY,
    CATEGORICAL_BOX_LINE_WIDTH_PT,
    CATEGORICAL_DISTRIBUTION_RENDER_OPTIONS,
    DEFAULT_CATEGORICAL_SUMMARY,
    DEFAULT_LEGEND_CURVE_CLEARANCE_MM,
    DEFAULT_LEGEND_EDGE_PADDING_MM,
    DEFAULT_LINE_STYLE_SEQUENCE,
    DEFAULT_LOG_MINOR_MULTIPLIERS,
    DEFAULT_LOG_MINOR_TICK_COUNT,
    DEFAULT_LOG_TICK_FORMAT,
    DEFAULT_PALETTE_COLORS,
    DEFAULT_PALETTE_PRESET,
    DEFAULT_RAW_POINT_JITTER_FRACTION,
    DEFAULT_SCALAR_FIELD_COLORMAP_ID,
    DEFAULT_SCALAR_FIELD_COLORS,
    FIXED_PUBLICATION_FRAME_POLICY,
    MAX_AUTO_LOG_EMPTY_RANGE_FACTOR,
    MAX_LEGEND_RESERVE_ITERATIONS,
    MAX_LINEAR_LEGEND_RESERVE_FRACTION,
    MAX_LOG_LEGEND_RESERVE_DECADES,
    MAX_POINT_LINE_MARKERS_PER_SERIES,
    MIN_BOX_REPLICATES,
    POINT_LINE_RENDER_OPTIONS,
    RHEOLOGY_FREQUENCY_X_RENDER_LABEL,
    UNIFIED_AXIS_LINEWIDTH_PT,
    UNIFIED_FONT_FAMILY,
    UNIFIED_FONT_SIZE_PT,
    UNIFIED_LEGEND_FONT_SIZE_PT,
    UNIFIED_LINE_WIDTH_PT,
    UNIFIED_MARKER_LINE_WIDTH_PT,
    UNIFIED_MARKER_SIZE_PT,
    UNIFIED_MINOR_TICK_LENGTH_PT,
    UNIFIED_MINOR_TICK_WIDTH_PT,
    UNIFIED_TICK_LENGTH_PT,
    UNIFIED_TICK_WIDTH_PT,
    anchored_log_decade_ticks,
    compact_linear_axis,
    is_removed_outside_legend_position,
    normalize_categorical_summary,
    normalize_legend_position,
    normalize_raw_point_jitter_fraction,
    rheology_metric_axis_label,
)
from sciplot_core.publication import (
    build_publication_intent,
    build_transform_ledger,
    build_transform_step,
    get_publication_profile,
    link_intent_to_transform_ledger,
    write_publication_artifacts,
)
from sciplot_core.qa import run_qa
from sciplot_core.study_model import (
    attach_run_artifacts_to_study_model,
    build_output_package_contract,
    normalize_study_model,
)

DEFAULT_PALETTE = DEFAULT_PALETTE_COLORS
STACKED_TEMPLATE_IDS = {"stacked_curve", "segmented_stacked_curve"}
CATEGORICAL_TEMPLATE_IDS = {"box", "box_strip"}
SCALAR_FIELD_TEMPLATE_IDS = {"heatmap", "contour_field", "annotated_heatmap"}
POINT_LINE_MARKERS = ("circle", "square", "diamond", "triangle")
MARKER_MAP = {
    "circle": "circle",
    "diamond": "diamond",
    "square": "square",
    "triangle": "triangle",
    "triangle_up": "triangle",
    "triangle_down": "triangledown",
    "plus": "plus",
    "cross": "cross",
    "none": "none",
    False: "none",
    True: "circle",
}


class StudioPreparationBlocked(ValueError):
    state = "needs_rule_repair"

    def __init__(self, reason_code: str, message: str) -> None:
        self.reason_code = reason_code
        super().__init__(message)


@dataclass(frozen=True)
class StudioSeries:
    label: str
    x_name: str
    y_name: str
    x_values: tuple[float, ...]
    y_values: tuple[float, ...]
    color: str
    line_width: float | None = None
    marker: str | bool | None = None
    marker_size: float | None = None
    line_style: str = "solid"
    presentation_kind: str = "curve"
    category_position: float | None = None


@dataclass(frozen=True)
class _VeuszStyleContract:
    font_family: str = UNIFIED_FONT_FAMILY
    font_size_pt: float = UNIFIED_FONT_SIZE_PT
    legend_font_size_pt: float = UNIFIED_LEGEND_FONT_SIZE_PT
    axis_linewidth_pt: float = UNIFIED_AXIS_LINEWIDTH_PT
    tick_width_pt: float = UNIFIED_TICK_WIDTH_PT
    tick_length_pt: float = UNIFIED_TICK_LENGTH_PT
    minor_tick_width_pt: float = UNIFIED_MINOR_TICK_WIDTH_PT
    minor_tick_length_pt: float = UNIFIED_MINOR_TICK_LENGTH_PT
    line_width_pt: float = UNIFIED_LINE_WIDTH_PT
    line_alpha: float = 0.92
    marker_alpha: float = 0.95
    marker_size_pt: float = UNIFIED_MARKER_SIZE_PT
    marker_line_width_pt: float = UNIFIED_MARKER_LINE_WIDTH_PT
    axes_labelpad_pt: float = 2.0
    xtick_major_pad_pt: float = 1.4
    ytick_major_pad_pt: float = 1.4
    legend_inset_fraction: float = 0.025
    legend_frameon: bool = False
    left_margin_mm: float = 14.0
    right_margin_mm: float = 4.5
    bottom_margin_mm: float = 11.0
    top_margin_mm: float = 5.5


@dataclass(frozen=True)
class _VeuszAxisContract:
    x_min: float | None = None
    x_max: float | None = None
    y_min: float | None = None
    y_max: float | None = None
    x_ticks: tuple[float, ...] = ()
    y_ticks: tuple[float, ...] = ()


def upstream_status() -> dict[str, Any]:
    return {
        "veusz": {
            "name": "Veusz",
            "path": str(VEUSZ_ROOT),
            "commit": VEUSZ_UPSTREAM_COMMIT,
            "license": "GPL-2.0-or-later",
            "vendored": VEUSZ_ROOT.exists(),
        },
    }


def maybe_reexec_with_qt_runtime(original_argv: list[str]) -> None:
    """Restart on macOS with the Qt framework path set before PyQt imports.

    The vendored Veusz helpers are compiled against Homebrew Qt. macOS must see
    those framework paths when the Python process starts, otherwise PyQt may
    load its bundled QtCore while the helper extensions load Homebrew QtGui.
    """
    if sys.platform != "darwin" or os.environ.get("SCIPLOT_STUDIO_QT_RUNTIME") == "1":
        return
    env = os.environ.copy()
    framework_paths = _qt_framework_paths()
    if not framework_paths:
        return
    joined = ":".join(str(path) for path in framework_paths)
    for key in ("DYLD_FRAMEWORK_PATH", "DYLD_LIBRARY_PATH"):
        current = env.get(key)
        env[key] = f"{joined}:{current}" if current else joined
    env["SCIPLOT_STUDIO_QT_RUNTIME"] = "1"
    os.execvpe(sys.executable, [sys.executable, "-m", "sciplot_core.cli", *original_argv], env)


def prepare_studio_document(
    target: str | Path,
    *,
    output_root: Path | None = None,
    rule_id: str | None = None,
    template: str | None = None,
    project_name: str | None = None,
    regenerate_generated: bool = False,
) -> dict[str, Any]:
    resolved = Path(target).expanduser().resolve()
    target_info = _resolve_studio_target(
        resolved,
        output_root=output_root,
        rule_id=rule_id,
        template=template,
        project_name=project_name,
    )
    if target_info["mode"] == "vsz":
        if _normalize_optional_string(rule_id):
            raise ValueError("--rule applies to raw data, a SciPlot project, or plot_request.json; not an existing VSZ.")
        return _existing_document_payload(target_info["document"])

    request_path = target_info["request"]
    project_dir = target_info["project_dir"]
    existing_document = _project_studio_document(project_dir)
    if (
        target_info.get("mode") == "project"
        and existing_document is not None
        and rule_id is None
        and template is None
        and project_name is None
        and not regenerate_generated
    ):
        launcher = _write_studio_launcher(project_dir)
        veusz_launcher = _write_veusz_launcher(project_dir, existing_document)
        export_edited_launcher = _write_export_edited_launcher(project_dir)
        generated_hash = _registered_generated_hash(project_dir)
        studio_block = _studio_block(
            document_path=existing_document,
            spec_path=_veusz_spec_path(existing_document),
            launcher=launcher,
            veusz_launcher=veusz_launcher,
            export_edited_launcher=export_edited_launcher,
            request_path=request_path,
            series_count=_count_veusz_series(existing_document),
            generated_hash=generated_hash,
        )
        _register_studio_block(project_dir, studio_block)
        return {
            "kind": "sciplot_studio_prepare",
            "operation_mode": normal_mode_payload(route="studio"),
            "project_dir": str(project_dir),
            "request": str(request_path),
            "document": str(existing_document),
            "launcher": str(launcher),
            "veusz_launcher": str(veusz_launcher),
            "export_edited_launcher": str(export_edited_launcher),
            "series_count": studio_block["series_count"],
            "document_state": studio_block["document_state"],
            "studio": studio_block,
            "preserved_existing_document": True,
        }
    _apply_studio_request_overrides(
        project_dir,
        request_path=request_path,
        rule_id=rule_id,
        template=template,
        project_name=project_name,
    )
    request = _read_json(request_path)
    effective_request, data_mapping_application = resolve_data_mapping_request(
        request,
        base_dir=request_path.parent,
    )
    if data_mapping_application is not None:
        request["transform_ledger"] = deepcopy(
            effective_request["transform_ledger"]
        )
    document_path = project_dir / "studio" / "document.vsz"
    document_path.parent.mkdir(parents=True, exist_ok=True)
    _archive_manual_document_if_needed(project_dir, document_path)
    series, axis_info, transform_steps, source_root = _series_from_request(
        request,
        base_dir=request_path.parent,
    )
    if isinstance(axis_info.get("data_mapping_coverage"), dict):
        request["data_mapping_coverage"] = json_safe(
            axis_info["data_mapping_coverage"]
        )
    study_model = normalize_study_model(
        request.get("study_model")
        if isinstance(request.get("study_model"), dict)
        else {"kind": "sciplot_study_model", "version": 1, "samples": [], "figure_queue": []}
    )
    transform_ledger = build_transform_ledger(
        study_model,
        request=request,
        input_path=source_root,
        steps=transform_steps,
        existing=request.get("transform_ledger") if isinstance(request.get("transform_ledger"), dict) else None,
    )
    publication_intent = build_publication_intent(
        study_model,
        request=request,
        existing=request.get("publication_intent") if isinstance(request.get("publication_intent"), dict) else None,
    )
    publication_intent = link_intent_to_transform_ledger(publication_intent, transform_ledger)
    study_model["publication_intent_ref"] = "publication_intent.json"
    request["study_model"] = study_model
    request["publication_intent"] = publication_intent
    request["transform_ledger"] = transform_ledger
    request_path.write_text(
        json.dumps(json_safe(request), indent=2, ensure_ascii=False),
        encoding="utf-8",
    )
    spec_path = _write_veusz_document(document_path, request=request, series=series, axis_info=axis_info)
    launcher = _write_studio_launcher(project_dir)
    veusz_launcher = _write_veusz_launcher(project_dir, document_path)
    export_edited_launcher = _write_export_edited_launcher(project_dir)
    generated_hash = existing_file_sha256(document_path)
    studio_block = _studio_block(
        document_path=document_path,
        spec_path=spec_path,
        launcher=launcher,
        veusz_launcher=veusz_launcher,
        export_edited_launcher=export_edited_launcher,
        request_path=request_path,
        series_count=len(series),
        generated_hash=generated_hash,
    )
    _register_studio_block(project_dir, studio_block)
    return {
        "kind": "sciplot_studio_prepare",
        "operation_mode": normal_mode_payload(route="studio"),
        "project_dir": str(project_dir),
        "request": str(request_path),
        "document": str(document_path),
        "launcher": str(launcher),
        "veusz_launcher": str(veusz_launcher),
        "export_edited_launcher": str(export_edited_launcher),
        "series_count": len(series),
        "document_state": studio_block["document_state"],
        "studio": studio_block,
    }


def run_studio_command(
    *,
    target: Path | None = None,
    output_root: Path | None = None,
    rule_id: str | None = None,
    template: str | None = None,
    project_name: str | None = None,
    new: bool = False,
    advanced_editor: bool = False,
    export: str | None = None,
    json_output: bool = False,
    prepare_only: bool = False,
    qt_smoke: bool = False,
    original_argv: list[str] | None = None,
) -> int:
    if qt_smoke:
        # GUI smoke runs inside CI/Codex processes which may not own an Aqua
        # application session.  Exercise the real MainWindow offscreen so the
        # check cannot crash in macOS application registration.
        _prefer_offscreen_export_platform()
        maybe_reexec_with_qt_runtime(original_argv or ["studio", "--qt-smoke"])
        payload = qt_smoke_payload(target.expanduser() if target is not None else None)
        print(json.dumps(json_safe(payload), indent=2, ensure_ascii=False))
        return 0

    if new:
        payload = {"kind": "sciplot_studio_session", "mode": "new", "upstreams": upstream_status()}
        if json_output or prepare_only:
            print(json.dumps(json_safe(payload), indent=2, ensure_ascii=False))
            return 0
        maybe_reexec_with_qt_runtime(original_argv or ["studio", "--new"])
        return launch_veusz_gui(None)

    if target is None:
        raise ValueError("studio needs PATH or --new.")

    if advanced_editor:
        maybe_reexec_with_qt_runtime(original_argv or ["studio", str(target), "--advanced-editor"])
        return launch_veusz_gui(target.expanduser())

    if not (json_output or prepare_only or export):
        maybe_reexec_with_qt_runtime(original_argv or ["studio", str(target)])
        return launch_sciplot_studio(
            target,
            output_root=output_root,
            rule_id=rule_id,
            template=template,
            project_name=project_name,
        )

    if json_output or prepare_only or export:
        command = ["studio", str(target)]
        if rule_id:
            command.extend(["--rule", rule_id])
        if template:
            command.extend(["--template", template])
        if project_name:
            command.extend(["--name", project_name])
        if export:
            command.extend(["--export", export])
        if json_output:
            command.append("--json")
        if prepare_only:
            command.append("--prepare-only")
        maybe_reexec_with_qt_runtime(original_argv or command)

    payload = prepare_studio_document(
        target,
        output_root=output_root,
        rule_id=rule_id,
        template=template,
        project_name=project_name,
    )
    document_path = Path(payload["document"])
    if export:
        requested_formats = _split_formats(export)
        standalone_export = payload.get("mode") == "vsz"
        standalone_root = (
            output_root.expanduser().resolve()
            if standalone_export and output_root is not None
            else document_path.parent / "exports"
        )
        export_dir = standalone_root / "figures" if standalone_export and output_root is not None else None
        export_payload = export_studio_document(
            document_path,
            formats=requested_formats,
            output_dir=export_dir,
        )
        payload["exports"] = export_payload["exports"]
        if payload.get("project_dir"):
            studio_run = publish_studio_export_run(
                project_dir=Path(payload["project_dir"]),
                request_path=Path(payload["request"]),
                document_path=document_path,
                exports=payload["exports"],
            )
            payload["studio_run"] = studio_run
            _register_studio_exports(Path(payload["project_dir"]), payload["exports"], studio_run=studio_run)
        elif standalone_export:
            receipt = publish_standalone_export_receipt(
                document_path=document_path,
                requested_formats=requested_formats,
                exports=payload["exports"],
                artifact_root=standalone_root,
            )
            payload["standalone_export"] = receipt
            payload["status"] = receipt["status"]
            payload["state"] = receipt["state"]
            payload["export_ready"] = receipt["export_ready"]

    if json_output or prepare_only or export:
        print(json.dumps(json_safe(payload), indent=2, ensure_ascii=False))
        if export:
            studio_run = payload.get("studio_run")
            standalone_receipt = payload.get("standalone_export")
            if isinstance(studio_run, dict):
                if studio_run.get("ready_to_use") is not True:
                    return 1
            elif not isinstance(standalone_receipt, dict) or standalone_receipt.get("export_ready") is not True:
                return 1
        return 0

    return launch_veusz_gui(document_path)


def qt_smoke_payload(document_path: Path | None = None) -> dict[str, Any]:
    _ensure_veusz_on_path()
    from PyQt6 import QtCore, QtWidgets

    app = QtWidgets.QApplication.instance()
    created_app = app is None
    if app is None:
        app = QtWidgets.QApplication([])
    # Construct the complete editor window.  Opening a VSZ here can trigger an
    # upstream import-security confirmation dialog, which is intentionally left
    # to the separate reopen/export smoke rather than an offscreen GUI check.
    window = _create_veusz_window(None)
    document_probe: dict[str, Any] = {
        "document": None,
        "document_loaded": None,
        "datasets": [],
        "pages": [],
    }
    if document_path is not None:
        resolved_document = document_path.expanduser().resolve()
        if not resolved_document.is_file():
            raise FileNotFoundError(resolved_document)
        from veusz import document as veusz_document

        loaded_document = veusz_document.Document()
        # Load directly rather than through MainWindow's error dialog.  A
        # missing saved-script command must fail the smoke process instead of
        # hanging behind an offscreen modal dialog.
        loaded_document.load(str(resolved_document))
        document_probe = {
            "document": str(resolved_document),
            "document_loaded": True,
            "datasets": sorted(str(name) for name in loaded_document.data),
            "pages": [str(child.name) for child in loaded_document.basewidget.children],
        }
    payload = {
        "kind": "sciplot_studio_qt_smoke",
        "status": "passed",
        "qt_version": QtCore.QT_VERSION_STR,
        "pyqt_version": QtCore.PYQT_VERSION_STR,
        "window": type(window).__name__,
        "main_window_constructed": True,
        **document_probe,
        "upstreams": upstream_status(),
    }
    window.close()
    if created_app:
        app.quit()
    return payload


def launch_veusz_gui(document_path: Path | None) -> int:
    _ensure_veusz_on_path()
    from PyQt6 import QtWidgets

    app = QtWidgets.QApplication.instance() or QtWidgets.QApplication(sys.argv[:1])
    window = _create_veusz_window(document_path)
    window.show()
    return int(app.exec())


def launch_sciplot_studio(
    target: Path,
    *,
    output_root: Path | None,
    rule_id: str | None = None,
    template: str | None = None,
    project_name: str | None = None,
) -> int:
    payload = prepare_studio_document(
        target.expanduser().resolve(),
        output_root=output_root,
        rule_id=rule_id,
        template=template,
        project_name=project_name,
    )
    return launch_veusz_gui(Path(payload["document"]))


def _create_veusz_window(document_path: Path | None) -> Any:
    ensure_veusz_qsettings_compat()
    from veusz.windows.mainwindow import MainWindow

    _ensure_veusz_loader_compat()
    _ensure_veusz_examples_menu_compat(MainWindow)
    window = MainWindow()
    if document_path is not None:
        window.openFileInWindow(str(document_path))
    else:
        window.setupDefaultDoc("graph")
    window.setWindowTitle("SciPlot Studio")
    _attach_sciplot_menu(window, document_path)
    window.resize(1200, 820)
    return window


def ensure_veusz_qsettings_compat() -> None:
    """Keep Veusz settings scoped to Veusz on macOS.

    Native QSettings includes the macOS global preference domain as a fallback.
    Veusz evaluates every returned value as one of its own settings, producing
    dozens of misleading ``Error interpreting item Apple...`` messages.  The
    adapter disables only that fallback and leaves Veusz's own preferences
    readable and writable.
    """
    from veusz import qtall as qt

    current = qt.QSettings
    if getattr(current, "_sciplot_fallbacks_disabled", False):
        return

    class SciPlotQSettings(current):
        _sciplot_fallbacks_disabled = True

        def __init__(self, *args: Any, **kwargs: Any) -> None:
            super().__init__(*args, **kwargs)
            self.setFallbacksEnabled(False)

    qt.QSettings = SciPlotQSettings


def _ensure_veusz_examples_menu_compat(main_window_type: type[Any]) -> None:
    """Treat the intentionally omitted upstream examples directory as optional."""
    from veusz import utils

    current = main_window_type.populateExamplesMenu
    if getattr(current, "_sciplot_missing_examples_safe", False):
        return

    def populate_examples_menu(window: Any) -> Any:
        if not Path(str(utils.exampleDirectory)).is_dir():
            return None
        return current(window)

    populate_examples_menu._sciplot_missing_examples_safe = True  # type: ignore[attr-defined]
    main_window_type.populateExamplesMenu = populate_examples_menu


def _ensure_veusz_loader_compat() -> None:
    """Keep Veusz script loading alive when optional import commands are absent."""
    from importlib import import_module

    # The upstream Veusz application imports this package during its startup
    # thread.  SciPlot constructs MainWindow directly, so repeat the same
    # registration step before loading a saved document.  Without it, native
    # Veusz dumps containing ImportString2D/ImportStringND fail with NameError.
    import_module("veusz.dataimport")

    from veusz import document as veusz_document
    from veusz.document import mime
    from veusz.document.commandinterface import CommandInterface, registerImportCommand

    for command_name in ("ImportString2D", "ImportStringND"):
        if (
            not hasattr(CommandInterface, command_name)
            or command_name not in CommandInterface.import_commands
            or CommandInterface.import_filenamearg.get(command_name) != -1
        ):
            raise RuntimeError(
                f"Veusz saved-data command {command_name} is unavailable in this Studio runtime."
            )

    if hasattr(CommandInterface, "ImportFITSFile"):
        pass
    else:

        def _missing_import_fits(self: Any, *_args: Any, **_kwargs: Any) -> None:
            raise RuntimeError("Veusz FITS import support is unavailable in this SciPlot Studio runtime.")

        CommandInterface.ImportFITSFile = _missing_import_fits

    def _sciplot_import_string(
        self: Any,
        descriptor: str,
        dstring: str,
        useblocks: bool = False,
    ) -> tuple[list[str], dict[str, int]]:
        dataset_name = str(descriptor).split("(", 1)[0].strip()
        if not dataset_name:
            raise ValueError(f"Unsupported Veusz ImportString descriptor: {descriptor!r}")
        values: list[float] = []
        invalid = 0
        for line in str(dstring).splitlines():
            text = line.strip()
            if not text or (useblocks and text.lower() == "no"):
                continue
            try:
                values.append(float(text))
            except ValueError:
                invalid += 1
        self.SetData(dataset_name, values)
        return [dataset_name], ({dataset_name: invalid} if invalid else {})

    if hasattr(CommandInterface, "ImportString"):
        if "ImportString" not in CommandInterface.import_commands:
            CommandInterface.import_commands.append("ImportString")
        CommandInterface.import_filenamearg["ImportString"] = -1
    else:
        registerImportCommand("ImportString", _sciplot_import_string, filenamearg=-1)

    if getattr(mime, "_sciplot_safe_clipboard", False):
        return
    original_get_clipboard_widget_mime = mime.getClipboardWidgetMime

    def _clipboard_mimedata() -> Any:
        clipboard = mime.qt.QApplication.clipboard()
        if clipboard is None:
            return None
        return clipboard.mimeData()

    def _safe_is_clipboard_data_mime() -> bool:
        mimedata = _clipboard_mimedata()
        return bool(mimedata is not None and mime.datamime in mimedata.formats())

    def _safe_get_clipboard_widget_mime() -> Any:
        if _clipboard_mimedata() is None:
            return None
        return original_get_clipboard_widget_mime()

    mime.isClipboardDataMime = _safe_is_clipboard_data_mime
    mime.getClipboardWidgetMime = _safe_get_clipboard_widget_mime
    veusz_document.isClipboardDataMime = _safe_is_clipboard_data_mime
    veusz_document.getClipboardWidgetMime = _safe_get_clipboard_widget_mime
    mime._sciplot_safe_clipboard = True


def _attach_sciplot_menu(window: Any, document_path: Path | None) -> None:
    if document_path is None:
        return
    try:
        from PyQt6 import QtGui, QtWidgets
    except Exception:
        return

    context = _project_context_for_document(document_path)
    menu = window.menuBar().addMenu("SciPlot")
    export_action = QtGui.QAction("Save And Export PDF/TIFF Through SciPlot QA", window)
    export_action.setEnabled(context is not None)

    def export_current_document() -> None:
        if context is None:
            return
        try:
            window.document.save(str(document_path))
            exports = export_studio_document(document_path, formats=["pdf", "tiff_300"])["exports"]
            studio_run = publish_studio_export_run(
                project_dir=context["project_dir"],
                request_path=context["request_path"],
                document_path=document_path,
                exports=exports,
            )
            _register_studio_exports(context["project_dir"], exports, studio_run=studio_run)
            QtWidgets.QMessageBox.information(
                window,
                "SciPlot Studio",
                f"Exported through SciPlot QA:\n{studio_run['output']}",
            )
        except Exception as exc:
            QtWidgets.QMessageBox.critical(window, "SciPlot Studio", str(exc))

    export_action.triggered.connect(export_current_document)
    menu.addAction(export_action)
    if context is None:
        export_action.setToolTip("Open a SciPlot project package to enable SciPlot QA export.")
    window._sciplot_actions = getattr(window, "_sciplot_actions", []) + [export_action]


def _project_context_for_document(document_path: Path) -> dict[str, Path] | None:
    candidate = document_path.expanduser().resolve()
    if candidate.parent.name == "studio":
        project_dir = candidate.parent.parent
        request_path = project_dir / "plot_request.json"
        if request_path.exists():
            return {"project_dir": project_dir, "request_path": request_path}
    return None


def _normalize_optional_string(value: str | None) -> str | None:
    if not isinstance(value, str):
        return None
    stripped = value.strip()
    return stripped or None


def _project_studio_document(project_dir: Path) -> Path | None:
    document = project_dir / "studio" / "document.vsz"
    if document.exists() and document.is_file():
        return document.resolve()
    manifest_paths = [project_dir / "intake_manifest.json", *sorted(project_dir.glob("*.sciplot.json"))]
    for manifest_path in manifest_paths:
        if not manifest_path.exists():
            continue
        try:
            payload = _read_json(manifest_path)
        except Exception:
            continue
        studio = payload.get("studio") if isinstance(payload.get("studio"), dict) else {}
        document_value = studio.get("document")
        if isinstance(document_value, str) and document_value.strip():
            candidate = Path(document_value).expanduser()
            if not candidate.is_absolute():
                candidate = project_dir / candidate
            if candidate.exists() and candidate.is_file():
                return candidate.resolve()
    return None


def _count_veusz_series(document_path: Path) -> int:
    try:
        text = document_path.read_text(encoding="utf-8")
    except OSError:
        return 0
    count = text.count("Add('xy',")
    return max(count - text.count("Add('xy', name='category_axis_label_provider'"), 0)


def export_studio_document(
    document_path: Path,
    *,
    formats: list[str],
    output_dir: Path | None = None,
) -> dict[str, Any]:
    from sciplot_core.veusz_runtime import needs_veusz_worker_process, veusz_worker_environment

    resolved_output_dir = output_dir.expanduser().resolve() if output_dir is not None else None
    if needs_veusz_worker_process():
        command = [
            sys.executable,
            "-m",
            "sciplot_core.veusz_worker",
            "export-document",
            str(document_path),
            "--formats",
            ",".join(formats),
        ]
        if resolved_output_dir is not None:
            command.extend(["--out", str(resolved_output_dir)])
        result = subprocess.run(
            command,
            text=True,
            capture_output=True,
            check=True,
            env=veusz_worker_environment(),
        )
        return json.loads(result.stdout)
    export_dir = resolved_output_dir or document_path.parent / "exports"
    log_root = export_dir.parent if resolved_output_dir is not None else document_path.parent
    stderr_log = log_root / "logs" / "veusz_export_stderr.log"
    exports: list[dict[str, Any]] = []
    with _capture_process_stderr(stderr_log):
        _prefer_offscreen_export_platform()
        _ensure_veusz_on_path()
        from PyQt6 import QtWidgets
        from veusz import dataimport, document, widgets
        from veusz.document import CommandInterface

        _ = dataimport, widgets
        existing_app = QtWidgets.QApplication.instance()
        app = existing_app or QtWidgets.QApplication([])
        try:
            doc = document.Document()
            doc.load(str(document_path))
            interface = CommandInterface(doc)
            export_dir.mkdir(parents=True, exist_ok=True)
            for fmt in formats:
                suffix, dpi = _export_suffix(fmt)
                output_path = export_dir / f"{document_path.stem}{suffix}"
                kwargs: dict[str, Any] = {"page": [0]}
                if dpi is not None:
                    kwargs["dpi"] = dpi
                if fmt == "pdf":
                    kwargs["pdfdpi"] = 72
                interface.Export(str(output_path), **kwargs)
                exports.append(
                    {
                        "format": fmt,
                        "path": str(output_path),
                        "exists": output_path.exists(),
                        "size_bytes": output_path.stat().st_size if output_path.exists() else 0,
                    }
                )
        finally:
            if existing_app is None:
                app.quit()
    payload: dict[str, Any] = {
        "kind": "sciplot_studio_export",
        "document": str(document_path),
        "export_dir": str(export_dir),
        "exports": exports,
    }
    if stderr_log.exists():
        payload["stderr_log"] = str(stderr_log)
    return payload


def publish_standalone_export_receipt(
    *,
    document_path: Path,
    requested_formats: list[str],
    exports: list[dict[str, Any]],
    artifact_root: Path,
) -> dict[str, Any]:
    resolved_root = artifact_root.expanduser().resolve()
    resolved_root.mkdir(parents=True, exist_ok=True)
    normalized_formats = list(dict.fromkeys(str(item).strip().casefold() for item in requested_formats if item))
    successful_formats = {
        str(item.get("format") or "").casefold()
        for item in exports
        if isinstance(item, dict)
        and item.get("exists") is True
        and int(item.get("size_bytes") or 0) > 0
    }
    requested_exports_complete = set(normalized_formats) <= successful_formats
    export_paths = [
        Path(str(item["path"])).expanduser().resolve()
        for item in exports
        if isinstance(item, dict) and isinstance(item.get("path"), str)
    ]
    export_dirs = {path.parent for path in export_paths}
    qa_required = "pdf" in normalized_formats
    if qa_required and requested_exports_complete and len(export_dirs) == 1:
        try:
            qa = run_qa(next(iter(export_dirs)))
        except (OSError, RuntimeError, ValueError) as exc:
            qa = {
                "kind": "sciplot_artifact_qa",
                "status": "failed",
                "reason": str(exc),
            }
    elif qa_required:
        qa = {
            "kind": "sciplot_artifact_qa",
            "status": "not_run",
            "reason": "Requested standalone exports were incomplete or did not share one artifact directory.",
        }
    else:
        qa = {
            "kind": "sciplot_artifact_qa",
            "status": "not_required",
            "reason": "No PDF was requested; run `sciplot qa` on a later PDF/TIFF pair.",
        }
    qa_passed = qa.get("status") in {"passed", "not_required"}
    export_ready = bool(requested_exports_complete and qa_passed)
    spec_reference = _veusz_spec_reference(document_path)
    receipt_path = resolved_root / "standalone_export_receipt.json"
    qa_path = resolved_root / "qa_report.json"
    qa_path.write_text(json.dumps(json_safe(qa), indent=2, ensure_ascii=False), encoding="utf-8")
    receipt = {
        "kind": "sciplot_standalone_vsz_export",
        "version": 1,
        "status": "passed" if export_ready else "failed",
        "state": "exported_exact_current" if export_ready else "needs_rule_repair",
        "scope": "standalone_exact_current_export",
        "document": str(document_path),
        "document_sha256": existing_file_sha256(document_path),
        "document_authority": "veusz_document",
        "spec_reference": spec_reference,
        "requested_formats": normalized_formats,
        "exports": json_safe(exports),
        "requested_exports_complete": requested_exports_complete,
        "artifact_qa": json_safe(qa),
        "artifact_qa_path": str(qa_path),
        "export_ready": export_ready,
        "project_delivery_complete": False,
        "provenance_complete": False,
        "journal_compliance_established": False,
        "receipt_path": str(receipt_path),
        "limitations": [
            "This receipt proves exact-current VSZ export and artifact QA only.",
            "A standalone VSZ has no SciPlot request, raw-data archive, transform ledger, or portable project delivery.",
            "An optional SciPlot spec sidecar is not required to reopen or export the exact current VSZ.",
        ],
    }
    receipt_path.write_text(
        json.dumps(json_safe(receipt), indent=2, ensure_ascii=False),
        encoding="utf-8",
    )
    return receipt


def publish_studio_export_run(
    *,
    project_dir: Path,
    request_path: Path,
    document_path: Path,
    exports: list[dict[str, Any]],
) -> dict[str, Any]:
    request = _read_json(request_path)
    effective_request, data_mapping_application = resolve_data_mapping_request(
        request,
        base_dir=request_path.parent,
    )
    document_state = _studio_document_state(
        document_path,
        generated_hash=_registered_generated_hash(project_dir),
    )
    output_dir = _next_studio_run_dir(project_dir)
    figures_dir = output_dir / "figures"
    figures_dir.mkdir(parents=True, exist_ok=True)

    copied_exports: list[dict[str, Any]] = []
    figures: list[str] = []
    for item in exports:
        source_value = item.get("path")
        if not isinstance(source_value, str):
            continue
        source = Path(source_value).expanduser()
        if not source.exists() or not source.is_file():
            continue
        destination = figures_dir / source.name
        shutil.copy2(source, destination)
        copied = {
            **item,
            "source": str(source),
            "path": str(destination),
            "relative_path": str(destination.relative_to(output_dir)),
        }
        copied_exports.append(copied)
        figures.append(str(destination))

    output_dir.mkdir(parents=True, exist_ok=True)
    (output_dir / "request_snapshot.json").write_text(
        json.dumps(json_safe(request), indent=2, ensure_ascii=False),
        encoding="utf-8",
    )
    input_path = _resolve_request_input(request, base_dir=request_path.parent)
    raw_archive = _archive_studio_input(input_path, output_dir) if input_path is not None else {}
    existing_transform_ledger = _verified_mapping_ledger_extension(
        request.get("transform_ledger"),
        effective_request.get("transform_ledger")
        if data_mapping_application is not None
        else None,
    )
    snapshot_source = _studio_snapshot_source(
        input_path,
        project_dir=project_dir,
        transform_ledger=existing_transform_ledger,
    )
    processed_source = _write_studio_data_snapshot(snapshot_source, output_dir) if snapshot_source is not None else None
    intake_manifest_path = project_dir / "intake_manifest.json"
    intake_manifest = _read_json(intake_manifest_path) if intake_manifest_path.exists() else {}
    semantic = _studio_export_semantic_payload(
        request=request,
        intake_manifest=intake_manifest,
    )
    metric_source = _studio_metric_source(snapshot_source if snapshot_source is not None else input_path)
    analysis_metrics = (
        compute_analysis_metrics(
            source_path=metric_source,
            processed_source=metric_source,
            semantic=semantic,
            output_dir=output_dir,
        )
        if metric_source is not None and semantic.get("rule_id")
        else []
    )
    study_model = normalize_study_model(
        request.get("study_model")
        if isinstance(request.get("study_model"), dict)
        else {"kind": "sciplot_study_model", "version": 1, "samples": [], "figure_queue": []}
    )
    publication_intent = build_publication_intent(
        study_model,
        request=request,
        existing=request.get("publication_intent") if isinstance(request.get("publication_intent"), dict) else None,
    )
    publication_profile = get_publication_profile(publication_intent["target_profile_id"])
    transform_ledger = build_transform_ledger(
        study_model,
        request=request,
        input_path=input_path or document_path,
        existing=existing_transform_ledger,
    )
    visual_transforms = _studio_visual_presentation_transforms(document_path)
    if visual_transforms:
        presentation_input = metric_source or snapshot_source or input_path or document_path
        presentation_step = build_transform_step(
            step_id="veusz_visual_presentation",
            operation="apply_recorded_visual_presentation_transforms",
            input_path=presentation_input,
            output_path=document_path,
            implementation_ref="sciplot_core.studio._apply_template_series_transforms",
            parameters={
                "transforms": visual_transforms,
                "source_values_preserved_outside_visual_presentation": True,
            },
        )
        transform_ledger["steps"] = [
            step
            for step in transform_ledger.get("steps", [])
            if isinstance(step, dict) and step.get("id") != presentation_step["id"]
        ] + [presentation_step]
    if (
        isinstance(existing_transform_ledger, dict)
        and existing_transform_ledger.get("status") == "pending_runtime"
        and not existing_transform_ledger.get("steps")
    ):
        # The document may have been prepared by an older SciPlot version that
        # did not persist runtime preprocessing. Do not rewrite that uncertainty
        # as an identity transform merely because the edited VSZ now exists.
        transform_ledger["status"] = "incomplete_lineage"
        transform_ledger["steps"] = []
        transform_ledger["limitations"] = [
            "The saved Veusz document predates persisted runtime transform steps; "
            "preprocessing lineage requires review."
        ]
    publication_intent = link_intent_to_transform_ledger(publication_intent, transform_ledger)
    study_model["publication_intent_ref"] = "publication_intent.json"
    publication_artifacts = write_publication_artifacts(
        output_dir,
        publication_intent=publication_intent,
        transform_ledger=transform_ledger,
        publication_profile=publication_profile,
    )
    _write_studio_analysis_report(
        output_dir,
        request=request,
        document_path=document_path,
        figures=figures,
        analysis_metrics=analysis_metrics,
    )
    qa = _run_studio_qa(
        output_dir,
        publication_profile=publication_profile,
        strict_publication=bool(request.get("publication_strict")),
        veusz_documents=[document_path],
    )
    publication_qa = qa.get("publication") if isinstance(qa.get("publication"), dict) else {}
    publication_artifacts = write_publication_artifacts(
        output_dir,
        publication_intent=publication_intent,
        transform_ledger=transform_ledger,
        publication_profile=publication_profile,
        publication_qa=publication_qa,
    )
    study_model = attach_run_artifacts_to_study_model(
        study_model,
        output_dir=output_dir,
        figures=figures,
        analysis_metrics=analysis_metrics,
        qa=qa,
    )
    layout_quality = _studio_layout_quality_from_spec(document_path)
    result = {
        "kind": "sciplot_studio_export_result",
        "engine": "veusz",
        "render_engine": "veusz",
        "qa_target": "veusz_export",
        "document": str(document_path),
        "veusz_document": str(document_path),
        "veusz_spec": str(_veusz_spec_path(document_path)),
        "document_authority": document_state["authority"],
        "exported_document_hash": document_state["current_hash"],
        "manual_edit_detected": document_state["manual_edit_detected"],
        "export_formats": [str(item.get("format")) for item in copied_exports if item.get("format")],
        "exports": copied_exports,
        "outputs": figures,
        "processed": processed_source is not None,
        "processed_source": str(processed_source) if processed_source is not None else None,
        "data_snapshot_source": str(snapshot_source) if snapshot_source is not None else None,
        "analysis_metrics": analysis_metrics,
        "template": request.get("template") or request.get("recipe") or "veusz_document",
        "operation_mode": normal_mode_payload(route="studio"),
        "data_mapping_application": json_safe(data_mapping_application),
        "data_mapping_coverage": json_safe(
            request.get("data_mapping_coverage")
        ),
    }
    manifest = {
        "kind": "sciplot_run",
        "created_at": datetime.now(UTC).isoformat(),
        "request_path": str(request_path),
        "request": json_safe(request),
        "route": "studio",
        "semantic": semantic,
        "final_recipe": None,
        "input": str(input_path) if input_path is not None else "",
        "raw_archive": json_safe(raw_archive),
        "output": str(output_dir),
        "figures": figures,
        "result": json_safe(result),
        "study_model": json_safe(study_model),
        "publication_intent": json_safe(publication_intent),
        "transform_ledger": json_safe(transform_ledger),
        "journal_profile": json_safe(publication_profile),
        "publication_qa": json_safe(publication_qa),
        "publication_artifacts": json_safe(publication_artifacts),
        "qa": qa,
        "render_engine": "veusz",
        "qa_target": "veusz_export",
        "veusz_document": str(document_path),
        "veusz_spec": str(_veusz_spec_path(document_path)),
        "manual_edit_hash": existing_file_sha256(document_path),
        "document_authority": document_state["authority"],
        "exported_document_hash": document_state["current_hash"],
        "manual_edit_detected": document_state["manual_edit_detected"],
        "document_state": document_state,
        "layout_policy": {
            "kind": "sciplot_layout_policy",
            "policy_id": "veusz_native_document",
            "review_mode": "safe_preview_with_optional_advanced_editor",
        },
        "layout_quality": layout_quality,
        "operation_mode": normal_mode_payload(route="studio"),
        "data_mapping_application": json_safe(data_mapping_application),
        "data_mapping_coverage": json_safe(
            request.get("data_mapping_coverage")
        ),
        "studio": {
            "engine": "veusz",
            "render_engine": "veusz",
            "qa_target": "veusz_export",
            "document": str(document_path),
            "spec": str(_veusz_spec_path(document_path)),
            "manual_edit_hash": existing_file_sha256(document_path),
            "document_authority": document_state["authority"],
            "exported_document_hash": document_state["current_hash"],
            "manual_edit_detected": document_state["manual_edit_detected"],
            "document_state": document_state,
            "upstream": upstream_status()["veusz"],
            "operation_mode": normal_mode_payload(route="studio"),
        },
    }
    manifest["revision_brief"] = _write_studio_revision_brief(output_dir, manifest=manifest)
    _write_studio_review_html(output_dir, manifest=manifest)
    studio_snapshot = output_dir / "studio"
    if studio_snapshot.exists():
        shutil.rmtree(studio_snapshot)
    if document_path.parent.exists():
        shutil.copytree(document_path.parent, studio_snapshot)
    (output_dir / "manifest.json").write_text(
        json.dumps(json_safe(manifest), indent=2, ensure_ascii=False),
        encoding="utf-8",
    )
    manifest["package_contract"] = build_output_package_contract(output_dir, manifest=manifest)
    manifest["delivery_package"] = build_delivery_package(output_dir, manifest=manifest)
    ready_to_use = bool(
        qa.get("status") == "passed"
        and manifest["package_contract"].get("complete") is True
        and manifest["delivery_package"].get("complete") is True
    )
    manifest["state"] = "ready" if ready_to_use else "needs_rule_repair"
    manifest["ready_to_use"] = ready_to_use
    (output_dir / "manifest.json").write_text(
        json.dumps(json_safe(manifest), indent=2, ensure_ascii=False),
        encoding="utf-8",
    )
    _register_studio_run(project_dir, manifest)
    return {
        "kind": "sciplot_studio_export_run",
        "output": str(output_dir),
        "manifest": str(output_dir / "manifest.json"),
        "review_html": str(output_dir / "review.html"),
        "revision_brief": str(output_dir / "revision_brief.md"),
        "figures": figures,
        "qa": qa,
        "package_contract": manifest["package_contract"],
        "delivery_package": manifest["delivery_package"],
        "state": manifest["state"],
        "ready_to_use": ready_to_use,
    }


def _verified_mapping_ledger_extension(
    current: object,
    verified_base: object,
) -> dict[str, Any] | None:
    if not isinstance(verified_base, dict):
        return deepcopy(current) if isinstance(current, dict) else None
    if not isinstance(current, dict):
        return deepcopy(verified_base)
    base_steps = (
        verified_base.get("steps")
        if isinstance(verified_base.get("steps"), list)
        else []
    )
    current_steps = (
        current.get("steps")
        if isinstance(current.get("steps"), list)
        else []
    )
    if current_steps[: len(base_steps)] != base_steps:
        raise ValueError(
            "Studio transform lineage no longer extends the verified "
            "DataMappingProposal ledger."
        )
    return deepcopy(current)


def _studio_export_semantic_payload(
    *,
    request: dict[str, Any],
    intake_manifest: dict[str, Any],
) -> dict[str, Any]:
    recognition = (
        intake_manifest.get("recognition")
        if isinstance(intake_manifest.get("recognition"), dict)
        else {}
    )
    rule_id = str(
        recognition.get("rule_id") or request.get("rule_id") or ""
    ).strip()
    rule = get_rule(rule_id) if rule_id else None
    rule_payload = (
        semantic_payload_from_rule(
            rule,
            confidence=100.0,
            reason=(
                recognition.get("reason")
                or "Resolved from the persisted request rule for Studio export."
            ),
        )
        if rule is not None
        else {}
    )
    experiment = (
        intake_manifest.get("experiment")
        if isinstance(intake_manifest.get("experiment"), dict)
        else {}
    )
    return {
        **rule_payload,
        **recognition,
        "semantic_family": (
            recognition.get("semantic_family")
            or rule_payload.get("semantic_family")
            or experiment.get("id")
            or rule_id
            or "unknown"
        ),
        "rule_id": recognition.get("rule_id") or rule_id or None,
        "reason": (
            recognition.get("reason")
            or rule_payload.get("reason")
            or "Exported from the canonical SciPlot Veusz document."
        ),
        "route": "studio",
    }


def _resolve_studio_target(
    path: Path,
    *,
    output_root: Path | None = None,
    rule_id: str | None = None,
    template: str | None = None,
    project_name: str | None = None,
) -> dict[str, Any]:
    if path.suffix.lower() == ".vsz":
        if not path.exists():
            raise FileNotFoundError(f"Veusz document not found: {path}")
        return {"mode": "vsz", "document": path}
    if path.is_dir():
        request = path / "plot_request.json"
        if not request.exists():
            return _qt_first_project_from_source(
                path,
                output_root=output_root,
                rule_id=rule_id,
                template=template,
                project_name=project_name,
            )
        return {"mode": "project", "project_dir": path, "request": request}
    if path.is_file() and path.suffix.lower() == ".json":
        return {"mode": "request", "project_dir": path.parent, "request": path}
    if path.exists():
        return _qt_first_project_from_source(
            path,
            output_root=output_root,
            rule_id=rule_id,
            template=template,
            project_name=project_name,
        )
    raise ValueError("studio accepts a SciPlot project directory, plot_request.json, or .vsz document.")


def _qt_first_project_from_source(
    path: Path,
    *,
    output_root: Path | None = None,
    rule_id: str | None = None,
    template: str | None = None,
    project_name: str | None = None,
) -> dict[str, Any]:
    from sciplot_core.intake import create_intake_project_from_session, prepare_intake_session

    project_root = output_root or Path("outputs") / "intake_projects"
    session = prepare_intake_session(path, output_root=project_root, requested_rule_id=rule_id)
    normalized_name = _normalize_optional_string(project_name)
    if normalized_name:
        session["project_name"] = normalized_name
        session_path = session.get("session_path")
        if isinstance(session_path, str) and session_path.strip():
            Path(session_path).write_text(
                json.dumps(json_safe(session), indent=2, ensure_ascii=False),
                encoding="utf-8",
            )
    project = create_intake_project_from_session(session)
    project_dir = Path(str(project["project_dir"])).expanduser().resolve()
    request = project_dir / "plot_request.json"
    _apply_studio_request_overrides(
        project_dir,
        request_path=request,
        rule_id=rule_id,
        template=template,
        project_name=normalized_name,
    )
    return {
        "mode": "source",
        "source": path,
        "session": session.get("session_path"),
        "project_dir": project_dir,
        "request": request,
    }


def _apply_studio_request_overrides(
    project_dir: Path,
    *,
    request_path: Path,
    rule_id: str | None = None,
    template: str | None = None,
    project_name: str | None = None,
) -> None:
    selected_rule_id = _normalize_optional_string(rule_id)
    selected_rule = get_rule(selected_rule_id) if selected_rule_id else None
    if selected_rule is not None and selected_rule.fixture_status != "ready":
        raise ValueError(f"Material rule `{selected_rule.rule_id}` is not ready for production use.")
    selected_rule_payload = (
        semantic_payload_from_rule(
            selected_rule,
            confidence=100.0,
            reason=f"Explicit material rule `{selected_rule.rule_id}` selected by the user or Luna/Codex.",
        )
        if selected_rule is not None
        else None
    )
    selected_template = _normalize_optional_string(template) or (selected_rule.template if selected_rule else None)
    selected_project_name = _normalize_optional_string(project_name)
    if not selected_rule and not selected_template and not selected_project_name:
        return
    if request_path.exists():
        request = _read_json(request_path)
        if selected_rule is not None:
            request["rule_id"] = selected_rule.rule_id
            request.setdefault("recipe", "auto")
            current_options = (
                dict(request.get("render_options")) if isinstance(request.get("render_options"), dict) else {}
            )
            explicit_key_payload = request.get("explicit_render_option_keys")
            explicit_keys = (
                {str(key) for key in explicit_key_payload if str(key) in current_options}
                if isinstance(explicit_key_payload, list | tuple | set)
                else set(current_options)
            )
            explicit_options = {key: current_options[key] for key in explicit_keys}
            current_options = dict((selected_rule_payload or {}).get("render_options") or {})
            current_options.setdefault("x_label_override", selected_rule.x_axis.display_label)
            current_options.setdefault("y_label_override", selected_rule.y_axis.display_label)
            current_options.update(explicit_options)
            request["render_options"] = current_options
        if selected_template:
            previous_template = str(request.get("template") or "").strip()
            if previous_template != selected_template:
                try:
                    from sciplot_core.contract import load_plot_contract

                    contract = load_plot_contract()
                    previous_defaults = (
                        contract.templates[previous_template].default_options
                        if previous_template in contract.templates
                        else {}
                    )
                    selected_defaults = (
                        contract.templates[selected_template].default_options
                        if selected_template in contract.templates
                        else {}
                    )
                    current_options = (
                        dict(request.get("render_options")) if isinstance(request.get("render_options"), dict) else {}
                    )
                    explicit_key_payload = request.get("explicit_render_option_keys")
                    explicit_keys = (
                        {str(key) for key in explicit_key_payload}
                        if isinstance(explicit_key_payload, list | tuple | set)
                        else set(current_options)
                    )
                    for key, value in previous_defaults.items():
                        if key not in explicit_keys and current_options.get(key) == value:
                            current_options.pop(key, None)
                    for key, value in selected_defaults.items():
                        current_options.setdefault(key, value)
                    request["render_options"] = current_options
                except Exception:
                    pass
            request["template"] = selected_template
        request_path.write_text(json.dumps(json_safe(request), indent=2, ensure_ascii=False), encoding="utf-8")
    for manifest_path in [project_dir / "intake_manifest.json", *sorted(project_dir.glob("*.sciplot.json"))]:
        if not manifest_path.exists():
            continue
        payload = _read_json(manifest_path)
        if selected_project_name:
            payload["project_name"] = selected_project_name
        if selected_template:
            experiment = payload.get("experiment") if isinstance(payload.get("experiment"), dict) else {}
            experiment["template"] = selected_template
            experiment["chart"] = selected_template
            payload["experiment"] = experiment
            plot_options = payload.get("plot_options") if isinstance(payload.get("plot_options"), dict) else {}
            plot_options["template"] = selected_template
            payload["plot_options"] = plot_options
        if selected_rule is not None:
            recognition = dict(selected_rule_payload or {})
            recognition.update(
                {
                    "confidence": 100.0,
                    "reason": f"Explicit material rule `{selected_rule.rule_id}` selected by the user or Luna/Codex.",
                    "needs_ai_intervention": False,
                    "production_status": "ready",
                }
            )
            payload["recognition"] = recognition
            experiment = payload.get("experiment") if isinstance(payload.get("experiment"), dict) else {}
            experiment["rule_id"] = selected_rule.rule_id
            experiment.setdefault("id", selected_rule.rule_id)
            experiment.setdefault("label", selected_rule.rule_id)
            payload["experiment"] = experiment
        manifest_path.write_text(json.dumps(json_safe(payload), indent=2, ensure_ascii=False), encoding="utf-8")


def _existing_document_payload(document_path: Path) -> dict[str, Any]:
    spec_reference = _veusz_spec_reference(document_path)
    return {
        "kind": "sciplot_studio_prepare",
        "mode": "vsz",
        "operation_mode": normal_mode_payload(route="studio"),
        "document": str(document_path),
        "studio": {
            "kind": "sciplot_studio_document",
            "engine": "veusz",
            "render_engine": "veusz",
            "qa_target": "veusz_export",
            "document": str(document_path),
            "spec": spec_reference["path"],
            "spec_reference": spec_reference,
            "manual_edit_hash": existing_file_sha256(document_path),
            "upstream": upstream_status()["veusz"],
            "operation_mode": normal_mode_payload(route="studio"),
        },
    }


def _next_studio_run_dir(project_dir: Path) -> Path:
    runs_dir = project_dir / "runs"
    runs_dir.mkdir(parents=True, exist_ok=True)
    index = 1
    while True:
        candidate = runs_dir / f"studio_{index:03d}"
        if not candidate.exists():
            return candidate
        index += 1


def _resolve_request_input(request: dict[str, Any], *, base_dir: Path) -> Path | None:
    value = request.get("input")
    if not isinstance(value, str) or not value.strip():
        return None
    path = Path(value).expanduser()
    if not path.is_absolute():
        path = base_dir / path
    return path.resolve()


def _archive_studio_input(input_path: Path, output_dir: Path) -> dict[str, Any]:
    raw_dir = output_dir / "raw"
    raw_dir.mkdir(parents=True, exist_ok=True)
    destination = raw_dir / input_path.name
    if input_path.is_dir():
        shutil.copytree(input_path, destination)
        kind = "directory"
    else:
        shutil.copy2(input_path, destination)
        kind = "file"
    return {"kind": kind, "source": str(input_path), "path": str(destination)}


def _write_studio_data_snapshot(input_path: Path, output_dir: Path) -> Path:
    processed_dir = output_dir / "processed"
    processed_dir.mkdir(parents=True, exist_ok=True)
    destination = processed_dir / "studio_export_data.xlsx"
    try:
        frames = _read_source_frames(input_path)
    except Exception as exc:
        raise StudioPreparationBlocked(
            "studio_data_snapshot_failed",
            f"Studio could not create a data snapshot from {input_path}: {exc}",
        ) from exc
    with pd.ExcelWriter(destination) as writer:
        used_names: set[str] = set()
        for index, (label, frame) in enumerate(frames, start=1):
            sheet_name = _excel_sheet_name(label, fallback=f"data_{index}", used=used_names)
            frame.to_excel(writer, sheet_name=sheet_name, index=False)
    return destination


def _studio_snapshot_source(
    input_path: Path | None,
    *,
    project_dir: Path,
    transform_ledger: dict[str, Any] | None,
) -> Path | None:
    """Prefer the current plotted table while retaining raw input separately.

    Instrument folders are not necessarily rectangular worksheets. Semantic
    preparation records the exact plot-ready output in the transform ledger;
    only project-local primary outputs are eligible for the delivery workbook.
    """
    if isinstance(transform_ledger, dict):
        steps = transform_ledger.get("steps") if isinstance(transform_ledger.get("steps"), list) else []
        for step in reversed(steps):
            if not isinstance(step, dict):
                continue
            artifacts = step.get("output_artifacts") if isinstance(step.get("output_artifacts"), list) else []
            ordered = sorted(
                (item for item in artifacts if isinstance(item, dict)),
                key=lambda item: 0 if item.get("role") == "output" else 1,
            )
            for artifact in ordered:
                path_value = artifact.get("path")
                if not isinstance(path_value, str) or not path_value.strip():
                    continue
                candidate = Path(path_value).expanduser().resolve()
                if not candidate.is_relative_to(project_dir.resolve()):
                    continue
                if candidate.exists() and (candidate.is_file() or candidate.is_dir()):
                    return candidate
    return input_path


def _studio_metric_source(source: Path | None) -> Path | None:
    """Resolve one canonical plotted table without guessing among raw files."""

    if source is None:
        return None
    if source.is_file():
        return source
    if not source.is_dir():
        return None
    supported_suffixes = {".csv", ".tsv", ".txt", ".xlsx", ".xls"}
    candidates = sorted(
        path for path in source.rglob("*") if path.is_file() and path.suffix.casefold() in supported_suffixes
    )
    if len(candidates) == 1:
        return candidates[0]
    preferred_tokens = ("comparison", "plotting_data", "source_curves", "prepared")
    preferred = [path for path in candidates if any(token in path.stem.casefold() for token in preferred_tokens)]
    return preferred[0] if len(preferred) == 1 else None


def _excel_sheet_name(label: str, *, fallback: str, used: set[str]) -> str:
    cleaned = "".join("_" if char in "[]:*?/\\'" else char for char in str(label).strip())
    cleaned = (cleaned or fallback)[:31]
    candidate = cleaned
    suffix = 1
    while candidate in used:
        trailer = f"_{suffix}"
        candidate = f"{cleaned[: 31 - len(trailer)]}{trailer}"
        suffix += 1
    used.add(candidate)
    return candidate


def _run_studio_qa(
    output_dir: Path,
    *,
    publication_profile: dict[str, Any] | None = None,
    strict_publication: bool = False,
    veusz_documents: list[Path] | None = None,
) -> dict[str, Any]:
    try:
        qa = run_qa(
            output_dir,
            publication_profile=publication_profile,
            strict_publication=strict_publication,
            veusz_documents=veusz_documents,
        )
        layout_documents: list[dict[str, Any]] = []
        critical_issues: list[dict[str, Any]] = []
        for document_path in veusz_documents or []:
            spec_path = _veusz_spec_path(document_path)
            spec = _read_json(spec_path) if spec_path.exists() else {}
            issues = [item for item in spec.get("layout_issues", []) if isinstance(item, dict)]
            layout_documents.append(
                {
                    "document": str(document_path),
                    "spec": str(spec_path),
                    "issues": json_safe(issues),
                }
            )
            critical_issues.extend(
                {"document": str(document_path), **item}
                for item in issues
                if str(item.get("severity") or "").casefold() == "critical"
            )
        qa["studio_layout"] = {
            "kind": "sciplot_studio_layout_qa",
            "status": "failed" if critical_issues else "passed",
            "documents": layout_documents,
            "critical_issues": json_safe(critical_issues),
        }
        if critical_issues:
            qa["status"] = "failed"
            qa["reason"] = "Critical exact-current Veusz layout issue(s): " + ", ".join(
                sorted({str(item.get("id") or "unknown") for item in critical_issues})
            )
        return qa
    except ValueError as exc:
        return {
            "status": "failed",
            "reason": str(exc),
            "pdf_count": 0,
            "pdfs": [],
            "goldens_checked": 0,
            "goldens_skipped": [],
        }


def _studio_layout_quality_from_spec(document_path: Path) -> dict[str, Any]:
    spec_path = _veusz_spec_path(document_path)
    spec = _read_json(spec_path) if spec_path.exists() else {}
    series = spec.get("series") if isinstance(spec.get("series"), list) else []
    axes = spec.get("axes") if isinstance(spec.get("axes"), dict) else {}
    x_axis = axes.get("x") if isinstance(axes.get("x"), dict) else {}
    y_axis = axes.get("y") if isinstance(axes.get("y"), dict) else {}
    issues = [item for item in spec.get("layout_issues", []) if isinstance(item, dict)]
    autofixes = [str(item) for item in spec.get("autofixes_applied", []) if isinstance(item, str)]
    return {
        "kind": "sciplot_studio_layout_quality",
        "review_mode": "native_veusz_editor",
        "needs_ai_intervention": any(item.get("severity") == "critical" for item in issues),
        "issue_ids": sorted({str(item["id"]) for item in issues if isinstance(item.get("id"), str)}),
        "autofixes_applied": sorted(set(autofixes)),
        "summaries": [
            {
                "kind": "sciplot_veusz_layout_summary",
                "render_engine": "veusz",
                "qa_target": "veusz_export",
                "template": spec.get("template"),
                "document": str(document_path),
                "spec": str(spec_path),
                "series_count": len(series),
                "requested_size_mm": spec.get("size_mm") if isinstance(spec.get("size_mm"), list) else [],
                "figure_size_mm": spec.get("size_mm") if isinstance(spec.get("size_mm"), list) else [],
                "axes": [
                    {
                        "x_label": x_axis.get("label"),
                        "y_label": y_axis.get("label"),
                        "x_bounds": [x_axis.get("min"), x_axis.get("max")],
                        "y_bounds": [y_axis.get("min"), y_axis.get("max")],
                        "x_ticks": x_axis.get("ticks") or [],
                        "y_ticks": y_axis.get("ticks") or [],
                        "legend": spec.get("legend", {}),
                    }
                ],
            }
        ],
    }


def _studio_visual_presentation_transforms(document_path: Path) -> list[dict[str, Any]]:
    spec_path = _veusz_spec_path(document_path)
    spec = _read_json(spec_path) if spec_path.exists() else {}
    return [dict(item) for item in spec.get("visual_data_transforms", []) if isinstance(item, dict)]


def _write_studio_analysis_report(
    output_dir: Path,
    *,
    request: dict[str, Any],
    document_path: Path,
    figures: list[str],
    analysis_metrics: list[dict[str, Any]],
) -> None:
    notes = request.get("review_notes") if isinstance(request.get("review_notes"), list) else []
    lines = [
        "# SciPlot Studio Export",
        "",
        "- Route: `studio`",
        "- Engine: `veusz`",
        f"- Document: `{document_path}`",
        f"- Figures: {len(figures)}",
        "",
        "## Analysis Metrics",
        "",
    ]
    if analysis_metrics:
        for item in analysis_metrics:
            value = item.get("value", "")
            unit = str(item.get("unit") or "").strip()
            status = str(item.get("status") or "ok")
            suffix = f" {unit}" if unit else ""
            lines.append(f"- `{item.get('metric')}`: {value}{suffix} ({status})")
            reason = str(item.get("reason") or "").strip()
            if reason:
                lines.append(f"  - {reason}")
    else:
        lines.append("- No deterministic rule metrics were registered for this export.")
    lines.extend(
        [
            "",
            "## Review Notes",
            "",
            *(f"- {note}" for note in notes),
        ]
    )
    if not notes:
        lines.append("- No review notes supplied.")
    (output_dir / "analysis_report.md").write_text("\n".join(lines) + "\n", encoding="utf-8")


def _write_studio_review_html(output_dir: Path, *, manifest: dict[str, Any]) -> None:
    figures = [Path(path) for path in manifest.get("figures", []) if isinstance(path, str)]
    figure_items = []
    for figure in figures:
        rel = figure.relative_to(output_dir) if figure.exists() and figure.is_relative_to(output_dir) else figure
        label = escape(str(rel))
        if figure.suffix.lower() in {".png", ".jpg", ".jpeg"}:
            figure_items.append(f'<li><a href="{label}">{label}</a><br><img src="{label}" alt="{label}"></li>')
        else:
            figure_items.append(f'<li><a href="{label}">{label}</a></li>')
    request = manifest.get("request") if isinstance(manifest.get("request"), dict) else {}
    notes = request.get("review_notes") if isinstance(request.get("review_notes"), list) else []
    note_items = [f"<li>{escape(str(note))}</li>" for note in notes] or ["<li>No review notes supplied.</li>"]
    revision_brief = manifest.get("revision_brief")
    html = "\n".join(
        [
            "<!doctype html>",
            "<html>",
            "<head>",
            '<meta charset="utf-8">',
            "<title>SciPlot Studio Review</title>",
            "<style>",
            "body{font-family:Arial,sans-serif;margin:32px;line-height:1.45}",
            "img{max-width:720px;border:1px solid #ddd}",
            "</style>",
            "</head>",
            "<body>",
            "<h1>SciPlot Studio Review</h1>",
            "<p>Route: <code>studio</code>; engine: <code>Veusz</code>.</p>",
            "<h2>Review Notes</h2>",
            "<ul>",
            *note_items,
            "</ul>",
            "<h2>Figures</h2>",
            "<ul>",
            *(figure_items or ["<li>No figures were exported.</li>"]),
            "</ul>",
            "<h2>Revision</h2>",
            "<ul>",
            (
                f'<li><a href="{escape(str(revision_brief))}">Revision brief for assisted repair</a></li>'
                if isinstance(revision_brief, str) and revision_brief
                else "<li>No revision brief was generated.</li>"
            ),
            "</ul>",
            "</body>",
            "</html>",
        ]
    )
    (output_dir / "review.html").write_text(html + "\n", encoding="utf-8")


def _write_studio_revision_brief(output_dir: Path, *, manifest: dict[str, Any]) -> str:
    figures = [Path(path) for path in manifest.get("figures", []) if isinstance(path, str)]
    figure_lines = []
    for figure in figures:
        rel = figure.relative_to(output_dir) if figure.exists() and figure.is_relative_to(output_dir) else figure
        figure_lines.append(f"- `{rel}`")
    qa = manifest.get("qa") if isinstance(manifest.get("qa"), dict) else {}
    studio = manifest.get("studio") if isinstance(manifest.get("studio"), dict) else {}
    lines = [
        "# SciPlot Studio Revision Brief",
        "",
        "Use this brief for optional assisted repair of the SciPlot request or Veusz document bridge.",
        "",
        "## Run",
        "",
        f"- Output: `{output_dir}`",
        f"- Request: `{manifest.get('request_path')}`",
        "- Route: `studio`",
        f"- Veusz document: `{studio.get('document') or ''}`",
        f"- QA: `{qa.get('status') or 'unknown'}`",
        "",
        "## Figures",
        "",
        *(figure_lines or ["- No figures were recorded."]),
        "",
        "## Assisted Repair Request",
        "",
        "请按这些修改意见调整 SciPlot 数据识别、请求生成、数据整理或 Veusz 文档桥接，然后重新导出：",
        "",
        "- 数据导入/预处理：",
        "- 自动生成的 Veusz 对象：",
        "- 需要保留的 Veusz 手工编辑：",
        "- 导出格式或 QA：",
        "- 其他：",
    ]
    (output_dir / "revision_brief.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    return "revision_brief.md"


def _read_json(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"Expected JSON object: {path}")
    return payload


def _scalar_field_role_columns(
    frame: pd.DataFrame,
    *,
    render_options: dict[str, Any],
) -> tuple[object, object, object]:
    numeric = _coerced_numeric_frame(frame)
    numeric_columns = [column for column in numeric.columns if numeric[column].notna().any()]
    if len(numeric_columns) < 3:
        raise StudioPreparationBlocked(
            "scalar_field_needs_xyz_columns",
            "Scalar-field rendering needs three numeric X/Y/Z columns.",
        )
    requested = render_options.get("data_variables")
    requested = requested if isinstance(requested, dict) else {}
    resolved: list[object] = []
    available_by_text = {str(column).strip().casefold(): column for column in frame.columns}
    for role in ("x", "y", "z"):
        value = requested.get(role)
        if isinstance(value, str) and value.strip():
            column = available_by_text.get(value.strip().casefold())
            if column is None:
                raise StudioPreparationBlocked(
                    "scalar_field_role_column_missing",
                    f"Scalar-field role `{role}` refers to missing column `{value}`.",
                )
            resolved.append(column)
            continue
        alias = next(
            (
                column
                for column in numeric_columns
                if str(column).strip().casefold() in {role, role.upper().casefold()}
            ),
            None,
        )
        if alias is not None and alias not in resolved:
            resolved.append(alias)
            continue
        fallback = next((column for column in numeric_columns if column not in resolved), None)
        if fallback is None:
            raise StudioPreparationBlocked(
                "scalar_field_role_column_missing",
                f"Scalar-field role `{role}` could not be resolved.",
            )
        resolved.append(fallback)
    return resolved[0], resolved[1], resolved[2]


def _scalar_field_from_frames(
    frames: list[tuple[str, pd.DataFrame]],
    *,
    render_options: dict[str, Any],
) -> tuple[list[StudioSeries], dict[str, Any]]:
    if len(frames) != 1:
        raise StudioPreparationBlocked(
            "scalar_field_needs_one_table",
            "Scalar-field rendering currently accepts one plot-ready X/Y/Z table per figure.",
        )
    _source_label, frame = frames[0]
    x_column, y_column, z_column = _scalar_field_role_columns(frame, render_options=render_options)
    numeric = _coerced_numeric_frame(frame)
    field = numeric[[x_column, y_column, z_column]].dropna().copy()
    if field.empty:
        raise StudioPreparationBlocked(
            "scalar_field_has_no_finite_rows",
            "Scalar-field X/Y/Z columns contain no complete numeric rows.",
        )
    if field.duplicated([x_column, y_column]).any():
        raise StudioPreparationBlocked(
            "scalar_field_duplicate_xy",
            "Scalar-field X/Y pairs must be unique; aggregate duplicates explicitly before rendering.",
        )
    x_values = sorted(float(value) for value in field[x_column].unique())
    y_values = sorted(float(value) for value in field[y_column].unique())
    if len(x_values) < 2 or len(y_values) < 2:
        raise StudioPreparationBlocked(
            "scalar_field_grid_too_small",
            "Scalar-field rendering needs at least two unique X and two unique Y coordinates.",
        )
    expected_rows = len(x_values) * len(y_values)
    if len(field) != expected_rows:
        raise StudioPreparationBlocked(
            "scalar_field_incomplete_grid",
            f"Scalar-field grid is incomplete: expected {expected_rows} unique X/Y cells, found {len(field)}.",
        )
    pivot = field.pivot(index=y_column, columns=x_column, values=z_column).reindex(
        index=y_values,
        columns=x_values,
    )
    if pivot.isna().any().any():
        raise StudioPreparationBlocked(
            "scalar_field_incomplete_grid",
            "Scalar-field grid contains missing cells after X/Y pivoting.",
        )
    z_values = [[float(value) for value in row] for row in pivot.to_numpy(dtype=float)]
    if not all(math.isfinite(value) for row in z_values for value in row):
        raise StudioPreparationBlocked(
            "scalar_field_non_finite_z",
            "Scalar-field Z values must all be finite.",
        )
    zscale = str(render_options.get("zscale") or "linear").strip().casefold()
    if zscale not in {"linear", "sqrt", "log", "squared"}:
        raise ValueError("Scalar-field zscale must be linear, sqrt, log, or squared.")
    if zscale == "log" and any(value <= 0.0 for row in z_values for value in row):
        raise StudioPreparationBlocked(
            "scalar_field_log_requires_positive_z",
            "Scalar-field logarithmic color scaling requires strictly positive Z values.",
        )
    x_label = _veusz_axis_label(render_options.get("x_label_override") or str(x_column))
    y_label = _veusz_axis_label(render_options.get("y_label_override") or str(y_column))
    z_label = _veusz_axis_label(render_options.get("z_label_override") or str(z_column))
    scalar_field = {
        "data_name": "scalar_field_z",
        "x_column": str(x_column),
        "y_column": str(y_column),
        "z_column": str(z_column),
        "x_values": x_values,
        "y_values": y_values,
        "z_values": z_values,
        "z_label": z_label,
        "z_data_min": min(value for row in z_values for value in row),
        "z_data_max": max(value for row in z_values for value in row),
        "grid_shape": [len(y_values), len(x_values)],
    }
    surrogate = StudioSeries(
        label=z_label,
        x_name="scalar_field_extent_x",
        y_name="scalar_field_extent_y",
        x_values=(x_values[0], x_values[-1]),
        y_values=(y_values[0], y_values[-1]),
        color=DEFAULT_PALETTE[0],
        marker="none",
        presentation_kind="scalar_field",
    )
    return [surrogate], {
        "x_label": x_label,
        "y_label": y_label,
        "scalar_field": scalar_field,
    }


def _series_from_request(
    request: dict[str, Any],
    *,
    base_dir: Path,
) -> tuple[list[StudioSeries], dict[str, Any], list[dict[str, Any]], Path]:
    input_value = request.get("input")
    if not isinstance(input_value, str) or not input_value.strip():
        raise ValueError("plot_request.json needs an input path for Studio document generation.")
    source = Path(input_value).expanduser()
    if not source.is_absolute():
        source = (base_dir / source).resolve()
    source_root = source
    effective_request, mapping_application = resolve_data_mapping_request(
        request,
        base_dir=base_dir,
    )
    effective_input = effective_request.get("input")
    if not isinstance(effective_input, str) or not effective_input.strip():
        raise ValueError(
            "Resolved data mapping request has no effective input path."
        )
    source = Path(effective_input).expanduser()
    if not source.is_absolute():
        source = (base_dir / source).resolve()
    request = effective_request
    render_options = _effective_render_options(request)
    transform_steps = [
        dict(step)
        for step in (
            mapping_application.get("transform_steps", [])
            if mapping_application is not None
            else []
        )
        if isinstance(step, dict)
    ]
    source, semantic_steps = _studio_source_for_request(
        source,
        request=request,
        base_dir=base_dir,
    )
    transform_steps.extend(semantic_steps)
    frames = _read_source_frames(source, request=request)
    raw_series: list[StudioSeries] = []
    axis_info: dict[str, Any] = {"x_label": "x", "y_label": "y"}
    if _request_template(request) in SCALAR_FIELD_TEMPLATE_IDS:
        raw_series, axis_info = _scalar_field_from_frames(
            frames,
            render_options=render_options,
        )
    elif _request_template(request) in CATEGORICAL_TEMPLATE_IDS:
        raw_series, axis_info = _categorical_series_from_frames(
            frames,
            render_options=render_options,
        )
    else:
        for frame_index, (source_label, frame) in enumerate(frames):
            numeric = _coerced_numeric_frame(frame)
            if numeric.shape[1] < 2:
                continue
            pairs = _xy_pairs_for_request(numeric, request=request)
            first_x, first_y = pairs[0]
            if axis_info["x_label"] == "x":
                axis_info["x_label"] = _axis_label_from_column(frame, first_x)
            if axis_info["y_label"] == "y":
                axis_info["y_label"] = _axis_label_from_column(frame, first_y)
            for column_index, (x_column, y_column) in enumerate(pairs, start=1):
                pair_frame = numeric[[x_column, y_column]].dropna()
                if pair_frame.empty:
                    continue
                x_values = tuple(float(value) for value in pair_frame[x_column].tolist())
                y_values = tuple(float(value) for value in pair_frame[y_column].tolist())
                fallback = source_label if len(pairs) == 1 else str(y_column)
                label = _series_label_from_column(frame[y_column], fallback=fallback)
                raw_series.append(
                    StudioSeries(
                        label=label,
                        x_name=f"x_{frame_index + 1}_{column_index}",
                        y_name=f"y_{frame_index + 1}_{column_index}",
                        x_values=x_values,
                        y_values=y_values,
                        color=DEFAULT_PALETTE[(len(raw_series)) % len(DEFAULT_PALETTE)],
                    )
                )

    if not raw_series:
        raise StudioPreparationBlocked(
            "no_plottable_numeric_series",
            f"Studio found no plottable numeric x/y series in {source}; no placeholder data were generated.",
        )

    render_options = _apply_domain_render_defaults(render_options, request=request, axis_info=axis_info)
    styled = _apply_series_options(raw_series, render_options=render_options, request=request)
    if axis_info.get("presentation_kind") == "categorical_replicates":
        styled = _reindex_categorical_series(styled, render_options=render_options)
        axis_info["category_labels"] = [_category_axis_label(item.label) for item in styled]
        axis_info["category_positions"] = [float(index) for index in range(1, len(styled) + 1)]
        axis_info["raw_replicate_count"] = sum(len(item.y_values) for item in styled)
    styled = _apply_template_series_transforms(styled, request=request, render_options=render_options)
    if mapping_application is not None:
        axis_info["data_mapping_coverage"] = _mapping_series_coverage(
            styled,
            mapping_application=mapping_application,
            request=request,
        )
    axis_info["x_label"] = _veusz_axis_label(render_options.get("x_label_override") or axis_info["x_label"])
    axis_info["y_label"] = _veusz_axis_label(render_options.get("y_label_override") or axis_info["y_label"])
    return styled, axis_info, transform_steps, source_root


def _mapping_series_coverage(
    series: list[StudioSeries],
    *,
    mapping_application: dict[str, Any],
    request: dict[str, Any],
) -> dict[str, Any]:
    expected_labels = [
        str(label).strip()
        for label in mapping_application.get("expected_sample_labels", [])
        if str(label).strip()
    ]
    expected_count = int(
        mapping_application.get("expected_series_count_min")
        or len(expected_labels)
    )
    actual_labels = [str(item.label).strip() for item in series]
    missing_labels = [
        expected
        for expected in expected_labels
        if not any(
            _mapping_label_matches(actual, expected)
            for actual in actual_labels
        )
    ]
    passed = len(series) >= expected_count and not missing_labels
    coverage = {
        "kind": "sciplot_data_mapping_series_coverage",
        "version": 1,
        "status": "passed" if passed else "failed",
        "proposal_id": mapping_application.get("proposal_id"),
        "template": _request_template(request),
        "expected_sample_labels": expected_labels,
        "actual_series_labels": actual_labels,
        "expected_series_count_min": expected_count,
        "actual_series_count": len(series),
        "missing_sample_labels": missing_labels,
        "silent_omission_detected": not passed,
    }
    if not passed:
        missing = ", ".join(missing_labels) or "unknown mapped source"
        raise StudioPreparationBlocked(
            "mapped_source_coverage_incomplete",
            "Studio would omit confirmed mapped sources "
            f"({missing}); expected at least {expected_count} series but "
            f"prepared {len(series)}.",
        )
    return coverage


def _mapping_label_matches(actual: str, expected: str) -> bool:
    actual_key = " ".join(actual.casefold().split())
    expected_key = " ".join(expected.casefold().split())
    if actual_key == expected_key:
        return True
    separators = (" ", " (", " [", " /", " -", " —", ":")
    return any(
        actual_key.startswith(expected_key + separator)
        or actual_key.endswith(separator + expected_key)
        for separator in separators
    )


def _veusz_axis_label(value: object) -> str:
    """Translate legacy Matplotlib math delimiters to Veusz markup."""

    label = str(value or "").replace("$", "")
    # Veusz can keep an unbraced numeric subscript active for the following
    # punctuation (for example, ``\sigma_0)`` rendered ``0)`` at script size).
    # Group the common single-digit form so only the intended glyph is reduced.
    return re.sub(r"_(\d)", r"_{\1}", label)


def _veusz_literal_text(value: object) -> str:
    """Escape sample/category text so Veusz does not treat identifiers as math markup."""

    text = str(value or "").replace("\\", "\ue000")
    text = re.sub(r"([_\^\[\]\{\}])", r"\\\1", text)
    return text.replace("\ue000", "{\\backslash}")


def _category_axis_label(value: object) -> str:
    """Compact a trailing millimetre qualifier while preserving its meaning."""

    text = str(value or "").strip()
    match = re.fullmatch(r"(.+?)\s+(\([^()]+\))", text)
    if match is None or len(text) < 10:
        return text
    qualifier = match.group(2).strip("()")
    millimetre = re.fullmatch(r"(\d+(?:\.\d+)?)\s*mm", qualifier, flags=re.IGNORECASE)
    if millimetre is not None:
        return f"{match.group(1)}/{millimetre.group(1)}"
    return text


def _clean_studio_cell(value: object) -> str:
    if value is None or pd.isna(value):
        return ""
    return str(value).strip()


def _categorical_metric_label(value: object) -> str:
    label = _clean_studio_cell(value)
    return re.sub(r"\.\d+$", "", label).strip()


def _categorical_axis_label(metric: str, unit: str) -> str:
    if not metric:
        metric = "Value"
    normalized_unit = unit.strip()
    if normalized_unit.casefold() in {"", "1", "a.u.", "au"}:
        return metric
    return f"{metric} ({normalized_unit})"


def _deterministic_category_positions(center: float, count: int, *, fraction: float) -> tuple[float, ...]:
    if count <= 1:
        return (center,)
    bounded = min(max(float(fraction), 0.0), 0.35)
    step = (2.0 * bounded) / float(count - 1)
    return tuple(center - bounded + index * step for index in range(count))


def _categorical_series_from_frames(
    frames: list[tuple[str, pd.DataFrame]],
    *,
    render_options: dict[str, Any],
) -> tuple[list[StudioSeries], dict[str, Any]]:
    grouped: dict[str, list[float]] = {}
    metric_labels: list[str] = []
    units: list[str] = []
    for source_label, frame in frames:
        if frame.shape[0] < 3:
            continue
        for column in frame.columns:
            values = pd.to_numeric(frame[column].iloc[2:], errors="coerce").dropna()
            if values.empty:
                continue
            sample = _clean_studio_cell(frame[column].iloc[1]) or source_label or str(column)
            grouped.setdefault(sample, []).extend(float(value) for value in values.tolist())
            metric = _categorical_metric_label(column)
            if metric:
                metric_labels.append(metric)
            unit = _clean_studio_cell(frame[column].iloc[0])
            if unit:
                units.append(unit)
    if not grouped:
        return [], {"x_label": "Sample", "y_label": "Value"}
    distinct_metrics = list(dict.fromkeys(metric_labels))
    distinct_units = list(dict.fromkeys(units))
    normalized_metrics = {metric.casefold() for metric in distinct_metrics}
    normalized_units = {re.sub(r"\s+", " ", unit).strip().casefold() for unit in distinct_units}
    if len(normalized_metrics) > 1:
        raise StudioPreparationBlocked(
            "mixed_categorical_metrics",
            "Categorical replicate rendering requires one metric; found: " + ", ".join(distinct_metrics),
        )
    if len(normalized_units) > 1:
        raise StudioPreparationBlocked(
            "mixed_categorical_units",
            "Categorical replicate rendering requires one unit; found: " + ", ".join(distinct_units),
        )
    metric = distinct_metrics[0] if distinct_metrics else "Value"
    unit = distinct_units[0] if distinct_units else ""
    jitter = normalize_raw_point_jitter_fraction(
        render_options.get("raw_point_jitter_fraction", DEFAULT_RAW_POINT_JITTER_FRACTION)
    )
    series: list[StudioSeries] = []
    for index, (sample, values) in enumerate(grouped.items(), start=1):
        series.append(
            StudioSeries(
                label=sample,
                x_name=f"category_x_{index}",
                y_name=f"category_y_{index}",
                x_values=_deterministic_category_positions(float(index), len(values), fraction=jitter),
                y_values=tuple(values),
                color=DEFAULT_PALETTE[(index - 1) % len(DEFAULT_PALETTE)],
                presentation_kind="categorical_replicates",
                category_position=float(index),
            )
        )
    return series, {
        "x_label": "Sample",
        "y_label": _categorical_axis_label(metric, unit),
        "presentation_kind": "categorical_replicates",
        "category_labels": list(grouped),
        "category_positions": [float(index) for index in range(1, len(grouped) + 1)],
        "raw_replicate_count": sum(len(values) for values in grouped.values()),
    }


def _reindex_categorical_series(
    series: list[StudioSeries],
    *,
    render_options: dict[str, Any],
) -> list[StudioSeries]:
    jitter = normalize_raw_point_jitter_fraction(
        render_options.get("raw_point_jitter_fraction", DEFAULT_RAW_POINT_JITTER_FRACTION)
    )
    return [
        replace(
            item,
            x_values=_deterministic_category_positions(float(index), len(item.y_values), fraction=jitter),
            category_position=float(index),
        )
        for index, item in enumerate(series, start=1)
    ]


def _studio_source_for_request(
    source: Path,
    *,
    request: dict[str, Any],
    base_dir: Path,
) -> tuple[Path, list[dict[str, Any]]]:
    rule_id = str(request.get("rule_id") or "").strip()
    if not rule_id:
        return source, []
    from sciplot_core.semantic import classify_source, prepare_semantic_source

    output_dir = base_dir / "studio"
    semantic = classify_source(source, requested_rule_id=rule_id)
    curation_value = request.get("curation")
    curation_path: Path | None = None
    if isinstance(curation_value, str) and curation_value.strip():
        curation_path = Path(curation_value).expanduser()
        if not curation_path.is_absolute():
            curation_path = (base_dir / curation_path).resolve()
    prepared = prepare_semantic_source(
        source,
        output_dir=output_dir,
        semantic=semantic,
        curation_path=curation_path,
        series_order=request.get("series_order"),
        column_confirmations=request.get("column_confirmations"),
        replicate_mode=request.get("replicate_mode"),
    )
    prepared_source = prepared.get("source")
    transform_steps = [step for step in prepared.get("transform_steps", []) if isinstance(step, dict)]
    if isinstance(prepared_source, str) and prepared_source.strip():
        return Path(prepared_source).expanduser(), transform_steps
    return source, transform_steps


def _read_source_frames(source: Path, *, request: dict[str, Any] | None = None) -> list[tuple[str, pd.DataFrame]]:
    files: list[Path]
    if source.is_dir():
        files = [
            path
            for path in sorted(source.rglob("*"))
            if path.is_file() and path.suffix.lower() in {".csv", ".tsv", ".txt", ".xlsx", ".xls"}
        ]
        if _is_rheology_sweep_request(request):
            text_files = [path for path in files if path.suffix.lower() in {".csv", ".tsv", ".txt"}]
            if text_files:
                files = text_files
    elif source.is_file():
        files = [source]
    else:
        raise FileNotFoundError(f"Studio source not found: {source}")
    frames: list[tuple[str, pd.DataFrame]] = []
    for path in files:
        try:
            frames.append((_source_label_from_path(path), _read_table(path)))
        except Exception:
            continue
    if not frames:
        raise ValueError(f"Studio could not read any numeric table from {source}.")
    return frames


def _source_label_from_path(path: Path) -> str:
    stem = path.stem
    if "__" in stem:
        left, right = stem.rsplit("__", maxsplit=1)
        if left == right:
            return right
    return stem


def _read_table(path: Path) -> pd.DataFrame:
    suffix = path.suffix.lower()
    if suffix in {".xlsx", ".xls"}:
        return pd.read_excel(path)
    text = decode_text(path)
    lines = text.splitlines()
    for index, line in enumerate(lines):
        if "Interval data:" in line:
            header = line.split("Interval data:", maxsplit=1)[1].lstrip("\t, ")
            table_text = "\n".join([header, *lines[index + 1 :]])
            return pd.read_csv(StringIO(table_text), sep="\t", engine="python")
    tab_count = text.count("\t")
    comma_count = text.count(",")
    if suffix == ".tsv" or tab_count > comma_count:
        separator: str | None = "\t"
    elif suffix == ".csv" or comma_count:
        separator = ","
    else:
        separator = None
    return pd.read_csv(StringIO(text), sep=separator, engine="python")


def _coerced_numeric_frame(frame: pd.DataFrame) -> pd.DataFrame:
    metadata_rows = _structured_metadata_prefix_rows(frame)
    numeric = frame.iloc[metadata_rows:].apply(
        pd.to_numeric,
        errors="coerce",
    )
    useful_columns = [column for column in numeric.columns if numeric[column].notna().sum() >= 2]
    return numeric[useful_columns].dropna(how="all")


def _structured_metadata_prefix_rows(frame: pd.DataFrame) -> int:
    if frame.shape[0] < 3:
        return 0
    for row_index in range(min(2, frame.shape[0])):
        values = [
            str(value).strip().casefold()
            for value in frame.iloc[row_index].tolist()
            if not pd.isna(value) and str(value).strip()
        ]
        if not values:
            continue
        unit_values = [value for value in values if _is_unit_label(value)]
        nonnumeric_units = [
            value
            for value in unit_values
            if not _is_finite_numeric_text(value)
        ]
        if (
            len(unit_values) >= max(1, math.ceil(len(values) * 0.5))
            and nonnumeric_units
        ):
            return min(2, frame.shape[0])
    return 0


def _is_finite_numeric_text(value: str) -> bool:
    try:
        return math.isfinite(float(value))
    except ValueError:
        return False


def _xy_pairs_for_request(numeric: pd.DataFrame, *, request: dict[str, Any]) -> list[tuple[Any, Any]]:
    metric_pair = _preferred_metric_pair(request)
    if metric_pair is not None:
        x_metric, y_metric = metric_pair
        pairs = _metric_xy_pairs(numeric, x_metric=x_metric, y_metric=y_metric)
        if pairs:
            return pairs
    return _xy_pairs(numeric)


def _xy_pairs(numeric: pd.DataFrame) -> list[tuple[Any, Any]]:
    columns = list(numeric.columns)
    if len(columns) >= 4 and len(columns) % 2 == 0:
        even_columns = columns[0::2]
        odd_columns = columns[1::2]
        if _columns_look_like_repeated_x(even_columns):
            return list(zip(even_columns, odd_columns, strict=True))
    return [(columns[0], column) for column in columns[1:]]


def _columns_look_like_repeated_x(columns: list[Any]) -> bool:
    cleaned = [_clean_column_label(column).split(".")[0].casefold() for column in columns]
    return len(set(cleaned)) == 1 or all(label in {"x", "time", "temperature", "frequency"} for label in cleaned)


def _preferred_metric_pair(request: dict[str, Any]) -> tuple[str, str] | None:
    x_metric = _clean_metric_id(request.get("x_metric"))
    y_metric = _clean_metric_id(request.get("y_metric"))
    study_model = request.get("study_model") if isinstance(request.get("study_model"), dict) else {}
    figure_queue = study_model.get("figure_queue") if isinstance(study_model.get("figure_queue"), list) else []
    if (not x_metric or not y_metric) and figure_queue:
        first_figure = next((item for item in figure_queue if isinstance(item, dict)), {})
        x_metric = x_metric or _clean_metric_id(first_figure.get("x_metric"))
        y_metric = y_metric or _clean_metric_id(first_figure.get("y_metric"))
    rule_id = str(request.get("rule_id") or "").strip()
    if not x_metric or not y_metric:
        if rule_id == "rheology_frequency_sweep":
            x_metric = x_metric or "angular_frequency"
            y_metric = y_metric or "storage_modulus"
        elif rule_id == "rheology_temperature_sweep":
            x_metric = x_metric or "temperature"
            y_metric = y_metric or "storage_modulus"
    if x_metric and y_metric:
        return x_metric, y_metric
    return None


def _clean_metric_id(value: Any) -> str:
    if not isinstance(value, str):
        return ""
    return value.strip().casefold().replace(" ", "_").replace("-", "_")


_METRIC_ALIASES: dict[str, tuple[str, ...]] = {
    "angular_frequency": ("angular frequency", "frequency", "omega"),
    "temperature": ("temperature", "temp"),
    "storage_modulus": ("storage modulus", "g'", "g prime"),
    "loss_modulus": ("loss modulus", 'g"', "g double prime"),
    "loss_factor": ("loss factor", "tan delta", "tan_delta"),
    "complex_modulus": ("complex modulus", "complex shear modulus", "g*"),
    "complex_viscosity": ("complex viscosity", "viscosity"),
}


def _metric_xy_pairs(numeric: pd.DataFrame, *, x_metric: str, y_metric: str) -> list[tuple[Any, Any]]:
    columns = list(numeric.columns)
    x_columns = [column for column in columns if _column_matches_metric(column, x_metric)]
    y_columns = [column for column in columns if _column_matches_metric(column, y_metric)]
    pairs: list[tuple[Any, Any]] = []
    for y_column in y_columns:
        suffix = _duplicate_column_suffix(y_column)
        x_column = next(
            (column for column in x_columns if _duplicate_column_suffix(column) == suffix),
            x_columns[0] if x_columns else None,
        )
        if x_column is not None:
            pairs.append((x_column, y_column))
    return pairs


def _column_matches_metric(column: Any, metric: str) -> bool:
    aliases = _METRIC_ALIASES.get(metric, (metric,))
    label = _normal_metric_label(_column_base_label(column))
    return any(label == _normal_metric_label(alias) for alias in aliases)


def _column_base_label(column: Any) -> str:
    label = _clean_column_label(column)
    if "." in label:
        base, suffix = label.rsplit(".", maxsplit=1)
        if suffix.isdigit():
            return base
    return label


def _duplicate_column_suffix(column: Any) -> str:
    label = _clean_column_label(column)
    if "." in label:
        _base, suffix = label.rsplit(".", maxsplit=1)
        if suffix.isdigit():
            return suffix
    return ""


def _normal_metric_label(label: str) -> str:
    text = label.casefold().replace("′", "'").replace("δ", "delta")
    return "".join(character for character in text if character.isalnum() or character in {"'", '"', "*"})


def _is_rheology_sweep_request(request: dict[str, Any] | None) -> bool:
    if not isinstance(request, dict):
        return False
    return str(request.get("rule_id") or "").strip() in {"rheology_frequency_sweep", "rheology_temperature_sweep"}


def _clean_column_label(column: Any) -> str:
    label = str(column).strip()
    return label or "value"


def _axis_label_from_column(frame: pd.DataFrame, column: Any) -> str:
    label = _clean_column_label(column)
    if column not in frame:
        return label
    unit = _unit_label_from_column(frame[column])
    if not unit or unit.casefold() in label.casefold():
        return label
    return f"{label} ({unit})"


def _unit_label_from_column(values: pd.Series) -> str:
    for value in values.tolist()[:8]:
        if pd.isna(value):
            continue
        text = str(value).strip().strip("[]")
        if not text:
            continue
        try:
            float(text)
            continue
        except ValueError:
            pass
        if text == "PA":
            continue
        if _is_unit_label(text.casefold()):
            return text
    return ""


def _series_label_from_column(values: pd.Series, *, fallback: str) -> str:
    leading = [str(value).strip() for value in values.tolist()[:4] if not pd.isna(value) and str(value).strip()]
    if len(leading) >= 2:
        first_is_unit = _is_unit_label(leading[0].casefold())
        second_is_unit = _is_unit_label(leading[1].casefold())
        if second_is_unit:
            # Comparison workbooks may store the sample label immediately
            # above the unit. Preserve numeric sample IDs and labels such as
            # `PA`, whose case-folded spelling is also the unit `Pa`.
            return leading[0]
        if first_is_unit and not second_is_unit:
            # Semantic tables may store unit first and sample second.
            return leading[1]
    strings: list[str] = []
    for value in values.tolist():
        if pd.isna(value):
            continue
        text = str(value).strip()
        if not text:
            continue
        try:
            float(text)
            continue
        except ValueError:
            strings.append(text)
    for text in reversed(strings):
        lowered = text.casefold()
        if not _is_unit_label(lowered):
            return text
    return fallback


def _is_unit_label(label: str) -> bool:
    unit = label.strip().strip("[]").strip()
    return unit in {
        "1",
        "%",
        "a.u.",
        "au",
        "c",
        "cm^-1",
        "count",
        "degree",
        "degc",
        "hz",
        "kj/m2",
        "min",
        "mins",
        "mv",
        "mn·m",
        "mpa",
        "mpa·s",
        "nm",
        "nm^-1",
        "pa",
        "pa·s",
        "rad/s",
        "s",
        "sec",
        "seconds",
        "um",
        "µm",
        "μm",
        "°c",
        "w/g",
    }


def _apply_series_options(
    series: list[StudioSeries],
    *,
    render_options: dict[str, Any],
    request: dict[str, Any],
) -> list[StudioSeries]:
    include = _string_list(render_options.get("series_include"))
    order = _string_list(render_options.get("series_order")) or _string_list(request.get("series_order"))
    styles = render_options.get("series_styles") if isinstance(render_options.get("series_styles"), list) else []
    palette = _palette_for_render_options(render_options)
    marker_sequence = _string_list(render_options.get("marker_sequence"))
    if not marker_sequence:
        marker_sequence = list(POINT_LINE_MARKERS)
    line_style_sequence = _string_list(render_options.get("line_style_sequence"))
    if not line_style_sequence:
        line_style_sequence = list(DEFAULT_LINE_STYLE_SEQUENCE)
    by_label = {item.label: item for item in series}
    ordered = [by_label[label] for label in order if label in by_label]
    ordered.extend(item for item in series if item.label not in {entry.label for entry in ordered})
    if include:
        include_set = set(include)
        ordered = [item for item in ordered if item.label in include_set]
    style_by_label: dict[str, dict[str, Any]] = {}
    for style in styles:
        if isinstance(style, dict):
            label = style.get("label") or style.get("sample") or style.get("name") or style.get("series_id")
            if isinstance(label, str):
                style_by_label[label] = style
    styled: list[StudioSeries] = []
    template_id = _request_template(request)
    for index, item in enumerate(ordered):
        style = style_by_label.get(item.label, {})
        if style.get("visible") is False or style.get("enabled") is False:
            continue
        default_marker = (
            marker_sequence[index % len(marker_sequence)]
            if (template_id == "point_line" or item.presentation_kind == "categorical_replicates")
            else "none"
        )
        if template_id == "point_line" and len(ordered) > len(marker_sequence):
            default_line_style = line_style_sequence[(index // len(marker_sequence)) % len(line_style_sequence)]
        elif template_id != "point_line" and len(ordered) > 1:
            default_line_style = line_style_sequence[index % len(line_style_sequence)]
        else:
            default_line_style = "solid"
        styled.append(
            StudioSeries(
                label=item.label,
                x_name=item.x_name,
                y_name=item.y_name,
                x_values=item.x_values,
                y_values=item.y_values,
                color=str(style.get("color") or palette[index % len(palette)]),
                line_width=UNIFIED_LINE_WIDTH_PT,
                marker=style.get("marker", item.marker or default_marker),
                marker_size=UNIFIED_MARKER_SIZE_PT,
                line_style=str(style.get("line_style") or style.get("linestyle") or default_line_style),
                presentation_kind=item.presentation_kind,
                category_position=item.category_position,
            )
        )
    return styled or series


def _effective_render_options(request: dict[str, Any]) -> dict[str, Any]:
    template_id = _request_template(request)
    merged: dict[str, Any] = {}
    try:
        from sciplot_core.contract import load_plot_contract

        contract = load_plot_contract()
        template = contract.templates.get(template_id)
        if template is not None:
            merged.update(template.default_options)
    except Exception:
        if template_id == "stacked_curve":
            merged.update({"series_label_mode": "inline", "baseline": "none", "reverse_x": False})

    if isinstance(request.get("render_options"), dict):
        merged.update(request["render_options"])
    return merged


def _palette_for_render_options(render_options: dict[str, Any]) -> tuple[str, ...]:
    explicit_palette = _string_list(render_options.get("palette_colors"))
    if explicit_palette:
        return tuple(explicit_palette)
    palette_id = str(render_options.get("palette_preset") or DEFAULT_PALETTE_PRESET)
    try:
        from sciplot_core.contract import load_plot_contract

        contract = load_plot_contract()
        palette = contract.palettes.get(palette_id)
        if palette is not None and palette.categorical:
            return tuple(str(color) for color in palette.categorical)
    except Exception:
        return DEFAULT_PALETTE
    return DEFAULT_PALETTE


def _veusz_style_contract(render_options: dict[str, Any]) -> _VeuszStyleContract:
    style_id = str(render_options.get("style_preset") or "nature")
    try:
        from sciplot_core.contract import load_plot_contract, normalize_style_alias

        contract = load_plot_contract()
        style = contract.styles.get(normalize_style_alias(style_id))
        if style is None:
            return _VeuszStyleContract()
        base = _VeuszStyleContract(
            # Typography and physical strokes are deliberately not read from
            # template/style overrides.  They are the project-wide hard
            # contract; style presets remain only for semantic/layout
            # compatibility and palette/theme selection.
            font_family=UNIFIED_FONT_FAMILY,
            font_size_pt=UNIFIED_FONT_SIZE_PT,
            legend_font_size_pt=UNIFIED_LEGEND_FONT_SIZE_PT,
            axis_linewidth_pt=UNIFIED_AXIS_LINEWIDTH_PT,
            tick_width_pt=UNIFIED_TICK_WIDTH_PT,
            tick_length_pt=UNIFIED_TICK_LENGTH_PT,
            minor_tick_width_pt=UNIFIED_MINOR_TICK_WIDTH_PT,
            minor_tick_length_pt=UNIFIED_MINOR_TICK_LENGTH_PT,
            line_width_pt=UNIFIED_LINE_WIDTH_PT,
            line_alpha=float(style.stroke.line_alpha),
            marker_alpha=float(style.stroke.marker_alpha),
            marker_size_pt=UNIFIED_MARKER_SIZE_PT,
            marker_line_width_pt=UNIFIED_MARKER_LINE_WIDTH_PT,
            axes_labelpad_pt=float(style.spacing.axes_labelpad),
            xtick_major_pad_pt=float(style.spacing.xtick_major_pad),
            ytick_major_pad_pt=float(style.spacing.ytick_major_pad),
            legend_inset_fraction=float(style.spacing.legend_inset_fraction),
            legend_frameon=bool(style.annotation.legend_frameon),
            left_margin_mm=float(contract.global_frame.left_margin_mm),
            right_margin_mm=float(contract.global_frame.right_margin_mm),
            bottom_margin_mm=float(contract.global_frame.bottom_margin_mm),
            top_margin_mm=float(contract.global_frame.top_margin_mm),
        )
    except Exception:
        base = _VeuszStyleContract()
    # Explicit request-level typography/stroke values are intentionally
    # ignored.  Veusz editing remains available after generation, but every
    # generated template starts from the same SciPlot hard standard.
    return base


def _apply_domain_render_defaults(
    render_options: dict[str, Any],
    *,
    request: dict[str, Any],
    axis_info: dict[str, Any],
) -> dict[str, Any]:
    updated = dict(render_options)
    explicit_options = request.get("render_options") if isinstance(request.get("render_options"), dict) else {}
    template_id = _request_template(request)
    category_positions = axis_info.get("category_positions")
    if template_id == "point_line":
        for key, value in POINT_LINE_RENDER_OPTIONS.items():
            if key not in explicit_options:
                updated[key] = list(value) if isinstance(value, list) else value
    if template_id in CATEGORICAL_TEMPLATE_IDS and isinstance(category_positions, list) and category_positions:
        for key, value in CATEGORICAL_DISTRIBUTION_RENDER_OPTIONS.items():
            if key not in explicit_options:
                updated[key] = list(value) if isinstance(value, list) else value
        updated["summary_statistic"] = normalize_categorical_summary(
            updated.get("summary_statistic") or DEFAULT_CATEGORICAL_SUMMARY
        )
        updated["raw_point_jitter_fraction"] = normalize_raw_point_jitter_fraction(
            updated.get("raw_point_jitter_fraction", DEFAULT_RAW_POINT_JITTER_FRACTION)
        )
        updated.setdefault("x_min", float(min(category_positions)) - 0.5)
        updated.setdefault("x_max", float(max(category_positions)) + 0.5)
        updated.setdefault("x_ticks", list(category_positions))
        updated.setdefault("x_label_override", "Sample")
        updated.setdefault("legend_position", "none")
        updated.setdefault("series_label_mode", "none")
        if str(request.get("rule_id") or "").strip() == "impact_metric":
            category_labels = [str(value) for value in axis_info.get("category_labels") or []]
            thickness_labels = bool(category_labels) and all(
                re.fullmatch(r".+?\s+\(\d+(?:\.\d+)?\s*mm\)", label, flags=re.IGNORECASE)
                or re.fullmatch(r".+?/\d+(?:\.\d+)?", label)
                for label in category_labels
            )
            if thickness_labels:
                updated["x_label_override"] = "Sample / thickness (mm)"
            if "y_label_override" not in explicit_options:
                updated["y_label_override"] = "Impact strength (kJ/m²)"
    if template_id in STACKED_TEMPLATE_IDS and _looks_like_wavenumber_axis(axis_info):
        label_mode = str(updated.get("series_label_mode") or "").strip().casefold()
        legend_position = str(updated.get("legend_position") or "").strip().casefold()
        domain_defaults: dict[str, Any] = {
            "reverse_x": True,
            "x_min": 400.0,
            "x_max": 4000.0,
            "baseline": "linear_endpoints",
            "series_label_side": "left",
            "show_y_ticks": False,
            "x_label_override": "Wavenumber (cm^-1)",
            "y_label_override": "Absorbance (offset)",
            "size": "120x110",
        }
        for key, value in domain_defaults.items():
            if key not in explicit_options:
                updated[key] = value
        if legend_position in {"", "auto", "none", "hide", "hidden", "off"}:
            updated["legend_position"] = "none"
        if label_mode in {"", "auto", "legend", "inline", "edge"}:
            updated["series_label_mode"] = "inline"
    if _looks_like_torque_axis(axis_info) or str(request.get("rule_id") or "").strip() == "torque_curve":
        x_label = str(updated.get("x_label_override") or "").strip().casefold()
        if x_label in {"", "time"}:
            updated["x_label_override"] = "Time (s)"
        y_label = str(updated.get("y_label_override") or "").strip().casefold()
        if y_label in {"", "screw torque", "torque"}:
            updated["y_label_override"] = "Screw torque (N·m)"
        updated.setdefault("stack_spacing_scale", 0.05)
        if str(updated.get("series_label_mode") or "").casefold() in {"", "auto", "inline"}:
            updated["series_label_mode"] = "legend"
    if _looks_like_frequency_axis(axis_info):
        updated.setdefault("xscale", "log")
        metric_label = next(
            (
                label
                for candidate in (
                    updated.get("y_metric"),
                    request.get("y_metric"),
                    updated.get("y_label_override"),
                    axis_info.get("y_label"),
                )
                if (label := rheology_metric_axis_label(candidate)) is not None
            ),
            None,
        )
        rule_id = str(request.get("rule_id") or "").strip()
        rheology_frequency = rule_id == "rheology_frequency_sweep" or metric_label is not None
        x_axis_text = str(axis_info.get("x_label") or "").casefold()
        if rheology_frequency or "angular" in x_axis_text or "rad" in x_axis_text:
            updated.setdefault("x_label_override", RHEOLOGY_FREQUENCY_X_RENDER_LABEL)
        if rheology_frequency:
            updated.setdefault("yscale", "log")
            updated.setdefault("x_tick_format", DEFAULT_LOG_TICK_FORMAT)
            updated.setdefault("y_tick_format", DEFAULT_LOG_TICK_FORMAT)
            if "y_label_override" not in explicit_options and metric_label is not None:
                updated["y_label_override"] = metric_label
    if _looks_like_tensile_axis(axis_info):
        if "x_label_override" not in explicit_options:
            updated["x_label_override"] = "Tensile Strain (%)"
        if "y_label_override" not in explicit_options:
            updated["y_label_override"] = "Tensile Stress (MPa)"
        updated.setdefault("axis_mode", "auto_positive")
    if str(request.get("rule_id") or "").strip() == "rheology_stress_relaxation":
        updated.setdefault("x_label_override", "Time (s)")
        updated.setdefault("y_label_override", "Normalized stress (\\sigma/\\sigma_0)")
    if str(request.get("rule_id") or "").strip() == "gpc_sec_chromatogram":
        detected_y_label = str(axis_info.get("y_label") or "").strip()
        requested_y_label = str(updated.get("y_label_override") or "").strip().casefold()
        if detected_y_label and requested_y_label in {"", "detector response", "detector response (a.u.)"}:
            updated["y_label_override"] = detected_y_label
    return updated


def _explicit_render_options(request: dict[str, Any]) -> dict[str, Any]:
    options = request.get("render_options") if isinstance(request.get("render_options"), dict) else {}
    explicit_keys = request.get("explicit_render_option_keys")
    if not isinstance(explicit_keys, list | tuple | set):
        return options
    return {str(key): options[str(key)] for key in explicit_keys if str(key) in options}


def _label_load(series: list[StudioSeries]) -> dict[str, int]:
    labels = [str(item.label) for item in series]
    return {
        "series_count": len(labels),
        "max_label_length": max((len(label) for label in labels), default=0),
        "total_label_length": sum(len(label) for label in labels),
        "duplicate_count": len(labels) - len(set(labels)),
    }


def _compact_replicate_series_labels(
    series: list[StudioSeries],
) -> tuple[list[StudioSeries], list[dict[str, str]]]:
    """Drop a shared leading descriptor while retaining sample and repeat identity."""

    pattern = re.compile(
        r"^(?P<prefix>.+?)\s+(?P<kind>repeat|replicate|specimen)\s+(?P<index>\d+)$",
        flags=re.IGNORECASE,
    )
    matches = [pattern.fullmatch(str(item.label).strip()) for item in series]
    if len(series) < 5 or any(match is None for match in matches):
        return series, []
    parsed = [match for match in matches if match is not None]
    prefixes = {match.group("prefix").casefold() for match in parsed}
    kinds = {match.group("kind").casefold() for match in parsed}
    if len(prefixes) != 1 or len(kinds) != 1:
        return series, []

    prefix = parsed[0].group("prefix").strip()
    tokens = prefix.split()
    acronym_index = next(
        (
            index
            for index, token in enumerate(tokens)
            if sum(character.isupper() for character in token) >= 2
        ),
        None,
    )
    compact_prefix = " ".join(tokens[acronym_index:]) if acronym_index is not None else prefix
    if "_" in compact_prefix:
        identifier_parts = [part for part in compact_prefix.split("_") if part]
        if len(identifier_parts) > 1 and len(identifier_parts[-1]) <= 8:
            compact_prefix = identifier_parts[-1]
    if len(compact_prefix) >= len(prefix):
        return series, []
    compacted_labels = [
        f"{compact_prefix} {'s' if match.group('kind').casefold() == 'specimen' else 'r'}{match.group('index')}"
        for match in parsed
    ]
    if len(set(compacted_labels)) != len(compacted_labels):
        return series, []
    mapping = [
        {"source_label": item.label, "display_label": display}
        for item, display in zip(series, compacted_labels, strict=True)
    ]
    return [
        replace(item, label=display)
        for item, display in zip(series, compacted_labels, strict=True)
    ], mapping


def _legend_is_dense(series: list[StudioSeries]) -> bool:
    load = _label_load(series)
    return (
        load["series_count"] > 8
        or load["max_label_length"] >= 15
        or load["total_label_length"] >= 90
        or load["duplicate_count"] >= 4
    )


def _wide_size_for_dense_legend(series: list[StudioSeries]) -> str:
    load = _label_load(series)
    if load["series_count"] > 16 or load["total_label_length"] >= 150:
        return "180x55"
    return "120x55"


def _legend_axis_bounds(
    series: list[StudioSeries],
    render_options: dict[str, Any],
    axis: str,
    *,
    axis_contract: _VeuszAxisContract | None = None,
) -> tuple[float, float, str] | None:
    values = [
        float(value)
        for item in series
        for value in (item.x_values if axis == "x" else item.y_values)
        if math.isfinite(float(value))
    ]
    scale = _axis_scale(render_options, axis)
    if scale == "log":
        values = [value for value in values if value > 0]
    if not values:
        return None
    if axis_contract is not None:
        minimum = _optional_float(getattr(axis_contract, f"{axis}_min"))
        maximum = _optional_float(getattr(axis_contract, f"{axis}_max"))
        if minimum is not None and maximum is not None and not math.isclose(minimum, maximum):
            if scale == "log":
                if minimum <= 0.0 or maximum <= 0.0:
                    return None
                return math.log10(minimum), math.log10(maximum), scale
            return minimum, maximum, scale
    minimum = _optional_float(render_options.get(f"{axis}_min"))
    maximum = _optional_float(render_options.get(f"{axis}_max"))
    minimum = min(values) if minimum is None else minimum
    maximum = max(values) if maximum is None else maximum
    if scale == "log":
        ticks = anchored_log_decade_ticks(values)
        if ticks:
            minimum = min(minimum, ticks[0])
            maximum = max(maximum, ticks[-1])
        if minimum <= 0 or maximum <= minimum:
            return None
        return math.log10(minimum), math.log10(maximum), scale
    if maximum <= minimum:
        return None
    padding = (maximum - minimum) * 0.05
    return minimum - padding, maximum + padding, scale


def _legend_curve_samples(
    series: list[StudioSeries],
    render_options: dict[str, Any],
    *,
    axis_contract: _VeuszAxisContract | None = None,
) -> list[tuple[float, float]]:
    x_bounds = _legend_axis_bounds(series, render_options, "x", axis_contract=axis_contract)
    y_bounds = _legend_axis_bounds(series, render_options, "y", axis_contract=axis_contract)
    if x_bounds is None or y_bounds is None:
        return []
    x_low, x_high, x_scale = x_bounds
    y_low, y_high, y_scale = y_bounds

    def normalized(value: float, low: float, high: float, scale: str) -> float | None:
        if scale == "log":
            if value <= 0:
                return None
            value = math.log10(value)
        return (value - low) / (high - low)

    samples: list[tuple[float, float]] = []
    for item in series:
        points: list[tuple[float, float]] = []
        for x_value, y_value in zip(item.x_values, item.y_values, strict=True):
            x_norm = normalized(float(x_value), x_low, x_high, x_scale)
            y_norm = normalized(float(y_value), y_low, y_high, y_scale)
            if x_norm is None or y_norm is None:
                continue
            if math.isfinite(x_norm) and math.isfinite(y_norm) and 0.0 <= x_norm <= 1.0 and 0.0 <= y_norm <= 1.0:
                points.append((x_norm, y_norm))
        for index, point in enumerate(points):
            samples.append(point)
            if index == 0:
                continue
            previous = points[index - 1]
            for step in range(1, 5):
                fraction = step / 5.0
                samples.append(
                    (
                        previous[0] + (point[0] - previous[0]) * fraction,
                        previous[1] + (point[1] - previous[1]) * fraction,
                    )
                )
    return samples


def _legend_footprint(
    series: list[StudioSeries],
    render_options: dict[str, Any],
) -> dict[str, float | int]:
    """Estimate Veusz's graph-local key box in final physical units."""

    style = _veusz_style_contract(render_options)
    width_mm, height_mm = _size_mm(str(render_options.get("size") or "60x55"))
    graph_width_mm = max(float(width_mm) - style.left_margin_mm - style.right_margin_mm, 1.0)
    graph_height_mm = max(float(height_mm) - style.top_margin_mm - style.bottom_margin_mm, 1.0)
    load = _label_load(series)
    columns = _legend_columns(
        series_count=load["series_count"],
        mode="inside_best",
        max_label_length=load["max_label_length"],
        figure_width_mm=float(width_mm),
    )
    rows = max(1, math.ceil(load["series_count"] / columns))
    point_to_mm = 25.4 / 72.0
    font_height_mm = max(style.legend_font_size_pt * 1.2 * point_to_mm, 0.1)
    max_text_width_mm = max(load["max_label_length"] * style.legend_font_size_pt * 0.56 * point_to_mm, 0.2)
    key_length_mm = 4.0
    box_width_mm = (max_text_width_mm + font_height_mm + key_length_mm) * columns + font_height_mm * (columns - 1)
    box_height_mm = rows * font_height_mm
    if style.legend_frameon:
        margin_mm = 0.15 * font_height_mm
        box_width_mm += 2.0 * margin_mm
        box_height_mm += margin_mm
    return {
        "columns": columns,
        "rows": rows,
        "font_height_mm": font_height_mm,
        "graph_width_mm": graph_width_mm,
        "graph_height_mm": graph_height_mm,
        "box_width_mm": min(box_width_mm, graph_width_mm * 0.92),
        "box_height_mm": min(box_height_mm, graph_height_mm * 0.82),
    }


def _point_rectangle_distance_mm(
    point: tuple[float, float],
    rectangle: tuple[float, float, float, float],
    *,
    graph_width_mm: float,
    graph_height_mm: float,
) -> float:
    x_value, y_value = point
    left, right, bottom, top = rectangle
    dx = max(left - x_value, 0.0, x_value - right) * graph_width_mm
    dy = max(bottom - y_value, 0.0, y_value - top) * graph_height_mm
    return math.hypot(dx, dy)


def _auto_inside_legend_placement(
    series: list[StudioSeries],
    render_options: dict[str, Any],
    *,
    template_id: str,
) -> dict[str, Any]:
    axis_contract = _veusz_axis_contract(render_options, template_id=template_id, series=series)
    samples = _legend_curve_samples(series, render_options, axis_contract=axis_contract)
    footprint = _legend_footprint(series, render_options)
    graph_width_mm = float(footprint["graph_width_mm"])
    graph_height_mm = float(footprint["graph_height_mm"])
    width = float(footprint["box_width_mm"]) / graph_width_mm
    height = float(footprint["box_height_mm"]) / graph_height_mm
    edge_padding_mm = max(
        0.0,
        _optional_float(render_options.get("legend_edge_padding_mm")) or DEFAULT_LEGEND_EDGE_PADDING_MM,
    )
    horizontal_pad = min(edge_padding_mm / graph_width_mm, max(0.0, 1.0 - width))
    vertical_pad = min(edge_padding_mm / graph_height_mm, max(0.0, 1.0 - height))
    candidates = {
        "upper_right": (
            1.0 - horizontal_pad - width,
            1.0 - horizontal_pad,
            1.0 - vertical_pad - height,
            1.0 - vertical_pad,
        ),
        "lower_right": (
            1.0 - horizontal_pad - width,
            1.0 - horizontal_pad,
            vertical_pad,
            vertical_pad + height,
        ),
        "upper_left": (
            horizontal_pad,
            horizontal_pad + width,
            1.0 - vertical_pad - height,
            1.0 - vertical_pad,
        ),
        "lower_left": (horizontal_pad, horizontal_pad + width, vertical_pad, vertical_pad + height),
    }
    clearance_mm = max(
        0.0,
        _optional_float(render_options.get("legend_curve_clearance_mm")) or DEFAULT_LEGEND_CURVE_CLEARANCE_MM,
    )
    order = ("upper_right", "lower_right", "upper_left", "lower_left")
    metrics: dict[str, dict[str, Any]] = {}
    for name, rectangle in candidates.items():
        distances = [
            _point_rectangle_distance_mm(
                point,
                rectangle,
                graph_width_mm=graph_width_mm,
                graph_height_mm=graph_height_mm,
            )
            for point in samples
        ]
        minimum = min(distances, default=float("inf"))
        overlaps = sum(distance <= 1e-9 for distance in distances)
        near = sum(distance < clearance_mm for distance in distances)
        proximity_load = sum(
            (clearance_mm - distance) / clearance_mm
            for distance in distances
            if clearance_mm > 0.0 and distance < clearance_mm
        )
        metrics[name] = {
            "rectangle_fraction": [round(value, 6) for value in rectangle],
            "overlap_samples": overlaps,
            "near_samples": near,
            "minimum_curve_clearance_mm": None if not math.isfinite(minimum) else round(minimum, 6),
            "clearance_deficit_mm": (0.0 if not math.isfinite(minimum) else round(max(clearance_mm - minimum, 0.0), 6)),
            "proximity_load": round(proximity_load, 6),
        }

    def score(name: str) -> tuple[Any, ...]:
        item = metrics[name]
        minimum = item["minimum_curve_clearance_mm"]
        safe = minimum is None or float(minimum) >= clearance_mm
        return (
            int(item["overlap_samples"] > 0),
            int(item["overlap_samples"]),
            int(not safe),
            float(item["proximity_load"]),
            float(item["clearance_deficit_mm"]),
            -(float(minimum) if minimum is not None else float("inf")),
            order.index(name),
        )

    selected = min(order, key=score) if samples else "lower_right"
    selected_metrics = metrics[selected]
    minimum = selected_metrics["minimum_curve_clearance_mm"]
    return {
        "position": selected,
        "method": "final_size_physical_clearance_v1",
        "required_curve_clearance_mm": clearance_mm,
        "edge_padding_mm": edge_padding_mm,
        "minimum_curve_clearance_mm": minimum,
        "clearance_status": (
            "safe" if minimum is None or float(minimum) >= clearance_mm else "best_available_needs_reserve"
        ),
        "footprint": {key: round(float(value), 6) for key, value in footprint.items()},
        "candidates": metrics,
    }


def _legend_placement_on_vertical_side(
    placement: dict[str, Any],
    *,
    lower: bool,
) -> dict[str, Any]:
    """Keep reserve iterations on the side whose axis bound is being expanded."""

    order = ("lower_right", "lower_left") if lower else ("upper_right", "upper_left")
    metrics = placement.get("candidates") if isinstance(placement.get("candidates"), dict) else {}
    required = _optional_float(placement.get("required_curve_clearance_mm")) or 0.0

    def score(name: str) -> tuple[Any, ...]:
        item = metrics.get(name) if isinstance(metrics.get(name), dict) else {}
        minimum = _optional_float(item.get("minimum_curve_clearance_mm"))
        overlap = int(item.get("overlap_samples") or 0)
        safe = minimum is None or minimum >= required
        return (
            int(overlap > 0),
            overlap,
            int(not safe),
            float(item.get("proximity_load") or 0.0),
            float(item.get("clearance_deficit_mm") or 0.0),
            -(minimum if minimum is not None else float("inf")),
            order.index(name),
        )

    selected = min(order, key=score)
    selected_metrics = metrics.get(selected) if isinstance(metrics.get(selected), dict) else {}
    minimum = _optional_float(selected_metrics.get("minimum_curve_clearance_mm"))
    revised = dict(placement)
    revised["position"] = selected
    revised["minimum_curve_clearance_mm"] = minimum
    revised["clearance_status"] = "safe" if minimum is None or minimum >= required else "best_available_needs_reserve"
    return revised


def _reserve_vertical_legend_clearance(
    render_options: dict[str, Any],
    *,
    request: dict[str, Any],
    series: list[StudioSeries],
    template_id: str,
    placement: dict[str, Any],
) -> tuple[dict[str, Any], dict[str, Any]]:
    position = str(placement.get("position") or "")
    if position not in {"lower_left", "lower_right", "upper_left", "upper_right"}:
        return render_options, placement
    required = _optional_float(placement.get("required_curve_clearance_mm")) or 0.0
    initial_minimum = _optional_float(placement.get("minimum_curve_clearance_mm"))
    if initial_minimum is None or initial_minimum >= required:
        return render_options, placement
    lower = position.startswith("lower")
    bound_key = "y_min" if lower else "y_max"
    if bound_key in _explicit_render_options(request):
        return render_options, placement
    graph_height_mm = max(float(placement["footprint"]["graph_height_mm"]), 1.0)
    scale = _axis_scale(render_options, "y")
    updated = dict(render_options)
    revised = placement
    original_bound: float | None = None
    total_reserve = 0.0
    for _attempt in range(MAX_LEGEND_RESERVE_ITERATIONS):
        minimum = _optional_float(revised.get("minimum_curve_clearance_mm"))
        if minimum is None or minimum >= required:
            break
        axis_contract = _veusz_axis_contract(updated, template_id=template_id, series=series)
        y_min = axis_contract.y_min
        y_max = axis_contract.y_max
        if y_min is None or y_max is None or y_max <= y_min:
            break
        if original_bound is None:
            original_bound = y_min if lower else y_max
        deficit_mm = required - minimum
        previous_bound = updated.get(bound_key)
        if scale == "log":
            if y_min <= 0.0:
                break
            span = math.log10(y_max) - math.log10(y_min)
            increment = min(
                MAX_LOG_LEGEND_RESERVE_DECADES - total_reserve,
                max(0.005, deficit_mm / graph_height_mm * span * 1.5),
            )
            if increment <= 0.0:
                break
            if lower:
                updated["y_min"] = 10.0 ** (math.log10(y_min) - increment)
            else:
                updated["y_max"] = 10.0 ** (math.log10(y_max) + increment)
        else:
            span = y_max - y_min
            maximum_total = span * MAX_LINEAR_LEGEND_RESERVE_FRACTION
            increment = min(
                maximum_total - total_reserve,
                max(span * 0.005, deficit_mm / graph_height_mm * span * 1.5),
            )
            if increment <= 0.0:
                break
            if lower:
                updated["y_min"] = y_min - increment
            else:
                updated["y_max"] = y_max + increment
        candidate = _legend_placement_on_vertical_side(
            _auto_inside_legend_placement(series, updated, template_id=template_id),
            lower=lower,
        )
        candidate_minimum = _optional_float(candidate.get("minimum_curve_clearance_mm"))
        current_metrics = revised.get("candidates", {}).get(str(revised.get("position") or ""), {})
        candidate_metrics = candidate.get("candidates", {}).get(str(candidate.get("position") or ""), {})
        current_overlap = int(current_metrics.get("overlap_samples") or 0)
        candidate_overlap = int(candidate_metrics.get("overlap_samples") or 0)
        current_load = float(current_metrics.get("proximity_load") or 0.0)
        candidate_load = float(candidate_metrics.get("proximity_load") or 0.0)
        candidate_improved = candidate_minimum is not None and (
            candidate_minimum > minimum + 1e-6
            or candidate_overlap < current_overlap
            or (candidate_overlap == current_overlap and candidate_load < current_load - 1e-6)
        )
        if not candidate_improved:
            if previous_bound is None:
                updated.pop(bound_key, None)
            else:
                updated[bound_key] = previous_bound
            break
        total_reserve += increment
        revised = candidate
    revised_minimum = _optional_float(revised.get("minimum_curve_clearance_mm"))
    if original_bound is None or revised_minimum is None or revised_minimum <= initial_minimum + 1e-6:
        return render_options, placement
    revised["axis_reserve"] = {
        "side": "bottom" if lower else "top",
        "original_bound": original_bound,
        "revised_bound": updated[bound_key],
        "scale": scale,
        **({"decades": round(total_reserve, 6)} if scale == "log" else {"axis_units": round(total_reserve, 6)}),
    }
    return updated, revised


def _marker_thin_factor(item: StudioSeries, *, template_id: str) -> int:
    """Keep point-line markers legible while preserving every line sample."""

    marker = str(item.marker or "none").strip().casefold()
    if template_id != "point_line" or marker == "none" or item.presentation_kind == "categorical_replicates":
        return 1
    point_count = min(len(item.x_values), len(item.y_values))
    return max(1, math.ceil(point_count / MAX_POINT_LINE_MARKERS_PER_SERIES))


def _apply_readability_render_defaults(
    render_options: dict[str, Any],
    *,
    request: dict[str, Any],
    axis_info: dict[str, Any],
    series: list[StudioSeries],
    template_id: str,
) -> dict[str, Any]:
    updated = dict(render_options)
    explicit_options = _explicit_render_options(request)
    label_mode = str(updated.get("series_label_mode") or "legend").strip().casefold()
    raw_legend_position = updated.get("legend_position")
    legend_position = normalize_legend_position(raw_legend_position)
    autofixes = _string_list(updated.get("_autofixes_applied"))
    temperature_axis_text = " ".join(
        str(value or "")
        for value in (
            request.get("rule_id"),
            updated.get("x_metric"),
            updated.get("x_label_override"),
            axis_info.get("x_label"),
        )
    ).casefold()
    if (
        "temperature" in temperature_axis_text
        and _axis_scale(updated, "x") == "linear"
        and not {"x_min", "x_max", "x_ticks"} & explicit_options.keys()
    ):
        compact_axis = compact_linear_axis(value for item in series for value in item.x_values if math.isfinite(value))
        if compact_axis is not None:
            x_min, x_max, x_ticks = compact_axis
            updated.update({"x_min": x_min, "x_max": x_max, "x_ticks": list(x_ticks)})
            autofixes.append("temperature_axis_compacted")
    if (
        str(request.get("rule_id") or "").strip() == "tga_curve"
        and _axis_scale(updated, "y") == "linear"
        and not {"y_min", "y_max", "y_ticks"} & explicit_options.keys()
    ):
        compact_axis = compact_linear_axis(value for item in series for value in item.y_values if math.isfinite(value))
        if compact_axis is not None:
            y_min, y_max, y_ticks = compact_axis
            updated.update({"y_min": y_min, "y_max": y_max, "y_ticks": list(y_ticks)})
            autofixes.append("tga_mass_axis_compacted")
    if str(request.get("rule_id") or "").strip() == "gpc_sec_chromatogram":
        if _axis_scale(updated, "x") == "linear" and not {"x_min", "x_max", "x_ticks"} & explicit_options.keys():
            compact_axis = compact_linear_axis(
                value for item in series for value in item.x_values if math.isfinite(value)
            )
            if compact_axis is not None:
                x_min, x_max, x_ticks = compact_axis
                updated.update({"x_min": x_min, "x_max": x_max, "x_ticks": list(x_ticks)})
                autofixes.append("gpc_elution_axis_compacted")
        if _axis_scale(updated, "y") == "linear" and not {"y_min", "y_max", "y_ticks"} & explicit_options.keys():
            compact_axis = compact_linear_axis(
                value for item in series for value in item.y_values if math.isfinite(value)
            )
            if compact_axis is not None:
                y_min, y_max, y_ticks = compact_axis
                updated.update({"y_min": y_min, "y_max": y_max, "y_ticks": list(y_ticks)})
                autofixes.append("gpc_response_axis_compacted")
    if is_removed_outside_legend_position(raw_legend_position):
        updated["legend_position"] = "auto"
        for key in ("legend_horz_position", "legend_vert_position", "legend_horz_manual", "legend_vert_manual"):
            updated.pop(key, None)
        autofixes.append("legend_outside_removed")

    if template_id in STACKED_TEMPLATE_IDS:
        if _looks_like_wavenumber_axis(axis_info):
            y_label = str(updated.get("y_label_override") or axis_info.get("y_label") or "").strip()
            if len(series) == 1 and str(updated.get("baseline") or "none").casefold() == "none":
                updated["show_y_ticks"] = True
                if not {"y_min", "y_max", "y_ticks"} & explicit_options.keys():
                    compact_axis = compact_linear_axis(
                        value for item in series for value in item.y_values if math.isfinite(value)
                    )
                    if compact_axis is not None:
                        y_min, y_max, y_ticks = compact_axis
                        updated.update({"y_min": y_min, "y_max": y_max, "y_ticks": list(y_ticks)})
                        autofixes.append("single_spectrum_y_axis_compacted")
                autofixes.append("single_spectrum_raw_y_scale")
            elif len(series) > 1:
                updated["show_y_ticks"] = False
                if "transmittance" in y_label.casefold():
                    updated["y_label_override"] = "Transmittance (offset)"
                elif "absorbance" in y_label.casefold() and "offset" not in y_label.casefold():
                    updated["y_label_override"] = "Absorbance (offset)"
        if label_mode in {"inline", "edge", "auto"} and len(series) > 1:
            updated.setdefault("series_label_offset_fraction", 0.018)
            updated.setdefault("series_label_vertical_align", "bottom")
            autofixes.append("direct_label_offset")
        if autofixes:
            updated["_autofixes_applied"] = sorted(set(autofixes))
        return updated
    if template_id in CATEGORICAL_TEMPLATE_IDS:
        if autofixes:
            updated["_autofixes_applied"] = sorted(set(autofixes))
        return updated

    if legend_position in {"", "auto"} and label_mode in {"", "auto", "legend"}:
        if _legend_is_dense(series) and "size" not in explicit_options:
            updated["size"] = _wide_size_for_dense_legend(series)
            autofixes.append("legend_auto_widened_inside")
        if _looks_like_torque_axis(axis_info) or str(request.get("rule_id") or "").strip() == "torque_curve":
            updated["legend_position"] = "upper_right"
            updated["series_label_mode"] = "legend"
            autofixes.append("legend_auto_upper_right")
        else:
            placement = _auto_inside_legend_placement(series, updated, template_id=template_id)
            updated, placement = _reserve_vertical_legend_clearance(
                updated,
                request=request,
                series=series,
                template_id=template_id,
                placement=placement,
            )
            position = str(placement["position"])
            updated["legend_position"] = position
            updated["series_label_mode"] = "legend"
            updated["_legend_placement_diagnostics"] = placement
            if isinstance(placement.get("axis_reserve"), dict):
                autofixes.append(f"legend_axis_reserve_{placement['axis_reserve']['side']}")
            footprint = placement["footprint"]
            graph_width_mm = max(float(footprint["graph_width_mm"]), 1.0)
            graph_height_mm = max(float(footprint["graph_height_mm"]), 1.0)
            box_width_mm = min(float(footprint["box_width_mm"]), graph_width_mm)
            box_height_mm = min(float(footprint["box_height_mm"]), graph_height_mm)
            edge_padding_mm = max(float(placement.get("edge_padding_mm") or 0.0), 0.0)
            horizontal_pad = min(edge_padding_mm / graph_width_mm, max(0.0, 1.0 - box_width_mm / graph_width_mm))
            vertical_pad = min(edge_padding_mm / graph_height_mm, max(0.0, 1.0 - box_height_mm / graph_height_mm))
            updated["legend_horz_position"] = "manual"
            updated["legend_vert_position"] = "manual"
            updated["legend_horz_manual"] = (
                horizontal_pad
                if position.endswith("left")
                else max(0.0, 1.0 - horizontal_pad - box_width_mm / graph_width_mm)
            )
            updated["legend_vert_manual"] = (
                vertical_pad
                if position.startswith("lower")
                else max(0.0, 1.0 - vertical_pad - box_height_mm / graph_height_mm)
            )
            placement["manual_anchor_fraction"] = {
                "x": round(float(updated["legend_horz_manual"]), 6),
                "y": round(float(updated["legend_vert_manual"]), 6),
            }
            autofixes.append("legend_corner_edge_reclaimed")
            autofixes.append(f"legend_auto_{position}")

    if autofixes:
        updated["_autofixes_applied"] = sorted(set(autofixes))
    return updated


def _apply_template_series_transforms(
    series: list[StudioSeries],
    *,
    request: dict[str, Any],
    render_options: dict[str, Any],
) -> list[StudioSeries]:
    transformed = series
    baseline_mode = str(render_options.get("baseline") or "none").strip().casefold()
    if baseline_mode != "none":
        transformed = [_baseline_correct_series(item) for item in transformed]
    if _request_template(request) in STACKED_TEMPLATE_IDS:
        transformed = _stack_studio_series(transformed, render_options=render_options)
    return transformed


def _baseline_correct_series(item: StudioSeries) -> StudioSeries:
    x_values = item.x_values
    y_values = item.y_values
    valid_indexes = [
        index
        for index, (x_value, y_value) in enumerate(zip(x_values, y_values, strict=True))
        if math.isfinite(x_value) and math.isfinite(y_value)
    ]
    if len(valid_indexes) < 3:
        return item

    n_edge = max(3, min(len(valid_indexes) // 12, 30))
    start_indexes = valid_indexes[:n_edge]
    end_indexes = valid_indexes[-n_edge:]
    x_start = _mean(x_values[index] for index in start_indexes)
    y_start = _mean(y_values[index] for index in start_indexes)
    x_end = _mean(x_values[index] for index in end_indexes)
    y_end = _mean(y_values[index] for index in end_indexes)
    if math.isclose(x_start, x_end):
        corrected = tuple(y_value - y_start if math.isfinite(y_value) else y_value for y_value in y_values)
    else:
        slope = (y_end - y_start) / (x_end - x_start)
        corrected = tuple(
            y_value - (y_start + slope * (x_value - x_start))
            if math.isfinite(x_value) and math.isfinite(y_value)
            else y_value
            for x_value, y_value in zip(x_values, y_values, strict=True)
        )
    return replace(item, y_values=corrected)


def _stack_studio_series(series: list[StudioSeries], *, render_options: dict[str, Any]) -> list[StudioSeries]:
    if len(series) <= 1:
        return series

    prepared: list[tuple[StudioSeries, tuple[float, ...], float, float]] = []
    spans: list[float] = []
    peak_heights: list[float] = []
    lower_guards: list[float] = []
    for item in series:
        finite = _finite_values(item.y_values)
        q01 = _quantile(finite, 0.01) if finite else 0.0
        shifted = tuple(y_value - q01 if math.isfinite(y_value) else y_value for y_value in item.y_values)
        shifted_finite = _finite_values(shifted)
        lower_guards.append(max(0.0, -min(shifted_finite)) if shifted_finite else 0.0)
        peak = _robust_peak_height(finite)
        prepared.append((item, shifted, peak, peak))
        spans.append(peak)
        peak_heights.append(peak)

    max_span = max(spans) if spans else 1.0
    max_peak = max(peak_heights) if peak_heights else max_span
    spacing_scale = _optional_float(render_options.get("stack_spacing_scale"))
    if spacing_scale is None:
        peak = max(max_peak, sys.float_info.epsilon)
        series_count = len(series)
        min_gap = 0.25 * peak
        padding = 0.10 * peak
        lower_guard = max(lower_guards) if lower_guards else 0.0
        required_span = series_count * peak + (series_count - 1) * min_gap + 2.0 * padding + lower_guard
        y_span = _nice_ceiling(required_span)
        gap = (y_span - series_count * peak - 2.0 * padding - lower_guard) / max(series_count - 1, 1)
        step = peak + max(gap, min_gap)
        floor = padding + lower_guard
    else:
        scale = max(spacing_scale, 0.05)
        floor = max(max_span * 0.22, max_peak * 0.16) * scale
        peak_clearance = max(max_span * 0.22 * 0.95, max_peak * 0.24)
        step = max(max_span * 1.22, max_peak + peak_clearance) * scale

    stacked: list[StudioSeries] = []
    for index, (item, shifted, _span, _peak) in enumerate(prepared):
        offset = floor + index * step
        stacked.append(replace(item, y_values=tuple(y_value + offset for y_value in shifted)))
    return stacked


def _request_template(request: dict[str, Any]) -> str:
    template = request.get("template")
    if isinstance(template, str) and template.strip():
        return template.strip()
    recipe = request.get("recipe")
    if isinstance(recipe, str) and recipe.strip() and recipe.strip() != "auto":
        return recipe.strip()
    return "curve"


def _looks_like_wavenumber_axis(axis_info: dict[str, Any]) -> bool:
    text = " ".join(str(value) for value in axis_info.values()).casefold()
    return "wavenumber" in text or ("cm" in text and ("-1" in text or "−1" in text or "^{-1}" in text))


def _looks_like_torque_axis(axis_info: dict[str, Any]) -> bool:
    text = " ".join(str(value) for value in axis_info.values()).casefold()
    return "torque" in text or "转矩" in text or "screw" in text


def _looks_like_frequency_axis(axis_info: dict[str, Any]) -> bool:
    text = " ".join(str(value) for value in axis_info.values()).casefold()
    return "frequency" in text or "angular" in text or "rad/s" in text or "hz" in text


def _looks_like_tensile_axis(axis_info: dict[str, Any]) -> bool:
    text = " ".join(str(value) for value in axis_info.values()).casefold()
    return ("strain" in text and "stress" in text) or "tensile" in text or "拉伸" in text


def _finite_values(values: tuple[float, ...]) -> list[float]:
    return [float(value) for value in values if math.isfinite(value)]


def _quantile(values: list[float], fraction: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    if len(ordered) == 1:
        return float(ordered[0])
    position = (len(ordered) - 1) * fraction
    lower = math.floor(position)
    upper = math.ceil(position)
    if lower == upper:
        return float(ordered[lower])
    weight = position - lower
    return float(ordered[lower] * (1.0 - weight) + ordered[upper] * weight)


def _robust_peak_height(values: list[float]) -> float:
    if not values:
        return 1.0
    span = _quantile(values, 0.99) - _quantile(values, 0.01)
    if math.isclose(span, 0.0):
        span = max(values) - min(values)
    if math.isclose(span, 0.0):
        span = max(abs(max(values)), 1.0) * 0.15
    return max(float(span), sys.float_info.epsilon)


def _nice_ceiling(value: float) -> float:
    if not math.isfinite(value) or value <= 0.0:
        return 1.0
    exponent = math.floor(math.log10(value))
    base = 10.0**exponent
    for multiplier in (1.0, 2.0, 5.0, 10.0):
        candidate = multiplier * base
        if candidate >= value - 1e-12:
            return float(candidate)
    return float(10.0 * base)


def _mean(values: Any) -> float:
    total = 0.0
    count = 0
    for value in values:
        total += float(value)
        count += 1
    return total / count if count else 0.0


def _write_veusz_document(
    path: Path,
    *,
    request: dict[str, Any],
    series: list[StudioSeries],
    axis_info: dict[str, Any],
) -> Path:
    render_options = _effective_render_options(request)
    render_options = _apply_domain_render_defaults(render_options, request=request, axis_info=axis_info)
    series, legend_label_mapping = _compact_replicate_series_labels(series)
    if legend_label_mapping:
        render_options = dict(render_options)
        render_options["_legend_label_mapping"] = legend_label_mapping
        render_options["_autofixes_applied"] = sorted(
            {
                *_string_list(render_options.get("_autofixes_applied")),
                "replicate_legend_prefix_compacted",
            }
        )
    template_id = _request_template(request)
    render_options = _apply_readability_render_defaults(
        render_options,
        request=request,
        axis_info=axis_info,
        series=series,
        template_id=template_id,
    )
    axis_info = dict(axis_info)
    axis_info["x_label"] = _veusz_axis_label(render_options.get("x_label_override") or axis_info["x_label"])
    axis_info["y_label"] = _veusz_axis_label(render_options.get("y_label_override") or axis_info["y_label"])
    legend_mode = _veusz_legend_mode(render_options, template_id=template_id)
    style = _veusz_style_contract(render_options)
    axis_contract = _veusz_axis_contract(render_options, template_id=template_id, series=series)
    width, height = _size_mm(str(render_options.get("size") or "60x55"))
    show_key = _show_veusz_key(template_id=template_id, render_options=render_options, series_count=len(series))
    show_direct_labels = _show_veusz_direct_labels(
        template_id=template_id,
        render_options=render_options,
        series_count=len(series),
        show_key=show_key,
    )
    spec = _build_veusz_plot_spec(
        request=request,
        render_options=render_options,
        template_id=template_id,
        series=series,
        axis_info=axis_info,
        axis_contract=axis_contract,
        style=style,
        width_mm=width,
        height_mm=height,
        legend_mode=legend_mode,
        show_key=show_key,
        show_direct_labels=show_direct_labels,
    )
    spec_path = _veusz_spec_path(path)
    spec_path.parent.mkdir(parents=True, exist_ok=True)
    spec_path.write_text(json.dumps(json_safe(spec), indent=2, ensure_ascii=False), encoding="utf-8")
    _save_veusz_document_from_spec(path, spec, spec_path=spec_path)
    generate_log = path.parent / "logs" / "veusz_generate_stderr.log"
    if generate_log.exists():
        spec["stderr_logs"] = {"generate": str(generate_log)}
    spec_path.write_text(json.dumps(json_safe(spec), indent=2, ensure_ascii=False), encoding="utf-8")
    return spec_path


def _categorical_plot_contract(
    series: list[StudioSeries],
    *,
    template_id: str,
    render_options: dict[str, Any],
) -> dict[str, Any] | None:
    categorical = [item for item in series if item.presentation_kind == "categorical_replicates"]
    if not categorical:
        return None
    summary_statistic = normalize_categorical_summary(
        render_options.get("summary_statistic") or DEFAULT_CATEGORICAL_SUMMARY
    )
    groups: list[dict[str, Any]] = []
    for index, item in enumerate(categorical, start=1):
        values = [float(value) for value in item.y_values if math.isfinite(float(value))]
        position = float(item.category_position if item.category_position is not None else index)
        eligible = summary_statistic == "median_iqr" and len(values) >= MIN_BOX_REPLICATES
        groups.append(
            {
                "label": item.label,
                "color": item.color,
                "position": position,
                "y_name": item.y_name,
                "raw_values": values,
                "replicate_count": len(values),
                "boxplot_eligible": eligible,
                "summary_status": (
                    "boxplot"
                    if eligible
                    else "raw_only"
                    if summary_statistic == "raw_only"
                    else "insufficient_replicates"
                ),
                "descriptive_statistics": {
                    "minimum": min(values),
                    "q1": _quantile(values, 0.25),
                    "median": _quantile(values, 0.5),
                    "q3": _quantile(values, 0.75),
                    "maximum": max(values),
                },
                "raw_points_visible": (
                    template_id == "box_strip" or summary_statistic == "raw_only" or len(values) < MIN_BOX_REPLICATES
                ),
            }
        )
    return {
        "kind": "sciplot_categorical_replicate_contract",
        "version": 1,
        "presentation_kind": "box_strip" if template_id == "box_strip" else "box",
        "summary_statistic": summary_statistic,
        "minimum_box_replicates": MIN_BOX_REPLICATES,
        "box_whisker_mode": "1.5IQR",
        "mean_marker_visible": False,
        "native_veusz_boxplot": summary_statistic == "median_iqr"
        and any(group["boxplot_eligible"] for group in groups),
        "raw_values_preserved": True,
        "raw_replicate_count": sum(group["replicate_count"] for group in groups),
        "visual_style": {
            "palette_policy": "relaxed_multi_category",
            "palette_preset": str(render_options.get("palette_preset") or DEFAULT_PALETTE_PRESET),
            "box_fill_mode": "series_color",
            "box_fill_transparency": CATEGORICAL_BOX_FILL_TRANSPARENCY,
            "box_fill_fraction": CATEGORICAL_BOX_FILL_FRACTION,
            "box_line_mode": "series_color",
            "box_line_width_pt": CATEGORICAL_BOX_LINE_WIDTH_PT,
        },
        "groups": groups,
        "insufficient_replicate_groups": [
            group["label"] for group in groups if group["summary_status"] == "insufficient_replicates"
        ],
    }


def _spectral_x_coverage_issue(
    series: list[StudioSeries],
    *,
    template_id: str,
    axis_info: dict[str, Any],
    axis_contract: _VeuszAxisContract,
) -> dict[str, Any] | None:
    if template_id not in STACKED_TEMPLATE_IDS or not _looks_like_wavenumber_axis(axis_info):
        return None
    if axis_contract.x_min is None or axis_contract.x_max is None:
        return None
    axis_low, axis_high = sorted((float(axis_contract.x_min), float(axis_contract.x_max)))
    axis_span = axis_high - axis_low
    values = [
        float(value)
        for item in series
        for value in item.x_values
        if math.isfinite(float(value)) and axis_low <= float(value) <= axis_high
    ]
    if axis_span <= 0.0 or len(values) < 2:
        return None
    data_low = min(values)
    data_high = max(values)
    coverage = (data_high - data_low) / axis_span
    if coverage >= 0.25:
        return None
    severity = "critical" if coverage < 0.08 else "warning"
    return {
        "id": "spectral_axis_data_coverage_low",
        "severity": severity,
        "message": (
            "Spectral data occupy too little of the requested wavenumber axis; the curve is visually collapsed."
            if severity == "critical"
            else "Spectral data occupy less than one quarter of the requested wavenumber axis."
        ),
        "axis_domain": [axis_low, axis_high],
        "data_domain": [data_low, data_high],
        "coverage_fraction": round(coverage, 6),
        "critical_threshold": 0.08,
        "warning_threshold": 0.25,
    }


def _semantic_series_contract_issues(
    series: list[StudioSeries],
    *,
    request: dict[str, Any],
) -> list[dict[str, Any]]:
    """Reject same-axis series that contradict the selected rule's metric contract."""

    rule_id = str(request.get("rule_id") or "").strip()
    labels = [str(item.label or "").casefold() for item in series]
    issues: list[dict[str, Any]] = []
    forbidden_by_rule = {
        "saxs_profile": ("azimuth", "angle"),
        "swelling_curve": ("gel fraction", "gel content"),
    }
    forbidden = forbidden_by_rule.get(rule_id, ())
    incompatible_labels = [
        item.label for item, label in zip(series, labels, strict=True) if any(token in label for token in forbidden)
    ]
    if incompatible_labels:
        issues.append(
            {
                "id": "incompatible_series_for_axis_metric",
                "severity": "critical",
                "message": "A same-table metric incompatible with the selected y-axis was included as a curve.",
                "rule_id": rule_id,
                "incompatible_series": incompatible_labels,
            }
        )
    if rule_id == "gpc_sec_chromatogram" and len(series) > 1:
        domains: list[tuple[float, float]] = []
        for item in series:
            values = [float(value) for value in item.x_values if math.isfinite(float(value))]
            if len(values) >= 2 and max(values) > min(values):
                domains.append((min(values), max(values)))
        if len(domains) == len(series):
            overlap = max(0.0, min(high for _low, high in domains) - max(low for low, _high in domains))
            minimum_span = min(high - low for low, high in domains)
            overlap_fraction = overlap / minimum_span if minimum_span > 0.0 else 0.0
            if overlap_fraction < 0.25:
                issues.append(
                    {
                        "id": "gpc_detector_time_domains_misaligned",
                        "severity": "critical" if overlap_fraction < 0.05 else "warning",
                        "message": (
                            "GPC detector traces share too little elution-time domain for a common-axis overlay."
                        ),
                        "series_domains": [[low, high] for low, high in domains],
                        "minimum_span_overlap_fraction": round(overlap_fraction, 6),
                        "critical_threshold": 0.05,
                        "warning_threshold": 0.25,
                    }
                )
    return issues


def _visual_data_transforms(
    *,
    template_id: str,
    render_options: dict[str, Any],
    series_count: int,
) -> list[dict[str, Any]]:
    transforms: list[dict[str, Any]] = []
    baseline_mode = str(render_options.get("baseline") or "none").strip().casefold()
    if baseline_mode != "none":
        transforms.append(
            {
                "id": "baseline_correction",
                "mode": baseline_mode,
                "implementation": "mean of up to 30 points at each endpoint with linear interpolation",
                "scientific_values_changed_in_visual_document": True,
            }
        )
    if template_id in STACKED_TEMPLATE_IDS and series_count > 1:
        transforms.append(
            {
                "id": "vertical_offset_stack",
                "mode": "q01_shift_and_auto_spacing",
                "series_count": series_count,
                "scientific_values_changed_in_visual_document": True,
                "purpose": "visual separation only; processed source table retains the unshifted values",
            }
        )
    return transforms


def _scalar_field_plot_contract(
    axis_info: dict[str, Any],
    *,
    render_options: dict[str, Any],
    template_id: str,
) -> dict[str, Any] | None:
    source = axis_info.get("scalar_field")
    if template_id not in SCALAR_FIELD_TEMPLATE_IDS or not isinstance(source, dict):
        return None
    data_min = float(source["z_data_min"])
    data_max = float(source["z_data_max"])
    z_min = _optional_float(render_options.get("z_min"))
    z_max = _optional_float(render_options.get("z_max"))
    z_min = data_min if z_min is None else z_min
    z_max = data_max if z_max is None else z_max
    if not math.isfinite(z_min) or not math.isfinite(z_max) or z_min >= z_max:
        raise ValueError("Scalar-field z_min and z_max must be finite and strictly increasing.")
    zscale = str(render_options.get("zscale") or "linear").strip().casefold()
    if zscale == "log" and z_min <= 0.0:
        raise ValueError("Scalar-field logarithmic color scaling requires z_min > 0.")
    colors_value = render_options.get("colormap_colors")
    colors = [str(value) for value in colors_value] if isinstance(colors_value, list | tuple) else []
    colors = [value for value in colors if re.fullmatch(r"#[0-9A-Fa-f]{6}(?:[0-9A-Fa-f]{2})?", value)]
    if len(colors) < 2:
        colors = list(DEFAULT_SCALAR_FIELD_COLORS)
    contour_levels = [
        value for value in _float_tuple(render_options.get("contour_levels")) if z_min <= value <= z_max
    ]
    highlight_levels = [
        value
        for value in _float_tuple(render_options.get("highlight_contour_levels"))
        if z_min <= value <= z_max
    ]
    show_contours = bool(contour_levels) or template_id == "contour_field"
    return {
        **json_safe(source),
        "z_min": z_min,
        "z_max": z_max,
        "zscale": zscale,
        "z_ticks": list(_float_tuple(render_options.get("z_ticks"))),
        "z_tick_format": str(
            render_options.get("z_tick_format")
            or (DEFAULT_LOG_TICK_FORMAT if zscale == "log" else "Auto")
        ),
        "show_colorbar": render_options.get("show_colorbar") is not False,
        "colormap_name": str(render_options.get("colormap_name") or DEFAULT_SCALAR_FIELD_COLORMAP_ID),
        "colormap_colors": colors,
        "color_invert": render_options.get("color_invert") is True,
        "field_mapping": str(render_options.get("field_mapping") or "bounds"),
        "field_draw_mode": str(render_options.get("field_draw_mode") or "rectangles"),
        "show_contours": show_contours,
        "contour_levels": contour_levels,
        "contour_color": str(render_options.get("contour_color") or "#FFFFFF"),
        "contour_line_style": str(render_options.get("contour_line_style") or "solid"),
        "contour_line_width_pt": UNIFIED_LINE_WIDTH_PT,
        "contour_labels": render_options.get("contour_labels") is True,
        "highlight_contour_levels": highlight_levels,
        "highlight_contour_color": str(render_options.get("highlight_contour_color") or "#111111"),
        "highlight_contour_line_style": str(
            render_options.get("highlight_contour_line_style") or "dashed"
        ),
        "highlight_contour_line_width_pt": UNIFIED_LINE_WIDTH_PT,
        "colorbar_direction": str(render_options.get("colorbar_direction") or "horizontal"),
        "colorbar_manual_position": render_options.get("colorbar_manual_position") is True,
        "colorbar_width_mm": float(render_options.get("colorbar_width_mm") or 31.0),
        "colorbar_height_mm": float(render_options.get("colorbar_height_mm") or 2.4),
        "colorbar_horz_manual": float(render_options.get("colorbar_horz_manual") or 0.86),
        "colorbar_vert_manual": float(
            render_options["colorbar_vert_manual"]
            if render_options.get("colorbar_vert_manual") is not None
            else 0.18
        ),
        "colorbar_foreground_color": str(
            render_options.get("colorbar_foreground_color") or "#111111"
        ),
        "colorbar_background_color": str(
            render_options.get("colorbar_background_color") or ""
        ),
        "colorbar_background_transparency": int(
            render_options.get("colorbar_background_transparency") or 0
        ),
        "colorbar_background_x_fraction": float(
            render_options.get("colorbar_background_x_fraction") or 0.5
        ),
        "colorbar_background_y_fraction": float(
            render_options.get("colorbar_background_y_fraction") or 0.86
        ),
        "colorbar_background_width_fraction": float(
            render_options.get("colorbar_background_width_fraction") or 0.44
        ),
        "colorbar_background_height_fraction": float(
            render_options.get("colorbar_background_height_fraction") or 0.24
        ),
    }


def _reference_guides_contract(render_options: dict[str, Any]) -> list[dict[str, Any]]:
    value = render_options.get("reference_guides")
    if not isinstance(value, list | tuple):
        return []
    guides: list[dict[str, Any]] = []
    for index, item in enumerate(value, start=1):
        if not isinstance(item, dict):
            continue
        kind = str(item.get("kind") or "band").strip().casefold()
        axis = str(item.get("axis_target") or item.get("axis") or "x").strip().casefold()
        if kind not in {"band", "line"} or axis not in {"x", "y"}:
            continue
        start = _optional_float(item.get("start"))
        end = _optional_float(item.get("end"))
        value_number = _optional_float(item.get("value"))
        if kind == "line" and value_number is not None:
            start = value_number
            end = value_number
        if start is None or end is None:
            continue
        transparency_value = item.get("transparency")
        transparency = (
            86 if transparency_value is None and kind == "band"
            else 35 if transparency_value is None
            else int(transparency_value)
        )
        guides.append(
            {
                "id": str(item.get("id") or f"guide_{index}"),
                "kind": kind,
                "axis": axis,
                "start": min(start, end),
                "end": max(start, end),
                "color": str(item.get("color") or "#6B7280"),
                "transparency": min(max(transparency, 0), 100),
                "line_width_pt": UNIFIED_LINE_WIDTH_PT,
                "line_style": str(item.get("line_style") or "dashed"),
            }
        )
    return guides


def _build_veusz_plot_spec(
    *,
    request: dict[str, Any],
    render_options: dict[str, Any],
    template_id: str,
    series: list[StudioSeries],
    axis_info: dict[str, Any],
    axis_contract: _VeuszAxisContract,
    style: _VeuszStyleContract,
    width_mm: float,
    height_mm: float,
    legend_mode: str,
    show_key: bool,
    show_direct_labels: bool,
) -> dict[str, Any]:
    scalar_field_contract = _scalar_field_plot_contract(
        axis_info,
        render_options=render_options,
        template_id=template_id,
    )
    categorical_contract = _categorical_plot_contract(
        series,
        template_id=template_id,
        render_options=render_options,
    )
    label_specs: list[dict[str, Any]] = []
    if show_direct_labels:
        side = str(render_options.get("series_label_side") or "auto").strip().casefold()
        reverse_x = render_options.get("reverse_x") is True
        if side not in {"left", "right"}:
            side = "left" if reverse_x else "right"
        align = "left" if side == "left" else "right"
        label_size = UNIFIED_FONT_SIZE_PT
        y_span = (
            axis_contract.y_max - axis_contract.y_min
            if axis_contract.y_max is not None and axis_contract.y_min is not None
            else 0.0
        )
        try:
            offset_fraction = float(render_options.get("series_label_offset_fraction") or 0.0)
        except (TypeError, ValueError):
            offset_fraction = 0.0
        y_offset = y_span * max(offset_fraction, 0.0)
        valign = str(render_options.get("series_label_vertical_align") or "centre").strip().casefold()
        if valign not in {"top", "bottom", "centre", "center"}:
            valign = "centre"
        if valign == "center":
            valign = "centre"
        for index, item in enumerate(series, start=1):
            anchor = _series_label_anchor(item, reverse_x=reverse_x, side=side)
            if anchor is None:
                continue
            x_pos, y_pos = anchor
            y_pos += y_offset
            label_specs.append(
                {
                    "name": f"label_{index}",
                    "label": item.label,
                    "x": x_pos,
                    "y": y_pos,
                    "align": align,
                    "valign": valign,
                    "color": item.color,
                    "size_pt": label_size,
                }
            )
    label_load = _label_load(series)
    layout_issues: list[dict[str, Any]] = []
    spectral_coverage_issue = _spectral_x_coverage_issue(
        series,
        template_id=template_id,
        axis_info=axis_info,
        axis_contract=axis_contract,
    )
    if spectral_coverage_issue is not None:
        layout_issues.append(spectral_coverage_issue)
    layout_issues.extend(_semantic_series_contract_issues(series, request=request))
    if show_key and template_id not in STACKED_TEMPLATE_IDS and _legend_is_dense(series):
        layout_issues.append(
            {
                "id": "legend_crowded_inside",
                "severity": "warning",
                "message": "A crowded curve legend remains inside the plot area.",
            }
        )
    legend_spec = {
        "show": show_key,
        "columns": _legend_columns(
            series_count=len(series),
            mode=legend_mode,
            max_label_length=label_load["max_label_length"],
            figure_width_mm=width_mm,
        ),
        "mode": legend_mode,
        "horz_position": _normalize_optional_string(render_options.get("legend_horz_position")),
        "vert_position": _normalize_optional_string(render_options.get("legend_vert_position")),
        "horz_manual": _optional_float(render_options.get("legend_horz_manual")),
        "vert_manual": _optional_float(render_options.get("legend_vert_manual")),
    }
    placement_diagnostics = render_options.get("_legend_placement_diagnostics")
    if isinstance(placement_diagnostics, dict):
        legend_spec["placement_diagnostics"] = json_safe(placement_diagnostics)
        if show_key and placement_diagnostics.get("clearance_status") != "safe":
            measured_clearance = _optional_float(placement_diagnostics.get("minimum_curve_clearance_mm"))
            overlap_detected = measured_clearance is not None and measured_clearance <= 0.0
            layout_issues.append(
                {
                    "id": "legend_curve_clearance_below_target",
                    "severity": "critical" if overlap_detected else "warning",
                    "message": (
                        "The inside legend overlaps plotted data at final size."
                        if overlap_detected
                        else "No inside legend corner reached the requested curve clearance at final size."
                    ),
                    "required_clearance_mm": placement_diagnostics.get("required_curve_clearance_mm"),
                    "measured_clearance_mm": placement_diagnostics.get("minimum_curve_clearance_mm"),
                }
            )
    if show_key:
        legend_spec["label_load"] = label_load
        label_mapping = render_options.get("_legend_label_mapping")
        if isinstance(label_mapping, list) and label_mapping:
            legend_spec["label_mapping"] = json_safe(label_mapping)
    return {
        "kind": "sciplot_veusz_plot_spec",
        "version": 1,
        "created_at": datetime.now(UTC).isoformat(),
        "render_engine": "veusz",
        "qa_target": "veusz_export",
        "template": template_id,
        "source_request": json_safe(request),
        "render_options": json_safe(render_options),
        "size_mm": [width_mm, height_mm],
        "frame_alignment": {
            "status": "locked",
            "margin_mode": FIXED_PUBLICATION_FRAME_POLICY.margin_mode,
            "outside_legend_allowed": FIXED_PUBLICATION_FRAME_POLICY.outside_legend_allowed,
            "auxiliary_frame_envelope": FIXED_PUBLICATION_FRAME_POLICY.auxiliary_frame_envelope,
            "auxiliary_text_envelope": FIXED_PUBLICATION_FRAME_POLICY.auxiliary_text_envelope,
            "margins_mm": {
                "left": style.left_margin_mm,
                "right": style.right_margin_mm,
                "bottom": style.bottom_margin_mm,
                "top": style.top_margin_mm,
            },
        },
        "autofixes_applied": _string_list(render_options.get("_autofixes_applied")),
        "layout_issues": layout_issues,
        "visual_data_transforms": _visual_data_transforms(
            template_id=template_id,
            render_options=render_options,
            series_count=len(series),
        ),
        "provenance": {
            "veusz": upstream_status()["veusz"],
        },
        "style": {
            "font_family": style.font_family,
            "font_size_pt": style.font_size_pt,
            "legend_font_size_pt": style.legend_font_size_pt,
            "axis_linewidth_pt": style.axis_linewidth_pt,
            "tick_width_pt": style.tick_width_pt,
            "tick_length_pt": style.tick_length_pt,
            "minor_tick_width_pt": style.minor_tick_width_pt,
            "minor_tick_length_pt": style.minor_tick_length_pt,
            "line_width_pt": style.line_width_pt,
            "line_alpha": style.line_alpha,
            "marker_alpha": style.marker_alpha,
            "marker_size_pt": style.marker_size_pt,
            "marker_line_width_pt": style.marker_line_width_pt,
            "axes_labelpad_pt": style.axes_labelpad_pt,
            "xtick_major_pad_pt": style.xtick_major_pad_pt,
            "ytick_major_pad_pt": style.ytick_major_pad_pt,
            "legend_frameon": style.legend_frameon,
            "margins_mm": {
                "left": style.left_margin_mm,
                "right": style.right_margin_mm,
                "bottom": style.bottom_margin_mm,
                "top": style.top_margin_mm,
            },
        },
        "axes": {
            "x": {
                "label": axis_info["x_label"],
                "scale": _axis_scale(render_options, "x"),
                "tick_format": str(
                    render_options.get("x_tick_format")
                    or (DEFAULT_LOG_TICK_FORMAT if _axis_scale(render_options, "x") == "log" else "Auto")
                ),
                "minor_tick_count": int(
                    render_options.get("minor_tick_count")
                    or (DEFAULT_LOG_MINOR_TICK_COUNT if _axis_scale(render_options, "x") == "log" else 20)
                ),
                "minor_ticks": _log_minor_ticks(
                    axis_contract.x_min,
                    axis_contract.x_max,
                    scale=_axis_scale(render_options, "x"),
                    major_ticks=axis_contract.x_ticks,
                ),
                "min": axis_contract.x_min,
                "max": axis_contract.x_max,
                "ticks": list(axis_contract.x_ticks),
                "reverse": render_options.get("reverse_x") is True,
                "mode": "labels" if categorical_contract is not None else "numeric",
                "category_labels": list(axis_info.get("category_labels") or []),
                "category_positions": list(axis_info.get("category_positions") or []),
            },
            "y": {
                "label": axis_info["y_label"],
                "scale": _axis_scale(render_options, "y"),
                "tick_format": str(
                    render_options.get("y_tick_format")
                    or (DEFAULT_LOG_TICK_FORMAT if _axis_scale(render_options, "y") == "log" else "Auto")
                ),
                "minor_tick_count": int(
                    render_options.get("minor_tick_count")
                    or (DEFAULT_LOG_MINOR_TICK_COUNT if _axis_scale(render_options, "y") == "log" else 20)
                ),
                "minor_ticks": _log_minor_ticks(
                    axis_contract.y_min,
                    axis_contract.y_max,
                    scale=_axis_scale(render_options, "y"),
                    major_ticks=axis_contract.y_ticks,
                ),
                "min": axis_contract.y_min,
                "max": axis_contract.y_max,
                "ticks": list(axis_contract.y_ticks),
                "show_ticks": render_options.get("show_y_ticks") is not False,
            },
        },
        "legend": legend_spec,
        "categorical": categorical_contract,
        "scalar_field": scalar_field_contract,
        "reference_guides": _reference_guides_contract(render_options),
        "series": [
            {
                "name": f"series_{index}",
                "label": item.label,
                "x_name": item.x_name,
                "y_name": item.y_name,
                "x_values": list(item.x_values),
                "y_values": list(item.y_values),
                "color": item.color,
                "line_width_pt": item.line_width,
                "line_style": item.line_style,
                "marker": str(MARKER_MAP.get(item.marker, item.marker or "none")),
                "marker_size_pt": item.marker_size,
                "marker_thin_factor": _marker_thin_factor(item, template_id=template_id),
                "marker_fill_color": (
                    "white"
                    if str(render_options.get("marker_fill_mode") or "filled").casefold() == "open"
                    else item.color
                ),
                "presentation_kind": item.presentation_kind,
                "category_position": item.category_position,
                "plot_line_hide": item.presentation_kind == "categorical_replicates",
                "raw_points_visible": (
                    next(
                        (
                            bool(group["raw_points_visible"])
                            for group in (categorical_contract or {}).get("groups", [])
                            if group.get("label") == item.label
                        ),
                        True,
                    )
                ),
            }
            for index, item in enumerate(series, start=1)
            if item.presentation_kind != "scalar_field"
        ],
        "direct_labels": label_specs,
    }


def _save_veusz_document_from_spec(
    path: Path,
    spec: dict[str, Any],
    *,
    spec_path: Path | None = None,
) -> None:
    from sciplot_core.veusz_runtime import needs_veusz_worker_process, veusz_worker_environment

    if needs_veusz_worker_process():
        resolved_spec = spec_path or _veusz_spec_path(path)
        if not resolved_spec.exists():
            resolved_spec.parent.mkdir(parents=True, exist_ok=True)
            resolved_spec.write_text(
                json.dumps(json_safe(spec), indent=2, ensure_ascii=False),
                encoding="utf-8",
            )
        subprocess.run(
            [
                sys.executable,
                "-m",
                "sciplot_core.veusz_worker",
                "save-spec",
                str(path),
                str(resolved_spec),
            ],
            text=True,
            capture_output=True,
            check=True,
            env=veusz_worker_environment(),
        )
        return
    stderr_log = path.parent / "logs" / "veusz_generate_stderr.log"
    with _capture_process_stderr(stderr_log):
        _prefer_offscreen_export_platform()
        _ensure_veusz_on_path()
        from PyQt6 import QtWidgets
        from veusz import dataimport, document, widgets
        from veusz.document import CommandInterface

        _ = dataimport, widgets
        app = QtWidgets.QApplication.instance()
        created_app = app is None
        if app is None:
            app = QtWidgets.QApplication([])
        try:
            doc = document.Document()
            interface = CommandInterface(doc)
            _apply_veusz_spec(interface, spec)
            path.parent.mkdir(parents=True, exist_ok=True)
            interface.Save(str(path))
            load_test = document.Document()
            load_test.load(str(path))
        finally:
            if created_app:
                app.quit()


def _hex_to_veusz_rgba(value: str) -> tuple[int, int, int, int]:
    text = str(value).strip().lstrip("#")
    if len(text) not in {6, 8} or not re.fullmatch(r"[0-9A-Fa-f]+", text):
        raise ValueError(f"Invalid scalar-field colormap color: {value}")
    alpha = int(text[6:8], 16) if len(text) == 8 else 255
    return int(text[0:2], 16), int(text[2:4], 16), int(text[4:6], 16), alpha


def _add_veusz_contour(
    interface: Any,
    *,
    name: str,
    data_name: str,
    levels: list[float],
    color: str,
    line_style: str,
    line_width_pt: float,
    show_labels: bool,
) -> None:
    if not levels:
        return
    interface.Add("contour", name=name, autoadd=False)
    interface.To(name)
    interface.Set("data", data_name)
    interface.Set("scaling", "manual")
    interface.Set("manualLevels", [float(value) for value in levels])
    interface.Set("numLevels", len(levels))
    interface.Set("Lines/lines", [(line_style, _pt(line_width_pt), color, False)])
    interface.Set("Fills/hide", True)
    interface.Set("SubLines/hide", True)
    interface.Set("ContourLabels/hide", not show_labels)
    interface.Set("keyLevels", False)
    interface.To("..")


def _add_veusz_scalar_field(interface: Any, scalar: dict[str, Any], style: dict[str, Any]) -> None:
    data_name = str(scalar["data_name"])
    interface.SetData2D(
        data_name,
        scalar["z_values"],
        xcent=[float(value) for value in scalar["x_values"]],
        ycent=[float(value) for value in scalar["y_values"]],
    )
    colormap_name = str(scalar["colormap_name"])
    colormap = [_hex_to_veusz_rgba(value) for value in scalar["colormap_colors"]]
    interface.AddCustom("colormap", colormap_name, colormap, mode="replace")
    # Veusz paints graph children in reverse object-tree order. Add overlays
    # first and the opaque image last so contours and the colorbar remain
    # visible above the scalar field.
    if scalar.get("show_contours") is True:
        _add_veusz_contour(
            interface,
            name="field_contours",
            data_name=data_name,
            levels=[float(value) for value in scalar.get("contour_levels") or []],
            color=str(scalar.get("contour_color") or "#FFFFFF"),
            line_style=str(scalar.get("contour_line_style") or "solid"),
            line_width_pt=UNIFIED_LINE_WIDTH_PT,
            show_labels=bool(scalar.get("contour_labels")),
        )
    _add_veusz_contour(
        interface,
        name="field_highlight_contours",
        data_name=data_name,
        levels=[float(value) for value in scalar.get("highlight_contour_levels") or []],
        color=str(scalar.get("highlight_contour_color") or "#111111"),
        line_style=str(scalar.get("highlight_contour_line_style") or "dashed"),
        line_width_pt=UNIFIED_LINE_WIDTH_PT,
        show_labels=False,
    )
    if scalar.get("show_colorbar") is True:
        interface.Add("colorbar", name="field_colorbar", autoadd=False)
        interface.To("field_colorbar")
        # Veusz WidgetChoice stores the sibling widget name, not an absolute
        # object-tree path.  An absolute path silently leaves the colorbar
        # detached and falls back to a synthetic 0--1 scale.
        interface.Set("widgetName", "field_image")
        # Keep the colorbar numerically identical to the image even though the
        # colorbar is created first to satisfy Veusz's reverse paint order.
        interface.Set("min", float(scalar["z_min"]))
        interface.Set("max", float(scalar["z_max"]))
        direction = str(scalar.get("colorbar_direction") or "horizontal").strip().casefold()
        if direction not in {"horizontal", "vertical"}:
            direction = "horizontal"
        interface.Set("direction", direction)
        if scalar.get("colorbar_manual_position") is True:
            interface.Set("horzPosn", "manual")
            interface.Set("vertPosn", "manual")
            interface.Set("horzManual", float(scalar.get("colorbar_horz_manual") or 0.0))
            interface.Set("vertManual", float(scalar.get("colorbar_vert_manual") or 0.0))
        elif direction == "horizontal":
            interface.Set("horzPosn", "right")
            interface.Set("vertPosn", "top")
        else:
            interface.Set("horzPosn", "manual")
            interface.Set("vertPosn", "manual")
            interface.Set("horzManual", float(scalar.get("colorbar_horz_manual") or 0.86))
            interface.Set("vertManual", float(scalar.get("colorbar_vert_manual") or 0.18))
        interface.Set("width", _cm_from_mm(float(scalar.get("colorbar_width_mm") or 2.4)))
        interface.Set("height", _cm_from_mm(float(scalar.get("colorbar_height_mm") or 24.0)))
        interface.Set("label", str(scalar.get("z_label") or "Z"))
        interface.Set("autoMirror", False)
        interface.Set("outerticks", True)
        foreground_color = str(scalar.get("colorbar_foreground_color") or "#111111")
        interface.Set("Line/color", foreground_color)
        interface.Set("Line/width", _pt(float(style["axis_linewidth_pt"])))
        interface.Set("Border/color", foreground_color)
        interface.Set("Border/width", _pt(float(style["axis_linewidth_pt"])))
        interface.Set("MajorTicks/width", _pt(float(style["tick_width_pt"])))
        interface.Set("MajorTicks/length", _pt(float(style["tick_length_pt"])))
        interface.Set("MinorTicks/width", _pt(float(style["minor_tick_width_pt"])))
        interface.Set("MinorTicks/length", _pt(float(style["minor_tick_length_pt"])))
        interface.Set("Label/size", _pt(float(style["font_size_pt"])))
        interface.Set("Label/color", foreground_color)
        interface.Set("TickLabels/size", _pt(float(style["font_size_pt"])))
        interface.Set("TickLabels/color", foreground_color)
        interface.Set("TickLabels/format", str(scalar.get("z_tick_format") or "Auto"))
        z_ticks = scalar.get("z_ticks") if isinstance(scalar.get("z_ticks"), list) else []
        if 1 < len(z_ticks) <= 12:
            interface.Set("MajorTicks/manualTicks", [float(value) for value in z_ticks])
        interface.To("..")
    background_color = str(scalar.get("colorbar_background_color") or "").strip()
    if scalar.get("show_colorbar") is True and background_color:
        interface.Add("rect", name="field_colorbar_background", autoadd=False)
        interface.To("field_colorbar_background")
        interface.Set("positioning", "relative")
        interface.Set("xPos", [float(scalar.get("colorbar_background_x_fraction") or 0.5)])
        interface.Set("yPos", [float(scalar.get("colorbar_background_y_fraction") or 0.86)])
        interface.Set(
            "width",
            [float(scalar.get("colorbar_background_width_fraction") or 0.44)],
        )
        interface.Set(
            "height",
            [float(scalar.get("colorbar_background_height_fraction") or 0.24)],
        )
        interface.Set("clip", True)
        interface.Set("Fill/color", background_color)
        interface.Set("Fill/hide", False)
        interface.Set(
            "Fill/transparency",
            min(max(int(scalar.get("colorbar_background_transparency") or 0), 0), 100),
        )
        interface.Set("Border/hide", True)
        interface.To("..")
    interface.Add("image", name="field_image", autoadd=False)
    interface.To("field_image")
    interface.Set("data", data_name)
    interface.Set("min", float(scalar["z_min"]))
    interface.Set("max", float(scalar["z_max"]))
    interface.Set("colorScaling", str(scalar["zscale"]))
    interface.Set("colorMap", colormap_name)
    interface.Set("colorInvert", bool(scalar.get("color_invert")))
    interface.Set("mapping", str(scalar.get("field_mapping") or "bounds"))
    interface.Set("drawMode", str(scalar.get("field_draw_mode") or "rectangles"))
    interface.To("..")


def _axis_midpoint(axis_spec: dict[str, Any]) -> float:
    minimum = float(axis_spec["min"])
    maximum = float(axis_spec["max"])
    if str(axis_spec.get("scale") or "linear") == "log" and minimum > 0.0 and maximum > 0.0:
        return math.sqrt(minimum * maximum)
    return 0.5 * (minimum + maximum)


def _add_veusz_reference_guides(interface: Any, spec: dict[str, Any]) -> None:
    guides = spec.get("reference_guides")
    if not isinstance(guides, list):
        return
    axes = spec["axes"]
    x_axis = axes["x"]
    y_axis = axes["y"]
    if any(x_axis.get(key) is None for key in ("min", "max")) or any(
        y_axis.get(key) is None for key in ("min", "max")
    ):
        return
    x_min, x_max = float(x_axis["min"]), float(x_axis["max"])
    y_min, y_max = float(y_axis["min"]), float(y_axis["max"])
    for index, guide in enumerate(guides, start=1):
        if not isinstance(guide, dict):
            continue
        axis = str(guide.get("axis") or "x")
        kind = str(guide.get("kind") or "band")
        start = float(guide["start"])
        end = float(guide["end"])
        if axis == "x":
            clipped_start = max(start, x_min)
            clipped_end = min(end, x_max)
            if clipped_end < clipped_start:
                continue
            center_x = 0.5 * (clipped_start + clipped_end)
            width_fraction = (clipped_end - clipped_start) / max(x_max - x_min, sys.float_info.epsilon)
            if kind == "line" or math.isclose(width_fraction, 0.0):
                width_fraction = max(width_fraction, 0.0025)
            center_y = _axis_midpoint(y_axis)
            height_fraction = 1.0
        else:
            clipped_start = max(start, y_min)
            clipped_end = min(end, y_max)
            if clipped_end < clipped_start:
                continue
            if str(y_axis.get("scale") or "linear") == "log" and clipped_start > 0.0 and clipped_end > 0.0:
                center_y = math.sqrt(clipped_start * clipped_end)
                height_fraction = math.log(clipped_end / clipped_start) / max(
                    math.log(y_max / y_min),
                    sys.float_info.epsilon,
                )
            else:
                center_y = 0.5 * (clipped_start + clipped_end)
                height_fraction = (clipped_end - clipped_start) / max(y_max - y_min, sys.float_info.epsilon)
            if kind == "line" or math.isclose(height_fraction, 0.0):
                height_fraction = max(height_fraction, 0.0025)
            center_x = _axis_midpoint(x_axis)
            width_fraction = 1.0
        interface.Add("rect", name=f"reference_guide_{index}", autoadd=False)
        interface.To(f"reference_guide_{index}")
        interface.Set("positioning", "axes")
        interface.Set("xPos", [center_x])
        interface.Set("yPos", [center_y])
        interface.Set("width", [min(max(width_fraction, 0.0), 1.0)])
        interface.Set("height", [min(max(height_fraction, 0.0), 1.0)])
        interface.Set("clip", True)
        interface.Set("Fill/color", str(guide.get("color") or "#6B7280"))
        transparency_value = guide.get("transparency")
        transparency = 86 if transparency_value is None else int(transparency_value)
        interface.Set("Fill/transparency", min(max(transparency, 0), 100))
        interface.Set("Fill/hide", False)
        interface.Set("Border/hide", True)
        interface.To("..")


def _apply_veusz_spec(interface: Any, spec: dict[str, Any]) -> None:
    style = spec["style"]
    axes = spec["axes"]
    size_mm = spec["size_mm"]
    categorical = spec.get("categorical") if isinstance(spec.get("categorical"), dict) else None
    for item in spec["series"]:
        x_data = "\n".join(f"{float(value):.12g}" for value in item["x_values"])
        y_data = "\n".join(f"{float(value):.12g}" for value in item["y_values"])
        interface.ImportString(f"{item['x_name']}(numeric)", x_data)
        interface.ImportString(f"{item['y_name']}(numeric)", y_data)
    if categorical is not None:
        groups = [group for group in categorical.get("groups", []) if isinstance(group, dict)]
        x_axis = axes.get("x") if isinstance(axes.get("x"), dict) else {}
        category_labels = x_axis.get("category_labels") if isinstance(x_axis.get("category_labels"), list) else []
        interface.SetDataText(
            "category_axis_labels",
            [
                _veusz_literal_text(category_labels[index] if index < len(category_labels) else group["label"])
                for index, group in enumerate(groups)
            ],
        )
        interface.ImportString(
            "category_axis_x(numeric)",
            "\n".join(f"{float(group['position']):.12g}" for group in groups),
        )
        interface.ImportString(
            "category_axis_y(numeric)",
            "\n".join(f"{float(group['descriptive_statistics']['median']):.12g}" for group in groups),
        )
    interface.Set("StyleSheet/Font/font", style["font_family"])
    interface.Set("StyleSheet/Font/size", _pt(float(style["font_size_pt"])))
    interface.Set("StyleSheet/Line/width", _pt(float(style["line_width_pt"])))
    interface.Set("width", f"{float(size_mm[0]):g}mm")
    interface.Set("height", f"{float(size_mm[1]):g}mm")
    interface.Add("page", name="page1", autoadd=False)
    interface.To("page1")
    interface.Set("width", f"{float(size_mm[0]):g}mm")
    interface.Set("height", f"{float(size_mm[1]):g}mm")
    interface.Set("Background/color", "white")
    interface.Set("Background/hide", False)
    interface.Add("graph", name="graph1", autoadd=False)
    interface.To("graph1")
    interface.Set("Border/hide", True)
    margins = style["margins_mm"]
    interface.Set("leftMargin", _cm_from_mm(float(margins["left"])))
    interface.Set("rightMargin", _cm_from_mm(float(margins["right"])))
    interface.Set("topMargin", _cm_from_mm(float(margins["top"])))
    interface.Set("bottomMargin", _cm_from_mm(float(margins["bottom"])))
    _add_veusz_axis(interface, "x", axes["x"], style)
    _add_veusz_axis(interface, "y", axes["y"], style)
    scalar = spec.get("scalar_field") if isinstance(spec.get("scalar_field"), dict) else None
    if scalar is not None:
        _add_veusz_scalar_field(interface, scalar, style)
    legend = spec["legend"]
    if legend["show"]:
        interface.Add("key", name="key1", autoadd=False)
        interface.To("key1")
        interface.Set("title", "")
        interface.Set("Text/size", _pt(float(style["legend_font_size_pt"])))
        interface.Set("keyLength", "0.40cm")
        interface.Set("marginSize", 0.15)
        interface.Set("columns", int(legend["columns"]))
        _apply_key_position(
            interface,
            str(legend.get("mode") or "inside_best"),
            horz_position=_normalize_optional_string(legend.get("horz_position")),
            vert_position=_normalize_optional_string(legend.get("vert_position")),
            horz_manual=_optional_float(legend.get("horz_manual")),
            vert_manual=_optional_float(legend.get("vert_manual")),
        )
        interface.Set("Background/hide", not bool(style["legend_frameon"]))
        interface.Set("Border/hide", not bool(style["legend_frameon"]))
        interface.To("..")
    if categorical is not None and categorical.get("native_veusz_boxplot") is True:
        categorical_style = categorical.get("visual_style") if isinstance(categorical.get("visual_style"), dict) else {}
        box_groups = [
            group
            for group in categorical.get("groups", [])
            if isinstance(group, dict) and group.get("boxplot_eligible") is True
        ]
        box_line_width = float(categorical_style.get("box_line_width_pt", CATEGORICAL_BOX_LINE_WIDTH_PT))
        for box_index, group in enumerate(box_groups, start=1):
            box_color = str(group.get("color") or DEFAULT_PALETTE_COLORS[(box_index - 1) % len(DEFAULT_PALETTE_COLORS)])
            box_name = f"categorical_boxplot_{box_index}"
            interface.Add("boxplot", name=box_name, autoadd=False)
            interface.To(box_name)
            interface.Set("values", (str(group["y_name"]),))
            interface.Set("posn", [float(group["position"])])
            interface.Set("whiskermode", str(categorical.get("box_whisker_mode") or "1.5IQR"))
            interface.Set(
                "fillfraction",
                float(categorical_style.get("box_fill_fraction", CATEGORICAL_BOX_FILL_FRACTION)),
            )
            interface.Set("meanmarker", "none")
            interface.Set("outliersmarker", "none")
            interface.Set("Fill/color", box_color)
            interface.Set(
                "Fill/transparency",
                int(categorical_style.get("box_fill_transparency", CATEGORICAL_BOX_FILL_TRANSPARENCY)),
            )
            interface.Set("Border/color", box_color)
            interface.Set("Border/width", _pt(box_line_width))
            interface.Set("Whisker/color", box_color)
            interface.Set("Whisker/width", _pt(box_line_width))
            interface.Set("MarkersLine/hide", True)
            interface.Set("MarkersFill/hide", True)
            interface.To("..")
    for item in spec["series"]:
        interface.Add("xy", name=item["name"], autoadd=False)
        interface.To(item["name"])
        interface.Set("xData", item["x_name"])
        interface.Set("yData", item["y_name"])
        interface.Set("key", _veusz_literal_text(item["label"]))
        interface.Set("PlotLine/color", item["color"])
        interface.Set("PlotLine/style", item.get("line_style") or "solid")
        interface.Set("MarkerFill/color", item.get("marker_fill_color") or item["color"])
        interface.Set("MarkerLine/color", item["color"])
        interface.Set("MarkerLine/width", _pt(float(style["marker_line_width_pt"])))
        interface.Set("marker", item["marker"])
        if item.get("plot_line_hide") is True:
            interface.Set("PlotLine/hide", True)
        if item.get("raw_points_visible") is False:
            interface.Set("MarkerFill/hide", True)
            interface.Set("MarkerLine/hide", True)
        interface.Set("PlotLine/transparency", _alpha_to_transparency(float(style["line_alpha"])))
        interface.Set("MarkerFill/transparency", _alpha_to_transparency(float(style["marker_alpha"])))
        interface.Set("MarkerLine/transparency", _alpha_to_transparency(float(style["marker_alpha"])))
        if item.get("line_width_pt") is not None:
            interface.Set("PlotLine/width", _pt(float(item["line_width_pt"])))
        marker = str(item.get("marker") or "none")
        if item.get("marker_size_pt") is not None:
            interface.Set("markerSize", _pt(float(item["marker_size_pt"])))
        elif marker != "none":
            interface.Set("markerSize", _pt(float(style["marker_size_pt"])))
        marker_thin_factor = max(1, int(item.get("marker_thin_factor") or 1))
        if marker_thin_factor > 1:
            interface.Set("thinfactor", marker_thin_factor)
        interface.To("..")
    if categorical is not None:
        interface.Add("xy", name="category_axis_label_provider", autoadd=False)
        interface.To("category_axis_label_provider")
        interface.Set("xData", "category_axis_x")
        interface.Set("yData", "category_axis_y")
        interface.Set("labels", "category_axis_labels")
        interface.Set("marker", "none")
        interface.Set("PlotLine/hide", True)
        interface.Set("MarkerFill/hide", True)
        interface.Set("MarkerLine/hide", True)
        interface.Set("ErrorBarLine/hide", True)
        interface.Set("Label/hide", True)
        interface.To("..")
    # Graph children are painted in reverse object-tree order.  Add reference
    # guides after data plotters so bands/lines paint first and never obscure
    # the scientific curves.
    _add_veusz_reference_guides(interface, spec)
    for item in spec["direct_labels"]:
        interface.Add("label", name=item["name"], autoadd=False)
        interface.To(item["name"])
        interface.Set("positioning", "axes")
        interface.Set("xPos", [float(item["x"])])
        interface.Set("yPos", [float(item["y"])])
        interface.Set("label", _veusz_literal_text(item["label"]))
        interface.Set("alignHorz", item["align"])
        interface.Set("alignVert", item.get("valign") or "centre")
        interface.Set("margin", "1pt" if item.get("valign") == "bottom" else "0pt")
        interface.Set("Text/size", _pt(float(item["size_pt"])))
        interface.Set("Text/color", item["color"])
        interface.Set("Background/hide", True)
        interface.Set("Border/hide", True)
        interface.To("..")
    interface.To("..")
    # Force an opaque export canvas.  Some Veusz PDF/TIFF backends retain an
    # alpha page when free-plotter guide rectangles are present even though
    # the Page background is set to white.  This page-level rectangle is added
    # after the graph, so reverse child painting draws it first as a true
    # background without covering any graph content.
    interface.Add("rect", name="page_export_background", autoadd=False)
    interface.To("page_export_background")
    interface.Set("positioning", "relative")
    interface.Set("xPos", [0.5])
    interface.Set("yPos", [0.5])
    interface.Set("width", [1.0])
    interface.Set("height", [1.0])
    interface.Set("Fill/color", "white")
    interface.Set("Fill/hide", False)
    interface.Set("Border/hide", True)
    interface.To("..")
    interface.To("..")


def _apply_key_position(
    interface: Any,
    mode: str,
    *,
    horz_position: str | None = None,
    vert_position: str | None = None,
    horz_manual: float | None = None,
    vert_manual: float | None = None,
) -> None:
    normalized = str(mode or "inside_best").strip().casefold()
    if normalized == "manual" or horz_position is not None or vert_position is not None:
        horz = str(horz_position or "manual")
        vert = str(vert_position or "manual")
        interface.Set("horzPosn", horz)
        interface.Set("vertPosn", vert)
        if horz == "manual":
            interface.Set("horzManual", float(horz_manual if horz_manual is not None else 0.5))
        if vert == "manual":
            interface.Set("vertManual", float(vert_manual if vert_manual is not None else 0.5))
        return
    if normalized in {"upper_right", "top_right"}:
        interface.Set("horzPosn", "right")
        interface.Set("vertPosn", "top")
        return
    if normalized in {"upper_left", "top_left"}:
        interface.Set("horzPosn", "left")
        interface.Set("vertPosn", "top")
        return
    if normalized in {"lower_left", "bottom_left"}:
        interface.Set("horzPosn", "left")
        interface.Set("vertPosn", "bottom")
        return
    interface.Set("horzPosn", "right")
    interface.Set("vertPosn", "bottom")


def _add_veusz_axis(interface: Any, axis: str, axis_spec: dict[str, Any], style: dict[str, Any]) -> None:
    interface.Add("axis", name=axis, autoadd=False)
    interface.To(axis)
    interface.Set("label", axis_spec["label"])
    if axis == "y":
        interface.Set("direction", "vertical")
    if axis_spec.get("mode") == "labels":
        interface.Set("mode", "labels")
    interface.Set("autoMirror", False)
    interface.Set("outerticks", True)
    interface.Set("Line/color", "black")
    interface.Set("Line/width", _pt(float(style["axis_linewidth_pt"])))
    interface.Set("MajorTicks/width", _pt(float(style["tick_width_pt"])))
    interface.Set("MajorTicks/length", _pt(float(style["tick_length_pt"])))
    interface.Set("MinorTicks/width", _pt(float(style["minor_tick_width_pt"])))
    interface.Set("MinorTicks/length", _pt(float(style["minor_tick_length_pt"])))
    interface.Set("MinorTicks/number", int(axis_spec.get("minor_tick_count") or 20))
    minor_ticks = axis_spec.get("minor_ticks") if isinstance(axis_spec.get("minor_ticks"), list) else []
    if minor_ticks:
        interface.Set("MinorTicks/manualTicks", [float(value) for value in minor_ticks])
    interface.Set("Label/size", _pt(float(style["font_size_pt"])))
    interface.Set("Label/offset", _pt(float(style["axes_labelpad_pt"])))
    interface.Set("TickLabels/size", _pt(float(style["font_size_pt"])))
    interface.Set("TickLabels/format", str(axis_spec.get("tick_format") or "Auto"))
    tick_offset = style["xtick_major_pad_pt"] if axis == "x" else style["ytick_major_pad_pt"]
    interface.Set("TickLabels/offset", _pt(float(tick_offset)))
    if axis == "y" and axis_spec.get("show_ticks") is False:
        interface.Set("MajorTicks/hide", True)
        interface.Set("MinorTicks/hide", True)
        interface.Set("TickLabels/hide", True)
    if axis_spec.get("min") is not None:
        interface.Set("min", float(axis_spec["min"]))
    if axis_spec.get("max") is not None:
        interface.Set("max", float(axis_spec["max"]))
    ticks = axis_spec.get("ticks") if isinstance(axis_spec.get("ticks"), list) else []
    if 1 < len(ticks) <= 12:
        interface.Set("MajorTicks/manualTicks", [float(value) for value in ticks])
    if axis_spec.get("scale") == "log":
        interface.Set("log", True)
    interface.To("..")


def _pt(value: float) -> str:
    return f"{float(value):g}pt"


def _cm_from_mm(value: float) -> str:
    return f"{float(value) / 10.0:g}cm"


def _alpha_to_transparency(alpha: float) -> int:
    if not math.isfinite(alpha):
        return 0
    bounded = min(max(float(alpha), 0.0), 1.0)
    return int(round((1.0 - bounded) * 100.0))


def _axis_scale(render_options: dict[str, Any], axis: str) -> str:
    value = render_options.get(f"{axis}scale")
    if isinstance(value, str) and value.strip().casefold() == "log":
        return "log"
    return "linear"


def _veusz_axis_contract(
    render_options: dict[str, Any],
    *,
    template_id: str,
    series: list[StudioSeries],
) -> _VeuszAxisContract:
    explicit_x_min = _optional_float(render_options.get("x_min")) is not None
    explicit_x_max = _optional_float(render_options.get("x_max")) is not None
    explicit_y_min = _optional_float(render_options.get("y_min")) is not None
    explicit_y_max = _optional_float(render_options.get("y_max")) is not None
    x_min = _optional_float(render_options.get("x_min"))
    x_max = _optional_float(render_options.get("x_max"))
    y_min = _optional_float(render_options.get("y_min"))
    y_max = _optional_float(render_options.get("y_max"))
    x_ticks = _float_tuple(render_options.get("x_ticks"))
    y_ticks = _float_tuple(render_options.get("y_ticks"))
    explicit_x_ticks = bool(x_ticks)
    explicit_y_ticks = bool(y_ticks)

    if series:
        try:
            from sciplot_core._bootstrap import ensure_legacy_core

            ensure_legacy_core()
            from src.plotting_primitives import compute_axis_limits

            limits = compute_axis_limits(
                [item.y_values for item in series],
                kind="line",
                axis_mode=str(render_options.get("axis_mode") or "auto"),
                legend_mode=_veusz_legend_mode(render_options, template_id=template_id),
                x_values=[item.x_values for item in series],
                xscale=_axis_scale(render_options, "x"),
                yscale=_axis_scale(render_options, "y"),
                x_padding=_optional_float(render_options.get("x_padding_fraction")) or 0.02,
                y_padding_top=_optional_float(render_options.get("y_padding_top"))
                or (0.08 if template_id in STACKED_TEMPLATE_IDS else 0.18),
                y_padding_bottom=_optional_float(render_options.get("y_padding_bottom"))
                or (0.04 if template_id in STACKED_TEMPLATE_IDS else 0.06),
            )
            if x_min is None:
                x_min = float(limits.xlim[0])
            if x_max is None:
                x_max = float(limits.xlim[1])
            if y_min is None:
                y_min = float(limits.ylim[0])
            if y_max is None:
                y_max = float(limits.ylim[1])
            if not x_ticks and limits.x_tick_policy is not None:
                x_ticks = tuple(float(value) for value in limits.x_tick_policy.major_ticks)
            if not y_ticks and limits.y_tick_policy is not None:
                y_ticks = tuple(float(value) for value in limits.y_tick_policy.major_ticks)
        except Exception:
            pass

    if series and _axis_scale(render_options, "x") == "log" and not explicit_x_ticks:
        positive_x_values = [value for item in series for value in item.x_values if math.isfinite(value) and value > 0]
        x_ticks = anchored_log_decade_ticks(positive_x_values)
        if x_ticks:
            if not explicit_x_min:
                x_min = min(float(x_min), x_ticks[0]) if x_min is not None else x_ticks[0]
            if not explicit_x_max:
                x_max = max(float(x_max), x_ticks[-1]) if x_max is not None else x_ticks[-1]
                data_max = max(positive_x_values)
                if x_max > data_max * MAX_AUTO_LOG_EMPTY_RANGE_FACTOR:
                    x_max = max(x_ticks[-1], data_max * AUTO_LOG_BOUND_PADDING_FACTOR)
    if series and _axis_scale(render_options, "y") == "log" and not explicit_y_ticks:
        positive_y_values = [value for item in series for value in item.y_values if math.isfinite(value) and value > 0]
        y_ticks = anchored_log_decade_ticks(positive_y_values)
        if y_ticks:
            if not explicit_y_min:
                y_min = min(float(y_min), y_ticks[0]) if y_min is not None else y_ticks[0]
            if not explicit_y_max:
                y_max = max(float(y_max), y_ticks[-1]) if y_max is not None else y_ticks[-1]
                data_max = max(positive_y_values)
                if y_max > data_max * MAX_AUTO_LOG_EMPTY_RANGE_FACTOR:
                    y_max = max(y_ticks[-1], data_max * AUTO_LOG_BOUND_PADDING_FACTOR)
    if x_ticks:
        if not explicit_x_min:
            x_min = min(float(x_min), min(x_ticks)) if x_min is not None else min(x_ticks)
        if not explicit_x_max:
            x_max = max(float(x_max), max(x_ticks)) if x_max is not None else max(x_ticks)
    if y_ticks:
        if not explicit_y_min:
            y_min = min(float(y_min), min(y_ticks)) if y_min is not None else min(y_ticks)
        if not explicit_y_max:
            y_max = max(float(y_max), max(y_ticks)) if y_max is not None else max(y_ticks)

    reverse_x = render_options.get("reverse_x") is True
    if reverse_x and x_min is not None and x_max is not None:
        x_min, x_max = x_max, x_min
    if x_ticks and x_min is not None and x_max is not None:
        low = min(x_min, x_max)
        high = max(x_min, x_max)
        tick_values = (
            [x_min, *x_ticks, x_max] if reverse_x and _axis_scale(render_options, "x") != "log" else list(x_ticks)
        )
        deduped: list[float] = []
        for value in tick_values:
            if value < low - 1e-9 or value > high + 1e-9:
                continue
            if not any(math.isclose(value, existing) for existing in deduped):
                deduped.append(value)
        x_ticks = tuple(sorted(deduped, reverse=x_min > x_max))
    if y_ticks and y_min is not None and y_max is not None:
        low = min(y_min, y_max)
        high = max(y_min, y_max)
        y_ticks = tuple(value for value in sorted(set(y_ticks)) if low - 1e-9 <= value <= high + 1e-9)
    return _VeuszAxisContract(
        x_min=x_min,
        x_max=x_max,
        y_min=y_min,
        y_max=y_max,
        x_ticks=x_ticks,
        y_ticks=y_ticks,
    )


def _veusz_legend_mode(render_options: dict[str, Any], *, template_id: str) -> str:
    legend_position = normalize_legend_position(render_options.get("legend_position"))
    if legend_position in {"none", "hide", "hidden", "off"}:
        return "none"
    if legend_position in {"upper_right", "upper_left", "lower_left", "lower_right", "manual"}:
        return legend_position
    if template_id in STACKED_TEMPLATE_IDS:
        label_mode = str(render_options.get("series_label_mode") or "").casefold()
        return "none" if label_mode in {"inline", "edge"} else "upper_right"
    return "inside_best"


def _legend_columns(
    *,
    series_count: int,
    mode: str = "inside_best",
    max_label_length: int = 0,
    figure_width_mm: float | None = None,
) -> int:
    if series_count <= 4:
        return 1
    if figure_width_mm is not None and figure_width_mm <= 60.5 and max_label_length >= 22:
        return 1
    return 2


def _show_veusz_direct_labels(
    *,
    template_id: str,
    render_options: dict[str, Any],
    series_count: int,
    show_key: bool,
) -> bool:
    if show_key or series_count <= 1 or template_id not in STACKED_TEMPLATE_IDS:
        return False
    label_mode = str(render_options.get("series_label_mode") or "").strip().casefold()
    return label_mode in {"inline", "edge", "auto"}


def _series_label_anchor(item: StudioSeries, *, reverse_x: bool, side: str) -> tuple[float, float] | None:
    points = sorted(
        (
            (float(x_value), float(y_value))
            for x_value, y_value in zip(item.x_values, item.y_values, strict=True)
            if math.isfinite(x_value) and math.isfinite(y_value)
        ),
        key=lambda pair: pair[0],
    )
    if not points:
        return None
    x_values = [point[0] for point in points]
    x_min = min(x_values)
    x_max = max(x_values)
    span = x_max - x_min
    if math.isclose(span, 0.0):
        target_x = x_min
    elif side == "left":
        target_x = x_max - span * 0.06 if reverse_x else x_min + span * 0.06
    else:
        target_x = x_min + span * 0.06 if reverse_x else x_max - span * 0.06
    nearest = min(points, key=lambda pair: abs(pair[0] - target_x))
    return nearest


def _show_veusz_key(*, template_id: str, render_options: dict[str, Any], series_count: int) -> bool:
    if template_id in SCALAR_FIELD_TEMPLATE_IDS:
        return False
    if series_count <= 1:
        return False
    if template_id in CATEGORICAL_TEMPLATE_IDS:
        return False
    label_mode = str(render_options.get("series_label_mode") or "legend").strip().casefold()
    legend_position = str(render_options.get("legend_position") or "auto").strip().casefold()
    if template_id in STACKED_TEMPLATE_IDS and label_mode in {"inline", "edge", "auto"}:
        return False
    if legend_position in {"none", "hide", "hidden", "off"}:
        return False
    return True


def _prefer_offscreen_export_platform() -> None:
    if "PyQt6.QtWidgets" in sys.modules:
        return
    current = os.environ.get("QT_QPA_PLATFORM")
    if current in {None, "", "minimal"}:
        os.environ["QT_QPA_PLATFORM"] = "offscreen"


def _write_studio_launcher(project_dir: Path) -> Path:
    launcher = project_dir / "Open_in_SciPlot_Studio.command"
    lines = [
        *portable_sciplot_prelude(),
        *portable_vsz_finder(),
        "",
        'DOCUMENT="$(find_vsz document.vsz)" || die "Cannot locate studio/document.vsz."',
        'if [[ "${1:-}" == "--check" ]]; then',
        '  exec "${SCIPLOT_CMD}" studio "${DOCUMENT}" --qt-smoke',
        "fi",
        'exec "${SCIPLOT_CMD}" studio "${PROJECT_DIR}"',
    ]
    launcher.write_text(
        "\n".join(lines) + "\n",
        encoding="utf-8",
    )
    launcher.chmod(0o755)
    return launcher


def _write_veusz_launcher(project_dir: Path, document_path: Path) -> Path:
    launcher = project_dir / "Open_in_Veusz.command"
    resolved_document = document_path.expanduser().resolve()
    document_name = shlex.quote(resolved_document.name)
    lines = [
        *portable_sciplot_prelude(),
        *portable_vsz_finder(extra_candidates=[resolved_document]),
        "",
        f"DOCUMENT_NAME={document_name}",
        'DOCUMENT="$(find_vsz "${DOCUMENT_NAME}")" || die "Cannot locate ${DOCUMENT_NAME}."',
        'if [[ "${1:-}" == "--check" ]]; then',
        '  exec "${SCIPLOT_CMD}" studio "${DOCUMENT}" --qt-smoke',
        "fi",
        'exec "${SCIPLOT_CMD}" studio "${DOCUMENT}" --advanced-editor',
    ]
    launcher.write_text(
        "\n".join(lines) + "\n",
        encoding="utf-8",
    )
    launcher.chmod(0o755)
    return launcher


def _write_export_edited_launcher(project_dir: Path) -> Path:
    launcher = project_dir / "Export_Edited_Veusz.command"
    lines = [
        *portable_sciplot_prelude(),
        *portable_vsz_finder(),
        "",
        'DOCUMENT="$(find_vsz document.vsz)" || die "Cannot locate studio/document.vsz."',
        'if [[ "${1:-}" == "--check" ]]; then',
        '  exec "${SCIPLOT_CMD}" studio "${DOCUMENT}" --qt-smoke',
        "fi",
        'exec "${SCIPLOT_CMD}" studio "${PROJECT_DIR}" --export pdf,tiff_300 --json',
    ]
    launcher.write_text(
        "\n".join(lines) + "\n",
        encoding="utf-8",
    )
    launcher.chmod(0o755)
    return launcher


def _veusz_spec_path(document_path: Path) -> Path:
    if document_path.name == "document.vsz":
        return document_path.parent / "spec.json"
    return document_path.with_suffix(".spec.json")


def _veusz_spec_reference(document_path: Path) -> dict[str, Any]:
    expected_path = _veusz_spec_path(document_path)
    exists = expected_path.is_file()
    return {
        "kind": "sciplot_veusz_spec_reference",
        "path": str(expected_path) if exists else None,
        "expected_path": str(expected_path),
        "exists": exists,
        "required_for_exact_current_export": False,
        "required_for_regeneration": True,
        "role": "optional_sciplot_generation_metadata",
    }


def _studio_document_state(document_path: Path, *, generated_hash: str | None) -> dict[str, Any]:
    current_hash = existing_file_sha256(document_path)
    manual_edit_detected = bool(generated_hash and current_hash and current_hash != generated_hash)
    if manual_edit_detected:
        authority = "veusz_manual"
    elif generated_hash and current_hash == generated_hash:
        authority = "sciplot_generated"
    else:
        authority = "veusz_document"
    regeneration_requires_archive = bool(current_hash and (manual_edit_detected or generated_hash is None))
    return {
        "kind": "sciplot_vsz_document_state",
        "authority": authority,
        "generated_hash": generated_hash,
        "current_hash": current_hash,
        "manual_edit_detected": manual_edit_detected,
        "preserve_on_open": True,
        "export_exact_current_document": True,
        "regeneration_requires_archive": regeneration_requires_archive,
    }


def _registered_generated_hash(project_dir: Path) -> str | None:
    for manifest_path in [project_dir / "intake_manifest.json", *sorted(project_dir.glob("*.sciplot.json"))]:
        if not manifest_path.exists():
            continue
        try:
            payload = _read_json(manifest_path)
        except Exception:
            continue
        studio = payload.get("studio") if isinstance(payload.get("studio"), dict) else {}
        value = studio.get("generated_hash")
        if isinstance(value, str) and value.strip():
            return value
    return None


def _archive_manual_document_if_needed(project_dir: Path, document_path: Path) -> None:
    if not document_path.exists():
        return
    current_hash = existing_file_sha256(document_path)
    generated_hash = _registered_generated_hash(project_dir)
    if generated_hash and current_hash == generated_hash:
        return
    history_dir = document_path.parent / "history"
    history_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    destination = history_dir / f"{document_path.stem}_{stamp}{document_path.suffix}"
    shutil.copy2(document_path, destination)
    spec_path = _veusz_spec_path(document_path)
    if spec_path.exists():
        shutil.copy2(spec_path, history_dir / f"{document_path.stem}_{stamp}.spec.json")


def _studio_block(
    *,
    document_path: Path,
    spec_path: Path,
    launcher: Path,
    veusz_launcher: Path,
    export_edited_launcher: Path,
    request_path: Path,
    series_count: int,
    generated_hash: str | None,
) -> dict[str, Any]:
    document_state = _studio_document_state(document_path, generated_hash=generated_hash)
    return {
        "kind": "sciplot_studio_document",
        "engine": "veusz",
        "render_engine": "veusz",
        "qa_target": "veusz_export",
        "status": "ready",
        "document": str(document_path),
        "spec": str(spec_path),
        "launcher": str(launcher),
        "veusz_launcher": str(veusz_launcher),
        "export_edited_launcher": str(export_edited_launcher),
        "generated_from": str(request_path),
        "series_count": series_count,
        "generated_hash": generated_hash,
        "manual_edit_hash": document_state["current_hash"],
        "document_authority": document_state["authority"],
        "manual_edit_detected": document_state["manual_edit_detected"],
        "document_state": document_state,
        "upstream": upstream_status()["veusz"],
        "operation_mode": normal_mode_payload(route="studio"),
    }


def _register_studio_block(project_dir: Path, studio_block: dict[str, Any]) -> None:
    for manifest_path in [project_dir / "intake_manifest.json", *sorted(project_dir.glob("*.sciplot.json"))]:
        if manifest_path.exists():
            payload = _read_json(manifest_path)
            payload["studio"] = studio_block
            manifest_path.write_text(json.dumps(json_safe(payload), indent=2, ensure_ascii=False), encoding="utf-8")


def _register_studio_exports(
    project_dir: Path,
    exports: list[dict[str, Any]],
    *,
    studio_run: dict[str, Any] | None = None,
) -> None:
    for manifest_path in [project_dir / "intake_manifest.json", *sorted(project_dir.glob("*.sciplot.json"))]:
        if manifest_path.exists():
            payload = _read_json(manifest_path)
            studio = payload.get("studio") if isinstance(payload.get("studio"), dict) else {}
            studio["exports"] = exports
            if studio_run is not None:
                studio["last_export_run"] = studio_run
            payload["studio"] = studio
            manifest_path.write_text(json.dumps(json_safe(payload), indent=2, ensure_ascii=False), encoding="utf-8")


def _register_studio_run(project_dir: Path, manifest: dict[str, Any]) -> None:
    last_run = {
        "completed_at": manifest.get("created_at"),
        "route": "studio",
        "output": manifest.get("output"),
        "figures": manifest.get("figures", []),
        "qa": manifest.get("qa", {}),
        "revision_brief": manifest.get("revision_brief"),
        "package_contract": manifest.get("package_contract", {}),
        "delivery_package": manifest.get("delivery_package", {}),
        "layout_quality": manifest.get("layout_quality", {}),
    }
    for manifest_path in [project_dir / "intake_manifest.json", *sorted(project_dir.glob("*.sciplot.json"))]:
        if not manifest_path.exists():
            continue
        payload = _read_json(manifest_path)
        payload["last_run"] = last_run
        payload["package_contract"] = manifest.get("package_contract", {})
        payload["delivery_package"] = manifest.get("delivery_package", {})
        payload["layout_quality"] = manifest.get("layout_quality", {})
        studio = payload.get("studio") if isinstance(payload.get("studio"), dict) else {}
        studio["last_export_run"] = {
            "kind": "sciplot_studio_export_run",
            "output": manifest.get("output"),
            "manifest": str(Path(str(manifest.get("output"))) / "manifest.json") if manifest.get("output") else None,
            "review_html": str(Path(str(manifest.get("output"))) / "review.html") if manifest.get("output") else None,
            "figures": manifest.get("figures", []),
            "qa": manifest.get("qa", {}),
        }
        payload["studio"] = studio
        payload["study_model"] = manifest.get("study_model", payload.get("study_model", {}))
        manifest_path.write_text(json.dumps(json_safe(payload), indent=2, ensure_ascii=False), encoding="utf-8")
    try:
        from sciplot_core.intake import refresh_intake_project_zip

        refresh_intake_project_zip(project_dir)
    except Exception:
        return


def _ensure_veusz_on_path() -> None:
    if VEUSZ_ROOT.exists():
        sys.path.insert(0, str(VEUSZ_ROOT))


@contextmanager
def _capture_process_stderr(log_path: Path):
    if os.environ.get("SCIPLOT_STUDIO_SHOW_QT_WARNINGS") == "1":
        yield None
        return
    log_path.parent.mkdir(parents=True, exist_ok=True)
    original_fd: int | None = None
    try:
        sys.stderr.flush()
        original_fd = os.dup(2)
        with tempfile.TemporaryFile(mode="w+b") as buffer:
            os.dup2(buffer.fileno(), 2)
            try:
                yield log_path
            finally:
                sys.stderr.flush()
                if original_fd is not None:
                    os.dup2(original_fd, 2)
                buffer.seek(0)
                captured = buffer.read()
        if captured.strip():
            log_path.write_bytes(captured)
        elif log_path.exists():
            log_path.unlink()
    finally:
        if original_fd is not None:
            os.close(original_fd)


def _qt_framework_paths() -> list[Path]:
    candidates = [Path("/opt/homebrew/opt/qtbase/lib"), Path("/opt/homebrew/opt/qt/lib")]
    if all(path.exists() for path in candidates):
        return candidates
    brew = shutil.which("brew")
    if not brew:
        return [path for path in candidates if path.exists()]
    paths: list[Path] = []
    for package in ("qtbase", "qt"):
        try:
            prefix = subprocess.check_output([brew, "--prefix", package], text=True, stderr=subprocess.DEVNULL).strip()
        except (OSError, subprocess.CalledProcessError):
            continue
        lib_path = Path(prefix) / "lib"
        if lib_path.exists():
            paths.append(lib_path)
    return paths


def _split_formats(value: str) -> list[str]:
    formats = [item.strip() for item in value.split(",") if item.strip()]
    return formats or ["pdf"]


def _export_suffix(fmt: str) -> tuple[str, int | None]:
    normalized = fmt.casefold()
    if normalized in {"tiff_300", "tif_300", "tiff"}:
        return "_300dpi.tiff", 300
    if normalized in {"png", "png_300"}:
        return "_300dpi.png", 300
    if normalized == "png_600":
        return "_600dpi.png", 600
    if normalized == "svg":
        return ".svg", None
    return ".pdf", None


def _size_mm(value: str) -> tuple[int, int]:
    try:
        left, right = value.lower().split("x", maxsplit=1)
        return max(1, int(float(left))), max(1, int(float(right)))
    except Exception:
        return 60, 55


def _string_list(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    return [item for item in (str(entry) for entry in value) if item]


def _optional_float(value: Any) -> float | None:
    try:
        if value is None or value == "":
            return None
        return float(value)
    except (TypeError, ValueError):
        return None


def _float_tuple(value: Any) -> tuple[float, ...]:
    if not isinstance(value, list | tuple):
        return ()
    parsed = [_optional_float(item) for item in value]
    return tuple(item for item in parsed if item is not None and math.isfinite(item))


def _log_minor_ticks(
    minimum: float | None,
    maximum: float | None,
    *,
    scale: str,
    major_ticks: tuple[float, ...] = (),
) -> list[float]:
    if scale != "log" or minimum is None or maximum is None:
        return []
    low, high = sorted((float(minimum), float(maximum)))
    if not math.isfinite(low) or not math.isfinite(high) or low <= 0 or high <= low:
        return []
    visible_major_ticks = sorted(
        float(value) for value in major_ticks if math.isfinite(value) and low <= float(value) <= high
    )
    if len(visible_major_ticks) >= 2:
        low, high = visible_major_ticks[0], visible_major_ticks[-1]
    elif len(visible_major_ticks) == 1:
        return []
    start_exponent = math.floor(math.log10(low)) - 1
    end_exponent = math.ceil(math.log10(high)) + 1
    ticks: list[float] = []
    for exponent in range(start_exponent, end_exponent + 1):
        decade = 10.0**exponent
        for multiplier in DEFAULT_LOG_MINOR_MULTIPLIERS:
            value = multiplier * decade
            if low < value < high:
                ticks.append(value)
    return ticks


__all__ = [
    "ensure_veusz_qsettings_compat",
    "export_studio_document",
    "maybe_reexec_with_qt_runtime",
    "prepare_studio_document",
    "publish_standalone_export_receipt",
    "publish_studio_export_run",
    "qt_smoke_payload",
    "run_studio_command",
    "upstream_status",
]
