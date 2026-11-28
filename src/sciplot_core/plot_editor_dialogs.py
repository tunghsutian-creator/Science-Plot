"""Curve controls, confirmations and export actions for the native plot editor."""

from __future__ import annotations

from collections.abc import Callable
from hashlib import sha256
from math import isfinite
from pathlib import Path
from typing import Any, Literal

from PyQt6 import QtCore, QtGui, QtWidgets

from sciplot_core.archive_plot_view import export_archive_figure
from sciplot_core.plot_engine.typed_intent import LINE_COLOR
from sciplot_core.plot_grammar.styles import COLOR
from sciplot_core.project_lifecycle.errors import EngineError


class CurveColorEdit(QtWidgets.QGroupBox):
    def __init__(self, submit: Callable[[str, str], None]) -> None:
        super().__init__("曲线颜色")
        self.hide()
        layout = QtWidgets.QHBoxLayout(self)
        self.curves = QtWidgets.QComboBox()
        self.curves.setAccessibleName("曲线")
        self.color = QtWidgets.QLineEdit()
        self.color.setAccessibleName("新曲线颜色（十六进制）")
        self.color.setPlaceholderText("例如 #2878B5")
        self.color.setValidator(QtGui.QRegularExpressionValidator(QtCore.QRegularExpression(COLOR["pattern"]), self.color))
        self.review = QtWidgets.QPushButton("核对曲线颜色…")
        for widget in (self.curves, self.color, self.review):
            layout.addWidget(widget)
        self.curves.currentIndexChanged.connect(self._selected_curve)
        self.color.textChanged.connect(self._update_review)
        self.review.clicked.connect(lambda: submit(self.curves.currentData(), self.color.text()))

    def load_targets(self, targets: dict[str, Any], *, same_figure: bool) -> bool:
        selected = self.curves.currentData() if same_figure else None
        with QtCore.QSignalBlocker(self.curves):
            self.curves.clear()
            self.curves.addItem("选择曲线", None)
            for target, edit in targets.items():
                if LINE_COLOR in edit["properties"]:
                    self.curves.addItem(f"{edit['label']}  ({target})", target)
            self.curves.setCurrentIndex(max(0, self.curves.findData(selected)))
        visible = self.curves.count() > 1
        self.setVisible(visible)
        self._selected_curve()
        return visible

    def _selected_curve(self) -> None:
        self.color.clear()
        self.color.setEnabled(self.curves.currentData() is not None)
        self._update_review()

    def _update_review(self) -> None:
        self.review.setEnabled(self.curves.currentData() is not None and self.color.hasAcceptableInput())


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


def approve_edit(parent: QtWidgets.QWidget, status: QtWidgets.QLabel, plan: dict[str, Any]) -> bool:
    prop = plan["property"]
    label = {"axis.label": "坐标轴标题", "axis.ticks": "主刻度", LINE_COLOR: "曲线颜色"}[prop]
    if plan["status"] == "no_change":
        status.setText(f"{label}未改变。")
        return False
    if prop == LINE_COLOR:
        target = plan["target"]
        return _confirm_line_color(parent, label=f"{target['label']} ({target['id']})",
                                   before=plan["before"], after=plan["after"])

    def display(value: Any) -> str:
        if isinstance(value, dict):
            return "自动刻度"
        if isinstance(value, list):
            return ", ".join(map(str, value)) if value else "隐藏主刻度"
        return str(value)

    return confirm(parent, f"核对{label}", f"现在：{display(plan['before'])}\n改为：{display(plan['after'])}\n"
                   f"坐标轴单位不变：{plan['target_context']['unit']}")


def _confirm_line_color(parent: QtWidgets.QWidget, *, label: str, before: str, after: str) -> bool:
    swatches = QtGui.QPixmap(240, 26)
    swatches.fill(QtCore.Qt.GlobalColor.transparent)
    with QtGui.QPainter(swatches) as painter:
        for x, color in ((0, before), (126, after)):
            painter.setPen(QtGui.QColor("#777777"))
            painter.setBrush(QtGui.QColor(color))
            painter.drawRect(x, 0, 113, 25)
    return confirm(parent, "核对曲线颜色", f"曲线：{label}\n现在：{before}\n改为：{after}", preview=swatches)


