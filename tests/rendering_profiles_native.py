"""Test-only, isolated native capture for immutable rendering profile baselines.

This captures evidence, never updates a fixture. Semantic role projection lives
in the profile test; full native settings and datasets remain inspectable.
"""

from importlib import import_module, metadata
import json
import math
from pathlib import Path
import platform
import re
import sys

from PIL import Image

from sciplot_core.foundation.file_hashing import file_sha256
from sciplot_core.foundation.json_hashing import canonical_json_sha256


def write_json(path, value):
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False) + "\n", encoding="utf-8")


def normalized(value):
    if hasattr(value, "tolist"):
        return normalized(value.tolist())
    if isinstance(value, (list, tuple)):
        return [normalized(item) for item in value]
    if isinstance(value, float) and not math.isfinite(value):
        return {"nonfinite": str(value)}
    if isinstance(value, (int, float, bool)) or value is None:
        return value
    value = str(value)
    match = re.fullmatch(r"([-+0-9.eE]+)(mm|cm|pt|in)", value)
    if match:
        return {"pt": float(match[1]) * {"mm": 72 / 25.4, "cm": 720 / 25.4, "pt": 1, "in": 72}[match[2]]}
    return value


def settings(widget, document):
    result = {}

    def visit(group, prefix=""):
        for name, node in group.setdict.items():
            path = prefix + name
            if hasattr(node, "setdict"):
                visit(node, path + "/")
            else:
                try:
                    value = normalized(node.get())
                except (TypeError, ValueError, AttributeError):
                    value = normalized(node.val)
                if isinstance(value, str) and (path.endswith("/color") or path.endswith("/backcolor")):
                    color = document.evaluate.colors.get(value)
                    if color.isValid():
                        rgba = color.rgba64()
                        value = {"rgba16": [rgba.red(), rgba.green(), rgba.blue(), rgba.alpha()]}
                result[path] = value

    visit(widget.settings)
    return result


def _painted_text(document, document_module):
    utils = import_module("veusz.utils")
    qt_gui = import_module("PyQt6.QtGui")
    original, result, primitives = utils.Renderer, [], []
    bar_type = import_module("veusz.widgets.bar").BarPlotter
    polygon_type = import_module("veusz.widgets.polygon").Polygon
    line_type = import_module("veusz.widgets.line").Line
    original_bar, original_polygon, original_line = bar_type.plotBars, polygon_type.draw, line_type.draw

    def points(xs, ys):
        return [[float(x) * 25.4 / 150, float(y) * 25.4 / 150] for x, y in zip(xs, ys, strict=True)]

    def bar_boxes(widget, painter, settings, index, clip, corners):
        for x1, y1, x2, y2 in zip(*corners, strict=True):
            if all(math.isfinite(v) for v in (x1, y1, x2, y2)) and x1 != x2 and y1 != y2:
                primitives.append({"widget_path": widget.path, "kind": "bar_fill", "data_index": index,
                                   "points_mm": points([x1, x2, x2, x1], [y1, y1, y2, y2])})
        return original_bar(widget, painter, settings, index, clip, corners)

    def polygon(widget, posn, helper, outerbounds=None):
        if not widget.settings.hide:
            xs, ys = widget._getPlotterCoords(posn)
            if xs is not None and ys is not None:
                primitives.append({"widget_path": widget.path, "kind": "polygon_fill", "points_mm": points(xs, ys)})
        return original_polygon(widget, posn, helper, outerbounds=outerbounds)

    def line(widget, posn, helper, outerbounds=None):
        if not widget.settings.hide and widget.settings.mode == "point-to-point":
            xs, ys = widget._getPlotterCoords(posn)
            xs2, ys2 = widget._getPlotterCoords(posn, xsetting="xPos2", ysetting="yPos2")
            if all(value is not None for value in (xs, ys, xs2, ys2)):
                for start, end in zip(points(xs, ys), points(xs2, ys2), strict=True):
                    primitives.append({"widget_path": widget.path, "kind": "line", "points_mm": [start, end]})
        return original_line(widget, posn, helper, outerbounds=outerbounds)

    def factory(*args, **kwargs):
        renderer = original(*args, **kwargs)
        render = renderer.render

        def measured():
            returned = render()
            font, actual_font = args[1], qt_gui.QFontInfo(args[1])
            widget = getattr(args[0], "widget", None)
            result.append({
                "widget_path": str(widget.path) if widget is not None else None,
                "text": str(args[4]),
                "bounds_mm": [float(value) * 25.4 / 150 for value in renderer.getBounds()],
                "anchor_mm": [float(args[2]) * 25.4 / 150, float(args[3]) * 25.4 / 150],
                "font_family": font.family(), "resolved_font_family": actual_font.family(),
                "font_size_pt": font.pointSizeF(), "font_pixel_size": font.pixelSize(),
                "font_weight": int(font.weight()), "italic": font.italic(),
                "angle": float(args[7] if len(args) > 7 else kwargs.get("angle", 0)),
            })
            return returned

        renderer.render = measured
        return renderer

    try:
        utils.Renderer = factory
        bar_type.plotBars, polygon_type.draw, line_type.draw = bar_boxes, polygon, line
        helper = document_module.PaintHelper(document, document.pageSize(0, dpi=(150, 150), integer=False), dpi=(150, 150))
        document.paintTo(helper, 0)
    finally:
        # Native Export may paint on worker threads; interception is synchronous only.
        utils.Renderer = original
        bar_type.plotBars, polygon_type.draw, line_type.draw = original_bar, original_polygon, original_line
    return sorted(result, key=lambda item: (item["text"], item["bounds_mm"])), primitives


