"""Confirmation and visible export controls for the native plot editor."""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from typing import Any

from PyQt6 import QtCore, QtGui, QtWidgets

from sciplot_core.archive_plot_view import export_archive_pdf
from sciplot_core.project_lifecycle.errors import EngineError

def confirm(parent: QtWidgets.QWidget, title: str, text: str, *, preview: QtGui.QPixmap | None = None) -> bool:
    dialog = QtWidgets.QDialog(parent)
    dialog.setWindowTitle(title)
    layout = QtWidgets.QVBoxLayout(dialog)
    label = QtWidgets.QLabel(text)
    label.setTextFormat(QtCore.Qt.TextFormat.PlainText)
    label.setWordWrap(True)
    layout.addWidget(label)
    if preview is not None:
        image = QtWidgets.QLabel()
        image.setPixmap(preview.scaled(600, 500, QtCore.Qt.AspectRatioMode.KeepAspectRatio))
        layout.addWidget(image)
    buttons = QtWidgets.QDialogButtonBox(
        QtWidgets.QDialogButtonBox.StandardButton.Save | QtWidgets.QDialogButtonBox.StandardButton.Cancel)
    buttons.accepted.connect(dialog.accept)
    buttons.rejected.connect(dialog.reject)
    layout.addWidget(buttons)
    return dialog.exec() == QtWidgets.QDialog.DialogCode.Accepted


def archive_pdf_action(window: QtWidgets.QMainWindow, plot: Path, status: QtWidgets.QLabel,
                       current: Callable[[], dict[str, Any]]) -> QtGui.QAction:
    action = QtGui.QAction("导出当前图 PDF…", window)
    action.setEnabled(False)
    window.menuBar().addMenu("文件").addAction(action)

    def export() -> None:
        if not action.isEnabled():
            return
        summary = current()
        revision = summary["revision_token"]
        project_id = summary["project_id"]
        filename, _ = QtWidgets.QFileDialog.getSaveFileName(
            window, "导出当前图 PDF", str(plot.with_suffix(".pdf")), "PDF (*.pdf)",
            options=QtWidgets.QFileDialog.Option.DontConfirmOverwrite)
        if not filename:
            return
        output = Path(filename if filename.lower().endswith(".pdf") else f"{filename}.pdf")
        try:
            export_archive_pdf(plot, output, project_id=project_id, revision=revision)
        except FileExistsError:
            status.setText("未导出：目标文件已存在，请另选文件名。")
        except EngineError as exc:
            if exc.reason_code in {"figure_handoff_revision_conflict", "project_file_identity_conflict"}:
                action.setEnabled(False)
                status.setText("未导出：项目或图已更新。请读取最新版本。")
            else:
                status.setText(f"未导出：{exc}")
        except (OSError, ValueError, RuntimeError) as exc:
            status.setText(f"未导出：{exc}")
        else:
            status.setText(f"已导出修订 {revision.revision}：{output}")

    action.triggered.connect(export)
    return action
