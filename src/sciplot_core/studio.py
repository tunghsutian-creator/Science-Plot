from __future__ import annotations

import hashlib
import json
import math
import os
import shutil
import subprocess
import sys
import tempfile
from contextlib import contextmanager
from dataclasses import dataclass, replace
from datetime import UTC, datetime
from html import escape
from io import StringIO
from pathlib import Path
from typing import Any

import pandas as pd

from sciplot_core._utils import decode_text, json_safe
from sciplot_core.delivery import build_delivery_package
from sciplot_core.intake import create_intake_project_from_session, prepare_intake_session
from sciplot_core.operation_modes import normal_mode_payload
from sciplot_core.policy import DEFAULT_PALETTE_PRESET, SPECTRUM_JOURNAL_COLORS
from sciplot_core.qa import run_qa
from sciplot_core.study_model import build_output_package_contract

REPO_ROOT = Path(__file__).resolve().parents[2]
VEUSZ_ROOT = REPO_ROOT / "third_party" / "veusz"
VEUSZ_COMMIT = "264084b06eb306d860c7757c637f37b78bb2333f"

DEFAULT_PALETTE = SPECTRUM_JOURNAL_COLORS
STACKED_TEMPLATE_IDS = {"stacked_curve", "segmented_stacked_curve"}
STUDIO_TEMPLATE_IDS = ("curve", "stacked_curve", "segmented_stacked_curve")
FIGURE_SIZE_PRESETS = ("60x55", "120x55", "180x55", "60x110", "120x110", "180x110")
EXPORT_FORMATS = ("pdf", "tiff_300")
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


@dataclass(frozen=True)
class _VeuszStyleContract:
    font_family: str = "Arial"
    font_size_pt: float = 6.5
    legend_font_size_pt: float = 5.8
    axis_linewidth_pt: float = 1.0
    tick_width_pt: float = 1.0
    tick_length_pt: float = 3.4
    minor_tick_width_pt: float = 0.8
    minor_tick_length_pt: float = 2.0
    line_width_pt: float = 1.2
    line_alpha: float = 0.92
    marker_alpha: float = 0.95
    marker_size_pt: float = 3.4
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
            "commit": VEUSZ_COMMIT,
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
    template: str | None = None,
    project_name: str | None = None,
) -> dict[str, Any]:
    resolved = Path(target).expanduser().resolve()
    target_info = _resolve_studio_target(
        resolved,
        output_root=output_root,
        template=template,
        project_name=project_name,
    )
    if target_info["mode"] == "vsz":
        return _existing_document_payload(target_info["document"])

    request_path = target_info["request"]
    project_dir = target_info["project_dir"]
    existing_document = _project_studio_document(project_dir)
    if (
        target_info.get("mode") == "project"
        and existing_document is not None
        and template is None
        and project_name is None
    ):
        launcher = _write_studio_launcher(project_dir)
        studio_block = _studio_block(
            document_path=existing_document,
            spec_path=_veusz_spec_path(existing_document),
            launcher=launcher,
            request_path=request_path,
            series_count=_count_veusz_series(existing_document),
            generated_hash=_registered_generated_hash(project_dir),
        )
        _register_studio_block(project_dir, studio_block)
        return {
            "kind": "sciplot_studio_prepare",
            "operation_mode": normal_mode_payload(route="studio"),
            "project_dir": str(project_dir),
            "request": str(request_path),
            "document": str(existing_document),
            "launcher": str(launcher),
            "series_count": studio_block["series_count"],
            "studio": studio_block,
            "preserved_existing_document": True,
        }
    _apply_studio_request_overrides(
        project_dir,
        request_path=request_path,
        template=template,
        project_name=project_name,
    )
    request = _read_json(request_path)
    document_path = project_dir / "studio" / "document.vsz"
    document_path.parent.mkdir(parents=True, exist_ok=True)
    _archive_manual_document_if_needed(project_dir, document_path)
    series, axis_info = _series_from_request(request, base_dir=request_path.parent)
    spec_path = _write_veusz_document(document_path, request=request, series=series, axis_info=axis_info)
    launcher = _write_studio_launcher(project_dir)
    generated_hash = _hash_file(document_path)
    studio_block = _studio_block(
        document_path=document_path,
        spec_path=spec_path,
        launcher=launcher,
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
        "series_count": len(series),
        "studio": studio_block,
    }


def run_studio_command(
    *,
    target: Path | None = None,
    output_root: Path | None = None,
    template: str | None = None,
    project_name: str | None = None,
    new: bool = False,
    export: str | None = None,
    json_output: bool = False,
    prepare_only: bool = False,
    qt_smoke: bool = False,
    original_argv: list[str] | None = None,
) -> int:
    if qt_smoke:
        maybe_reexec_with_qt_runtime(original_argv or ["studio", "--qt-smoke"])
        payload = qt_smoke_payload()
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

    if not (json_output or prepare_only or export):
        maybe_reexec_with_qt_runtime(original_argv or ["studio", str(target)])
        return launch_sciplot_studio(
            target,
            output_root=output_root,
            template=template,
            project_name=project_name,
        )

    if json_output or prepare_only or export:
        command = ["studio", str(target)]
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
        template=template,
        project_name=project_name,
    )
    document_path = Path(payload["document"])
    if export:
        export_payload = export_studio_document(document_path, formats=_split_formats(export))
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

    if json_output or prepare_only or export:
        print(json.dumps(json_safe(payload), indent=2, ensure_ascii=False))
        return 0

    return launch_veusz_gui(document_path)


def qt_smoke_payload() -> dict[str, Any]:
    _ensure_veusz_on_path()
    from PyQt6 import QtCore, QtWidgets
    from veusz.windows.simplewindow import SimpleWindow

    app = QtWidgets.QApplication.instance()
    created_app = app is None
    if app is None:
        app = QtWidgets.QApplication([])
    window = SimpleWindow("SciPlot Studio smoke")
    window.enableToolbar(True)
    payload = {
        "kind": "sciplot_studio_qt_smoke",
        "status": "passed",
        "qt_version": QtCore.QT_VERSION_STR,
        "pyqt_version": QtCore.PYQT_VERSION_STR,
        "window": type(window).__name__,
        "plot_window": type(window.plot).__name__,
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
    template: str | None = None,
    project_name: str | None = None,
) -> int:
    _ensure_veusz_on_path()
    from PyQt6 import QtWidgets

    app = QtWidgets.QApplication.instance() or QtWidgets.QApplication(sys.argv[:1])
    resolved = target.expanduser().resolve()
    if _is_raw_studio_source(resolved):
        window = _create_sciplot_studio_shell(
            source_path=resolved,
            output_root=output_root or Path("outputs") / "intake_projects",
            template=template,
            project_name=project_name,
        )
    elif resolved.is_dir() and (resolved / "plot_request.json").exists():
        window = _create_sciplot_project_shell(
            project_dir=resolved,
            output_root=output_root,
            template=template,
            project_name=project_name,
        )
    else:
        payload = prepare_studio_document(
            resolved,
            output_root=output_root,
            template=template,
            project_name=project_name,
        )
        window = _create_veusz_window(Path(payload["document"]))
    window.show()
    return int(app.exec())


def _create_veusz_window(document_path: Path | None) -> Any:
    from veusz.windows.mainwindow import MainWindow

    _ensure_veusz_loader_compat()
    window = MainWindow()
    if document_path is not None:
        window.openFileInWindow(str(document_path))
    else:
        window.setupDefaultDoc("graph")
    window.setWindowTitle("SciPlot Studio")
    _attach_sciplot_menu(window, document_path)
    window.resize(1200, 820)
    return window


def _ensure_veusz_loader_compat() -> None:
    """Keep Veusz script loading alive when optional import commands are absent."""
    from veusz import document as veusz_document
    from veusz.document import mime
    from veusz.document.commandinterface import CommandInterface, registerImportCommand

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


def _set_layout_margins(layout: Any, value: int = 12, spacing: int = 10) -> None:
    layout.setContentsMargins(value, value, value, value)
    layout.setSpacing(spacing)


def _group_box(title: str) -> Any:
    from PyQt6 import QtWidgets

    box = QtWidgets.QGroupBox(title)
    box.setFlat(False)
    return box