def _environment(font_files, text):
    from sciplot_core._paths import VEUSZ_ROOT

    qt_core = import_module("PyQt6.QtCore")
    qt_widgets = import_module("PyQt6.QtWidgets")
    packages = {}
    for name in ("PyQt6", "PyQt6-Qt6", "PyQt6-sip", "numpy", "Pillow", "PyMuPDF"):
        packages[name] = metadata.version(name)
    fonts = {name: file_sha256(Path(path)) for name, path in sorted(font_files.items())}
    if not fonts:
        raise ValueError("A rendering profile must pin its actual font files")
    renderer_files = {str(path.relative_to(VEUSZ_ROOT)): file_sha256(path)
                      for path in sorted((VEUSZ_ROOT / "veusz").rglob("*.py"))}
    return {
        "python": platform.python_version(), "python_binary_sha256": file_sha256(Path(sys.executable)),
        "platform": {"system": platform.system(), "release": platform.release(), "machine": platform.machine()},
        "packages": packages, "qt_compiled": qt_core.QT_VERSION_STR, "qt_runtime": qt_core.qVersion(),
        "qt_platform": qt_widgets.QApplication.platformName(),
        "renderer_python_sha256": canonical_json_sha256(renderer_files),
        "qt_modules_sha256": {name: file_sha256(Path(import_module("PyQt6." + name).__file__))
                              for name in ("QtCore", "QtGui", "QtWidgets", "QtSvg", "QtPrintSupport")},
        "font_files_sha256": fonts,
        "resolved_font_families": sorted({item["resolved_font_family"] for item in text}),
        "export": {"preview_dpi": 150, "tiff_dpi": 300, "pdfdpi": 72, "preview_background": "white"},
    }


def capture(document_path, output, font_files):
    from sciplot_core.veusz_worker.document_edit import loaded_native_document
    from sciplot_core.veusz_audit.pages import collect_page_geometry
    from sciplot_core.veusz_audit.layout import collect_layout_inventory
    from sciplot_core.native_process.identity import current_identity
    import pymupdf

    before = file_sha256(document_path)
    output.mkdir(parents=True, exist_ok=True)
    with loaded_native_document(document_path) as doc:
        widgets = []
        doc.walkNodes(lambda path, widget: widgets.append((path, widget)), nodetypes=("widget",))
        inventory = {path: {"type": widget.typename, "settings": settings(widget, doc)} for path, widget in widgets}
        datasets = {name: {"type": type(data).__name__, "data": normalized(data.data),
                           "serr": normalized(getattr(data, "serr", None)),
                           "nerr": normalized(getattr(data, "nerr", None)),
                           "perr": normalized(getattr(data, "perr", None))}
                    for name, data in doc.data.items()}
        doc_module = import_module("veusz.document")
        page_states, pages = collect_page_geometry(doc, doc_module.PaintHelper)
        graphs, grids, auxiliaries, axes = collect_layout_inventory(widgets, page_states)
        text, primitives = _painted_text(doc, doc_module)
        interface = doc_module.CommandInterface(doc)
        interface.Export(str(output / "native.png"), page=[0], dpi=150, backcolor="white")
        interface.Export(str(output / "native.pdf"), page=[0], pdfdpi=72)
        interface.Export(str(output / "native_300dpi.tiff"), page=[0], dpi=300)
        with Image.open(output / "native_300dpi.tiff") as image:
            export = {"tiff_size_px": list(image.size), "tiff_dpi": [float(value) for value in image.info.get("dpi", ())],
                      "tiff_compression": image.info.get("compression"), "tiff_mode": image.mode,
                      "preview_dpi": 150, "pdfdpi": 72}
        with pymupdf.open(output / "native.pdf") as pdf:
            export.update(pdf_pages=len(pdf), pdf_page_pt=list(pdf[0].rect),
                          pdf_fonts=sorted({font[3] for font in pdf[0].get_fonts()}))
        payload = {"document_sha256": before, "inventory": inventory, "datasets": datasets,
                   "geometry": {"pages": pages, "graphs": graphs, "grids": grids, "auxiliaries": auxiliaries, "axes": axes},
                   "painted_text": text, "painted_primitives": primitives, "export": export}
        write_json(output / "capture.json", payload)
        write_json(output / "full-native-settings.json", inventory)
        write_json(output / "datasets.json", datasets)
        write_json(output / "environment.json", _environment(font_files, text))
        write_json(output / "producer-identity.json", {"runtime_identity": current_identity(),
                   "capture_helper_sha256": file_sha256(Path(__file__)), "document_sha256": before})
    if before != file_sha256(document_path):
        raise AssertionError("Native capture mutated its input document")


if __name__ == "__main__":
    request = json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))
    capture(Path(request["document"]), Path(request["output"]), request["font_files"])
