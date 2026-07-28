"""Run Qt smoke checks and launch Veusz or SciPlot Studio windows."""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

from sciplot_core.studio_core.runtime import (
    upstream_status,
    _ensure_veusz_on_path,
)

from sciplot_core.studio_core.qt_safety import (
    _mainwindow_close_safety_probe,
)

from sciplot_core.studio_core.qt_window import (
    _create_veusz_window,
)

from sciplot_core.studio_core.studio_prepare import (
    prepare_studio_document,
)


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
    close_safety = _mainwindow_close_safety_probe(window)
    selected_widgets = getattr(window.treeedit, "selwidgets", [])
    selected_widget_path = (
        str(selected_widgets[0].path)
        if isinstance(selected_widgets, list) and selected_widgets
        else None
    )
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
        "window_title": window.windowTitle(),
        "initial_widget_path": selected_widget_path,
        "fail_closed_close_installed": bool(
            getattr(type(window).closeEvent, "_sciplot_fail_closed", False)
        ),
        "atomic_save_installed": bool(
            getattr(type(window).slotFileSave, "_sciplot_atomic_save", False)
            and getattr(
                type(window).slotFileSaveAs,
                "_sciplot_atomic_save_as",
                False,
            )
        ),
        "integrated_window_factory_installed": bool(
            getattr(
                getattr(type(window).CreateWindow, "__func__", None),
                "_sciplot_integrated_factory",
                False,
            )
        ),
        "close_safety": close_safety,
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
    delivery_root: Path | None = None,
    rule_id: str | None = None,
    template: str | None = None,
    project_name: str | None = None,
) -> int:
    payload = prepare_studio_document(
        target.expanduser().resolve(),
        output_root=output_root,
        delivery_root=delivery_root,
        rule_id=rule_id,
        template=template,
        project_name=project_name,
    )
    return launch_veusz_gui(Path(payload["document"]))