def _apply_sciplot_shell_style(shell: Any) -> None:
    shell.setObjectName("SciPlotStudioWindow")
    shell.resize(1320, 860)
    shell.setStyleSheet(
        """
        QMainWindow#SciPlotStudioWindow { background: #f4f5f6; }
        QToolBar#sciplotPrimaryToolbar {
            spacing: 6px;
            padding: 4px 8px;
            border: 0;
            border-bottom: 1px solid #d6d8dc;
            background: #f7f8f9;
        }
        QWidget#setupWorkspace, QWidget#refineWorkspace { background: #f4f5f6; }
        QGroupBox {
            font-weight: 600;
            border: 1px solid #d9dce0;
            border-radius: 8px;
            margin-top: 14px;
            background: #ffffff;
        }
        QGroupBox::title {
            subcontrol-origin: margin;
            left: 10px;
            padding: 0 4px;
        }
        QLabel#workspaceTitle {
            font-size: 17px;
            font-weight: 700;
        }
        QLabel#workspaceHint { color: #60646c; }
        QLabel#studioStatus { color: #555b64; }
        QTableWidget {
            border: 1px solid #d9dce0;
            border-radius: 6px;
            background: #ffffff;
            gridline-color: #eceef1;
        }
        """
    )


def _set_veusz_advanced_panels_visible(window: Any, visible: bool) -> None:
    for attr in ("console", "datadock", "formatdock"):
        widget = getattr(window, attr, None)
        if widget is not None:
            widget.setVisible(visible)
    for attr in ("maintoolbar", "datatoolbar"):
        toolbar = getattr(window, attr, None)
        if toolbar is not None:
            toolbar.setVisible(visible)
    treeedit = getattr(window, "treeedit", None)
    for attr in ("addtoolbar", "edittoolbar"):
        toolbar = getattr(treeedit, attr, None)
        if toolbar is not None:
            toolbar.setVisible(visible)


def _apply_sciplot_veusz_workspace_defaults(window: Any, *, embedded: bool = False) -> None:
    """Use Veusz as the real editor while keeping low-frequency UI folded away."""
    _set_veusz_advanced_panels_visible(window, False)
    if embedded:
        menu_bar = window.menuBar()
        if menu_bar is not None:
            menu_bar.hide()
        status_bar = window.statusBar()
        if status_bar is not None:
            status_bar.hide()


def _add_sciplot_view_menu(shell: Any, state: dict[str, Any]) -> None:
    from PyQt6 import QtGui

    view_menu = shell.menuBar().addMenu("View")
    advanced_action = QtGui.QAction("Advanced Veusz Panels", shell)
    advanced_action.setCheckable(True)

    def toggle_advanced(checked: bool) -> None:
        veusz_window = state.get("veusz_window")
        if veusz_window is not None:
            _set_veusz_advanced_panels_visible(veusz_window, checked)

    advanced_action.triggered.connect(toggle_advanced)
    view_menu.addAction(advanced_action)
    shell._sciplot_view_actions = getattr(shell, "_sciplot_view_actions", []) + [advanced_action]


def _create_sciplot_project_shell(
    *,
    project_dir: Path,
    output_root: Path | None,
    template: str | None,
    project_name: str | None,
) -> Any:
    from PyQt6 import QtCore, QtGui, QtWidgets

    project_dir = project_dir.expanduser().resolve()
    request_path = project_dir / "plot_request.json"
    request = _read_json(request_path)
    selected_template = _normalize_optional_string(template) or str(request.get("template") or "curve")
    selected_project_name = (
        _normalize_optional_string(project_name) or _manifest_project_name(project_dir) or project_dir.name
    )

    shell = QtWidgets.QMainWindow()
    shell.setWindowTitle("SciPlot Studio")
    _apply_sciplot_shell_style(shell)

    stack = QtWidgets.QStackedWidget()
    stack.setObjectName("studioWorkspaceStack")
    shell.setCentralWidget(stack)

    state: dict[str, Any] = {"veusz_window": None, "document_path": None}
    _add_sciplot_view_menu(shell, state)

    toolbar = QtWidgets.QToolBar("SciPlot")
    toolbar.setObjectName("sciplotPrimaryToolbar")
    toolbar.setMovable(False)
    shell.addToolBar(QtCore.Qt.ToolBarArea.TopToolBarArea, toolbar)
    back_action = QtGui.QAction("Back to Setup", shell)
    generate_action = QtGui.QAction("Generate", shell)
    save_action = QtGui.QAction("Save", shell)
    export_action = QtGui.QAction("Export", shell)
    back_action.setEnabled(False)
    save_action.setEnabled(False)
    export_action.setEnabled(False)
    toolbar.addAction(back_action)
    toolbar.addSeparator()
    toolbar.addAction(generate_action)
    toolbar.addAction(save_action)
    toolbar.addAction(export_action)

    setup_workspace = QtWidgets.QWidget()
    setup_workspace.setObjectName("setupWorkspace")
    setup_layout = QtWidgets.QVBoxLayout(setup_workspace)
    _set_layout_margins(setup_layout)
    title = QtWidgets.QLabel("Setup Workspace")
    title.setObjectName("workspaceTitle")
    hint = QtWidgets.QLabel("Confirm the reopened project's template before regenerating the Veusz figure.")
    hint.setObjectName("workspaceHint")
    setup_layout.addWidget(title)
    setup_layout.addWidget(hint)

    setup_box = _group_box("Project Setup")
    setup_box_layout = QtWidgets.QVBoxLayout(setup_box)
    _set_layout_margins(setup_box_layout)
    form = QtWidgets.QFormLayout()
    project_edit = QtWidgets.QLineEdit(str(project_dir))
    project_edit.setReadOnly(True)
    form.addRow("Project", project_edit)
    name_edit = QtWidgets.QLineEdit(selected_project_name)
    form.addRow("Name", name_edit)
    template_combo = QtWidgets.QComboBox()
    for template_id, label in _studio_template_choices():
        template_combo.addItem(label, template_id)
    template_index = template_combo.findData(selected_template)
    template_combo.setCurrentIndex(template_index if template_index >= 0 else 0)
    form.addRow("Template", template_combo)
    setup_box_layout.addLayout(form)

    status_label = QtWidgets.QLabel()
    status_label.setObjectName("studioStatus")
    status_label.setWordWrap(True)
    setup_box_layout.addWidget(status_label)
    actions = QtWidgets.QHBoxLayout()
    generate_button = QtWidgets.QPushButton("Generate")
    export_button = QtWidgets.QPushButton("Export")
    export_button.setEnabled(False)
    actions.addWidget(generate_button)
    actions.addWidget(export_button)
    setup_box_layout.addLayout(actions)
    setup_layout.addWidget(setup_box)
    setup_layout.addStretch(1)

    refine_workspace = QtWidgets.QWidget()
    refine_workspace.setObjectName("refineWorkspace")
    refine_layout = QtWidgets.QVBoxLayout(refine_workspace)
    refine_layout.setContentsMargins(0, 0, 0, 0)
    refine_layout.setSpacing(0)
    right_layout = QtWidgets.QVBoxLayout()
    right_layout.setContentsMargins(0, 0, 0, 0)
    refine_layout.addLayout(right_layout, 1)
    refine_status = QtWidgets.QLabel()
    refine_status.setObjectName("studioStatus")
    refine_status.setContentsMargins(10, 6, 10, 6)
    refine_layout.addWidget(refine_status)
    stack.addWidget(setup_workspace)
    stack.addWidget(refine_workspace)

    def load_document(document_path: Path) -> None:
        previous = state.get("veusz_window")
        if previous is not None:
            right_layout.removeWidget(previous)
            previous.setParent(None)
        veusz_window = _create_veusz_window(document_path)
        _apply_sciplot_veusz_workspace_defaults(veusz_window, embedded=True)
        state["veusz_window"] = veusz_window
        state["document_path"] = document_path
        right_layout.addWidget(veusz_window)
        status_label.setText(f"Loaded Veusz document:\n{document_path}")
        refine_status.setText(f"Refine Workspace · {document_path}")
        export_button.setEnabled(True)
        save_action.setEnabled(True)
        export_action.setEnabled(True)
        back_action.setEnabled(True)
        stack.setCurrentWidget(refine_workspace)

    def generate() -> None:
        try:
            payload = prepare_studio_document(
                project_dir,
                output_root=output_root,
                template=str(template_combo.currentData() or "curve"),
                project_name=name_edit.text().strip() or selected_project_name,
            )
            load_document(Path(payload["document"]))
        except Exception as exc:
            QtWidgets.QMessageBox.critical(shell, "SciPlot Studio", str(exc))

    def save_current() -> None:
        document_path = state.get("document_path")
        veusz_window = state.get("veusz_window")
        if isinstance(document_path, Path) and veusz_window is not None:
            veusz_window.document.save(str(document_path))
            refine_status.setText(f"Saved Veusz document · {document_path}")

    def export_current() -> None:
        try:
            document_path = state.get("document_path")
            veusz_window = state.get("veusz_window")
            if not isinstance(document_path, Path):
                return
            if veusz_window is not None:
                veusz_window.document.save(str(document_path))
            exports = export_studio_document(document_path, formats=list(EXPORT_FORMATS))["exports"]
            studio_run = publish_studio_export_run(
                project_dir=project_dir,
                request_path=request_path,
                document_path=document_path,
                exports=exports,
            )
            _register_studio_exports(project_dir, exports, studio_run=studio_run)
            status_label.setText(f"Exported through SciPlot QA:\n{studio_run['output']}")
            refine_status.setText(f"Exported through SciPlot QA · {studio_run['output']}")
        except Exception as exc:
            QtWidgets.QMessageBox.critical(shell, "SciPlot Studio", str(exc))

    generate_button.clicked.connect(generate)
    export_button.clicked.connect(export_current)
    back_action.triggered.connect(lambda: stack.setCurrentWidget(setup_workspace))
    generate_action.triggered.connect(generate)
    save_action.triggered.connect(save_current)
    export_action.triggered.connect(export_current)
    payload = prepare_studio_document(
        project_dir,
        output_root=output_root,
        template=template,
        project_name=project_name,
    )
    load_document(Path(payload["document"]))
    return shell


