"""Physical-grid overview: whole-panel selection, movement and image crop."""

from PyQt6 import QtCore, QtGui, QtWidgets

from . import model
from .desktop_sources import source_title


class AssemblyCanvas(QtWidgets.QWidget):
    panelSelected = QtCore.pyqtSignal(str)
    panelMoved = QtCore.pyqtSignal(str, int, int)
    panelCropped = QtCore.pyqtSignal(str, object)
    undoRequested = QtCore.pyqtSignal()
    redoRequested = QtCore.pyqtSignal()
    removeRequested = QtCore.pyqtSignal(str)

    def __init__(self, previews, parent=None):
        super().__init__(parent)
        self.previews = previews
        self.setObjectName("assemblyCanvas")
        self.setMinimumSize(380, 320)
        self.setFocusPolicy(QtCore.Qt.FocusPolicy.StrongFocus)
        self.setMouseTracking(True)
        self.document = None
        self.selected = ""
        self.crop_mode = False
        self.conflicts = {}
        self._press = None
        self._drag_position = None
        self._crop_start = None
        self._crop_end = None

    def set_document(self, document, selected=""):
        self.document = document
        self.selected = selected
        self.resolved = model.resolve_document(document)
        self.update()

    def page_rect(self):
        available = QtCore.QRectF(self.rect()).adjusted(32, 38, -32, -38)
        if not self.document:
            return available
        layout = self.document["layout"]
        scale = min(available.width() / layout["width_mm"], available.height() / layout["height_mm"])
        width, height = layout["width_mm"] * scale, layout["height_mm"] * scale
        return QtCore.QRectF(available.center().x() - width / 2, available.center().y() - height / 2, width, height)

    def physical_rect(self, values):
        page = self.page_rect()
        scale = page.width() / self.document["layout"]["width_mm"]
        x, y, width, height = values
        return QtCore.QRectF(page.x() + x * scale, page.y() + y * scale, width * scale, height * scale)

    def panel_rect(self, identifier):
        return self.physical_rect(next(item["cell_mm"] for item in self.resolved["panels"] if item["id"] == identifier))

    def cell_at(self, point):
        page = self.page_rect()
        if not page.contains(QtCore.QPointF(point)):
            return None
        layout = self.document["layout"]
        x = (point.x() - page.x()) / page.width() * layout["width_mm"]
        y = (point.y() - page.y()) / page.height() * layout["height_mm"]
        step_x = (layout["width_mm"] + layout["gap_x_mm"]) / layout["columns"]
        step_y = (layout["height_mm"] + layout["gap_y_mm"]) / layout["rows"]
        return min(int(y / step_y), layout["rows"] - 1), min(int(x / step_x), layout["columns"] - 1)

    def _panel_at(self, point):
        return next((panel for panel in reversed(self.document["panels"])
                     if self.panel_rect(panel["id"]).contains(QtCore.QPointF(point))), None)

    def paintEvent(self, _event):
        painter = QtGui.QPainter(self)
        painter.setRenderHint(QtGui.QPainter.RenderHint.Antialiasing)
        painter.fillRect(self.rect(), QtGui.QColor("#e9edf0"))
        if not self.document:
            return
        page = self.page_rect()
        painter.fillRect(page.translated(3, 4), QtGui.QColor("#c5ccd2"))
        painter.fillRect(page, QtCore.Qt.GlobalColor.white)
        painter.setPen(QtGui.QColor("#607080"))
        layout = self.document["layout"]
        painter.drawText(QtCore.QRectF(page.x(), page.y() - 26, page.width(), 20),
                         QtCore.Qt.AlignmentFlag.AlignCenter,
                         f"{layout['width_mm']:g} × {layout['height_mm']:g} mm  ·  {layout['rows']} × {layout['columns']}")
        painter.setPen(QtGui.QPen(QtGui.QColor("#d6dee5"), 1, QtCore.Qt.PenStyle.DashLine))
        for row in range(layout["rows"]):
            for column in range(layout["columns"]):
                cell_w = (layout["width_mm"] - (layout["columns"] - 1) * layout["gap_x_mm"]) / layout["columns"]
                cell_h = (layout["height_mm"] - (layout["rows"] - 1) * layout["gap_y_mm"]) / layout["rows"]
                painter.drawRect(self.physical_rect([column * (cell_w + layout["gap_x_mm"]),
                                                     row * (cell_h + layout["gap_y_mm"]), cell_w, cell_h]))
        for resolved in self.resolved["panels"]:
            panel = next(p for p in self.document["panels"] if p["id"] == resolved["id"])
            self._paint_panel(painter, panel, resolved)
        painter.setPen(QtGui.QColor("#607080"))
        painter.setFont(self.font())
        painter.drawText(QtCore.QRectF(page.x(), page.bottom() + 8, page.width(), 24),
                         QtCore.Qt.AlignmentFlag.AlignCenter,
                         "Placement preview · export checks the target physical size")
        if self._crop_start is not None and self._crop_end is not None:
            painter.setPen(QtGui.QPen(QtGui.QColor("#e99a20"), 2))
            painter.drawRect(QtCore.QRectF(self._crop_start, self._crop_end).normalized())
        elif self._press is not None and self._drag_position is not None:
            painter.setPen(QtGui.QPen(QtGui.QColor("#2176ae"), 2, QtCore.Qt.PenStyle.DashLine))
            painter.setBrush(QtGui.QColor(33, 118, 174, 30))
            painter.drawRect(self.panel_rect(self.selected).translated(self._drag_position - self._press))
        painter.end()

    def _paint_panel(self, painter, panel, resolved):
        painter.setFont(self.font())
        rectangle = self.physical_rect(resolved["cell_mm"])
        content = self.physical_rect(resolved["content_mm"])
        painter.fillRect(rectangle.adjusted(1, 1, -1, -1), QtCore.Qt.GlobalColor.white)
        image = self.previews.get(panel["source"])
        if not image.isNull():
            crop = panel.get("crop") or [0, 0, 1, 1]
            image = image.copy(QtCore.QRect(int(crop[0] * image.width()), int(crop[1] * image.height()),
                                           max(1, int((crop[2] - crop[0]) * image.width())),
                                           max(1, int((crop[3] - crop[1]) * image.height()))))
            painter.drawPixmap(self.image_rect(panel["id"], image).toRect(), image)
        else:
            painter.setPen(QtGui.QColor("#536577"))
            detail = "Preview unavailable · check source" if self.previews.error(panel["source"]) else "Loading current source preview…"
            painter.drawText(content.adjusted(10, 10, -10, -10),
                             QtCore.Qt.AlignmentFlag.AlignCenter | QtCore.Qt.TextFlag.TextWordWrap,
                             source_title(panel["source"]) + "\n" + detail)
        painter.setPen(QtGui.QColor("#152b40"))
        font = painter.font()
        font.setBold(True)
        font.setPointSize(12)
        painter.setFont(font)
        scale = self.page_rect().width() / self.document["layout"]["width_mm"]
        x, y = resolved["label_mm"]
        painter.drawText(QtCore.QPointF(self.page_rect().x() + x * scale,
                                       self.page_rect().y() + y * scale + painter.fontMetrics().ascent()), resolved["label"])
        color = "#c83d3d" if panel["id"] in self.conflicts else "#2176ae" if panel["id"] == self.selected else "#afbdc8"
        painter.setPen(QtGui.QPen(QtGui.QColor(color), 2 if panel["id"] == self.selected else 1))
        painter.drawRect(rectangle)
        if panel["id"] in self.conflicts:
            painter.drawText(rectangle.adjusted(6, 6, -6, -6), QtCore.Qt.AlignmentFlag.AlignBottom,
                             "Source changed · choose current version")

    def image_rect(self, identifier, image=None):
        panel = next(p for p in self.document["panels"] if p["id"] == identifier)
        resolved = next(p for p in self.resolved["panels"] if p["id"] == identifier)
        content = self.physical_rect(resolved["content_mm"])
        if image is None:
            image = self.previews.get(panel["source"])
            if not image.isNull():
                crop = panel.get("crop") or [0, 0, 1, 1]
                size = QtCore.QSizeF(image.width() * (crop[2] - crop[0]), image.height() * (crop[3] - crop[1]))
            else:
                return content
        else:
            size = QtCore.QSizeF(image.size())
        size.scale(content.size(), QtCore.Qt.AspectRatioMode.KeepAspectRatio)
        return QtCore.QRectF(content.center().x() - size.width() / 2, content.center().y() - size.height() / 2,
                             size.width(), size.height())

    def mousePressEvent(self, event):
        if event.button() != QtCore.Qt.MouseButton.LeftButton or not self.document:
            return
        self.setFocus()
        panel = self._panel_at(event.position())
        if panel is None:
            return
        self.selected = panel["id"]
        self.panelSelected.emit(self.selected)
        self._press = event.position()
        if self.crop_mode and panel["source"]["kind"] == "image":
            if not self.previews.get(panel["source"]).isNull() and self.image_rect(self.selected).contains(event.position()):
                self._crop_start = event.position()
        self.update()

    def mouseMoveEvent(self, event):
        if self._crop_start is not None:
            self._crop_end = event.position()
            self.update()
        elif self._press is not None and not self.crop_mode:
            self._drag_position = event.position()
            self.update()

    def mouseReleaseEvent(self, event):
        if event.button() != QtCore.Qt.MouseButton.LeftButton or self._press is None:
            return
        if self._crop_start is not None:
            image = self.image_rect(self.selected)
            region = QtCore.QRectF(self._crop_start, event.position()).normalized().intersected(image)
            if region.width() >= 4 and region.height() >= 4:
                panel = next(p for p in self.document["panels"] if p["id"] == self.selected)
                old = panel.get("crop") or [0, 0, 1, 1]
                crop = [old[0] + (region.left() - image.left()) / image.width() * (old[2] - old[0]),
                        old[1] + (region.top() - image.top()) / image.height() * (old[3] - old[1]),
                        old[0] + (region.right() - image.left()) / image.width() * (old[2] - old[0]),
                        old[1] + (region.bottom() - image.top()) / image.height() * (old[3] - old[1])]
                self.panelCropped.emit(self.selected, crop)
        elif not self.crop_mode and (event.position() - self._press).manhattanLength() >= QtWidgets.QApplication.startDragDistance():
            cell = self.cell_at(event.position())
            target = self._panel_at(event.position())
            if target is not None:
                cell = (target["row"], target["column"]) if target["id"] != self.selected else None
            if cell is not None:
                self.panelMoved.emit(self.selected, *cell)
        self._press = self._crop_start = self._crop_end = self._drag_position = None
        self.update()

    def keyPressEvent(self, event):
        if event.matches(QtGui.QKeySequence.StandardKey.Undo):
            self.undoRequested.emit()
        elif event.matches(QtGui.QKeySequence.StandardKey.Redo):
            self.redoRequested.emit()
        elif self.selected and event.key() in (QtCore.Qt.Key.Key_Delete, QtCore.Qt.Key.Key_Backspace):
            self.removeRequested.emit(self.selected)
        elif self.selected and event.key() in (QtCore.Qt.Key.Key_Left, QtCore.Qt.Key.Key_Right,
                                               QtCore.Qt.Key.Key_Up, QtCore.Qt.Key.Key_Down):
            panel = next(p for p in self.document["panels"] if p["id"] == self.selected)
            delta = {QtCore.Qt.Key.Key_Left: (0, -1), QtCore.Qt.Key.Key_Right: (0, 1),
                     QtCore.Qt.Key.Key_Up: (-1, 0), QtCore.Qt.Key.Key_Down: (1, 0)}[event.key()]
            row, column = panel["row"] + delta[0], panel["column"] + delta[1]
            if 0 <= row < self.document["layout"]["rows"] and 0 <= column < self.document["layout"]["columns"]:
                self.panelMoved.emit(self.selected, row, column)
        else:
            super().keyPressEvent(event)
            return
        event.accept()
