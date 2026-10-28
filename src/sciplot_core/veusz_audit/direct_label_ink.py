"""Read un-clipped literal-label ink from its existing native paint record.

A label control box omits descenders in upstream Veusz. Replay only this
widget's already recorded text into a bounded read-only measuring device;
QPainterPath uses the actual text-run font, baseline and painter transform.
No document, renderer defaults, recorded position, font or clipping is changed.
"""
from __future__ import annotations

from importlib import import_module
import math
from typing import Any


def painted_label_ink_bounds(widget: Any, state: dict[str, Any]) -> list[float]:
    qt: Any = import_module("veusz.qtall")
    helper = state["helper"]
    if float(widget.settings.angle) != 0:
        raise ValueError("Automatic inline glyph measurement supports unrotated literal labels only.")
    if tuple(helper.dpi) != (72.0, 72.0) or helper.scaling != 1:
        raise ValueError("Inline glyph measurement requires the recorded physical 72-dpi geometry.")
    record = helper.states[(widget, 0)].record

    class InkEngine(qt.QPaintEngine):  # type: ignore[misc, no-any-unimported]
        def __init__(self) -> None:
            super().__init__(qt.QPaintEngine.PaintEngineFeature.AllFeatures)
            self.transform = qt.QTransform()
            self.bounds: list[Any] = []
            self.unsupported: list[str] = []

        def begin(self, _device: Any) -> bool:
            return True

        def end(self) -> bool:
            return True

        def type(self) -> Any:
            return qt.QPaintEngine.Type.User

        def updateState(self, native_state: Any) -> None:
            self.transform = native_state.transform()

        def drawTextItem(self, point: Any, item: Any) -> None:
            try:
                font = item.font()
                flags = qt.QTextItem.RenderFlag
                decorations = flags.Underline | flags.Overline | flags.StrikeOut
                if item.renderFlags() & decorations or font.underline() or font.overline() or font.strikeOut():
                    raise ValueError("decorated_text")
                # Resolve shaping/fallback at the SAME paint-device DPI. A bare
                # QPainterPath.addText(font) would use screen DPI on some hosts.
                layout = qt.QTextLayout(item.text(), font, self.paintDevice())
                layout.beginLayout()
                line = layout.createLine()
                if not line.isValid():
                    raise ValueError("unshaped_text")
                line.setLineWidth(1e100)
                layout.endLayout()
                for run in layout.glyphRuns():
                    face = run.rawFont()
                    indexes, positions = run.glyphIndexes(), run.positions()
                    if not face.isValid() or len(indexes) != len(positions):
                        raise ValueError("unresolved_native_glyphs")
                    for index, position in zip(indexes, positions, strict=True):
                        path = face.pathForGlyph(index)
                        if path.isEmpty():
                            continue  # Spaces have advances but no painted ink.
                        path.translate(point.x()+position.x(), point.y()+position.y()-line.ascent())
                        self.bounds.append(self.transform.map(path).boundingRect())
            except (AttributeError, RuntimeError, TypeError, ValueError) as exc:
                self.unsupported.append(str(exc))

        def drawPath(self, _path: Any) -> None:
            self.unsupported.append("non_text_path")

        def drawPolygon(self, _points: Any, _mode: Any) -> None:
            self.unsupported.append("non_text_polygon")

        def drawPixmap(self, _rect: Any, _pixmap: Any, _source: Any) -> None:
            self.unsupported.append("non_vector_text")

    class InkDevice(qt.QPaintDevice):  # type: ignore[misc, no-any-unimported]
        def __init__(self, engine: Any) -> None:
            super().__init__()
            self.engine = engine

        def paintEngine(self) -> Any:
            return self.engine

        def metric(self, kind: Any) -> int:
            metrics = qt.QPaintDevice.PaintDeviceMetric
            values = {metrics.PdmWidth: math.ceil(helper.pagesize[0]),
                metrics.PdmHeight: math.ceil(helper.pagesize[1]), metrics.PdmWidthMM: math.ceil(helper.pagesize[0]*25.4/72),
                metrics.PdmHeightMM: math.ceil(helper.pagesize[1]*25.4/72), metrics.PdmNumColors: 16777216,
                metrics.PdmDepth: 32, metrics.PdmDpiX: 72, metrics.PdmDpiY: 72,
                metrics.PdmPhysicalDpiX: 72, metrics.PdmPhysicalDpiY: 72,
                metrics.PdmDevicePixelRatio: 1, metrics.PdmDevicePixelRatioScaled: 65536}
            return int(values.get(kind, 0))

    engine = InkEngine()
    device = InkDevice(engine)
    painter = qt.QPainter(device)
    try:
        if not painter.isActive():
            raise ValueError("The recorded inline-label measuring painter is inactive.")
        # Native RecordPaintDevice.play returns void; QPicture's fallback may
        # return bool. Only an explicit false is a failed replay.
        if record.play(painter) is False:
            raise ValueError("The recorded inline-label text could not be replayed for ink measurement.")
    finally:
        # Destroy the temporary painter before its owned measuring device.
        painter.end()
    if engine.unsupported or not engine.bounds:
        raise ValueError("The complete recorded literal glyph inventory is unavailable: " + ",".join(engine.unsupported))
    box = [min(rect.left() for rect in engine.bounds), min(rect.top() for rect in engine.bounds),
           max(rect.right() for rect in engine.bounds), max(rect.bottom() for rect in engine.bounds)]
    if not all(math.isfinite(value) for value in box) or box[0] >= box[2] or box[1] >= box[3]:
        raise ValueError("Recorded inline glyphs have no positive finite ink bounds.")
    return [float(value)*25.4/72 for value in box]
