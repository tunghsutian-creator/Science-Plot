from __future__ import annotations

import sys
from pathlib import Path

from sciplot_gui.workspace import resolve_canvas_workspace


def launch_canvas_application(
    target: Path,
    *,
    output_root: Path | None = None,
    rule_id: str | None = None,
    template: str | None = None,
    project_name: str | None = None,
) -> int:
    from PyQt6 import QtCore, QtWidgets

    from sciplot_gui.main_window import SciPlotCanvasWindow

    workspace = resolve_canvas_workspace(
        target,
        output_root=output_root,
        rule_id=rule_id,
        template=template,
        project_name=project_name,
    )
    application = QtWidgets.QApplication.instance()
    owns_application = application is None
    if application is None:
        application = QtWidgets.QApplication(sys.argv[:1])
    application.setApplicationName("SciPlot Canvas")
    application.setOrganizationName("SciPlot")
    application.setQuitOnLastWindowClosed(True)
    QtCore.QCoreApplication.setApplicationVersion("0.1.0-m2-dev")
    window = SciPlotCanvasWindow(workspace)
    window.show()
    if not owns_application:
        return 0
    return int(application.exec())


__all__ = ["launch_canvas_application"]
