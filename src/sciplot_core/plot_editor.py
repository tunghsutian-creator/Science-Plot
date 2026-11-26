"""A native read-only view with one edit owned by the existing plot protocol."""

from __future__ import annotations

from contextlib import ExitStack, closing
from hashlib import sha256
from importlib import import_module
from pathlib import Path
from typing import Any
from uuid import uuid4

from PyQt6 import QtCore, QtGui, QtWidgets

from sciplot_core.foundation.file_hashing import file_sha256
from sciplot_core.plot_protocol.client import call
from sciplot_core.plot_protocol.paths import TransportError
from sciplot_core.project_lifecycle.contracts import RevisionToken
from sciplot_core.project_lifecycle.errors import EngineError
from sciplot_core.studio_core.qt_compat import ensure_veusz_qsettings_compat
from sciplot_core.studio_core.runtime import ensure_veusz_runtime_path
from sciplot_core.veusz_worker.document_edit import loaded_native_document


class PlotEditor(QtWidgets.QMainWindow):
    def __init__(self, plot: Path, *, socket_path: Path | None, timeout: float, figure_id: str | None = None) -> None:
        super().__init__()
        self.plot = plot
        self.archive = plot.suffix == ".sciplot" and (plot.is_symlink() or not plot.is_dir())
        self.figure_id = figure_id
        self.archive_request: tuple[RevisionToken, dict[str, Any]] | None = None
        self.socket_path = socket_path
        self.timeout = timeout
        self.summary: dict[str, Any] = {}
        self.viewer: Any = None
        self.unconfirmed: tuple[int, str] | None = None
        self.setWindowTitle(f"{plot.name} · SciPlot" if self.archive else "SciPlot · 坐标轴标题")
        self.resize(680, 610)
        body = QtWidgets.QWidget(self)
        self.body_layout = QtWidgets.QVBoxLayout(body)
        self.status = QtWidgets.QLabel()
        self.status.setTextFormat(QtCore.Qt.TextFormat.PlainText)
        self.status.setWordWrap(True)
        self.body_layout.addWidget(self.status)
        form = QtWidgets.QHBoxLayout()
        self.axes = QtWidgets.QComboBox()
        self.axes.setAccessibleName("坐标轴")
        self.label = QtWidgets.QLineEdit()
        self.label.setAccessibleName("新坐标轴标题")
        self.label.setPlaceholderText("新坐标轴标题")
        self.review = QtWidgets.QPushButton("核对并保存…")
        self.retry = QtWidgets.QPushButton("确认上一次保存")
        self.retry.hide()
        self.retry.clicked.connect(self._retry_archive)
        self.refresh = QtWidgets.QPushButton("读取最新版本")
        for widget in (self.axes, self.label, self.review, self.refresh, self.retry):
            form.addWidget(widget)
        self.body_layout.addLayout(form)
        self.setCentralWidget(body)
        self.axes.currentIndexChanged.connect(self._selected_axis)
        self.review.clicked.connect(self._edit)
        self.refresh.clicked.connect(self._refresh)
        ensure_veusz_runtime_path()
        ensure_veusz_qsettings_compat()
        self._refresh(initial=True)

    def _call(self, method: str, **params: Any) -> dict[str, Any]:
        return call(method, {"plot": str(self.plot), **params},
                    socket_path=self.socket_path, timeout=self.timeout)

    def _selected_axis(self) -> None:
        target = self.axes.currentData()
        self.label.setText(self.summary.get("edit_targets", {}).get(target, {}).get("label", ""))
        enabled = target is not None and self.axes.isEnabled() and self.archive_request is None
        self.label.setEnabled(enabled)
        self.review.setEnabled(enabled)

    def _disable_editing(self) -> None:
        self.axes.setEnabled(False)
        self.label.setEnabled(False)
        self.review.setEnabled(False)

    def _refresh(self, initial: bool = False) -> None:
        try:
            self._load_current()
        except (OSError, ValueError, RuntimeError, KeyError) as exc:
            self._disable_editing()
            if initial:
                raise
            self.status.setText(f"未能读取最新版本：{exc}")

    def _load_current(self) -> None:
        if self.archive:
            self._load_archive()
            return
        summary = self._call("plot.describe", description={"scope": "summary"})
        if (summary.get("plot_type"), summary.get("plot_ir_version"), summary.get("plot")) != (
                "ManagedPlot", 2, str(self.plot)):
            raise ValueError("请提供一个现有 Managed v2 图的精确路径，不是项目目录、原始数据或 VSZ。")
        if self.summary and summary["plot_id"] != self.summary["plot_id"]:
            raise ValueError("这个路径上的图已被替换。请关闭窗口，再打开要编辑的图。")
        if self.unconfirmed is not None and summary["revision"] == self.unconfirmed[0]:
            raise ValueError(f"原操作仍未确认。请用原操作编号 {self.unconfirmed[1]} 恢复；不要再提交。")
        publication = summary["export_current"].get("publication", {})
        if summary.get("pending") or summary.get("status") != "current" or not publication.get("ready_to_use"):
            next_action = (summary.get("next_step") or {}).get("action", "plot.export")
            raise ValueError(f"这张图暂不能编辑。请先处理当前操作或恢复已核验的图：{next_action}。")
        self._view(Path(summary["artifact"]), publication["document_sha256"])
        self.unconfirmed = None
        self._show_summary(summary)

    def _show_summary(self, summary: dict[str, Any]) -> None:
        self.summary = summary
        self.axes.setEnabled(self.archive_request is None)
        self.axes.clear()
        self.axes.addItem("选择坐标轴", None)
        for target, edit in summary["edit_targets"].items():
            if "axis.label" in edit["properties"]:
                self.axes.addItem(f"{edit['label']}  ({target})", target)
        self.status.setText(f"修订 {summary['revision']} · {summary['plot_id']}。本窗口只修改坐标轴显示标题。")
        self._selected_axis()
        if self.archive_request is not None:
            self._show_archive_unconfirmed()

    def _load_archive(self) -> None:
        from sciplot_core.archive_plot_view import archive_plot_view

        with ExitStack() as staged:
            summary, native, seal = staged.enter_context(
                archive_plot_view(self.plot, self.summary.get("plot_id", self.figure_id)))
            if self.summary and summary["project_id"] != self.summary["project_id"]:
                raise ValueError("这个路径上的项目已被替换。请关闭窗口，再打开要编辑的项目。")
            self._view(native, seal, lifetime=staged)
        self._show_summary(summary)

    def _view(self, path: Path, expected_sha: str, *, lifetime: ExitStack | None = None) -> None:
        if file_sha256(path) != expected_sha:
            raise ValueError("原生图已改变，请读取最新版本。")
        with loaded_native_document(path) as document:
            if file_sha256(path) != expected_sha:
                raise ValueError("加载时原生图已改变，请读取最新版本。")
            PlotWindow = import_module("veusz.windows.plotwindow").PlotWindow
            viewer = PlotWindow(document, self)
        if lifetime is not None:
            retained = lifetime.pop_all()
            viewer.destroyed.connect(lambda: retained.close())
        viewer.setAttribute(QtCore.Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        viewer.setFocusPolicy(QtCore.Qt.FocusPolicy.NoFocus)
        self._close_viewer()
        self.viewer = viewer
        self.body_layout.insertWidget(0, viewer, 1)
        viewer.actionForceUpdate()

    def _close_viewer(self) -> None:
        if self.viewer is not None:
            self.removeToolBar(self.viewer.viewtoolbar)
            self.viewer.viewtoolbar.deleteLater()
            self.body_layout.removeWidget(self.viewer)
            self.viewer.close()
            self.viewer.deleteLater()
            self.viewer = None

    def closeEvent(self, event: QtGui.QCloseEvent | None) -> None:
        self._close_viewer()
        super().closeEvent(event)

    def _confirm(self, title: str, text: str, *, preview: QtGui.QPixmap | None = None) -> bool:
        dialog = QtWidgets.QDialog(self)
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

    def _edit(self) -> None:
        request = {"plot_id": self.summary["plot_id"], "base_revision": self.summary["revision"],
                   "idempotency_key": uuid4().hex, "property": "axis.label",
                   "target_id": self.axes.currentData(), "value": self.label.text()}
        if self.archive:
            self._edit_archive(request)
            return
        applying = False
        try:
            plan = self._call("plot.intent", request={**request, "mode": "plan"})
            if not self._approve_axis(plan):
                return
            applying = True
            result = self._call("plot.intent", request={**request, "mode": "apply"})
            if result["status"] == "needs_review":
                result = self._review_native(result)
        except TransportError as exc:
            self._disable_editing()
            if applying and (exc.repair or {}).get("request_sent"):
                key = (exc.repair or {}).get("idempotency_key", request["idempotency_key"])
                self.unconfirmed = self.summary["revision"], key
                self.status.setText(f"写入结果未确认。请读取最新版本；用原操作编号 {key} 恢复，不要再提交。")
            else:
                self.status.setText(f"未发出写入：{exc} 请先读取最新版本。")
            return
        except (OSError, ValueError, RuntimeError, KeyError) as exc:
            self._disable_editing()
            self.status.setText(f"无法确认保存：{exc} 请先读取最新版本。")
            return
        if result["commit_status"] == "committed":
            if result["ready_to_use"]:
                try:
                    self._load_current()
                except (OSError, ValueError, RuntimeError, KeyError) as exc:
                    self._disable_editing()
                    self.status.setText(f"修订 {result['revision']} 已保存，但未能刷新窗口：{exc}")
            else:
                self._disable_editing()
                self.status.setText(f"修订 {result['revision']} 已保存，但交付未完成。"
                                    "请使用 plot export 补导出，不要再提交同一修改。")
        elif result["status"] != "rejected":
            self._disable_editing()
            self.status.setText("操作尚未确认保存。请读取最新版本并按现有项目的继续提示操作。")

    def _approve_axis(self, plan: dict[str, Any]) -> bool:
        if plan["status"] == "no_change":
            self.status.setText("标题未改变。")
            return False
        return self._confirm("核对坐标轴标题", f"现在：{plan['before']}\n改为：{plan['after']}\n"
                             f"坐标轴单位不变：{plan['target_context']['unit']}")

    def _archive_intent(self, expected: RevisionToken, request: dict[str, Any]) -> dict[str, Any]:
        from sciplot_core.plot_engine.service import public_plot_service
        from sciplot_core.project_lifecycle.project_file_intent import project_file_axis_intent

        with closing(public_plot_service()) as service:
            return project_file_axis_intent(service, self.plot, request, expected_project_id=self.summary["project_id"],
                                            expected_revision=expected)

    def _edit_archive(self, request: dict[str, Any]) -> None:
        expected = self.summary["revision_token"]
        try:
            plan = self._archive_intent(expected, {**request, "mode": "plan"})
        except (OSError, ValueError, RuntimeError, KeyError) as exc:
            self._disable_editing()
            self.status.setText(f"未保存：{exc} 请读取最新版本。")
            return
        if self._approve_axis(plan):
            self._save_archive(expected, {**request, "mode": "apply"})

    def _retry_archive(self) -> None:
        if self.archive_request is not None:
            self._save_archive(*self.archive_request)

    def _show_archive_unconfirmed(self) -> None:
        assert self.archive_request is not None
        self._disable_editing()
        self.retry.show()
        self.status.setText("上一笔保存未确认。请确认原操作，不要重新提交。"
                            f"操作编号：{self.archive_request[1]['idempotency_key']}")

    def _save_archive(self, expected: RevisionToken, request: dict[str, Any]) -> None:
        try:
            receipt = self._archive_intent(expected, request)
        except EngineError as exc:
            if exc.reason_code == "project_file_save_unconfirmed" or self.archive_request is not None:
                self.archive_request = expected, request
                self._show_archive_unconfirmed()
                return
            self._disable_editing()
            self.status.setText(f"未保存：{exc} 请读取最新版本。")
            return
        except (OSError, ValueError, RuntimeError, KeyError):
            self.archive_request = expected, request
            self._show_archive_unconfirmed()
            return
        if not (receipt.get("saved") is True and receipt.get("idempotency_key") == request["idempotency_key"]):
            self.archive_request = expected, request
            self._show_archive_unconfirmed()
            return
        self.archive_request = None
        self.retry.hide()
        try:
            self._load_current()
        except (OSError, ValueError, RuntimeError, KeyError) as exc:
            self._disable_editing()
            self.status.setText(f"修订 {receipt['revision']} 已保存，但未能刷新窗口：{exc}")
        else:
            self.status.setText(f"已确认保存修订 {receipt['revision']}。{self.status.text()}")

    def _review_native(self, result: dict[str, Any]) -> dict[str, Any]:
        preview = result["preview"]
        data = Path(preview["path"]).read_bytes()
        image = QtGui.QPixmap()
        if sha256(data).hexdigest() != preview["sha256"] or not image.loadFromData(data):
            raise ValueError("待确认的原生预览已变更。")
        accepted = self._confirm("审阅原生候选图", "请核对下面的原生预览，再决定是否保存。", preview=image)
        return self._call("plot.decide", request={**result["next_step"]["request"], "accept": accepted})


def run_editor(plot: Path, *, socket_path: Path | None, timeout: float, figure_id: str | None = None) -> int:
    app: QtCore.QCoreApplication | None = QtCore.QCoreApplication.instance()
    if app is None:
        app = QtWidgets.QApplication([])
    plot = plot.expanduser()
    if plot.suffix != ".sciplot" or (not plot.is_symlink() and plot.is_dir()):
        if figure_id is not None:
            raise ValueError("--figure 只用于 .sciplot 项目文件。")
        plot = plot.resolve()
    window = PlotEditor(plot, socket_path=socket_path, timeout=timeout, figure_id=figure_id)
    window.show()
    return QtWidgets.QApplication.exec()