def archive_export_actions(window: QtWidgets.QMainWindow, plot: Path, status: QtWidgets.QLabel,
                           current: Callable[[], dict[str, Any]]) -> tuple[QtGui.QAction, QtGui.QAction]:
    menu = window.menuBar().addMenu("文件")

    def add_action(export_format: Literal["pdf", "tiff_300"], label: str, suffixes: tuple[str, ...],
                   file_filter: str) -> QtGui.QAction:
        title = f"导出当前图 {label}"
        action = menu.addAction(f"{title}…")
        action.setEnabled(False)

        def export() -> None:
            if not action.isEnabled():
                return
            summary = current()
            revision = summary["revision_token"]
            project_id = summary["project_id"]
            filename, _ = QtWidgets.QFileDialog.getSaveFileName(
                window, title, str(plot.with_suffix(suffixes[0])), file_filter,
                options=QtWidgets.QFileDialog.Option.DontConfirmOverwrite)
            if not filename:
                return
            output = Path(filename if filename.lower().endswith(suffixes) else filename + suffixes[0])
            try:
                export_archive_figure(plot, output, export_format=export_format, project_id=project_id, revision=revision)
            except FileExistsError:
                status.setText("未导出：目标文件已存在，请另选文件名。")
            except EngineError as exc:
                if exc.reason_code in {"figure_handoff_revision_conflict", "project_file_identity_conflict"}:
                    for export_action in actions:
                        export_action.setEnabled(False)
                    status.setText("未导出：项目或图已更新。请读取最新版本。")
                else:
                    status.setText(f"未导出：{exc}")
            except (OSError, ValueError, RuntimeError) as exc:
                status.setText(f"未导出：{exc}")
            else:
                status.setText(f"已导出修订 {revision.revision}：{output}")

        action.triggered.connect(export)
        return action

    actions = (add_action("pdf", "PDF", (".pdf",), "PDF (*.pdf)"),
               add_action("tiff_300", "300 dpi TIFF", (".tiff", ".tif"), "TIFF (*.tiff *.tif)"))
    return actions


def add_axis_editor(layout: QtWidgets.QVBoxLayout) -> tuple[QtWidgets.QComboBox, QtWidgets.QComboBox,
        QtWidgets.QLineEdit, QtWidgets.QPushButton, QtWidgets.QPushButton, QtWidgets.QPushButton]:
    """Create the shared label/tick form; the window owns all edit and retry actions."""
    form = QtWidgets.QHBoxLayout()
    axes = QtWidgets.QComboBox()
    axes.setAccessibleName("坐标轴")
    edit_property = QtWidgets.QComboBox()
    edit_property.setAccessibleName("坐标轴属性")
    edit_property.addItem("标题", "axis.label")
    edit_property.addItem("主刻度", "axis.ticks")
    label = QtWidgets.QLineEdit()
    label.setAccessibleName("新坐标轴标题")
    label.setPlaceholderText("新坐标轴标题")
    review = QtWidgets.QPushButton("核对并保存…")
    retry = QtWidgets.QPushButton("确认上一次保存")
    retry.hide()
    refresh = QtWidgets.QPushButton("读取最新版本")
    for widget in (axes, edit_property, label, review, refresh, retry):
        form.addWidget(widget)
    layout.addLayout(form)
    return axes, edit_property, label, review, refresh, retry


def parse_major_ticks(text: str, *, automatic: bool) -> list[float] | dict[str, str]:
    literal = text.strip()
    if not literal:
        return {"mode": "automatic"} if automatic else []
    value = [float(part) for part in literal.replace("，", ",").split(",")]
    if not all(isfinite(number) for number in value):
        raise ValueError("Nonfinite axis ticks")
    return value


def confirm_native_preview(window: QtWidgets.QWidget, preview: dict[str, Any]) -> bool:
    data = Path(preview["path"]).read_bytes()
    image = QtGui.QPixmap()
    if sha256(data).hexdigest() != preview["sha256"] or not image.loadFromData(data):
        raise ValueError("待确认的原生预览已变更。")
    return confirm(window, "审阅原生候选图", "请核对下面的原生预览，再决定是否保存。", preview=image)