def _create_sciplot_studio_shell(
    *,
    source_path: Path,
    output_root: Path,
    template: str | None,
    project_name: str | None,
) -> Any:
    from PyQt6 import QtCore, QtGui, QtWidgets

    session = prepare_intake_session(source_path, output_root=output_root)
    selected_template = _normalize_optional_string(template) or _template_from_session(session)
    selected_project_name = _normalize_optional_string(project_name) or str(
        session.get("project_name") or source_path.stem
    )

    shell = QtWidgets.QMainWindow()
    shell.setWindowTitle("SciPlot Studio")
    _apply_sciplot_shell_style(shell)

    stack = QtWidgets.QStackedWidget()
    stack.setObjectName("studioWorkspaceStack")
    shell.setCentralWidget(stack)

    state: dict[str, Any] = {
        "project_dir": None,
        "request_path": None,
        "document_path": None,
        "veusz_window": None,
        "exports": list(EXPORT_FORMATS),
    }
    _add_sciplot_view_menu(shell, state)

    toolbar = QtWidgets.QToolBar("SciPlot")
    toolbar.setObjectName("sciplotPrimaryToolbar")
    toolbar.setMovable(False)
    shell.addToolBar(QtCore.Qt.ToolBarArea.TopToolBarArea, toolbar)
    back_action = QtGui.QAction("Back to Setup", shell)
    generate_action = QtGui.QAction("Generate", shell)
    save_action = QtGui.QAction("Save", shell)
    undo_action = QtGui.QAction("Undo", shell)
    redo_action = QtGui.QAction("Redo", shell)
    export_action = QtGui.QAction("Export", shell)
    back_action.setEnabled(False)
    save_action.setEnabled(False)
    undo_action.setEnabled(False)
    redo_action.setEnabled(False)
    export_action.setEnabled(False)
    toolbar.addAction(back_action)
    toolbar.addSeparator()
    toolbar.addAction(generate_action)
    toolbar.addAction(save_action)
    toolbar.addAction(undo_action)
    toolbar.addAction(redo_action)
    toolbar.addSeparator()
    toolbar.addAction(export_action)

    setup_workspace = QtWidgets.QWidget()
    setup_workspace.setObjectName("setupWorkspace")
    setup_layout = QtWidgets.QVBoxLayout(setup_workspace)
    _set_layout_margins(setup_layout)
    title = QtWidgets.QLabel("Setup Workspace")
    title.setObjectName("workspaceTitle")
    hint = QtWidgets.QLabel("Choose the template, sample names, axes, size, and export formats before generating.")
    hint.setObjectName("workspaceHint")
    setup_layout.addWidget(title)
    setup_layout.addWidget(hint)
    splitter = QtWidgets.QSplitter(QtCore.Qt.Orientation.Horizontal)
    setup_layout.addWidget(splitter, 1)

    source_box = _group_box("Sources")
    source_box.setMinimumWidth(260)
    source_layout = QtWidgets.QVBoxLayout(source_box)
    _set_layout_margins(source_layout)
    form = QtWidgets.QFormLayout()
    source_edit = QtWidgets.QLineEdit(str(source_path))
    source_edit.setReadOnly(True)
    form.addRow("Data", source_edit)
    name_edit = QtWidgets.QLineEdit(selected_project_name)
    form.addRow("Project", name_edit)
    source_layout.addLayout(form)
    status_label = QtWidgets.QLabel(_session_summary(session))
    status_label.setObjectName("studioStatus")
    status_label.setWordWrap(True)
    source_layout.addWidget(status_label)
    source_layout.addStretch(1)

    mapping_box = _group_box("Mapping")
    mapping_box.setMinimumWidth(360)
    mapping_layout = QtWidgets.QVBoxLayout(mapping_box)
    _set_layout_margins(mapping_layout)
    groups_table = QtWidgets.QTableWidget()
    groups_table.setColumnCount(2)
    groups_table.setHorizontalHeaderLabels(["Legend", "Files"])
    groups_table.horizontalHeader().setStretchLastSection(True)
    _populate_groups_table(groups_table, _session_groups(session))
    mapping_layout.addWidget(groups_table, 1)
    order_actions = QtWidgets.QHBoxLayout()
    move_up_button = QtWidgets.QPushButton("Up")
    move_down_button = QtWidgets.QPushButton("Down")
    order_actions.addWidget(move_up_button)
    order_actions.addWidget(move_down_button)
    mapping_layout.addLayout(order_actions)

    figure_box = _group_box("Figure Setup")
    figure_box.setMinimumWidth(300)
    figure_box.setMaximumWidth(380)
    figure_layout = QtWidgets.QVBoxLayout(figure_box)
    _set_layout_margins(figure_layout)
    figure_form = QtWidgets.QFormLayout()
    template_combo = QtWidgets.QComboBox()
    for template_id, label in _studio_template_choices():
        template_combo.addItem(label, template_id)
    template_index = template_combo.findData(selected_template)
    template_combo.setCurrentIndex(template_index if template_index >= 0 else 0)
    figure_form.addRow("Template", template_combo)
    size_combo = QtWidgets.QComboBox()
    for size in FIGURE_SIZE_PRESETS:
        size_combo.addItem(size, size)
    size_combo.setCurrentIndex(size_combo.findData("120x110") if selected_template in STACKED_TEMPLATE_IDS else 0)
    figure_form.addRow("Size", size_combo)
    x_label_edit = QtWidgets.QLineEdit()
    x_label_edit.setPlaceholderText("Auto")
    figure_form.addRow("X label", x_label_edit)
    y_label_edit = QtWidgets.QLineEdit()
    y_label_edit.setPlaceholderText("Auto")
    figure_form.addRow("Y label", y_label_edit)
    x_min_edit = QtWidgets.QLineEdit()
    x_min_edit.setPlaceholderText("Auto")
    x_max_edit = QtWidgets.QLineEdit()
    x_max_edit.setPlaceholderText("Auto")
    range_row = QtWidgets.QHBoxLayout()
    range_row.addWidget(x_min_edit)
    range_row.addWidget(x_max_edit)
    figure_form.addRow("X min/max", range_row)
    reverse_x_check = QtWidgets.QCheckBox("Reverse X")
    log_x_check = QtWidgets.QCheckBox("Log X")
    log_y_check = QtWidgets.QCheckBox("Log Y")
    axes_row = QtWidgets.QHBoxLayout()
    axes_row.addWidget(reverse_x_check)
    axes_row.addWidget(log_x_check)
    axes_row.addWidget(log_y_check)
    figure_form.addRow("Axes", axes_row)
    label_mode_combo = QtWidgets.QComboBox()
    for label, value in (("Legend", "legend"), ("Inline", "inline"), ("Auto", "auto")):
        label_mode_combo.addItem(label, value)
    if selected_template in STACKED_TEMPLATE_IDS:
        label_mode_combo.setCurrentIndex(label_mode_combo.findData("inline"))
    figure_form.addRow("Labels", label_mode_combo)
    export_checks: dict[str, Any] = {}
    export_row = QtWidgets.QHBoxLayout()
    for fmt in EXPORT_FORMATS:
        check = QtWidgets.QCheckBox(fmt)
        check.setChecked(True)
        export_checks[fmt] = check
        export_row.addWidget(check)
    figure_form.addRow("Exports", export_row)
    figure_layout.addLayout(figure_form)

    actions = QtWidgets.QHBoxLayout()
    generate_button = QtWidgets.QPushButton("Generate")
    export_button = QtWidgets.QPushButton("Export")
    export_button.setEnabled(False)
    actions.addWidget(generate_button)
    actions.addWidget(export_button)
    figure_layout.addLayout(actions)
    figure_layout.addStretch(1)

    splitter.addWidget(source_box)
    splitter.addWidget(mapping_box)
    splitter.addWidget(figure_box)
    splitter.setStretchFactor(1, 1)

    refine_workspace = QtWidgets.QWidget()
    refine_workspace.setObjectName("refineWorkspace")
    refine_layout = QtWidgets.QVBoxLayout(refine_workspace)
    refine_layout.setContentsMargins(0, 0, 0, 0)
    refine_layout.setSpacing(0)
    right_layout = QtWidgets.QVBoxLayout()
    right_layout.setContentsMargins(0, 0, 0, 0)
    refine_layout.addLayout(right_layout, 1)
    refine_status = QtWidgets.QLabel("Refine Workspace")
    refine_status.setObjectName("studioStatus")
    refine_status.setContentsMargins(10, 6, 10, 6)
    refine_layout.addWidget(refine_status)

    stack.addWidget(setup_workspace)
    stack.addWidget(refine_workspace)

    def build_current_project() -> dict[str, Any]:
        edited_session = dict(session)
        edited_session["output_root"] = str(output_root.expanduser().resolve())
        edited_session["project_name"] = name_edit.text().strip() or source_path.stem or "SciPlot Project"
        edited_session["groups"] = _groups_from_table(groups_table, _session_groups(session))
        project = create_intake_project_from_session(edited_session)
        project_dir = Path(str(project["project_dir"])).expanduser().resolve()
        request_path = project_dir / "plot_request.json"
        selected = str(template_combo.currentData() or "curve")
        selected_exports = [
            fmt for fmt, check in export_checks.items() if check.isChecked()
        ] or list(EXPORT_FORMATS)
        state["exports"] = selected_exports
        _apply_panel_request_options(
            project_dir,
            request_path=request_path,
            exports=selected_exports,
            render_options=_panel_render_options(
                size=str(size_combo.currentData() or "60x55"),
                x_label=x_label_edit.text(),
                y_label=y_label_edit.text(),
                x_min=x_min_edit.text(),
                x_max=x_max_edit.text(),
                reverse_x=reverse_x_check.isChecked(),
                xscale="log" if log_x_check.isChecked() else "linear",
                yscale="log" if log_y_check.isChecked() else "linear",
                series_label_mode=str(label_mode_combo.currentData() or "legend"),
            ),
        )
        payload = prepare_studio_document(
            project_dir,
            output_root=output_root,
            template=selected,
            project_name=edited_session["project_name"],
        )
        state.update(
            {
                "project_dir": project_dir,
                "request_path": request_path,
                "document_path": Path(payload["document"]),
            }
        )
        return payload

    def load_payload(payload: dict[str, Any]) -> None:
        previous = state.get("veusz_window")
        if previous is not None:
            right_layout.removeWidget(previous)
            previous.setParent(None)
        veusz_window = _create_veusz_window(Path(payload["document"]))
        _apply_sciplot_veusz_workspace_defaults(veusz_window, embedded=True)
        state["veusz_window"] = veusz_window
        right_layout.addWidget(veusz_window)
        export_button.setEnabled(True)
        back_action.setEnabled(True)
        save_action.setEnabled(True)
        undo_action.setEnabled(True)
        redo_action.setEnabled(True)
        export_action.setEnabled(True)
        status_label.setText(f"SciPlot generated Veusz document:\n{payload['document']}")
        refine_status.setText(f"Refine Workspace · {payload['document']}")
        stack.setCurrentWidget(refine_workspace)

    def generate() -> None:
        try:
            load_payload(build_current_project())
        except Exception as exc:
            QtWidgets.QMessageBox.critical(shell, "SciPlot Studio", str(exc))

    def save_current() -> None:
        document_path = state.get("document_path")
        veusz_window = state.get("veusz_window")
        if isinstance(document_path, Path) and veusz_window is not None:
            veusz_window.document.save(str(document_path))
            refine_status.setText(f"Saved Veusz document · {document_path}")

    def undo_current() -> None:
        veusz_window = state.get("veusz_window")
        if veusz_window is not None and veusz_window.document.canUndo():
            veusz_window.document.undoOperation()

    def redo_current() -> None:
        veusz_window = state.get("veusz_window")
        if veusz_window is not None and veusz_window.document.canRedo():
            veusz_window.document.redoOperation()

    def export_current() -> None:
        try:
            document_path = state.get("document_path")
            project_dir = state.get("project_dir")
            request_path = state.get("request_path")
            veusz_window = state.get("veusz_window")
            if (
                not isinstance(document_path, Path)
                or not isinstance(project_dir, Path)
                or not isinstance(request_path, Path)
            ):
                return
            if veusz_window is not None:
                veusz_window.document.save(str(document_path))
            formats = state.get("exports") if isinstance(state.get("exports"), list) else list(EXPORT_FORMATS)
            exports = export_studio_document(document_path, formats=[str(item) for item in formats])["exports"]
            studio_run = publish_studio_export_run(
                project_dir=project_dir,
                request_path=request_path,
                document_path=document_path,
                exports=exports,
            )
            _register_studio_exports(project_dir, exports, studio_run=studio_run)
            status_label.setText(f"Exported through SciPlot QA:\n{studio_run['output']}")
            refine_status.setText(f"Exported through SciPlot QA · {studio_run['output']}")
        except Exception as exc:
            QtWidgets.QMessageBox.critical(shell, "SciPlot Studio", str(exc))

    generate_button.clicked.connect(generate)
    export_button.clicked.connect(export_current)
    move_up_button.clicked.connect(lambda: _move_table_row(groups_table, -1))
    move_down_button.clicked.connect(lambda: _move_table_row(groups_table, 1))
    back_action.triggered.connect(lambda: stack.setCurrentWidget(setup_workspace))
    generate_action.triggered.connect(generate)
    save_action.triggered.connect(save_current)
    undo_action.triggered.connect(undo_current)
    redo_action.triggered.connect(redo_current)
    export_action.triggered.connect(export_current)
    if template or project_name:
        generate()
    return shell


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


