"""A native figure view with edits owned by the existing plot protocol."""

from __future__ import annotations

from contextlib import ExitStack
from hashlib import sha256
from importlib import import_module
from math import isfinite
from pathlib import Path
from typing import Any
from uuid import uuid4

from PyQt6 import QtCore, QtGui, QtWidgets

from sciplot_core.archive_plot_view import archive_intent, archive_plot_view, editor_target_path, is_archive_target
from sciplot_core.foundation.file_hashing import file_sha256
from sciplot_core.plot_editor_dialogs import archive_pdf_action, confirm, confirm_line_color
from sciplot_core.plot_engine.typed_intent import LINE_COLOR
from sciplot_core.plot_grammar.styles import COLOR
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
        self.archive = is_archive_target(plot)
        self.figure_id = figure_id
        self.archive_project_id: str | None = None
        self.archive_request: tuple[RevisionToken, dict[str, Any]] | None = None
        self.socket_path = socket_path
        self.timeout = timeout
        self.summary: dict[str, Any] = {}
        self.viewer: Any = None
        self.unconfirmed: tuple[int, str] | None = None
        self.setWindowTitle(f"{plot.name} · SciPlot" if self.archive else "SciPlot · 坐标轴")
        self.resize(680, 610)
        body = QtWidgets.QWidget(self)
        self.body_layout = QtWidgets.QVBoxLayout(body)
        self.status = QtWidgets.QLabel()
        self.status.setTextFormat(QtCore.Qt.TextFormat.PlainText)
        self.status.setWordWrap(True)
        self.body_layout.addWidget(self.status)
        self.figures = QtWidgets.QComboBox()
        self.figures.setAccessibleName("项目图")
        self.figures.setPlaceholderText("选择要打开的图")
        self.figures.hide()
        self.figures.currentIndexChanged.connect(self._select_archive_plot)
        self.body_layout.addWidget(self.figures)
        form = QtWidgets.QHBoxLayout()
        self.axes = QtWidgets.QComboBox()
        self.axes.setAccessibleName("坐标轴")
        self.edit_property = QtWidgets.QComboBox()
        self.edit_property.setAccessibleName("坐标轴属性")
        self.edit_property.addItem("标题", "axis.label")
        self.edit_property.addItem("主刻度", "axis.ticks")
        self.label = QtWidgets.QLineEdit()
        self.label.setAccessibleName("新坐标轴标题")
        self.label.setPlaceholderText("新坐标轴标题")
        self.review = QtWidgets.QPushButton("核对并保存…")
        self.retry = QtWidgets.QPushButton("确认上一次保存")
        self.retry.hide()
        self.retry.clicked.connect(self._retry_archive)
        self.refresh = QtWidgets.QPushButton("读取最新版本")
        for widget in (self.axes, self.edit_property, self.label, self.review, self.refresh, self.retry):
            form.addWidget(widget)
        self.body_layout.addLayout(form)
        self.curve_colors = QtWidgets.QGroupBox("曲线颜色")
        self.curve_colors.hide()
        colors = QtWidgets.QHBoxLayout(self.curve_colors)
        self.curves = QtWidgets.QComboBox()
        self.curves.setAccessibleName("曲线")
        self.color = QtWidgets.QLineEdit()
        self.color.setAccessibleName("新曲线颜色（十六进制）")
        self.color.setPlaceholderText("例如 #2878B5")
        self.color.setValidator(QtGui.QRegularExpressionValidator(QtCore.QRegularExpression(COLOR["pattern"]), self.color))
        self.review_color = QtWidgets.QPushButton("核对曲线颜色…")
        for widget in (self.curves, self.color, self.review_color):
            colors.addWidget(widget)
        self.body_layout.addWidget(self.curve_colors)
        self.setCentralWidget(body)
        self.export_pdf = archive_pdf_action(self, plot, self.status, lambda: self.summary) if self.archive else None
        self.axes.currentIndexChanged.connect(self._selected_axis)
        self.edit_property.currentIndexChanged.connect(self._selected_axis)
        self.review.clicked.connect(self._edit)
        self.curves.currentIndexChanged.connect(self._selected_curve)
        self.color.textChanged.connect(self._update_color_review)
        self.review_color.clicked.connect(self._edit_color)
        self.refresh.clicked.connect(self._refresh)
        ensure_veusz_runtime_path()
        ensure_veusz_qsettings_compat()
        self._refresh(initial=True)

    def _call(self, method: str, **params: Any) -> dict[str, Any]:
        return call(method, {"plot": str(self.plot), **params},
                    socket_path=self.socket_path, timeout=self.timeout)

    def _selected_axis(self) -> None:
        target = self.axes.currentData()
        selected = self.summary.get("edit_targets", {}).get(target, {})
        enabled = target is not None and self.axes.isEnabled() and self.archive_request is None
        ticks = self.edit_property.currentData() == "axis.ticks"
        self.edit_property.setEnabled(enabled)
        self.label.setAccessibleName("主刻度" if ticks else "新坐标轴标题")
        self.label.setPlaceholderText("逗号分隔的主刻度" if ticks else "新坐标轴标题")
        self.label.setText("" if ticks else selected.get("label", ""))
        if enabled and ticks:
            try:
                if "axis.ticks" not in selected["properties"]:
                    raise ValueError("此坐标轴不支持设置主刻度。")
                if self.archive:
                    value = self.summary["axis_ticks"][target]
                else:
                    detail = self._call("plot.describe", description={"scope": "edit", "target": target,
                                                                     "property": "axis.ticks"})
                    if (detail["plot_id"], detail["revision"]) != (self.summary["plot_id"], self.summary["revision"]):
                        raise ValueError("图已更新。")
                    value = detail["current_value"]
                self.label.setText(", ".join(map(str, value)) if isinstance(value, list) else "")
                self.label.setPlaceholderText("留空恢复自动刻度" if self.summary.get("domain_semantics")
                                              else "留空隐藏主刻度")
            except (OSError, ValueError, RuntimeError, KeyError) as exc:
                self.status.setText(f"未读取主刻度：{exc} 请读取最新版本。")
                enabled = False
        self.label.setEnabled(enabled)
        self.review.setEnabled(enabled)

    def _disable_editing(self) -> None:
        self.axes.setEnabled(False)
        self.edit_property.setEnabled(False)
        self.label.setEnabled(False)
        self.review.setEnabled(False)
        self.curve_colors.setEnabled(False)
        if self.export_pdf is not None:
            self.export_pdf.setEnabled(False)

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
        same_figure = self.summary.get("plot_id") == summary["plot_id"]
        selected = self.axes.currentData() if same_figure else None
        selected_curve = self.curves.currentData() if same_figure else None
        self.summary = summary
        if self.export_pdf is not None:
            self.export_pdf.setEnabled(self.archive_request is None)
        self.axes.setEnabled(self.archive_request is None)
        with QtCore.QSignalBlocker(self.axes):
            self.axes.clear()
            self.axes.addItem("选择坐标轴", None)
            for target, edit in summary["edit_targets"].items():
                if "axis.label" in edit["properties"]:
                    self.axes.addItem(f"{edit['label']}  ({target})", target)
            self.axes.setCurrentIndex(max(0, self.axes.findData(selected)))
        with QtCore.QSignalBlocker(self.curves):
            self.curves.clear()
            self.curves.addItem("选择曲线", None)
            if self.archive:
                for target, edit in summary["edit_targets"].items():
                    if LINE_COLOR in edit["properties"]:
                        self.curves.addItem(f"{edit['label']}  ({target})", target)
            self.curves.setCurrentIndex(max(0, self.curves.findData(selected_curve)))
        has_colors = self.curves.count() > 1
        self.curve_colors.setVisible(has_colors)
        self.curve_colors.setEnabled(self.archive_request is None)
        self._selected_curve()
        edits = "坐标轴标题、主刻度和曲线颜色" if has_colors else "坐标轴标题和主刻度"
        self.status.setText(f"修订 {summary['revision']} · {summary['plot_id']}。可修改{edits}。")
        self._selected_axis()
        if self.archive_request is not None:
            self._show_archive_unconfirmed()

    def _select_archive_plot(self) -> None:
        plot_id = self.figures.currentData()
        if plot_id is None or plot_id == self.figure_id or self.archive_request is not None:
            return
        try:
            self._load_archive(plot_id)
        except (OSError, ValueError, RuntimeError, KeyError) as exc:
            self._disable_editing()
            with QtCore.QSignalBlocker(self.figures):
                self.figures.setCurrentIndex(self.figures.findData(self.figure_id))
            self.status.setText(f"无法打开所选图：{exc}")

    def _load_archive(self, selection: str | None = None) -> None:
        target = self.figure_id if selection is None else selection
        with ExitStack() as staged:
            summary, native, seal = staged.enter_context(
                archive_plot_view(self.plot, target, expected_project_id=self.archive_project_id))
            if native is None:
                self.archive_project_id = summary["project_id"]
                self._show_figure_choices(summary["figures"])
                return
            assert seal is not None
            self._view(native, seal, lifetime=staged)
        self.archive_project_id = summary["project_id"]
        self.figure_id = summary["plot_id"]
        self.figures.setEnabled(self.archive_request is None)
        self._show_summary(summary)

    def _show_figure_choices(self, choices: list[dict[str, str]]) -> None:
        self._disable_editing()
        with QtCore.QSignalBlocker(self.figures):
            self.figures.clear()
            for saved in choices:
                self.figures.addItem(f"{saved['figure_id']}  ({saved['plot_id']})", saved["plot_id"])
            self.figures.setCurrentIndex(-1)
        self.figures.show()
        self.status.setText("请选择要查看和编辑的图。")

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

    def _selected_curve(self) -> None:
        self.color.clear()
        self.color.setEnabled(self.curves.currentData() is not None)
        self._update_color_review()

    def _update_color_review(self) -> None:
        self.review_color.setEnabled(self.curves.currentData() is not None and self.color.hasAcceptableInput())

    def _intent_request(self, prop: str, target: str, value: Any) -> dict[str, Any]:
        return {"plot_id": self.summary["plot_id"], "base_revision": self.summary["revision"],
                "idempotency_key": uuid4().hex, "property": prop, "target_id": target, "value": value}

    def _edit_color(self) -> None:
        self._edit_archive(self._intent_request(LINE_COLOR, self.curves.currentData(), self.color.text()))

    def _edit(self) -> None:
        prop = self.edit_property.currentData()
        value: str | list[float] | dict[str, str] | None
        value = self._ticks_value() if prop == "axis.ticks" else self.label.text()
        if value is None:
            return
        request = self._intent_request(prop, self.axes.currentData(), value)
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

    def _ticks_value(self) -> list[float] | dict[str, str] | None:
        literal = self.label.text().strip()
        if not literal:
            return {"mode": "automatic"} if self.summary.get("domain_semantics") else []
        try:
            value = [float(part) for part in literal.replace("，", ",").split(",")]
            if not all(isfinite(number) for number in value):
                raise ValueError
        except ValueError:
            self.status.setText("主刻度须为逗号分隔的有限数字，例如 0, 5, 10。")
            return None
        return value

    def _approve_axis(self, plan: dict[str, Any]) -> bool:
        ticks = plan["property"] == "axis.ticks"
        label = "主刻度" if ticks else "坐标轴标题"
        if plan["status"] == "no_change":
            self.status.setText(f"{label}未改变。")
            return False

        def display(value: Any) -> str:
            if isinstance(value, dict):
                return "自动刻度"
            if isinstance(value, list):
                return ", ".join(map(str, value)) if value else "隐藏主刻度"
            return str(value)

        return confirm(self, f"核对{label}", f"现在：{display(plan['before'])}\n改为：{display(plan['after'])}\n"
                             f"坐标轴单位不变：{plan['target_context']['unit']}")

    def _edit_archive(self, request: dict[str, Any]) -> None:
        expected = self.summary["revision_token"]
        try:
            plan = archive_intent(self.plot, {**request, "mode": "plan"},
                                  expected_project_id=self.summary["project_id"], expected_revision=expected)
        except (OSError, ValueError, RuntimeError, KeyError) as exc:
            self._disable_editing()
            self.status.setText(f"未保存：{exc} 请读取最新版本。")
            return
        if plan["property"] == LINE_COLOR:
            if plan["status"] == "no_change":
                self.status.setText("曲线颜色未改变。")
                return
            target = plan["target"]
            approved = confirm_line_color(self, label=f"{target['label']} ({target['id']})",
                                          before=plan["before"], after=plan["after"])
        else:
            approved = self._approve_axis(plan)
        if approved:
            self._save_archive(expected, {**request, "mode": "apply"})

    def _retry_archive(self) -> None:
        if self.archive_request is not None:
            self._save_archive(*self.archive_request)

    def _show_archive_unconfirmed(self) -> None:
        assert self.archive_request is not None
        self.figures.setEnabled(False)
        self._disable_editing()
        self.retry.show()
        self.status.setText("上一笔保存未确认。请确认原操作，不要重新提交。"
                            f"操作编号：{self.archive_request[1]['idempotency_key']}")

    def _save_archive(self, expected: RevisionToken, request: dict[str, Any]) -> None:
        try:
            receipt = archive_intent(self.plot, request, expected_project_id=self.summary["project_id"],
                                     expected_revision=expected)
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
        accepted = confirm(self, "审阅原生候选图", "请核对下面的原生预览，再决定是否保存。", preview=image)
        return self._call("plot.decide", request={**result["next_step"]["request"], "accept": accepted})


def run_editor(plot: Path, *, socket_path: Path | None, timeout: float, figure_id: str | None = None) -> int:
    app: QtCore.QCoreApplication | None = QtCore.QCoreApplication.instance()
    if app is None:
        app = QtWidgets.QApplication([])
    plot = editor_target_path(plot, figure_id)
    window = PlotEditor(plot, socket_path=socket_path, timeout=timeout, figure_id=figure_id)
    window.show()
    return QtWidgets.QApplication.exec()
