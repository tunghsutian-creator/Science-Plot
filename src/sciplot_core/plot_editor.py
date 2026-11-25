"""A native read-only view with one edit owned by the existing plot protocol."""

from __future__ import annotations

from hashlib import sha256
from importlib import import_module
from pathlib import Path
from typing import Any
from uuid import uuid4

from PyQt6 import QtCore, QtGui, QtWidgets

from sciplot_core.foundation.file_hashing import file_sha256
from sciplot_core.plot_protocol.client import call
from sciplot_core.plot_protocol.paths import TransportError
from sciplot_core.studio_core.qt_compat import ensure_veusz_qsettings_compat
from sciplot_core.studio_core.runtime import ensure_veusz_runtime_path
from sciplot_core.veusz_worker.document_edit import loaded_native_document


class PlotEditor(QtWidgets.QMainWindow):
    def __init__(self, plot: Path, *, socket_path: Path | None, timeout: float) -> None:
        super().__init__()
        self.plot = plot
        self.socket_path = socket_path
        self.timeout = timeout
        self.summary: dict[str, Any] = {}
        self.viewer: Any = None
        self.unconfirmed: tuple[int, str] | None = None
        self.setWindowTitle("SciPlot · 坐标轴标题")
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
        self.refresh = QtWidgets.QPushButton("读取最新版本")
        for widget in (self.axes, self.label, self.review, self.refresh):
            form.addWidget(widget)
        self.body_layout.addLayout(form)
        self.setCentralWidget(body)
        self.axes.currentIndexChanged.connect(self._selected_axis)
        self.review.clicked.connect(self._edit)
        self.refresh.clicked.connect(self._refresh)
        self._refresh(initial=True)

    def _call(self, method: str, **params: Any) -> dict[str, Any]:
        return call(method, {"plot": str(self.plot), **params},
                    socket_path=self.socket_path, timeout=self.timeout)

    def _selected_axis(self) -> None:
        target = self.axes.currentData()
        self.label.setText(self.summary.get("edit_targets", {}).get(target, {}).get("label", ""))
        self.label.setEnabled(target is not None)
        self.review.setEnabled(target is not None)

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
        self.summary = summary
        self.axes.setEnabled(True)
        self.axes.clear()
        self.axes.addItem("选择坐标轴", None)
        for target, edit in summary["edit_targets"].items():
            if "axis.label" in edit["properties"]:
                self.axes.addItem(f"{edit['label']}  ({target})", target)
        self.status.setText(f"修订 {summary['revision']} · {summary['plot_id']}。本窗口只修改坐标轴显示标题。")
        self._selected_axis()

    def _view(self, path: Path, expected_sha: str) -> None:
        if file_sha256(path) != expected_sha:
            raise ValueError("原生图已改变，请读取最新版本。")
        with loaded_native_document(path) as document:
            if file_sha256(path) != expected_sha:
                raise ValueError("加载时原生图已改变，请读取最新版本。")
            PlotWindow = import_module("veusz.windows.plotwindow").PlotWindow
            viewer = PlotWindow(document, self)
        viewer.setAttribute(QtCore.Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        viewer.setFocusPolicy(QtCore.Qt.FocusPolicy.NoFocus)
        if self.viewer is not None:
            self.removeToolBar(self.viewer.viewtoolbar)
            self.viewer.viewtoolbar.deleteLater()
            self.body_layout.removeWidget(self.viewer)
            self.viewer.close()
            self.viewer.deleteLater()
        self.viewer = viewer
        self.body_layout.insertWidget(0, viewer, 1)
        viewer.actionForceUpdate()

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
        applying = False
        try:
            plan = self._call("plot.intent", request={**request, "mode": "plan"})
            if plan["status"] == "no_change":
                self.status.setText("标题未改变。")
                return
            context = plan["target_context"]
            if not self._confirm("核对坐标轴标题",
                                 f"现在：{plan['before']}\n改为：{plan['after']}\n"
                                 f"坐标轴单位不变：{context['unit']}"):
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

    def _review_native(self, result: dict[str, Any]) -> dict[str, Any]:
        preview = result["preview"]
        data = Path(preview["path"]).read_bytes()
        image = QtGui.QPixmap()
        if sha256(data).hexdigest() != preview["sha256"] or not image.loadFromData(data):
            raise ValueError("待确认的原生预览已变更。")
        accepted = self._confirm("审阅原生候选图", "请核对下面的原生预览，再决定是否保存。", preview=image)
        return self._call("plot.decide", request={**result["next_step"]["request"], "accept": accepted})


def run_editor(plot: Path, *, socket_path: Path | None, timeout: float) -> int:
    app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
    ensure_veusz_runtime_path()
    ensure_veusz_qsettings_compat()
    window = PlotEditor(plot.expanduser().resolve(), socket_path=socket_path, timeout=timeout)
    window.show()
    return app.exec()