def _manifest_project_name(project_dir: Path) -> str | None:
    for manifest_path in [project_dir / "intake_manifest.json", *sorted(project_dir.glob("*.sciplot.json"))]:
        if not manifest_path.exists():
            continue
        try:
            payload = _read_json(manifest_path)
        except Exception:
            continue
        value = payload.get("project_name")
        if isinstance(value, str) and value.strip():
            return value.strip()
    return None


def _studio_template_choices() -> list[tuple[str, str]]:
    try:
        from sciplot_core.contract import load_plot_contract

        contract = load_plot_contract()
        choices: list[tuple[str, str]] = []
        for template_id in STUDIO_TEMPLATE_IDS:
            spec = contract.templates.get(template_id)
            label = getattr(spec, "label", None) or template_id.replace("_", " ").title()
            choices.append((template_id, f"{label} ({template_id})"))
        return choices
    except Exception:
        return [
            ("curve", "Curve (curve)"),
            ("stacked_curve", "Stacked curve (stacked_curve)"),
            ("segmented_stacked_curve", "Segmented stacked curve (segmented_stacked_curve)"),
        ]


def _normalize_optional_string(value: str | None) -> str | None:
    if not isinstance(value, str):
        return None
    stripped = value.strip()
    return stripped or None


def _is_raw_studio_source(path: Path) -> bool:
    if path.suffix.lower() in {".vsz", ".json"}:
        return False
    if path.is_dir() and (path / "plot_request.json").exists():
        return False
    return path.exists()


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
    return text.count("Add('xy',")


def _template_from_session(session: dict[str, Any]) -> str:
    experiment_type = str(session.get("experiment_type_id") or "").casefold()
    if "spectrum" in experiment_type or "stack" in experiment_type:
        return "stacked_curve"
    return "curve"


def _session_groups(session: dict[str, Any]) -> list[dict[str, Any]]:
    groups = session.get("groups") if isinstance(session.get("groups"), list) else []
    normalized = [group for group in groups if isinstance(group, dict)]
    if normalized:
        return normalized
    source = Path(str(session.get("input_path") or "source")).expanduser()
    return [{"sample": source.stem or source.name or "Sample 1", "files": []}]


def _session_summary(session: dict[str, Any]) -> str:
    label = session.get("experiment_label") or session.get("experiment_type_id") or "Unknown"
    confidence = session.get("confidence")
    reason = session.get("reason") or ""
    return f"Detected: {label}\nConfidence: {confidence}\n{reason}"


def _populate_groups_table(table: Any, groups: list[dict[str, Any]]) -> None:
    from PyQt6 import QtCore, QtWidgets

    table.setRowCount(len(groups))
    for row, group in enumerate(groups):
        files = group.get("files") if isinstance(group.get("files"), list) else []
        filenames = ", ".join(
            str(item.get("name") or item.get("source_path") or "") for item in files if isinstance(item, dict)
        )
        sample_item = QtWidgets.QTableWidgetItem(str(group.get("sample") or f"Sample {row + 1}"))
        sample_item.setData(QtCore.Qt.ItemDataRole.UserRole, row)
        table.setItem(row, 0, sample_item)
        files_item = QtWidgets.QTableWidgetItem(filenames)
        files_item.setData(QtCore.Qt.ItemDataRole.UserRole, row)
        table.setItem(row, 1, files_item)


