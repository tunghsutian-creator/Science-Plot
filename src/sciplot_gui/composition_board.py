from __future__ import annotations

from pathlib import Path
from typing import Any

from PyQt6 import QtCore, QtGui, QtWidgets

from sciplot_core.canvas.composition import (
    COMPOSITE_CANVAS_WIDTH_MM,
    CompositionProject,
    CompositionSlot,
)
from sciplot_gui.theme import CanvasThemeTokens

_UNITS_PER_MM = 4.0
_PAGE_ORIGIN = QtCore.QPointF(58.0, 52.0)
_CARD_INSET = 3.0


class CompositionModuleItem(QtWidgets.QGraphicsObject):
    """A draggable display proxy for one immutable source VSZ module."""

    def __init__(
        self,
        *,
        board: CompositionBoard,
        module_id: str,
        title: str,
        size: QtCore.QSizeF,
        home_pos: QtCore.QPointF,
        preview_path: Path | None,
        assigned_slot: str | None,
    ) -> None:
        super().__init__()
        self.board = board
        self.module_id = module_id
        self.title = title
        self.assigned_slot = assigned_slot
        self.home_pos = QtCore.QPointF(home_pos)
        self._rect = QtCore.QRectF(0.0, 0.0, size.width(), size.height())
        self._dragging = False
        self._hovered = False
        self._pixmap = QtGui.QPixmap()
        if preview_path is not None and preview_path.is_file():
            self._pixmap.load(str(preview_path))
        self.setPos(self.home_pos)
        self.setZValue(20.0)
        self.setFlags(
            QtWidgets.QGraphicsItem.GraphicsItemFlag.ItemIsMovable
            | QtWidgets.QGraphicsItem.GraphicsItemFlag.ItemIsSelectable
            | QtWidgets.QGraphicsItem.GraphicsItemFlag.ItemIsFocusable
            | QtWidgets.QGraphicsItem.GraphicsItemFlag.ItemSendsGeometryChanges
        )
        self.setAcceptHoverEvents(True)
        self.setCursor(QtCore.Qt.CursorShape.OpenHandCursor)
        self.setToolTip(
            f"{title}\nDrag to a publication slot. The source VSZ remains unchanged."
        )

    def boundingRect(self) -> QtCore.QRectF:
        return self._rect.adjusted(-2.0, -2.0, 2.0, 2.0)

    def paint(
        self,
        painter: QtGui.QPainter,
        option: QtWidgets.QStyleOptionGraphicsItem,
        widget: QtWidgets.QWidget | None = None,
    ) -> None:
        del option, widget
        painter.setRenderHint(QtGui.QPainter.RenderHint.Antialiasing, True)
        tokens = self.board.theme_tokens
        selected = self.isSelected() or self._dragging
        border_color = QtGui.QColor(tokens.focus if selected else tokens.border)
        border_width = 2.2 if selected else 1.0
        painter.setPen(QtGui.QPen(border_color, border_width))
        painter.setBrush(QtGui.QBrush(QtGui.QColor("#ffffff")))
        painter.drawRoundedRect(self._rect, 5.0, 5.0)

        image_rect = self._rect.adjusted(5.0, 5.0, -5.0, -22.0)
        if not self._pixmap.isNull() and image_rect.height() > 4.0:
            source_size = self._pixmap.size()
            scaled = source_size.scaled(
                max(1, round(image_rect.width())),
                max(1, round(image_rect.height())),
                QtCore.Qt.AspectRatioMode.KeepAspectRatio,
            )
            target = QtCore.QRectF(
                image_rect.center().x() - scaled.width() / 2.0,
                image_rect.center().y() - scaled.height() / 2.0,
                float(scaled.width()),
                float(scaled.height()),
            )
            painter.drawPixmap(
                target,
                self._pixmap,
                QtCore.QRectF(self._pixmap.rect()),
            )
        else:
            painter.setPen(QtGui.QPen(QtGui.QColor(tokens.muted_text), 1.0))
            painter.drawText(
                image_rect,
                QtCore.Qt.AlignmentFlag.AlignCenter,
                "VSZ",
            )

        title_rect = QtCore.QRectF(
            7.0,
            max(2.0, self._rect.height() - 19.0),
            max(1.0, self._rect.width() - 14.0),
            15.0,
        )
        font = painter.font()
        font.setPointSizeF(8.0)
        font.setWeight(QtGui.QFont.Weight.DemiBold)
        painter.setFont(font)
        painter.setPen(QtGui.QPen(QtGui.QColor(tokens.text)))
        metrics = QtGui.QFontMetricsF(font)
        label = metrics.elidedText(
            self.title,
            QtCore.Qt.TextElideMode.ElideMiddle,
            title_rect.width(),
        )
        painter.drawText(
            title_rect,
            QtCore.Qt.AlignmentFlag.AlignLeft | QtCore.Qt.AlignmentFlag.AlignVCenter,
            label,
        )

    def hoverEnterEvent(self, event: QtWidgets.QGraphicsSceneHoverEvent) -> None:
        self._hovered = True
        self.update()
        super().hoverEnterEvent(event)

    def hoverLeaveEvent(self, event: QtWidgets.QGraphicsSceneHoverEvent) -> None:
        self._hovered = False
        self.update()
        super().hoverLeaveEvent(event)

    def mousePressEvent(self, event: QtWidgets.QGraphicsSceneMouseEvent) -> None:
        self._dragging = True
        self.setCursor(QtCore.Qt.CursorShape.ClosedHandCursor)
        self.setZValue(60.0)
        self.board.set_selected_module(self.module_id)
        self.update()
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event: QtWidgets.QGraphicsSceneMouseEvent) -> None:
        super().mouseMoveEvent(event)
        self.board.highlight_drop_target(self.board.snap_slot_at(event.scenePos()))

    def mouseReleaseEvent(self, event: QtWidgets.QGraphicsSceneMouseEvent) -> None:
        super().mouseReleaseEvent(event)
        target_slot = self.board.snap_slot_at(event.scenePos())
        self._dragging = False
        self.setCursor(QtCore.Qt.CursorShape.OpenHandCursor)
        self.setZValue(20.0)
        self.setPos(self.home_pos)
        self.board.highlight_drop_target(None)
        self.update()
        self.board.queue_drop(self.module_id, target_slot)


