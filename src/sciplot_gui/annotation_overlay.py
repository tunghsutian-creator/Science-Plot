from __future__ import annotations

import math
from typing import Any

from PyQt6 import QtCore, QtGui, QtWidgets

from sciplot_core.canvas.annotations import (
    ReviewAnnotation,
    ReviewAnnotationStyle,
    annotation_geometry_from_points,
    annotation_geometry_points,
)


class ReviewOverlayItem(QtWidgets.QGraphicsItem):
    """One movable display-only review mark in the PlotWindow scene."""

    def __init__(
        self,
        annotation: ReviewAnnotation,
        scene_geometry: dict[str, Any],
        *,
        selection_color: str,
        moved_callback: Any = None,
        preview: bool = False,
    ) -> None:
        super().__init__()
        self.annotation = annotation
        self._moved_callback = moved_callback
        self._preview = bool(preview)
        self._selection_color = QtGui.QColor(selection_color)
        scene_points = annotation_geometry_points(
            annotation.shape,
            scene_geometry,
        )
        origin_x = min(point[0] for point in scene_points)
        origin_y = min(point[1] for point in scene_points)
        if annotation.shape == "text":
            origin_x, origin_y = scene_points[0]
        self._local_points = [
            QtCore.QPointF(point[0] - origin_x, point[1] - origin_y)
            for point in scene_points
        ]
        self.setPos(origin_x, origin_y)
        self._shape_bounds = self._calculate_shape_bounds()
        if not preview:
            self.setFlags(
                QtWidgets.QGraphicsItem.GraphicsItemFlag.ItemIsSelectable
                | QtWidgets.QGraphicsItem.GraphicsItemFlag.ItemIsMovable
                | QtWidgets.QGraphicsItem.GraphicsItemFlag.ItemSendsGeometryChanges
            )
            self.setAcceptHoverEvents(True)
            self.setCursor(QtCore.Qt.CursorShape.OpenHandCursor)
        else:
            self.setAcceptedMouseButtons(QtCore.Qt.MouseButton.NoButton)
        self.setZValue(30.0 if preview else 20.0)

    @property
    def annotation_id(self) -> str:
        return self.annotation.annotation_id

    def _font(self) -> QtGui.QFont:
        font = QtGui.QFont()
        font.setPointSizeF(self.annotation.style.font_size)
        return font

    def _text_bounds(self) -> QtCore.QRectF:
        metrics = QtGui.QFontMetricsF(self._font())
        text = self.annotation.text or "Review note"
        measured = metrics.boundingRect(
            QtCore.QRectF(0.0, 0.0, 220.0, 1000.0),
            int(
                QtCore.Qt.AlignmentFlag.AlignLeft
                | QtCore.Qt.AlignmentFlag.AlignTop
                | QtCore.Qt.TextFlag.TextWordWrap
            ),
            text,
        )
        width = min(max(measured.width() + 18.0, 72.0), 238.0)
        height = max(measured.height() + 14.0, 32.0)
        return QtCore.QRectF(0.0, 0.0, width, height)

    def _calculate_shape_bounds(self) -> QtCore.QRectF:
        if self.annotation.shape == "text":
            return self._text_bounds()
        xs = [point.x() for point in self._local_points]
        ys = [point.y() for point in self._local_points]
        bounds = QtCore.QRectF(
            min(xs),
            min(ys),
            max(max(xs) - min(xs), 1.0),
            max(max(ys) - min(ys), 1.0),
        )
        return bounds.normalized()

    def boundingRect(self) -> QtCore.QRectF:
        padding = max(self.annotation.style.line_width * 2.5, 8.0)
        return self._shape_bounds.adjusted(
            -padding,
            -padding,
            padding,
            padding,
        )

    def _pen(self) -> QtGui.QPen:
        color = QtGui.QColor(self.annotation.style.color)
        color.setAlphaF(
            self.annotation.style.opacity * (0.72 if self._preview else 1.0)
        )
        pen = QtGui.QPen(color, self.annotation.style.line_width)
        pen.setCosmetic(True)
        pen.setCapStyle(QtCore.Qt.PenCapStyle.RoundCap)
        pen.setJoinStyle(QtCore.Qt.PenJoinStyle.RoundJoin)
        return pen

    def _brush(self) -> QtGui.QBrush:
        color = QtGui.QColor(self.annotation.style.fill_color)
        color.setAlphaF(
            min(self.annotation.style.opacity * 0.34, 0.42)
            * (0.72 if self._preview else 1.0)
        )
        return QtGui.QBrush(color)

    def _arrow_head(
        self,
        start: QtCore.QPointF,
        end: QtCore.QPointF,
    ) -> QtGui.QPolygonF:
        angle = math.atan2(end.y() - start.y(), end.x() - start.x())
        length = max(9.0, self.annotation.style.line_width * 4.0)
        spread = math.radians(27.0)
        first = QtCore.QPointF(
            end.x() - length * math.cos(angle - spread),
            end.y() - length * math.sin(angle - spread),
        )
        second = QtCore.QPointF(
            end.x() - length * math.cos(angle + spread),
            end.y() - length * math.sin(angle + spread),
        )
        return QtGui.QPolygonF([end, first, second])

    def paint(
        self,
        painter: QtGui.QPainter,
        option: QtWidgets.QStyleOptionGraphicsItem,
        widget: QtWidgets.QWidget | None = None,
    ) -> None:
        del option, widget
        painter.save()
        painter.setRenderHint(QtGui.QPainter.RenderHint.Antialiasing, True)
        pen = self._pen()
        painter.setPen(pen)
        painter.setBrush(self._brush())
        shape = self.annotation.shape
        if shape == "text":
            rect = self._text_bounds()
            painter.drawRoundedRect(rect, 8.0, 8.0)
            painter.setFont(self._font())
            text_color = QtGui.QColor(self.annotation.style.color)
            text_color.setAlphaF(self.annotation.style.opacity)
            painter.setPen(QtGui.QPen(text_color))
            painter.drawText(
                rect.adjusted(9.0, 7.0, -9.0, -7.0),
                int(
                    QtCore.Qt.AlignmentFlag.AlignLeft
                    | QtCore.Qt.AlignmentFlag.AlignTop
                    | QtCore.Qt.TextFlag.TextWordWrap
                ),
                self.annotation.text or "Review note",
            )
        elif shape == "arrow":
            start, end = self._local_points
            painter.setBrush(QtGui.QBrush(pen.color()))
            painter.drawLine(start, end)
            painter.drawPolygon(self._arrow_head(start, end))
        elif shape == "rectangle":
            first, second = self._local_points
            painter.drawRoundedRect(
                QtCore.QRectF(first, second).normalized(),
                4.0,
                4.0,
            )
        elif shape == "ellipse":
            first, second = self._local_points
            painter.drawEllipse(QtCore.QRectF(first, second).normalized())
        elif shape == "freehand":
            path = QtGui.QPainterPath(self._local_points[0])
            for point in self._local_points[1:]:
                path.lineTo(point)
            painter.setBrush(QtCore.Qt.BrushStyle.NoBrush)
            painter.drawPath(path)
        if self.isSelected() and not self._preview:
            selection_pen = QtGui.QPen(
                self._selection_color,
                1.5,
                QtCore.Qt.PenStyle.DashLine,
            )
            selection_pen.setCosmetic(True)
            painter.setPen(selection_pen)
            painter.setBrush(QtCore.Qt.BrushStyle.NoBrush)
            painter.drawRoundedRect(
                self._shape_bounds.adjusted(-5.0, -5.0, 5.0, 5.0),
                5.0,
                5.0,
            )
        painter.restore()

    def scene_geometry(self) -> dict[str, Any]:
        points = [
            (
                self.pos().x() + point.x(),
                self.pos().y() + point.y(),
            )
            for point in self._local_points
        ]
        return annotation_geometry_from_points(self.annotation.shape, points)

    def mousePressEvent(
        self,
        event: QtWidgets.QGraphicsSceneMouseEvent,
    ) -> None:
        self.setCursor(QtCore.Qt.CursorShape.ClosedHandCursor)
        super().mousePressEvent(event)

    def mouseReleaseEvent(
        self,
        event: QtWidgets.QGraphicsSceneMouseEvent,
    ) -> None:
        super().mouseReleaseEvent(event)
        self.setCursor(QtCore.Qt.CursorShape.OpenHandCursor)
        if self._moved_callback is not None:
            self._moved_callback(
                self.annotation.annotation_id,
                self.scene_geometry(),
            )