def _groups_from_table(table: Any, original_groups: list[dict[str, Any]]) -> list[dict[str, Any]]:
    from PyQt6 import QtCore

    groups: list[dict[str, Any]] = []
    for row in range(table.rowCount()):
        item = table.item(row, 0)
        source_index = item.data(QtCore.Qt.ItemDataRole.UserRole) if item is not None else row
        try:
            source_group = original_groups[int(source_index)]
        except (IndexError, TypeError, ValueError):
            source_group = original_groups[row] if row < len(original_groups) else {}
        sample = item.text().strip() if item is not None else ""
        updated = dict(source_group)
        updated["sample"] = sample or str(source_group.get("sample") or f"Sample {row + 1}")
        groups.append(updated)
    return groups


def _move_table_row(table: Any, direction: int) -> None:
    row = table.currentRow()
    target = row + direction
    if row < 0 or target < 0 or target >= table.rowCount():
        return
    column_count = table.columnCount()
    row_items = [table.takeItem(row, column) for column in range(column_count)]
    target_items = [table.takeItem(target, column) for column in range(column_count)]
    for column, item in enumerate(target_items):
        table.setItem(row, column, item)
    for column, item in enumerate(row_items):
        table.setItem(target, column, item)
    table.setCurrentCell(target, 0)


def _panel_render_options(
    *,
    size: str,
    x_label: str,
    y_label: str,
    x_min: str,
    x_max: str,
    reverse_x: bool,
    xscale: str,
    yscale: str,
    series_label_mode: str,
) -> dict[str, Any]:
    options: dict[str, Any] = {"size": size, "series_label_mode": series_label_mode}
    x_label_value = _normalize_optional_string(x_label)
    y_label_value = _normalize_optional_string(y_label)
    if x_label_value:
        options["x_label_override"] = x_label_value
    if y_label_value:
        options["y_label_override"] = y_label_value
    x_min_value = _optional_float(x_min)
    x_max_value = _optional_float(x_max)
    if x_min_value is not None:
        options["x_min"] = x_min_value
    if x_max_value is not None:
        options["x_max"] = x_max_value
    if reverse_x:
        options["reverse_x"] = True
    if xscale == "log":
        options["xscale"] = "log"
    if yscale == "log":
        options["yscale"] = "log"
    return options


def _apply_panel_request_options(
    project_dir: Path,
    *,
    request_path: Path,
    exports: list[str],
    render_options: dict[str, Any],
) -> None:
    if request_path.exists():
        request = _read_json(request_path)
        request["exports"] = exports
        existing_options = request.get("render_options") if isinstance(request.get("render_options"), dict) else {}
        request["render_options"] = {**existing_options, **render_options}
        request_path.write_text(json.dumps(json_safe(request), indent=2, ensure_ascii=False), encoding="utf-8")
    for manifest_path in [project_dir / "intake_manifest.json", *sorted(project_dir.glob("*.sciplot.json"))]:
        if not manifest_path.exists():
            continue
        payload = _read_json(manifest_path)
        plot_options = payload.get("plot_options") if isinstance(payload.get("plot_options"), dict) else {}
        existing_render = (
            plot_options.get("render_options")
            if isinstance(plot_options.get("render_options"), dict)
            else {}
        )
        payload["plot_options"] = {
            **plot_options,
            "exports": exports,
            "render_options": {**existing_render, **render_options},
        }
        manifest_path.write_text(json.dumps(json_safe(payload), indent=2, ensure_ascii=False), encoding="utf-8")


def export_studio_document(document_path: Path, *, formats: list[str]) -> dict[str, Any]:
    stderr_log = document_path.parent / "logs" / "veusz_export_stderr.log"
    exports: list[dict[str, Any]] = []
    with _capture_process_stderr(stderr_log):
        _prefer_offscreen_export_platform()
        _ensure_veusz_on_path()
        from PyQt6 import QtWidgets
        from veusz import dataimport, document, widgets
        from veusz.document import CommandInterface

        _ = dataimport, widgets
        app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
        try:
            doc = document.Document()
            doc.load(str(document_path))
            interface = CommandInterface(doc)
            export_dir = document_path.parent / "exports"
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
            app.quit()
    payload: dict[str, Any] = {"kind": "sciplot_studio_export", "document": str(document_path), "exports": exports}
    if stderr_log.exists():
        payload["stderr_log"] = str(stderr_log)
    return payload


def publish_studio_export_run(
    *,
    project_dir: Path,
    request_path: Path,
    document_path: Path,
    exports: list[dict[str, Any]],
) -> dict[str, Any]:
    request = _read_json(request_path)
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
    processed_source = _write_studio_data_snapshot(input_path, output_dir) if input_path is not None else None
    _write_studio_analysis_report(output_dir, request=request, document_path=document_path, figures=figures)
    qa = _run_studio_qa(output_dir)
    layout_quality = _studio_layout_quality_from_spec(document_path)
    result = {
        "kind": "sciplot_studio_export_result",
        "engine": "veusz",
        "render_engine": "veusz",
        "qa_target": "veusz_export",
        "document": str(document_path),
        "veusz_document": str(document_path),
        "veusz_spec": str(_veusz_spec_path(document_path)),
        "export_formats": [str(item.get("format")) for item in copied_exports if item.get("format")],
        "exports": copied_exports,
        "outputs": figures,
        "processed": processed_source is not None,
        "processed_source": str(processed_source) if processed_source is not None else None,
        "template": request.get("template") or request.get("recipe") or "veusz_document",
        "operation_mode": normal_mode_payload(route="studio"),
    }
    manifest = {
        "kind": "sciplot_run",
        "created_at": datetime.now(UTC).isoformat(),
        "request_path": str(request_path),
        "request": json_safe(request),
        "route": "studio",
        "semantic": {
            "semantic_family": "veusz_document",
            "rule_id": request.get("rule_id"),
            "reason": "Exported from the native Veusz document embedded in SciPlot Studio.",
        },
        "final_recipe": None,
        "input": str(input_path) if input_path is not None else "",
        "raw_archive": json_safe(raw_archive),
        "output": str(output_dir),
        "figures": figures,
        "result": json_safe(result),
        "study_model": json_safe(request.get("study_model") if isinstance(request.get("study_model"), dict) else {}),
        "qa": qa,
        "render_engine": "veusz",
        "qa_target": "veusz_export",
        "veusz_document": str(document_path),
        "veusz_spec": str(_veusz_spec_path(document_path)),
        "manual_edit_hash": _hash_file(document_path),
        "layout_policy": {
            "kind": "sciplot_layout_policy",
            "policy_id": "veusz_native_document",
            "review_mode": "native_veusz_editor",
        },
        "layout_quality": layout_quality,
        "operation_mode": normal_mode_payload(route="studio"),
        "studio": {
            "engine": "veusz",
            "render_engine": "veusz",
            "qa_target": "veusz_export",
            "document": str(document_path),
            "spec": str(_veusz_spec_path(document_path)),
            "manual_edit_hash": _hash_file(document_path),
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
    }


def _resolve_studio_target(
    path: Path,
    *,
    output_root: Path | None = None,
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
            template=template,
            project_name=project_name,
        )
    raise ValueError("studio accepts a SciPlot project directory, plot_request.json, or .vsz document.")


def _qt_first_project_from_source(
    path: Path,
    *,
    output_root: Path | None = None,
    template: str | None = None,
    project_name: str | None = None,
) -> dict[str, Any]:
    project_root = output_root or Path("outputs") / "intake_projects"
    session = prepare_intake_session(path, output_root=project_root)
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
    template: str | None = None,
    project_name: str | None = None,
) -> None:
    selected_template = _normalize_optional_string(template)
    selected_project_name = _normalize_optional_string(project_name)
    if not selected_template and not selected_project_name:
        return
    if request_path.exists():
        request = _read_json(request_path)
        if selected_template:
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
        manifest_path.write_text(json.dumps(json_safe(payload), indent=2, ensure_ascii=False), encoding="utf-8")


def _existing_document_payload(document_path: Path) -> dict[str, Any]:
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
            "spec": str(_veusz_spec_path(document_path)),
            "manual_edit_hash": _hash_file(document_path),
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
    except Exception:
        frames = [(input_path.stem or "source", pd.DataFrame({"source_path": [str(input_path)]}))]
    with pd.ExcelWriter(destination) as writer:
        used_names: set[str] = set()
        for index, (label, frame) in enumerate(frames, start=1):
            sheet_name = _excel_sheet_name(label, fallback=f"data_{index}", used=used_names)
            frame.to_excel(writer, sheet_name=sheet_name, index=False)
    return destination


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


