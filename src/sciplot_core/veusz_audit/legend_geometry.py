"""Measure current native XY strokes against actual painted key rectangles."""

import math
from typing import Any

from sciplot_core.veusz_audit.measurements import _distance_pt, _setting_hidden


def _clip(a: tuple[float, float], b: tuple[float, float], box: list[float]) -> tuple[Any, Any] | None:
    low, high = 0.0, 1.0
    dx, dy = b[0] - a[0], b[1] - a[1]
    for p, q in ((-dx, a[0] - box[0]), (dx, box[2] - a[0]),
                 (-dy, a[1] - box[1]), (dy, box[3] - a[1])):
        if p == 0:
            if q < 0:
                return None
        elif p < 0:
            low = max(low, q / p)
        else:
            high = min(high, q / p)
        if low > high:
            return None
    return (a[0] + low * dx, a[1] + low * dy), (a[0] + high * dx, a[1] + high * dy)


def _point_box(point: tuple[float, float], box: list[float]) -> float:
    return math.hypot(max(box[0] - point[0], 0, point[0] - box[2]),
                      max(box[1] - point[1], 0, point[1] - box[3]))


def _segment_box(a: tuple[float, float], b: tuple[float, float], box: list[float]) -> float:
    if _clip(a, b, box) is not None:
        return 0.0
    dx, dy = b[0] - a[0], b[1] - a[1]
    length = dx * dx + dy * dy
    distances = [_point_box(a, box), _point_box(b, box)]
    for x, y in ((box[0], box[1]), (box[0], box[3]), (box[2], box[1]), (box[2], box[3])):
        t = min(1.0, max(0.0, ((x - a[0]) * dx + (y - a[1]) * dy) / length)) if length else 0.0
        distances.append(math.hypot(x - a[0] - t * dx, y - a[1] - t * dy))
    return min(distances)


def _curve_distance(widget: Any, state: dict[str, Any], box: list[float]) -> float:
    s, helper = widget.settings, state["helper"]
    if widget.typename != "xy" or s.PlotLine.steps != "off" or s.PlotLine.interpType != "linear":
        raise ValueError("Current legend measurement supports straight native XY geometry only.")
    if not _setting_hidden(s.FillAbove) or not _setting_hidden(s.FillBelow):
        raise ValueError("Filled XY geometry needs its own native clearance measurement.")
    xs, ys = s.get("xData").getData(widget.document), s.get("yData").getData(widget.document)
    if xs is None or ys is None or len(xs.data) != len(ys.data):
        raise ValueError("Current XY coordinates are unavailable or unpaired.")
    if s.errorStyle != "none" and any(getattr(data, field, None) is not None
                                      for data in (xs, ys) for field in ("serr", "perr", "nerr")):
        raise ValueError("Error-bar geometry needs its own native clearance measurement.")
    if (s.get("scalePoints").getData(widget.document) is not None
            or s.Color.get("points").getData(widget.document) is not None
            or s.get("labels").getData(widget.document, checknull=True)):
        raise ValueError("Variable marker or labelled dataset segmentation is unsupported.")
    axes = widget.fetchAxes()
    if axes is None:
        raise ValueError("Current native XY axes are unavailable.")
    bounds = helper.states[(widget, 0)].bounds
    clip = [float(value) * 25.4 / 72 for value in widget.clipAxesBounds(axes, bounds).getCoords()]
    points = zip(axes[0].dataToPlotterCoords(bounds, xs.data),
                 axes[1].dataToPlotterCoords(bounds, ys.data), strict=True)
    line = not _setting_hidden(s.PlotLine) and s.PlotLine.style != "none"
    marker = s.marker != "none" and (not _setting_hidden(s.MarkerLine) or not _setting_hidden(s.MarkerFill))
    line_width = _distance_pt(s.PlotLine.get("width"), helper)
    if line and (line_width is None or line_width <= 0):
        raise ValueError("The native curve stroke width is unavailable.")
    # Conservative envelope includes native SquareCap corners and BevelJoin.
    line_radius = math.sqrt(2) * (line_width or 0) * 25.4 / 144
    # plotClippedPolyline(autoexpand=True) expands clipping by a full pen width.
    expansion = (line_width or 0) * 25.4 / 72
    line_clip = [clip[0] - expansion, clip[1] - expansion,
                 clip[2] + expansion, clip[3] + expansion]
    marker_radius = _marker_radius(s, helper) if marker else 0.0
    minimum, previous = math.inf, None
    for x, y in points:
        point = (float(x) * 25.4 / 72, float(y) * 25.4 / 72)
        if not all(math.isfinite(value) for value in point):
            if s.nanHandling == "break-on":
                previous = None
            continue
        if marker and _point_box(point, clip) <= marker_radius:
            minimum = min(minimum, max(0, _point_box(point, box) - marker_radius))
        if line and previous is not None:
            segment = _clip(previous, point, line_clip)
            if segment is not None:
                minimum = min(minimum, max(0, _segment_box(*segment, box) - line_radius))
        previous = point
    return minimum


