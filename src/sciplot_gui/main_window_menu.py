"""Attach SciPlot project, export, and assistant actions to a Veusz window."""

from __future__ import annotations

from pathlib import Path
from typing import Any
from sciplot_core.studio_figure_set_contract import (
    is_primary_figure_set_export_scope,
)

from sciplot_core.studio import (
    atomic_save_veusz_document,
    build_studio_figure_set_export_scope,
    configure_studio_window_presentation,
    export_studio_document,
    publish_standalone_export_receipt,
    publish_studio_export_run,
    resolve_studio_project_context,
)


def _attach_sciplot_menu(window: Any, document_path: Path | None) -> None:
    if document_path is None:
        return
    document_key = str(document_path.expanduser().resolve())
    if getattr(window, "_sciplot_attached_document", None) == document_key:
        return
    try:
        from PyQt6 import QtGui
    except Exception:
        return

    context = resolve_studio_project_context(document_path)
    menu = window.menuBar().addMenu("SciPlot")
    actions: list[Any] = []
    try:
        from sciplot_gui.studio_project import (
            attach_studio_project,
            configure_studio_project_services,
        )
        from sciplot_gui.studio_project_services import StudioProjectServices

        configure_studio_project_services(
            StudioProjectServices(
                atomic_save_document=atomic_save_veusz_document,
                export_document=export_studio_document,
                publish_standalone_export=publish_standalone_export_receipt,
                publish_project_export=publish_studio_export_run,
                build_figure_set_scope=build_studio_figure_set_export_scope,
                is_complete_figure_set_scope=is_primary_figure_set_export_scope,
            )
        )

        project = attach_studio_project(
            window,
            document_path,
            project_dir=context["project_dir"] if context is not None else None,
            request_path=context["request_path"] if context is not None else None,
        )
        export_action = QtGui.QAction(
            "Save And Export Exact-Current PDF/TIFF",
            window,
        )
        export_action.setToolTip(
            "Save the current Veusz document, export PDF/TIFF, and run SciPlot "
            "artifact QA. Project packages also build the portable delivery."
        )
        export_action.triggered.connect(project.export_current_document)
        menu.addAction(export_action)
        project.bind_export_action(export_action)
        project_action = project.dock.toggleViewAction()
        project_action.setText("Show SciPlot Project")
        menu.addAction(project_action)
        actions.extend([export_action, project_action])
    except Exception as exc:
        project_unavailable = QtGui.QAction(
            f"SciPlot Project unavailable: {type(exc).__name__}",
            window,
        )
        project_unavailable.setEnabled(False)
        project_unavailable.setToolTip(str(exc))
        menu.addAction(project_unavailable)
        actions.append(project_unavailable)
    try:
        from sciplot_gui.studio_assistant import attach_studio_assistant

        assistant = attach_studio_assistant(window, document_path)
        project = getattr(window, "_sciplot_project_bridge", None)
        if project is not None and hasattr(project, "bind_assistant"):
            project.bind_assistant(assistant)
        menu.addSeparator()
        assistant_action = assistant.dock.toggleViewAction()
        assistant_action.setText("Show SciPlot AI")
        menu.addAction(assistant_action)
        actions.append(assistant_action)
    except Exception as exc:
        assistant_unavailable = QtGui.QAction(
            f"SciPlot AI unavailable: {type(exc).__name__}",
            window,
        )
        assistant_unavailable.setEnabled(False)
        assistant_unavailable.setToolTip(str(exc))
        menu.addSeparator()
        menu.addAction(assistant_unavailable)
        actions.append(assistant_unavailable)
    window._sciplot_actions = getattr(window, "_sciplot_actions", []) + actions
    window._sciplot_attached_document = document_key


def install_studio_window_presentation() -> None:
    """Register the native Veusz menu and docks with the Core window factory."""

    configure_studio_window_presentation(_attach_sciplot_menu)