def _run_studio_qa(output_dir: Path) -> dict[str, Any]:
    try:
        return run_qa(output_dir)
    except ValueError as exc:
        return {
            "status": "skipped",
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


def _write_studio_analysis_report(
    output_dir: Path,
    *,
    request: dict[str, Any],
    document_path: Path,
    figures: list[str],
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
        "## Review Notes",
        "",
        *(f"- {note}" for note in notes),
    ]
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


def _series_from_request(request: dict[str, Any], *, base_dir: Path) -> tuple[list[StudioSeries], dict[str, str]]:
    input_value = request.get("input")
    if not isinstance(input_value, str) or not input_value.strip():
        raise ValueError("plot_request.json needs an input path for Studio document generation.")
    source = Path(input_value).expanduser()
    if not source.is_absolute():
        source = (base_dir / source).resolve()
    render_options = _effective_render_options(request)
    source = _studio_source_for_request(source, request=request, base_dir=base_dir)
    frames = _read_source_frames(source, request=request)
    metric_pair = _preferred_metric_pair(request)
    raw_series: list[StudioSeries] = []
    axis_info = {"x_label": "x", "y_label": "y"}
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
            if metric_pair is not None and len(pairs) == 1:
                label = source_label
            else:
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
        raw_series = [
            StudioSeries(
                label="SciPlot placeholder",
                x_name="x_1_1",
                y_name="y_1_1",
                x_values=(0.0, 1.0),
                y_values=(0.0, 1.0),
                color=DEFAULT_PALETTE[0],
            )
        ]

    render_options = _apply_domain_render_defaults(render_options, request=request, axis_info=axis_info)
    styled = _apply_series_options(raw_series, render_options=render_options, request=request)
    styled = _apply_template_series_transforms(styled, request=request, render_options=render_options)
    axis_info["x_label"] = str(render_options.get("x_label_override") or axis_info["x_label"])
    axis_info["y_label"] = str(render_options.get("y_label_override") or axis_info["y_label"])
    return styled, axis_info


def _studio_source_for_request(source: Path, *, request: dict[str, Any], base_dir: Path) -> Path:
    rule_id = str(request.get("rule_id") or "").strip()
    if rule_id != "tensile_curve":
        return source
    from sciplot_core.semantic import classify_source, prepare_semantic_source

    output_dir = base_dir / "studio"
    semantic = classify_source(source, requested_rule_id=rule_id)
    prepared = prepare_semantic_source(
        source,
        output_dir=output_dir,
        semantic=semantic,
        series_order=request.get("series_order"),
        column_confirmations=request.get("column_confirmations"),
        replicate_mode=request.get("replicate_mode"),
    )
    prepared_source = prepared.get("source")
    if isinstance(prepared_source, str) and prepared_source.strip():
        return Path(prepared_source).expanduser()
    return source


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
    separator = "\t" if suffix == ".tsv" or "\t" in text else None
    return pd.read_csv(StringIO(text), sep=separator, engine="python")


def _coerced_numeric_frame(frame: pd.DataFrame) -> pd.DataFrame:
    numeric = frame.apply(pd.to_numeric, errors="coerce")
    useful_columns = [column for column in numeric.columns if numeric[column].notna().sum() >= 2]
    return numeric[useful_columns].dropna(how="all")


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
        first_figure = figure_queue[0] if isinstance(figure_queue[0], dict) else {}
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
    "loss_modulus": ("loss modulus", "g\"", "g double prime"),
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
        "c",
        "degc",
        "hz",
        "mn·m",
        "mpa",
        "mpa·s",
        "nm",
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
    default_line_width = _default_line_width(render_options)
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
    for index, item in enumerate(ordered):
        style = style_by_label.get(item.label, {})
        if style.get("visible") is False or style.get("enabled") is False:
            continue
        styled.append(
            StudioSeries(
                label=item.label,
                x_name=item.x_name,
                y_name=item.y_name,
                x_values=item.x_values,
                y_values=item.y_values,
                color=str(style.get("color") or palette[index % len(palette)]),
                line_width=_optional_float(style.get("line_width")) or default_line_width,
                marker=style.get("marker", item.marker or "none"),
                marker_size=_optional_float(style.get("marker_size")),
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
        family = tuple(str(item) for item in style.typography.font_family)
        return _VeuszStyleContract(
            font_family=family[0] if family else "Arial",
            font_size_pt=float(style.typography.font_size_pt),
            legend_font_size_pt=float(style.typography.legend_font_size_pt),
            axis_linewidth_pt=float(style.stroke.axis_linewidth_pt),
            tick_width_pt=float(style.stroke.tick_width_pt),
            tick_length_pt=float(style.stroke.tick_length_pt),
            minor_tick_width_pt=float(style.stroke.minor_tick_width_pt),
            minor_tick_length_pt=float(style.stroke.minor_tick_length_pt),
            line_width_pt=float(style.stroke.line_width_pt),
            line_alpha=float(style.stroke.line_alpha),
            marker_alpha=float(style.stroke.marker_alpha),
            marker_size_pt=float(style.stroke.marker_size_pt),
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
        return _VeuszStyleContract()


def _default_line_width(render_options: dict[str, Any]) -> float:
    return _veusz_style_contract(render_options).line_width_pt


def _apply_domain_render_defaults(
    render_options: dict[str, Any],
    *,
    request: dict[str, Any],
    axis_info: dict[str, str],
) -> dict[str, Any]:
    updated = dict(render_options)
    explicit_options = request.get("render_options") if isinstance(request.get("render_options"), dict) else {}
    template_id = _request_template(request)
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
            "palette_preset": "spectrum_journal_8",
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
        updated.setdefault("x_label_override", "Angular frequency (rad/s)")
    if _looks_like_tensile_axis(axis_info):
        updated.setdefault("x_label_override", "Tensile Strain (%)")
        updated.setdefault("y_label_override", "Tensile Stress (MPa)")
        updated.setdefault("axis_mode", "auto_positive")
    if str(request.get("rule_id") or "").strip() == "rheology_stress_relaxation":
        updated.setdefault("x_label_override", "Time (s)")
        updated.setdefault("y_label_override", "Normalized stress ($\\sigma/\\sigma_0$)")
    return updated


def _explicit_render_options(request: dict[str, Any]) -> dict[str, Any]:
    return request.get("render_options") if isinstance(request.get("render_options"), dict) else {}


def _label_load(series: list[StudioSeries]) -> dict[str, int]:
    labels = [str(item.label) for item in series]
    return {
        "series_count": len(labels),
        "max_label_length": max((len(label) for label in labels), default=0),
        "total_label_length": sum(len(label) for label in labels),
        "duplicate_count": len(labels) - len(set(labels)),
    }


def _legend_needs_outside_right(series: list[StudioSeries]) -> bool:
    load = _label_load(series)
    return (
        load["series_count"] > 8
        or load["max_label_length"] >= 15
        or load["total_label_length"] >= 90
        or load["duplicate_count"] >= 4
    )


def _wide_size_for_legend(series: list[StudioSeries]) -> str:
    load = _label_load(series)
    if load["series_count"] > 16 or load["total_label_length"] >= 150:
        return "180x55"
    return "120x55"


def _apply_readability_render_defaults(
    render_options: dict[str, Any],
    *,
    request: dict[str, Any],
    axis_info: dict[str, str],
    series: list[StudioSeries],
    template_id: str,
) -> dict[str, Any]:
    updated = dict(render_options)
    explicit_options = _explicit_render_options(request)
    label_mode = str(updated.get("series_label_mode") or "legend").strip().casefold()
    legend_position = str(updated.get("legend_position") or "auto").strip().casefold()
    autofixes = _string_list(updated.get("_autofixes_applied"))

    if template_id in STACKED_TEMPLATE_IDS:
        if label_mode in {"inline", "edge", "auto"} and len(series) > 1:
            updated.setdefault("series_label_offset_fraction", 0.018)
            updated.setdefault("series_label_vertical_align", "bottom")
            autofixes.append("direct_label_offset")
        if autofixes:
            updated["_autofixes_applied"] = sorted(set(autofixes))
        return updated

    if legend_position in {"", "auto"} and label_mode in {"", "auto", "legend"}:
        if _legend_needs_outside_right(series):
            updated["legend_position"] = "outside_right"
            updated["series_label_mode"] = "legend"
            if "size" not in explicit_options:
                updated["size"] = _wide_size_for_legend(series)
            autofixes.append("legend_auto_outside_right")
        elif _looks_like_torque_axis(axis_info) or str(request.get("rule_id") or "").strip() == "torque_curve":
            updated["legend_position"] = "upper_right"
            updated["series_label_mode"] = "legend"
            autofixes.append("legend_auto_upper_right")

    if autofixes:
        updated["_autofixes_applied"] = sorted(set(autofixes))
    return updated


def _adapt_style_for_legend(
    style: _VeuszStyleContract,
    *,
    legend_mode: str,
    series: list[StudioSeries],
) -> _VeuszStyleContract:
    if legend_mode != "outside_right":
        return style
    load = _label_load(series)
    required = 30.0
    if load["series_count"] > 12 or load["max_label_length"] >= 15:
        required = 39.0
    if load["series_count"] > 20 or load["total_label_length"] >= 150:
        required = 52.0
    return replace(style, right_margin_mm=max(style.right_margin_mm, required))


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


def _looks_like_wavenumber_axis(axis_info: dict[str, str]) -> bool:
    text = " ".join(str(value) for value in axis_info.values()).casefold()
    return "wavenumber" in text or ("cm" in text and ("-1" in text or "−1" in text or "^{-1}" in text))


def _looks_like_torque_axis(axis_info: dict[str, str]) -> bool:
    text = " ".join(str(value) for value in axis_info.values()).casefold()
    return "torque" in text or "转矩" in text or "screw" in text


def _looks_like_frequency_axis(axis_info: dict[str, str]) -> bool:
    text = " ".join(str(value) for value in axis_info.values()).casefold()
    return "frequency" in text or "angular" in text or "rad/s" in text or "hz" in text


def _looks_like_tensile_axis(axis_info: dict[str, str]) -> bool:
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
    axis_info: dict[str, str],
) -> Path:
    render_options = _effective_render_options(request)
    render_options = _apply_domain_render_defaults(render_options, request=request, axis_info=axis_info)
    template_id = _request_template(request)
    render_options = _apply_readability_render_defaults(
        render_options,
        request=request,
        axis_info=axis_info,
        series=series,
        template_id=template_id,
    )
    legend_mode = _veusz_legend_mode(render_options, template_id=template_id)
    style = _veusz_style_contract(render_options)
    style = _adapt_style_for_legend(style, legend_mode=legend_mode, series=series)
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
    _save_veusz_document_from_spec(path, spec)
    generate_log = path.parent / "logs" / "veusz_generate_stderr.log"
    if generate_log.exists():
        spec["stderr_logs"] = {"generate": str(generate_log)}
    spec_path = _veusz_spec_path(path)
    spec_path.write_text(json.dumps(json_safe(spec), indent=2, ensure_ascii=False), encoding="utf-8")
    return spec_path


def _build_veusz_plot_spec(
    *,
    request: dict[str, Any],
    render_options: dict[str, Any],
    template_id: str,
    series: list[StudioSeries],
    axis_info: dict[str, str],
    axis_contract: _VeuszAxisContract,
    style: _VeuszStyleContract,
    width_mm: float,
    height_mm: float,
    legend_mode: str,
    show_key: bool,
    show_direct_labels: bool,
) -> dict[str, Any]:
    label_specs: list[dict[str, Any]] = []
    if show_direct_labels:
        side = str(render_options.get("series_label_side") or "auto").strip().casefold()
        reverse_x = render_options.get("reverse_x") is True
        if side not in {"left", "right"}:
            side = "left" if reverse_x else "right"
        align = "left" if side == "left" else "right"
        label_size = max(style.legend_font_size_pt, min(style.font_size_pt, 6.2))
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
    if (
        show_key
        and template_id not in STACKED_TEMPLATE_IDS
        and legend_mode != "outside_right"
        and _legend_needs_outside_right(series)
    ):
        layout_issues.append(
            {
                "id": "legend_crowded_inside",
                "severity": "warning",
                "message": "A crowded curve legend remains inside the plot area.",
            }
        )
    legend_spec = {
        "show": show_key,
        "columns": _legend_columns(series_count=len(series), mode=legend_mode),
        "mode": legend_mode,
    }
    if show_key:
        legend_spec["label_load"] = label_load
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
        "autofixes_applied": _string_list(render_options.get("_autofixes_applied")),
        "layout_issues": layout_issues,
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
                "min": axis_contract.x_min,
                "max": axis_contract.x_max,
                "ticks": list(axis_contract.x_ticks),
                "reverse": render_options.get("reverse_x") is True,
            },
            "y": {
                "label": axis_info["y_label"],
                "scale": _axis_scale(render_options, "y"),
                "min": axis_contract.y_min,
                "max": axis_contract.y_max,
                "ticks": list(axis_contract.y_ticks),
                "show_ticks": render_options.get("show_y_ticks") is not False,
            },
        },
        "legend": legend_spec,
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
                "marker": str(MARKER_MAP.get(item.marker, item.marker or "none")),
                "marker_size_pt": item.marker_size,
            }
            for index, item in enumerate(series, start=1)
        ],
        "direct_labels": label_specs,
    }