def _marker_radius(settings: Any, helper: Any) -> float:
    """Bound the actual native marker path, equal-area scaling and stroked corners."""
    from veusz import qtall as qt
    from veusz.utils.points import area_scales, getPointPainterPath, scalePath

    size = _distance_pt(settings.get("markerSize"), helper)
    width = _distance_pt(settings.MarkerLine.get("width"), helper)
    if size is None or size <= 0 or width is None or width < 0:
        raise ValueError("The native marker dimensions are unavailable.")
    path, _fill = getPointPainterPath(settings.marker, size, width)
    if settings.MarkerFill.newMarkerSizes and settings.marker in area_scales:
        path = scalePath(path, area_scales[settings.marker])
    if not _setting_hidden(settings.MarkerLine):
        if width <= 0:
            raise ValueError("Cosmetic marker strokes need a device-specific measurement.")
        stroker = qt.QPainterPathStroker()
        stroker.setWidth(width)
        stroker.setCapStyle(qt.Qt.PenCapStyle.SquareCap)
        stroker.setJoinStyle(qt.Qt.PenJoinStyle.MiterJoin)
        stroker.setMiterLimit(4.0)  # Native Line.makeQPen; plotMarkers sets MiterJoin.
        path = path.united(stroker.createStroke(path))
    bounds = path.boundingRect()
    radius = max(math.hypot(x, y) for x in (bounds.left(), bounds.right())
                 for y in (bounds.top(), bounds.bottom())) * 25.4 / 72
    if not math.isfinite(radius) or radius <= 0:
        raise ValueError("The native marker path has no finite extent.")
    return radius


def collect_legend_geometry(ordered: list[tuple[str, Any]], states: dict[str, dict[str, Any]]) -> dict[str, Any]:
    """Read existing painted state; unsupported geometry never establishes clearance."""
    from veusz.widgets.key import ControlKey

    records, hidden, unsupported = [], [], []
    for path, widget in ordered:
        if widget.typename != "key":
            continue
        if widget.settings.hide is True:
            hidden.append({"path": path, "graph_path": str(widget.parent.path), "hidden": True})
            continue
        try:
            if path not in states:
                raise ValueError("A visible native key has no painted geometry.")
            state = states[path]
            controls = [c for c in state["helper"].getControlGraph(widget) or []
                        if isinstance(c, ControlKey) and c.widget is widget]
            if len(controls) != 1:
                raise ValueError("One complete native key boundary is required.")
            x, y = controls[0].posn
            width, height = controls[0].dims
            box = [float(v) * 25.4 / 72 for v in (x, y, x + width, y + height)]
            if width <= 0 or height <= 0 or not all(math.isfinite(v) for v in box):
                raise ValueError("Native key bounds must be positive and finite.")
            distances = []
            for curve_path, curve in ordered:
                if (curve.parent is widget.parent and "PlotLine" in curve.settings.setdict
                        and not _setting_hidden(curve.settings)):
                    if curve_path not in states:
                        raise ValueError(f"Visible native curve has no painted geometry: {curve_path}")
                    distances.append(_curve_distance(curve, states[curve_path], box))
            minimum = min(distances, default=math.inf)
            records.append({"path": path, "graph_path": str(widget.parent.path), "page": state["page"],
                            "bounds_mm": box, "curve_count": len(distances),
                            "minimum_curve_clearance_mm": minimum if math.isfinite(minimum) else None})
        except (AttributeError, KeyError, TypeError, ValueError) as exc:
            unsupported.append({"path": path, "reason": str(exc)})
    return {"kind": "sciplot_native_legend_geometry", "version": 1,
            "coverage_complete": not unsupported, "legends": records, "hidden_legends": hidden,
            "unsupported": unsupported,
            "envelope": "conservative_native_path_bounds_and_square_cap_strokes"}
