"""Receive Finder document events in the bundled Qt application process."""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
import subprocess
import sys
from typing import cast

from PyQt6.QtCore import QEvent, QTimer, Qt
from PyQt6.QtGui import QFileOpenEvent
from PyQt6.QtWidgets import QApplication, QMessageBox

from sciplot_core.project_lifecycle.errors import EngineError
from sciplot_core.project_lifecycle.project_file_summary import project_file_summary


class FinderApplication(QApplication):
    """Dispatch both cold and warm file requests, not just launcher arguments."""

    def __init__(
        self, argv: list[str], open_document: Callable[[Path], None], rejected: Callable[[], None],
    ) -> None:
        self._open_document = open_document
        self._rejected = rejected
        self._received_document_event = False
        super().__init__(argv)

    def start(self, arguments: list[str], welcome: Callable[[], None]) -> None:
        if arguments:
            for argument in arguments:
                self._queue_document(argument)
        else:
            # Give Launch Services' initial open event a turn before Welcome
            # takes over a startup with no document.
            QTimer.singleShot(400, lambda: self._welcome_if_empty(welcome))

    def _welcome_if_empty(self, welcome: Callable[[], None]) -> None:
        if not self._received_document_event:
            welcome()
            self.quit()

    def _queue_document(self, local_path: str) -> None:
        self._received_document_event = True
        path = Path(local_path)
        if path.suffix != ".sciplot":
            QTimer.singleShot(0, self._rejected)
        else:
            # Keep the exact local path: the archive owner checks its type
            # and final symlink rather than reading through a resolved alias.
            QTimer.singleShot(0, lambda: self._open_document(path))

    def event(self, event: QEvent | None) -> bool:
        if event is not None and event.type() == QEvent.Type.FileOpen:
            opened = cast(QFileOpenEvent, event)
            url = opened.url()
            self._queue_document(url.toLocalFile() if not url.isEmpty() else opened.file())
            return True
        return super().event(event)


def main() -> int:
    """Open its saved project summary, or the connection guide without a file."""
    command = Path(__file__).resolve().parents[2] / "MacOS" / "sciplot"
    dialogs: list[QMessageBox] = []

    def message(title: str, detail: str, icon: QMessageBox.Icon) -> None:
        dialog = QMessageBox()
        dialog.setWindowTitle(title)
        dialog.setTextFormat(Qt.TextFormat.PlainText)
        dialog.setText(detail)
        dialog.setIcon(icon)
        dialog.setStandardButtons(QMessageBox.StandardButton.Close)
        dialogs.append(dialog)
        dialog.finished.connect(lambda _: dialogs.remove(dialog))
        dialog.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose)
        dialog.show()
        dialog.raise_()
        dialog.activateWindow()

    def rejected() -> None:
        message("无法打开", "请选择本机的 .sciplot 项目文件。", QMessageBox.Icon.Warning)

    def open_document(path: Path) -> None:
        try:
            result = project_file_summary(path, None)
        except EngineError as error:
            if error.reason_code == "project_file_figure_ambiguous":
                detail = "项目包含多张图。请在命令行或 AI 中指定要查看的图。"
            elif error.reason_code == "project_file_figure_unsupported":
                detail = "这个项目的图格式暂不支持在这里查看。"
            else:
                detail = "无法读取这个项目。请检查文件是否存在，以及是否为有效的 .sciplot 项目。"
            message("无法打开", detail, QMessageBox.Icon.Warning)
            return
        message(
            "SciPlot 项目信息",
            f"{path.name}\n图 ID：{result['plot_id']}\n修订：{result['revision']}\n当前窗口仅查看项目状态。",
            QMessageBox.Icon.Information,
        )

    def show_welcome() -> None:
        subprocess.Popen([str(command), "--welcome"])

    # Positional filenames belong to this launcher, not to Qt's own flags.
    app = FinderApplication(sys.argv[:1], open_document, rejected)
    app.start(sys.argv[1:], show_welcome)
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
