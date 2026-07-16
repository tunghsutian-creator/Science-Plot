from __future__ import annotations

import hashlib
import sys
from pathlib import Path
from typing import Any

from sciplot_core._paths import VEUSZ_ROOT
from sciplot_core.canvas.model import CanvasSession


def _load_qt_veusz() -> dict[str, Any]:
    runtime = str(VEUSZ_ROOT)
    if runtime not in sys.path:
        sys.path.insert(0, runtime)

    from sciplot_core.studio import ensure_veusz_qsettings_compat

    ensure_veusz_qsettings_compat()
    from PyQt6 import QtCore, QtWidgets
    from veusz import dataimport, document, widgets
    from veusz.document.operations import OperationMultiple, OperationSettingSet
    from veusz.windows.plotwindow import PlotWindow

    _ = dataimport, widgets
    return {
        "QtCore": QtCore,
        "QtWidgets": QtWidgets,
        "Document": document.Document,
        "OperationMultiple": OperationMultiple,
        "OperationSettingSet": OperationSettingSet,
        "PlotWindow": PlotWindow,
    }


class VeuszCanvasAdapter:
    """The sole SciPlot boundary around Veusz Document and PlotWindow."""

    def __init__(
        self,
        document_path: Path,
        *,
        parent: Any = None,
        visible: bool = False,
    ) -> None:
        runtime = _load_qt_veusz()
        self._QtCore = runtime["QtCore"]
        self._QtWidgets = runtime["QtWidgets"]
        self._OperationMultiple = runtime["OperationMultiple"]
        self._OperationSettingSet = runtime["OperationSettingSet"]

        self.document_path = document_path.expanduser().resolve()
        if not self.document_path.is_file():
            raise FileNotFoundError(self.document_path)

        application = self._QtWidgets.QApplication.instance()
        self.owns_application = application is None
        self.application = application or self._QtWidgets.QApplication([])
        self.assert_gui_thread()

        self.document = runtime["Document"]()
        self.document.load(str(self.document_path))
        self.plot_window = runtime["PlotWindow"](self.document, parent)
        self.plot_window.rendercontrol.updateNumberThreads(num=0)
        self.plot_window.setTimeout(-1)
        width, height = self.document.docSize()
        self.plot_window.resize(max(int(width) + 16, 320), max(int(height) + 16, 240))
        if visible:
            self.plot_window.show()
        self.force_redraw()

    def assert_gui_thread(self) -> None:
        application = self._QtWidgets.QApplication.instance()
        if application is None:
            raise RuntimeError("A QApplication is required for the live canvas.")
        if self._QtCore.QThread.currentThread() is not application.thread():
            raise RuntimeError(
                "Veusz Document mutations must run on the Qt GUI thread."
            )

    def force_redraw(self) -> str:
        self.assert_gui_thread()
        self.plot_window.actionForceUpdate()
        self.application.processEvents()
        fingerprint = self.render_fingerprint()
        if not fingerprint:
            raise RuntimeError("Embedded PlotWindow did not produce a rendered pixmap.")
        return fingerprint

    def render_fingerprint(self) -> str:
        pixmap = self.plot_window.pixmapitem.pixmap()
        if pixmap.isNull() or pixmap.width() <= 1 or pixmap.height() <= 1:
            return ""
        byte_array = self._QtCore.QByteArray()
        buffer = self._QtCore.QBuffer(byte_array)
        buffer.open(self._QtCore.QIODevice.OpenModeFlag.WriteOnly)
        try:
            if not pixmap.save(buffer, "PNG"):
                raise RuntimeError("Could not serialize the live canvas pixmap.")
        finally:
            buffer.close()
        return hashlib.sha256(bytes(byte_array)).hexdigest()

    def bind_object_registry(self, session: CanvasSession) -> list[dict[str, Any]]:
        self.assert_gui_thread()
        inventory: list[dict[str, Any]] = []

        def walk(parent: Any, parent_key: str) -> None:
            type_counts: dict[str, int] = {}
            for child in parent.children:
                object_type = str(child.typename)
                type_index = type_counts.get(object_type, 0)
                type_counts[object_type] = type_index + 1
                structural_key = f"{parent_key}/{object_type}[{type_index}]"
                record = session.object_registry.bind(
                    structural_key=structural_key,
                    current_path=str(child.path),
                    object_type=object_type,
                    revision=session.revision,
                )
                inventory.append(
                    {
                        "object_id": record.object_id,
                        "structural_key": structural_key,
                        "path": str(child.path),
                        "object_type": object_type,
                        "display_name": str(child.name),
                    }
                )
                walk(child, structural_key)

        walk(self.document.basewidget, "root")
        return inventory

    def visible_text_targets(
        self,
        session: CanvasSession,
    ) -> list[dict[str, Any]]:
        candidates: list[tuple[tuple[int, int, int, int], dict[str, Any]]] = []
        for item in self.bind_object_registry(session):
            object_type = item["object_type"]
            if object_type not in {"axis", "label", "colorbar"}:
                continue
            setting_path = f"{item['path']}/label"
            try:
                setting = self.document.resolveSettingPath(None, setting_path)
            except ValueError:
                continue
            value = setting.get()
            widget_hidden = self._optional_bool_setting(f"{item['path']}/hide", False)
            label_hidden = (
                self._optional_bool_setting(f"{item['path']}/Label/hide", False)
                if object_type in {"axis", "colorbar"}
                else False
            )
            visible = not widget_hidden and not label_hidden
            auxiliary = "colorbar" in str(item["path"]).casefold()
            score = (
                0 if visible else 1,
                0 if str(value).strip() else 1,
                1 if auxiliary else 0,
                0 if object_type == "axis" else 1,
            )
            candidates.append(
                (
                    score,
                    {
                        **item,
                        "setting_path": setting_path,
                        "value": value,
                        "target_role": (
                            "axis_label"
                            if object_type == "axis"
                            else "visible_text_label"
                        ),
                        "visible": visible,
                    },
                )
            )
        if not candidates:
            return []
        candidates.sort(key=lambda item: item[0])
        return [target for _, target in candidates if target["visible"] is True]

    def first_visible_text_target(
        self,
        session: CanvasSession,
    ) -> dict[str, Any]:
        targets = self.visible_text_targets(session)
        if not targets:
            raise RuntimeError(
                "The document does not contain a visible editable text setting."
            )
        return targets[0]

    def first_axis_label_target(
        self,
        session: CanvasSession,
    ) -> dict[str, Any]:
        """Compatibility alias for the broader visible-text characterization seam."""

        return self.first_visible_text_target(session)

    def _optional_bool_setting(self, setting_path: str, default: bool) -> bool:
        try:
            return bool(self.document.resolveSettingPath(None, setting_path).get())
        except ValueError:
            return default

    def setting_value(self, setting_path: str) -> Any:
        self.assert_gui_thread()
        return self.document.resolveSettingPath(None, setting_path).get()

    @property
    def page_count(self) -> int:
        return int(self.document.getNumberPages())

    @property
    def current_page(self) -> int:
        return int(self.plot_window.getPageNumber())

    def set_page(self, page_index: int) -> int:
        self.assert_gui_thread()
        self.plot_window.setPageNumber(int(page_index))
        self.application.processEvents()
        return self.current_page

    @property
    def zoom_factor(self) -> float:
        return float(self.plot_window.zoomfactor)

    def set_zoom_factor(self, zoom: float) -> float:
        self.assert_gui_thread()
        self.plot_window.setZoomFactor(float(zoom))
        self.application.processEvents()
        return self.zoom_factor

    def zoom_to_page(self) -> float:
        self.assert_gui_thread()
        self.plot_window.slotViewZoomPage()
        self.application.processEvents()
        return self.zoom_factor

    def validate_setting_value(self, setting_path: str, value: Any) -> Any:
        self.assert_gui_thread()
        setting = self.document.resolveSettingPath(None, setting_path)
        return setting.normalize(value)

    def apply_setting_batch(
        self,
        changes: list[dict[str, Any]],
        *,
        description: str,
    ) -> list[dict[str, Any]]:
        self.assert_gui_thread()
        prepared: list[dict[str, Any]] = []
        operations: list[Any] = []
        for change in changes:
            setting_path = str(change["setting_path"])
            normalized = self.validate_setting_value(setting_path, change["value"])
            old_value = self.setting_value(setting_path)
            prepared.append(
                {
                    "setting_path": setting_path,
                    "old_value": old_value,
                    "new_value": normalized,
                }
            )
            operations.append(self._OperationSettingSet(setting_path, normalized))
        self.document.applyOperation(
            self._OperationMultiple(
                operations, descr=description or "SciPlot canvas edit"
            )
        )
        self.force_redraw()
        return prepared

    @property
    def can_undo(self) -> bool:
        return bool(self.document.canUndo())

    @property
    def can_redo(self) -> bool:
        return bool(self.document.canRedo())

    def undo(self) -> str:
        self.assert_gui_thread()
        if not self.can_undo:
            raise RuntimeError("The live canvas has no operation to undo.")
        self.document.undoOperation()
        return self.force_redraw()

    def redo(self) -> str:
        self.assert_gui_thread()
        if not self.can_redo:
            raise RuntimeError("The live canvas has no operation to redo.")
        self.document.redoOperation()
        return self.force_redraw()

    def save(self, path: Path | None = None) -> Path:
        self.assert_gui_thread()
        target = (path or self.document_path).expanduser().resolve()
        target.parent.mkdir(parents=True, exist_ok=True)
        self.document.save(str(target))
        self.document_path = target
        return target

    def save_recovery_snapshot(self, path: Path) -> Path:
        """Serialize current in-memory state without changing canonical authority."""

        self.assert_gui_thread()
        target = path.expanduser().resolve()
        target.parent.mkdir(parents=True, exist_ok=True)
        previous_filename = self.document.filename
        was_modified = self.document.isModified()
        try:
            self.document.save(str(target))
        finally:
            self.document.filename = previous_filename
            self.document.modified = was_modified
        return target

    def interaction_characterization(self) -> dict[str, Any]:
        """Exercise PlotWindow's selection and axis-coordinate seams."""

        self.assert_gui_thread()
        helper = self.plot_window.painthelper
        if helper is None:
            raise RuntimeError("PlotWindow has no PaintHelper after redraw.")

        bounds_items = list(helper.widgetBoundsIterator())
        graph_item = next(
            (
                (widget, bounds)
                for widget, bounds in bounds_items
                if widget.typename == "graph"
            ),
            None,
        )
        if graph_item is None:
            raise RuntimeError(
                "The document does not contain a graph interaction surface."
            )
        _, bounds = graph_item
        scene_x = ((float(bounds[0]) + float(bounds[2])) / 2.0) * helper.cgscale
        scene_y = ((float(bounds[1]) + float(bounds[3])) / 2.0) * helper.cgscale
        scene_point = self._QtCore.QPointF(scene_x, scene_y)
        viewport_point = self.plot_window.mapFromScene(scene_point)

        selected: list[dict[str, str]] = []

        def on_selected(widget: Any, mode: str) -> None:
            selected.append({"path": str(widget.path), "mode": str(mode)})

        self.plot_window.sigWidgetClicked.connect(on_selected)
        try:
            self.plot_window.identifyAndClickWidget(
                scene_x,
                scene_y,
                self._QtCore.Qt.KeyboardModifier.NoModifier,
            )
        finally:
            self.plot_window.sigWidgetClicked.disconnect(on_selected)

        axis_values = {
            str(axis.name): float(value)
            for axis, value in self.plot_window.axesForPoint(viewport_point).items()
        }
        return {
            "selection_signal_received": bool(selected),
            "selection": selected[-1] if selected else None,
            "axis_coordinates_reported": bool(axis_values),
            "axis_values": axis_values,
            "scene_point": [scene_x, scene_y],
        }

    def close(self) -> None:
        self.assert_gui_thread()
        self.plot_window.rendercontrol.exitThreads()
        self.plot_window.close()
        self.application.processEvents()


__all__ = ["VeuszCanvasAdapter"]