def _save_veusz_document_from_spec(path: Path, spec: dict[str, Any]) -> None:
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


def _apply_veusz_spec(interface: Any, spec: dict[str, Any]) -> None:
    style = spec["style"]
    axes = spec["axes"]
    size_mm = spec["size_mm"]
    for item in spec["series"]:
        x_data = "\n".join(f"{float(value):.12g}" for value in item["x_values"])
        y_data = "\n".join(f"{float(value):.12g}" for value in item["y_values"])
        interface.ImportString(f"{item['x_name']}(numeric)", x_data)
        interface.ImportString(f"{item['y_name']}(numeric)", y_data)
    interface.Set("StyleSheet/Font/font", style["font_family"])
    interface.Set("StyleSheet/Font/size", _pt(float(style["font_size_pt"])))
    interface.Set("StyleSheet/Line/width", _pt(float(style["line_width_pt"])))
    interface.Set("width", f"{float(size_mm[0]):g}mm")
    interface.Set("height", f"{float(size_mm[1]):g}mm")
    interface.Add("page", name="page1", autoadd=False)
    interface.To("page1")
    interface.Set("width", f"{float(size_mm[0]):g}mm")
    interface.Set("height", f"{float(size_mm[1]):g}mm")
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
    legend = spec["legend"]
    if legend["show"]:
        interface.Add("key", name="key1", autoadd=False)
        interface.To("key1")
        interface.Set("title", "")
        interface.Set("Text/size", _pt(float(style["legend_font_size_pt"])))
        interface.Set("keyLength", "0.40cm")
        interface.Set("marginSize", 0.15)
        interface.Set("columns", int(legend["columns"]))
        _apply_key_position(interface, str(legend.get("mode") or "inside_best"))
        interface.Set("Background/hide", not bool(style["legend_frameon"]))
        interface.Set("Border/hide", not bool(style["legend_frameon"]))
        interface.To("..")
    for item in spec["series"]:
        interface.Add("xy", name=item["name"], autoadd=False)
        interface.To(item["name"])
        interface.Set("xData", item["x_name"])
        interface.Set("yData", item["y_name"])
        interface.Set("key", item["label"])
        interface.Set("PlotLine/color", item["color"])
        interface.Set("MarkerFill/color", item["color"])
        interface.Set("MarkerLine/color", item["color"])
        interface.Set("marker", item["marker"])
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
        interface.To("..")
    for item in spec["direct_labels"]:
        interface.Add("label", name=item["name"], autoadd=False)
        interface.To(item["name"])
        interface.Set("positioning", "axes")
        interface.Set("xPos", [float(item["x"])])
        interface.Set("yPos", [float(item["y"])])
        interface.Set("label", item["label"])
        interface.Set("alignHorz", item["align"])
        interface.Set("alignVert", item.get("valign") or "centre")
        interface.Set("margin", "1pt" if item.get("valign") == "bottom" else "0pt")
        interface.Set("Text/size", _pt(float(item["size_pt"])))
        interface.Set("Text/color", item["color"])
        interface.Set("Background/hide", True)
        interface.Set("Border/hide", True)
        interface.To("..")
    interface.To("..")
    interface.To("..")


def _apply_key_position(interface: Any, mode: str) -> None:
    normalized = str(mode or "inside_best").strip().casefold()
    if normalized == "outside_right":
        interface.Set("horzPosn", "manual")
        interface.Set("horzManual", 1.02)
        interface.Set("vertPosn", "top")
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
    interface.Set("autoMirror", False)
    interface.Set("outerticks", True)
    interface.Set("Line/color", "black")
    interface.Set("Line/width", _pt(float(style["axis_linewidth_pt"])))
    interface.Set("MajorTicks/width", _pt(float(style["tick_width_pt"])))
    interface.Set("MajorTicks/length", _pt(float(style["tick_length_pt"])))
    interface.Set("MinorTicks/width", _pt(float(style["minor_tick_width_pt"])))
    interface.Set("MinorTicks/length", _pt(float(style["minor_tick_length_pt"])))
    interface.Set("Label/size", _pt(float(style["font_size_pt"])))
    interface.Set("Label/offset", _pt(float(style["axes_labelpad_pt"])))
    interface.Set("TickLabels/size", _pt(float(style["font_size_pt"])))
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