class CompositionBoard(QtWidgets.QGraphicsView):
    """Exact-mm arrangement surface; all mutations leave through dropRequested."""

    dropRequested = QtCore.pyqtSignal(str, object)
    selectedModuleChanged = QtCore.pyqtSignal(str)

    def __init__(
        self,
        *,
        parent: QtWidgets.QWidget | None = None,
    ) -> None:
        scene = QtWidgets.QGraphicsScene(parent)
        super().__init__(scene, parent)
        self.setObjectName("compositionBoard")
        self.setAccessibleName("183 millimetre composition board")
        self.setAccessibleDescription(
            "Drag immutable figure modules between exact publication slots."
        )
        self.setRenderHints(
            QtGui.QPainter.RenderHint.Antialiasing
            | QtGui.QPainter.RenderHint.TextAntialiasing
            | QtGui.QPainter.RenderHint.SmoothPixmapTransform
        )
        self.setFrameShape(QtWidgets.QFrame.Shape.NoFrame)
        self.setHorizontalScrollBarPolicy(QtCore.Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.setVerticalScrollBarPolicy(QtCore.Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.setDragMode(QtWidgets.QGraphicsView.DragMode.NoDrag)
        self.setTransformationAnchor(
            QtWidgets.QGraphicsView.ViewportAnchor.AnchorViewCenter
        )
        self.project: CompositionProject | None = None
        self.preview_records: dict[str, dict[str, Any]] = {}
        self.module_items: dict[str, CompositionModuleItem] = {}
        self.slot_rects: dict[str, QtCore.QRectF] = {}
        self.slot_outlines: dict[str, QtWidgets.QGraphicsRectItem] = {}
        self.selected_module_id: str | None = None
        self._highlighted_slot: str | None = None
        self.theme_tokens = self._fallback_theme_tokens()
        self.setBackgroundBrush(QtGui.QColor(self.theme_tokens.canvas_well))

    def _fallback_theme_tokens(self) -> CanvasThemeTokens:
        from sciplot_gui.theme import build_canvas_theme

        application = QtWidgets.QApplication.instance()
        palette = application.palette() if application is not None else self.palette()
        return build_canvas_theme(palette)

    def set_theme(self, tokens: CanvasThemeTokens) -> None:
        self.theme_tokens = tokens
        self.setBackgroundBrush(QtGui.QColor(tokens.canvas_well))
        if self.project is not None:
            self.refresh(self.project, self.preview_records)

    @property
    def page_rect(self) -> QtCore.QRectF:
        if self.project is None:
            return QtCore.QRectF()
        height = self.project.active_variant.layout.canvas_height_mm
        return QtCore.QRectF(
            _PAGE_ORIGIN.x(),
            _PAGE_ORIGIN.y(),
            COMPOSITE_CANVAS_WIDTH_MM * _UNITS_PER_MM,
            height * _UNITS_PER_MM,
        )

    def _slot_scene_rect(self, slot: CompositionSlot) -> QtCore.QRectF:
        return QtCore.QRectF(
            _PAGE_ORIGIN.x() + slot.x_mm * _UNITS_PER_MM,
            _PAGE_ORIGIN.y() + slot.y_mm * _UNITS_PER_MM,
            slot.width_mm * _UNITS_PER_MM,
            slot.height_mm * _UNITS_PER_MM,
        )

    def refresh(
        self,
        project: CompositionProject,
        preview_records: dict[str, dict[str, Any]] | None = None,
    ) -> None:
        self.project = project
        if preview_records is not None:
            self.preview_records = dict(preview_records)
        scene = self.scene()
        scene.clear()
        self.module_items.clear()
        self.slot_rects.clear()
        self.slot_outlines.clear()
        self._highlighted_slot = None
        variant = project.active_variant
        page = self.page_rect

        shadow = scene.addRect(
            page.translated(3.0, 4.0),
            QtGui.QPen(QtCore.Qt.PenStyle.NoPen),
            QtGui.QBrush(QtGui.QColor(0, 0, 0, 28)),
        )
        shadow.setZValue(-3.0)
        paper = scene.addRect(
            page,
            QtGui.QPen(QtGui.QColor(self.theme_tokens.border), 0.8),
            QtGui.QBrush(QtGui.QColor("#ffffff")),
        )
        paper.setZValue(-2.0)
        self._draw_rulers(page)

        for slot in variant.layout.slots:
            slot_rect = self._slot_scene_rect(slot)
            self.slot_rects[slot.slot_id] = slot_rect
            outline = scene.addRect(
                slot_rect.adjusted(1.5, 1.5, -1.5, -1.5),
                QtGui.QPen(
                    QtGui.QColor(self.theme_tokens.border),
                    1.0,
                    QtCore.Qt.PenStyle.DashLine,
                ),
                QtGui.QBrush(QtCore.Qt.BrushStyle.NoBrush),
            )
            outline.setZValue(2.0)
            outline.setAcceptedMouseButtons(QtCore.Qt.MouseButton.NoButton)
            self.slot_outlines[slot.slot_id] = outline
            badge = scene.addSimpleText(slot.panel_label)
            font = badge.font()
            font.setPointSizeF(12.0)
            font.setWeight(QtGui.QFont.Weight.Bold)
            badge.setFont(font)
            badge.setBrush(QtGui.QColor(self.theme_tokens.text))
            badge.setPos(slot_rect.left() + 8.0, slot_rect.top() + 5.0)
            badge.setZValue(45.0)
            badge.setAcceptedMouseButtons(QtCore.Qt.MouseButton.NoButton)

        unassigned_index = 0
        for module in project.source_modules:
            placement = variant.placement(module.module_id)
            slot_rect = (
                self.slot_rects.get(placement.slot_ref)
                if placement.slot_ref is not None
                else None
            )
            if slot_rect is not None:
                home = QtCore.QPointF(
                    slot_rect.left() + _CARD_INSET,
                    slot_rect.top() + _CARD_INSET,
                )
                size = QtCore.QSizeF(
                    max(42.0, slot_rect.width() - 2.0 * _CARD_INSET),
                    max(38.0, slot_rect.height() - 2.0 * _CARD_INSET),
                )
            else:
                column = unassigned_index % 4
                row = unassigned_index // 4
                home = QtCore.QPointF(
                    page.left() + column * 172.0,
                    page.bottom() + 64.0 + row * 112.0,
                )
                size = QtCore.QSizeF(156.0, 96.0)
                unassigned_index += 1
            preview_value = self.preview_records.get(module.module_id, {}).get(
                "preview"
            )
            preview_path = Path(str(preview_value)) if preview_value else None
            item = CompositionModuleItem(
                board=self,
                module_id=module.module_id,
                title=module.title,
                size=size,
                home_pos=home,
                preview_path=preview_path,
                assigned_slot=placement.slot_ref,
            )
            scene.addItem(item)
            self.module_items[module.module_id] = item
            if module.module_id == self.selected_module_id:
                item.setSelected(True)

        tray_y = page.bottom() + 45.0
        tray_label = scene.addSimpleText("MODULE TRAY  •  source previews only")
        font = tray_label.font()
        font.setPointSizeF(8.0)
        font.setWeight(QtGui.QFont.Weight.DemiBold)
        tray_label.setFont(font)
        tray_label.setBrush(QtGui.QColor(self.theme_tokens.muted_text))
        tray_label.setPos(page.left(), tray_y)
        tray_label.setZValue(1.0)
        tray_label.setAcceptedMouseButtons(QtCore.Qt.MouseButton.NoButton)

        scene_height = page.bottom() + 185.0 + max(0, unassigned_index - 1) // 4 * 112.0
        scene.setSceneRect(
            0.0,
            0.0,
            page.right() + 58.0,
            scene_height,
        )
        self.fit_board()

    def _draw_rulers(self, page: QtCore.QRectF) -> None:
        scene = self.scene()
        ruler_pen = QtGui.QPen(QtGui.QColor(self.theme_tokens.muted_text), 0.7)
        label_font = QtGui.QFont()
        label_font.setPointSizeF(7.0)
        top_y = page.top() - 15.0
        scene.addLine(page.left(), top_y, page.right(), top_y, ruler_pen)
        for millimetre in range(0, 184, 5):
            x = page.left() + millimetre * _UNITS_PER_MM
            major = millimetre % 30 == 0 or millimetre == 183
            tick = 7.0 if major else 3.5
            scene.addLine(x, top_y, x, top_y + tick, ruler_pen)
            if major:
                label = scene.addSimpleText(str(millimetre))
                label.setFont(label_font)
                label.setBrush(QtGui.QColor(self.theme_tokens.muted_text))
                label.setPos(x - label.boundingRect().width() / 2.0, top_y - 15.0)
        unit = scene.addSimpleText("mm")
        unit.setFont(label_font)
        unit.setBrush(QtGui.QColor(self.theme_tokens.muted_text))
        unit.setPos(page.right() + 10.0, top_y - 8.0)

        left_x = page.left() - 15.0
        scene.addLine(left_x, page.top(), left_x, page.bottom(), ruler_pen)
        height = round(page.height() / _UNITS_PER_MM)
        for millimetre in range(0, height + 1, 5):
            y = page.top() + millimetre * _UNITS_PER_MM
            major = millimetre % 10 == 0 or millimetre == height
            tick = 7.0 if major else 3.5
            scene.addLine(left_x, y, left_x + tick, y, ruler_pen)
            if major:
                label = scene.addSimpleText(str(millimetre))
                label.setFont(label_font)
                label.setBrush(QtGui.QColor(self.theme_tokens.muted_text))
                label.setPos(
                    left_x - label.boundingRect().width() - 4.0,
                    y - label.boundingRect().height() / 2.0,
                )

    def set_selected_module(self, module_id: str) -> None:
        if module_id not in self.module_items:
            return
        self.selected_module_id = module_id
        for candidate, item in self.module_items.items():
            item.setSelected(candidate == module_id)
            item.update()
        self.selectedModuleChanged.emit(module_id)

    def snap_slot_at(self, scene_pos: QtCore.QPointF) -> str | None:
        for slot_id, rect in self.slot_rects.items():
            if rect.contains(scene_pos):
                return slot_id
        page = self.page_rect.adjusted(-8.0, -8.0, 8.0, 8.0)
        if page.contains(scene_pos) and self.slot_rects:
            return min(
                self.slot_rects,
                key=lambda slot_id: QtCore.QLineF(
                    scene_pos,
                    self.slot_rects[slot_id].center(),
                ).length(),
            )
        return None

    def highlight_drop_target(self, slot_ref: str | None) -> None:
        if self._highlighted_slot == slot_ref:
            return
        self._highlighted_slot = slot_ref
        for slot_id, outline in self.slot_outlines.items():
            highlighted = slot_id == slot_ref
            outline.setPen(
                QtGui.QPen(
                    QtGui.QColor(
                        self.theme_tokens.focus
                        if highlighted
                        else self.theme_tokens.border
                    ),
                    2.4 if highlighted else 1.0,
                    (
                        QtCore.Qt.PenStyle.SolidLine
                        if highlighted
                        else QtCore.Qt.PenStyle.DashLine
                    ),
                )
            )

    def queue_drop(self, module_id: str, slot_ref: str | None) -> None:
        if self.project is None:
            return
        current = self.project.active_variant.placement(module_id).slot_ref
        if current == slot_ref:
            return
        QtCore.QTimer.singleShot(
            0,
            lambda module_id=module_id, slot_ref=slot_ref: self.dropRequested.emit(
                module_id,
                slot_ref,
            ),
        )

    def fit_board(self) -> None:
        if self.scene().sceneRect().isEmpty():
            return
        self.fitInView(
            self.scene().sceneRect(),
            QtCore.Qt.AspectRatioMode.KeepAspectRatio,
        )

    def resizeEvent(self, event: QtGui.QResizeEvent) -> None:
        super().resizeEvent(event)
        self.fit_board()

    def keyPressEvent(self, event: QtGui.QKeyEvent) -> None:
        if self.project is None or self.selected_module_id is None:
            super().keyPressEvent(event)
            return
        variant = self.project.active_variant
        current = variant.placement(self.selected_module_id).slot_ref
        if (
            event.key()
            in {
                QtCore.Qt.Key.Key_Left,
                QtCore.Qt.Key.Key_Right,
            }
            and current in variant.layout.slot_ids
        ):
            index = variant.layout.slot_ids.index(current)
            delta = -1 if event.key() == QtCore.Qt.Key.Key_Left else 1
            target_index = min(
                max(index + delta, 0),
                len(variant.layout.slot_ids) - 1,
            )
            self.queue_drop(
                self.selected_module_id,
                variant.layout.slot_ids[target_index],
            )
            event.accept()
            return
        if event.key() in {QtCore.Qt.Key.Key_Delete, QtCore.Qt.Key.Key_Backspace}:
            self.queue_drop(self.selected_module_id, None)
            event.accept()
            return
        super().keyPressEvent(event)


__all__ = ["CompositionBoard", "CompositionModuleItem"]
