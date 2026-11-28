"""A native figure view with edits owned by the existing plot protocol."""

from __future__ import annotations

from contextlib import ExitStack
from importlib import import_module
from pathlib import Path
from typing import Any
from uuid import uuid4

from PyQt6 import QtCore, QtGui, QtWidgets

from sciplot_core.archive_plot_view import archive_plot_view, editor_target_path, is_archive_target
from sciplot_core.foundation.file_hashing import file_sha256
from sciplot_core.plot_editor_dialogs import (
    CurveColorEdit, add_axis_editor, approve_edit, archive_export_actions, confirm_native_preview, parse_major_ticks,
)
from sciplot_core.plot_engine.service import public_plot_service
from sciplot_core.plot_engine.typed_intent import LINE_COLOR
from sciplot_core.plot_protocol.client import call
from sciplot_core.plot_protocol.paths import TransportError
from sciplot_core.project_lifecycle.contracts import RevisionToken
from sciplot_core.project_lifecycle.errors import EngineError
from sciplot_core.project_lifecycle.project_file import ProjectFileSession
from sciplot_core.project_lifecycle.project_file_intent import project_file_intent
from sciplot_core.project_lifecycle.project_file_summary import project_file_read_session
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
        self._archive_session: ProjectFileSession | None = None
        self._archive_lifetime = ExitStack()
        self.destroyed.connect(self._archive_lifetime.close)
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
        (self.axes, self.edit_property, self.label, self.review, self.refresh, self.retry) = add_axis_editor(self.body_layout)
        self.retry.clicked.connect(self._retry_archive)
        self.curve_colors = CurveColorEdit(self._edit_color)
        self.body_layout.addWidget(self.curve_colors)
        self.setCentralWidget(body)
        self.export_pdf, self.export_tiff = (archive_export_actions(self, plot, self.status, lambda: self.summary)
                                            if self.archive else (None, None))
        self.axes.currentIndexChanged.connect(self._selected_axis)
        self.edit_property.currentIndexChanged.connect(self._selected_axis)
        self.review.clicked.connect(self._edit)
        self.refresh.clicked.connect(self._refresh)
        ensure_veusz_runtime_path()
        ensure_veusz_qsettings_compat()
        # A window owns its renderer, not a reusable project write session.
        # Every view/edit below still admits its own archive revision.
        self._archive_service = public_plot_service() if self.archive else None
        if self._archive_service is not None:
            self.destroyed.connect(self._archive_service.close)
        try:
            self._refresh(initial=True)
        except Exception:
            if self._archive_service is not None:
                self._archive_service.close()
            raise

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
        for action in (self.export_pdf, self.export_tiff):
            if action is not None:
                action.setEnabled(False)

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
        self.summary = summary
        for action in (self.export_pdf, self.export_tiff):
            if action is not None:
                action.setEnabled(self.archive_request is None)
        self.axes.setEnabled(self.archive_request is None)
        with QtCore.QSignalBlocker(self.axes):
            self.axes.clear()
            self.axes.addItem("选择坐标轴", None)
            for target, edit in summary["edit_targets"].items():
                if "axis.label" in edit["properties"]:
                    self.axes.addItem(f"{edit['label']}  ({target})", target)
            self.axes.setCurrentIndex(max(0, self.axes.findData(selected)))
        has_colors = self.curve_colors.load_targets(
            summary["edit_targets"] if self.archive else {}, same_figure=same_figure)
        self.curve_colors.setEnabled(self.archive_request is None)
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
        session = self._archive_session
        if session is not None and session.matches_path(self.plot):
            if target == self.summary.get("plot_id") and self.viewer is not None:
                self._show_summary(self.summary)
                return
            summary, has_view = self._show_archive_view(session, target)
        else:
            with ExitStack() as staged:
                session = staged.enter_context(project_file_read_session(self.plot))
                summary, has_view = self._show_archive_view(session, target)
                self._archive_lifetime.close()
                self._archive_lifetime.enter_context(staged.pop_all())
                self._archive_session = session
        if not has_view:
            self.archive_project_id = summary["project_id"]
            self._show_figure_choices(summary["figures"])
            return
        self.archive_project_id = summary["project_id"]
        self.figure_id = summary["plot_id"]
        self.figures.setEnabled(self.archive_request is None)
        self._show_summary(summary)

    def _show_archive_view(self, session: ProjectFileSession, target: str | None) -> tuple[dict[str, Any], bool]:
        assert self._archive_service is not None
        summary, native, seal = archive_plot_view(
            self._archive_service, session, target, expected_project_id=self.archive_project_id)
        if native is not None:
            assert seal is not None
            self._view(native, seal)
        return summary, native is not None

    def _show_figure_choices(self, choices: list[dict[str, str]]) -> None:
        self._disable_editing()
        with QtCore.QSignalBlocker(self.figures):
            self.figures.clear()
            for saved in choices:
                self.figures.addItem(f"{saved['figure_id']}  ({saved['plot_id']})", saved["plot_id"])
            self.figures.setCurrentIndex(-1)
        self.figures.show()
        self.status.setText("请选择要查看和编辑的图。")

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
        if self._archive_service is not None:
            self._archive_service.close()
        self._archive_lifetime.close()
        self._archive_session = None
        super().closeEvent(event)

    def _intent_request(self, prop: str, target: str, value: Any) -> dict[str, Any]:
        return {"plot_id": self.summary["plot_id"], "base_revision": self.summary["revision"],
                "idempotency_key": uuid4().hex, "property": prop, "target_id": target, "value": value}

    def _edit_color(self, target: str, color: str) -> None:
        self._edit_archive(self._intent_request(LINE_COLOR, target, color))

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
            if not approve_edit(self, self.status, plan):
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
        try:
            return parse_major_ticks(self.label.text(), automatic=bool(self.summary.get("domain_semantics")))
        except ValueError:
            self.status.setText("主刻度须为逗号分隔的有限数字，例如 0, 5, 10。")
            return None

    def _edit_archive(self, request: dict[str, Any]) -> None:
        expected = self.summary["revision_token"]
        assert self._archive_service is not None
        try:
            plan = project_file_intent(self._archive_service, self.plot, {**request, "mode": "plan"},
                                       expected_project_id=self.summary["project_id"], expected_revision=expected,
                                       preview_session=self._archive_session)
        except (OSError, ValueError, RuntimeError, KeyError) as exc:
            self._disable_editing()
            self.status.setText(f"未保存：{exc} 请读取最新版本。")
            return
        if approve_edit(self, self.status, plan):
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
        assert self._archive_service is not None
        try:
            receipt = project_file_intent(self._archive_service, self.plot, request,
                                          expected_project_id=self.summary["project_id"], expected_revision=expected)
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
        accepted = confirm_native_preview(self, result["preview"])
        return self._call("plot.decide", request={**result["next_step"]["request"], "accept": accepted})


def run_editor(plot: Path, *, socket_path: Path | None, timeout: float, figure_id: str | None = None) -> int:
    app: QtCore.QCoreApplication | None = QtCore.QCoreApplication.instance()
    if app is None:
        app = QtWidgets.QApplication([])
    plot = editor_target_path(plot, figure_id)
    window = PlotEditor(plot, socket_path=socket_path, timeout=timeout, figure_id=figure_id)
    window.show()
    return QtWidgets.QApplication.exec()