def _import_string_lines(name: str, values: tuple[float, ...]) -> list[str]:
    body = "\n".join(f"{value:.12g}" for value in values)
    return [f"ImportString({_py_string(name + '(numeric)')},'''", body, "''')"]


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
    x_min = _optional_float(render_options.get("x_min"))
    x_max = _optional_float(render_options.get("x_max"))
    y_min = _optional_float(render_options.get("y_min"))
    y_max = _optional_float(render_options.get("y_max"))
    x_ticks: tuple[float, ...] = ()
    y_ticks: tuple[float, ...] = ()

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
            if limits.x_tick_policy is not None:
                x_ticks = tuple(float(value) for value in limits.x_tick_policy.major_ticks)
            if limits.y_tick_policy is not None:
                y_ticks = tuple(float(value) for value in limits.y_tick_policy.major_ticks)
        except Exception:
            pass

    reverse_x = render_options.get("reverse_x") is True
    if reverse_x and x_min is not None and x_max is not None:
        x_min, x_max = x_max, x_min
    if x_ticks and x_min is not None and x_max is not None:
        low = min(x_min, x_max)
        high = max(x_min, x_max)
        tick_values = [x_min, *x_ticks, x_max] if reverse_x else list(x_ticks)
        deduped: list[float] = []
        for value in tick_values:
            if value < low - 1e-9 or value > high + 1e-9:
                continue
            if not any(math.isclose(value, existing) for existing in deduped):
                deduped.append(value)
        x_ticks = tuple(sorted(deduped, reverse=x_min > x_max))
    return _VeuszAxisContract(
        x_min=x_min,
        x_max=x_max,
        y_min=y_min,
        y_max=y_max,
        x_ticks=x_ticks,
        y_ticks=y_ticks,
    )


def _veusz_legend_mode(render_options: dict[str, Any], *, template_id: str) -> str:
    legend_position = str(render_options.get("legend_position") or "auto").strip().casefold()
    if legend_position in {"none", "hide", "hidden", "off"}:
        return "none"
    if legend_position in {"outside_right", "upper_right", "upper_left", "lower_left", "lower_right"}:
        return legend_position
    if template_id in STACKED_TEMPLATE_IDS:
        label_mode = str(render_options.get("series_label_mode") or "").casefold()
        return "none" if label_mode in {"inline", "edge"} else "upper_right"
    return "inside_best"


def _axis_style_lines(
    style: _VeuszStyleContract,
    *,
    axis: str,
    render_options: dict[str, Any],
) -> list[str]:
    tick_offset = style.xtick_major_pad_pt if axis == "x" else style.ytick_major_pad_pt
    lines = [
        "Set('autoMirror', False)",
        "Set('outerticks', True)",
        "Set('Line/color', 'black')",
        f"Set('Line/width', '{_pt(style.axis_linewidth_pt)}')",
        f"Set('MajorTicks/width', '{_pt(style.tick_width_pt)}')",
        f"Set('MajorTicks/length', '{_pt(style.tick_length_pt)}')",
        f"Set('MinorTicks/width', '{_pt(style.minor_tick_width_pt)}')",
        f"Set('MinorTicks/length', '{_pt(style.minor_tick_length_pt)}')",
        f"Set('Label/size', '{_pt(style.font_size_pt)}')",
        f"Set('Label/offset', '{_pt(style.axes_labelpad_pt)}')",
        f"Set('TickLabels/size', '{_pt(style.font_size_pt)}')",
        f"Set('TickLabels/offset', '{_pt(tick_offset)}')",
    ]
    if axis == "y" and render_options.get("show_y_ticks") is False:
        lines.extend(
            [
                "Set('MajorTicks/hide', True)",
                "Set('MinorTicks/hide', True)",
                "Set('TickLabels/hide', True)",
            ]
        )
    return lines


def _axis_range_lines(
    render_options: dict[str, Any],
    *,
    axis: str,
    axis_contract: _VeuszAxisContract,
) -> list[str]:
    lines: list[str] = []
    min_value = axis_contract.x_min if axis == "x" else axis_contract.y_min
    max_value = axis_contract.x_max if axis == "x" else axis_contract.y_max
    if min_value is not None:
        lines.append(f"Set('min', {min_value!r})")
    if max_value is not None:
        lines.append(f"Set('max', {max_value!r})")
    ticks = axis_contract.x_ticks if axis == "x" else axis_contract.y_ticks
    if 1 < len(ticks) <= 12:
        lines.append(f"Set('MajorTicks/manualTicks', {list(ticks)!r})")
    if _axis_scale(render_options, axis) == "log":
        lines.append("Set('log', True)")
    return lines


def _graph_margin_lines(style: _VeuszStyleContract) -> list[str]:
    left = _cm_from_mm(style.left_margin_mm)
    right = _cm_from_mm(style.right_margin_mm)
    top = _cm_from_mm(style.top_margin_mm)
    bottom = _cm_from_mm(style.bottom_margin_mm)
    return [
        f"Set('leftMargin', '{left}')",
        f"Set('rightMargin', '{right}')",
        f"Set('topMargin', '{top}')",
        f"Set('bottomMargin', '{bottom}')",
    ]


def _legend_columns(*, series_count: int, mode: str = "inside_best") -> int:
    if series_count <= 1:
        return 1
    if mode == "outside_right":
        if series_count > 24:
            return 3
        if series_count > 12:
            return 2
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


def _direct_label_lines(
    series: list[StudioSeries],
    *,
    render_options: dict[str, Any],
    style: _VeuszStyleContract,
) -> list[str]:
    side = str(render_options.get("series_label_side") or "auto").strip().casefold()
    reverse_x = render_options.get("reverse_x") is True
    if side not in {"left", "right"}:
        side = "left" if reverse_x else "right"
    align = "left" if side == "left" else "right"
    label_size = max(style.legend_font_size_pt, min(style.font_size_pt, 6.2))
    lines: list[str] = []
    for index, item in enumerate(series, start=1):
        anchor = _series_label_anchor(item, reverse_x=reverse_x, side=side)
        if anchor is None:
            continue
        x_pos, y_pos = anchor
        lines.extend(
            [
                f"Add('label', name='label_{index}', autoadd=False)",
                f"To('label_{index}')",
                "Set('positioning', 'axes')",
                f"Set('xPos', [{x_pos!r}])",
                f"Set('yPos', [{y_pos!r}])",
                f"Set('label', {_py_string(item.label)})",
                f"Set('alignHorz', {_py_string(align)})",
                "Set('alignVert', 'centre')",
                "Set('margin', '0pt')",
                f"Set('Text/size', '{_pt(label_size)}')",
                f"Set('Text/color', {_py_string(item.color)})",
                "Set('Background/hide', True)",
                "Set('Border/hide', True)",
                "To('..')",
            ]
        )
    return lines


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
    if series_count <= 1:
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
    launcher.write_text(
        "\n".join(
            [
                "#!/bin/zsh",
                "set -euo pipefail",
                'PROJECT_DIR="${0:A:h}"',
                f'cd "{REPO_ROOT}"',
                'skill/scripts/sciplot studio "${PROJECT_DIR}"',
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    launcher.chmod(0o755)
    return launcher


def _veusz_spec_path(document_path: Path) -> Path:
    if document_path.name == "document.vsz":
        return document_path.parent / "spec.json"
    return document_path.with_suffix(".spec.json")


def _hash_file(path: Path) -> str | None:
    if not path.exists() or not path.is_file():
        return None
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _registered_generated_hash(project_dir: Path) -> str | None:
    for manifest_path in [project_dir / "intake_manifest.json", *sorted(project_dir.glob("*.sciplot.json"))]:
        if not manifest_path.exists():
            continue
        try:
            payload = _read_json(manifest_path)
        except Exception:
            continue
        studio = payload.get("studio") if isinstance(payload.get("studio"), dict) else {}
        value = studio.get("generated_hash") or studio.get("manual_edit_hash")
        if isinstance(value, str) and value.strip():
            return value
    return None


def _archive_manual_document_if_needed(project_dir: Path, document_path: Path) -> None:
    if not document_path.exists():
        return
    current_hash = _hash_file(document_path)
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
    request_path: Path,
    series_count: int,
    generated_hash: str | None,
) -> dict[str, Any]:
    return {
        "kind": "sciplot_studio_document",
        "engine": "veusz",
        "render_engine": "veusz",
        "qa_target": "veusz_export",
        "status": "ready",
        "document": str(document_path),
        "spec": str(spec_path),
        "launcher": str(launcher),
        "generated_from": str(request_path),
        "series_count": series_count,
        "generated_hash": generated_hash,
        "manual_edit_hash": _hash_file(document_path),
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
    if normalized == "png":
        return ".png", 150
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


def _py_string(value: str) -> str:
    return repr(value)


__all__ = [
    "export_studio_document",
    "maybe_reexec_with_qt_runtime",
    "prepare_studio_document",
    "qt_smoke_payload",
    "run_studio_command",
    "upstream_status",
]