class AnnotationOverlayController(QtCore.QObject):
    """Own drawing gestures and review items without touching the VSZ."""

    annotationSelected = QtCore.pyqtSignal(str)
    geometryCreated = QtCore.pyqtSignal(str, object)
    geometryMoved = QtCore.pyqtSignal(str, object)
    toolCancelled = QtCore.pyqtSignal()

    def __init__(
        self,
        plot_window: QtWidgets.QGraphicsView,
        *,
        selection_color: str = "#0a84ff",
        parent: QtCore.QObject | None = None,
    ) -> None:
        super().__init__(parent)
        self.plot_window = plot_window
        self.scene = plot_window.scene
        self._selection_color = selection_color
        self._tool = "select"
        self._start: QtCore.QPointF | None = None
        self._freehand_points: list[QtCore.QPointF] = []
        self._preview_item: ReviewOverlayItem | None = None
        self._items: dict[str, ReviewOverlayItem] = {}
        self._rendering = False
        self.plot_window.viewport().installEventFilter(self)
        self.scene.selectionChanged.connect(self._scene_selection_changed)

    @property
    def tool(self) -> str:
        return self._tool

    @property
    def selected_annotation_id(self) -> str | None:
        for annotation_id, item in self._items.items():
            if item.isSelected():
                return annotation_id
        return None

    def set_selection_color(self, color: str) -> None:
        self._selection_color = str(color)

    def set_tool(self, tool: str) -> str:
        if tool not in {
            "select",
            "text",
            "arrow",
            "rectangle",
            "ellipse",
            "freehand",
        }:
            raise ValueError(f"Unsupported review tool: {tool!r}")
        self.cancel_gesture()
        self._tool = tool
        cursor = (
            QtCore.Qt.CursorShape.ArrowCursor
            if tool == "select"
            else QtCore.Qt.CursorShape.CrossCursor
        )
        self.plot_window.viewport().setCursor(cursor)
        return tool

    def _scene_selection_changed(self) -> None:
        if self._rendering:
            return
        annotation_id = self.selected_annotation_id
        if annotation_id is not None:
            self.annotationSelected.emit(annotation_id)

    def select_annotation(self, annotation_id: str | None) -> None:
        self._rendering = True
        try:
            self.scene.clearSelection()
            if annotation_id is not None and annotation_id in self._items:
                self._items[annotation_id].setSelected(True)
                self._items[annotation_id].ensureVisible(
                    QtCore.QRectF(),
                    24,
                    24,
                )
        finally:
            self._rendering = False

    def set_annotations(
        self,
        entries: list[tuple[ReviewAnnotation, dict[str, Any]]],
    ) -> None:
        selected = self.selected_annotation_id
        self._rendering = True
        try:
            for item in self._items.values():
                self.scene.removeItem(item)
            self._items.clear()
            for annotation, scene_geometry in entries:
                item = ReviewOverlayItem(
                    annotation,
                    scene_geometry,
                    selection_color=self._selection_color,
                    moved_callback=self.geometryMoved.emit,
                )
                self.scene.addItem(item)
                self._items[annotation.annotation_id] = item
            if selected in self._items:
                self._items[selected].setSelected(True)
        finally:
            self._rendering = False

    def cancel_gesture(self) -> None:
        self._start = None
        self._freehand_points = []
        if self._preview_item is not None:
            self.scene.removeItem(self._preview_item)
            self._preview_item = None

    def _inside_page(self, point: QtCore.QPointF) -> bool:
        return self.plot_window.pixmapitem.boundingRect().contains(point)

    def _geometry_for_points(
        self,
        start: QtCore.QPointF,
        end: QtCore.QPointF,
    ) -> dict[str, Any]:
        if self._tool == "text":
            return {"position": [end.x(), end.y()]}
        if self._tool == "arrow":
            return {
                "start": [start.x(), start.y()],
                "end": [end.x(), end.y()],
            }
        if self._tool in {"rectangle", "ellipse"}:
            rect = QtCore.QRectF(start, end).normalized()
            return {
                "rect": [
                    rect.left(),
                    rect.top(),
                    rect.width(),
                    rect.height(),
                ]
            }
        if self._tool == "freehand":
            return {
                "points": [
                    [point.x(), point.y()]
                    for point in self._freehand_points
                ]
            }
        raise ValueError(f"Unsupported review drawing tool: {self._tool!r}")

    def _show_preview(self, geometry: dict[str, Any]) -> None:
        if self._preview_item is not None:
            self.scene.removeItem(self._preview_item)
        annotation = ReviewAnnotation(
            page_index=0,
            shape=self._tool,
            coordinate_space="page",
            geometry=geometry,
            text="Review note" if self._tool == "text" else "",
            style=ReviewAnnotationStyle(),
        )
        self._preview_item = ReviewOverlayItem(
            annotation,
            geometry,
            selection_color=self._selection_color,
            preview=True,
        )
        self.scene.addItem(self._preview_item)

    def eventFilter(
        self,
        watched: QtCore.QObject,
        event: QtCore.QEvent,
    ) -> bool:
        if watched is not self.plot_window.viewport() or self._tool == "select":
            return super().eventFilter(watched, event)
        if (
            event.type() == QtCore.QEvent.Type.KeyPress
            and isinstance(event, QtGui.QKeyEvent)
            and event.key() == QtCore.Qt.Key.Key_Escape
        ):
            self.cancel_gesture()
            self.toolCancelled.emit()
            event.accept()
            return True
        if not isinstance(event, QtGui.QMouseEvent):
            return super().eventFilter(watched, event)
        point = self.plot_window.mapToScene(event.position().toPoint())
        if (
            event.type() == QtCore.QEvent.Type.MouseButtonPress
            and event.button() == QtCore.Qt.MouseButton.LeftButton
        ):
            if not self._inside_page(point):
                return True
            self._start = QtCore.QPointF(point)
            self._freehand_points = [QtCore.QPointF(point)]
            event.accept()
            return True
        if (
            event.type() == QtCore.QEvent.Type.MouseMove
            and self._start is not None
            and event.buttons() & QtCore.Qt.MouseButton.LeftButton
        ):
            if self._tool == "freehand":
                if (
                    not self._freehand_points
                    or QtCore.QLineF(self._freehand_points[-1], point).length() >= 2.0
                ):
                    self._freehand_points.append(QtCore.QPointF(point))
            geometry = self._geometry_for_points(self._start, point)
            if self._tool != "freehand" or len(self._freehand_points) >= 2:
                self._show_preview(geometry)
            event.accept()
            return True
        if (
            event.type() == QtCore.QEvent.Type.MouseButtonRelease
            and event.button() == QtCore.Qt.MouseButton.LeftButton
            and self._start is not None
        ):
            start = self._start
            if self._tool == "freehand" and (
                not self._freehand_points
                or self._freehand_points[-1] != point
            ):
                self._freehand_points.append(QtCore.QPointF(point))
            distance = QtCore.QLineF(start, point).length()
            geometry = self._geometry_for_points(start, point)
            valid = (
                self._tool == "text"
                or (
                    self._tool == "freehand"
                    and len(self._freehand_points) >= 2
                    and distance >= 2.0
                )
                or distance >= 4.0
            )
            self.cancel_gesture()
            if valid:
                self.geometryCreated.emit(self._tool, geometry)
            event.accept()
            return True
        return super().eventFilter(watched, event)

    def close(self) -> None:
        self.cancel_gesture()
        self.plot_window.viewport().removeEventFilter(self)
        self.scene.selectionChanged.disconnect(self._scene_selection_changed)
        self._rendering = True
        try:
            for item in self._items.values():
                self.scene.removeItem(item)
            self._items.clear()
        finally:
            self._rendering = False


__all__ = [
    "AnnotationOverlayController",
    "ReviewOverlayItem",
]
