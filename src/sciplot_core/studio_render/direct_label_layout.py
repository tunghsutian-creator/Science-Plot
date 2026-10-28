"""Versioned new-creation direct labels; old requests keep legacy anchors.

Planning reserves conservative text rectangles against complete clipped segments.
The native audit must independently establish actual painted clearance: this
estimate is never native evidence, and an infeasible fixed frame is a blocker.
"""
from __future__ import annotations

from copy import deepcopy
import math
from typing import Any, cast

from sciplot_core.foundation.rectangle_geometry import clip_segment, rectangle_distance
from sciplot_core.plot_layout.decorations import PT_MM, text_width_mm
from sciplot_core.policy.frame_export import DEFAULT_LEGEND_CURVE_CLEARANCE_MM
from sciplot_core.studio_render.models import StudioPreparationBlocked, StudioSeries, _VeuszAxisContract, _VeuszStyleContract
from sciplot_core.studio_render.template_resolution import _explicit_render_options
from sciplot_core.studio_render.value_parsing import _size_mm

DIRECT_LABEL_LAYOUT_VERSION = "physical-clearance-v1"
DIRECT_LABEL_LAYOUT_KEY = "direct_label_layout_version"
_PLACEMENT_OPTIONS = {"series_label_side", "series_label_offset_fraction", "series_label_vertical_align"}
# Extra guard covers normal-font glyph overhang beyond the native text metrics.
NATIVE_TEXT_GUARD_MM = 0.25


def freeze_new_direct_label_layout(request: dict[str, Any], *, template: str) -> dict[str, Any]:
    """Only the actual new-creation gateway selects a new persistent default."""
    result = deepcopy(request)
    if "intent" in request or template != "stacked_curve" or DIRECT_LABEL_LAYOUT_KEY in request:
        return result
    options = request.get("render_options") or {}
    explicit = _explicit_render_options(request)
    if (_PLACEMENT_OPTIONS.intersection(explicit)
            or options.get("series_label_mode", "auto") not in {"auto", "inline", "edge"}):
        return result
    result[DIRECT_LABEL_LAYOUT_KEY] = DIRECT_LABEL_LAYOUT_VERSION
    return result


def active_direct_label_layout(request: dict[str, Any]) -> str | None:
    """The recorded version selects defaults; declared placements retain priority."""
    if DIRECT_LABEL_LAYOUT_KEY not in request:
        return None
    version = request[DIRECT_LABEL_LAYOUT_KEY]
    if version != DIRECT_LABEL_LAYOUT_VERSION:
        raise ValueError("Unknown persisted direct-label layout version.")
    if _PLACEMENT_OPTIONS.intersection(_explicit_render_options(request)):
        return None
    return DIRECT_LABEL_LAYOUT_VERSION


def _text_width(text: str, font_size_pt: float) -> float:
    # Reuse the existing conservative display-cell budget, with the wide Latin
    # capitals that exceed its average-cell allowance. Actual native metrics
    # remain the independent delivery gate, not this deterministic estimate.
    return text_width_mm(text, font_size_pt) + sum(char in "MW@%" for char in text)*font_size_pt*PT_MM*.30


def automatic_label_boxes(series: list[StudioSeries], *, render_options: dict[str, Any],
                          axis: _VeuszAxisContract, style: _VeuszStyleContract,
                          side: str) -> list[tuple[float, float]]:
    """Return deterministic axes anchors for whole-label, fixed-frame clearance."""
    bounds = (axis.x_min, axis.x_max, axis.y_min, axis.y_max)
    if any(value is None or not math.isfinite(value) for value in bounds):
        raise StudioPreparationBlocked("direct_label_layout_unavailable", "Automatic labels require complete finite axis bounds.")
    # Above validation establishes these exact optional bounds without changing axes.
    xmin, xmax, ymin, ymax = (float(cast(float, value)) for value in bounds)
    if xmax == xmin or ymax == ymin:
        raise StudioPreparationBlocked("direct_label_layout_unavailable", "Automatic labels require nonzero axis spans.")
    xlog, ylog = (render_options.get(name) == "log" for name in ("xscale", "yscale"))
    if (xlog and min(xmin, xmax) <= 0) or (ylog and min(ymin, ymax) <= 0):
        raise StudioPreparationBlocked("direct_label_layout_unavailable", "Logarithmic label axes require positive bounds.")
    tx = math.log10 if xlog else float
    ty = math.log10 if ylog else float
    left, right, bottom, top = tx(xmin), tx(xmax), ty(ymin), ty(ymax)
    figure_width, figure_height = _size_mm(str(render_options.get("size") or "60x55"))
    width = figure_width - style.left_margin_mm - style.right_margin_mm
    height = figure_height - style.top_margin_mm - style.bottom_margin_mm
    gap = DEFAULT_LEGEND_CURVE_CLEARANCE_MM
    edge = NATIVE_TEXT_GUARD_MM
    if width <= 2*edge or height <= 2*edge:
        raise StudioPreparationBlocked("direct_label_layout_infeasible", "The fixed graph frame cannot contain automatic labels.")

    def project(x: float, y: float) -> tuple[float, float]:
        u = (tx(x)-left)/(right-left)
        return (u*width, (top-ty(y))/(top-bottom)*height)

    segments: list[tuple[tuple[float, float], tuple[float, float], float]] = []
    anchor_points: list[list[tuple[float, float]]] = []
    for item in series:
        previous = None
        points = []
        radius = math.sqrt(2) * (item.line_width or style.line_width_pt) * PT_MM/2
        marker_radius = 0.0
        if item.marker not in {None, False, "none"}:
            # Conservative planning only. The independent native audit measures
            # the actual marker path, equal-area scaling and stroked envelope.
            marker_radius = (2*(item.marker_size or style.marker_size_pt)
                             + 4*(item.marker_line_width or style.marker_line_width_pt))*PT_MM
        for x, y in zip(item.x_values, item.y_values, strict=True):
            if not (math.isfinite(x) and math.isfinite(y)) or (xlog and x <= 0) or (ylog and y <= 0):
                previous = None
                continue
            point = project(x, y)
            points.append(point)
            if marker_radius and -marker_radius <= point[0] <= width+marker_radius and -marker_radius <= point[1] <= height+marker_radius:
                segments.append((point, point, marker_radius))
            if previous is not None and item.line_style != "none":
                clipped = clip_segment(previous, point, [-radius, -radius, width+radius, height+radius])
                if clipped is not None:
                    segments.append((*clipped, radius))
            previous = point
        if not points:
            raise StudioPreparationBlocked("direct_label_layout_unavailable", "A labelled spectral curve has no finite points.")
        anchor_points.append(points)
    if not segments:
        raise StudioPreparationBlocked("direct_label_layout_unavailable", "No visible spectral segments establish automatic label clearance.")

    occupied: list[list[float]] = []
    anchors = []
    for item, points in zip(series, anchor_points, strict=True):
        lines = str(item.label).splitlines() or [""]
        label_width = max(_text_width(line, style.font_size_pt) for line in lines) + 2*edge
        label_height = style.font_size_pt*PT_MM*1.8*len(lines) + 2*edge
        limit_x, limit_y = width-edge-label_width, height-edge-label_height
        if limit_x < edge or limit_y < edge:
            raise StudioPreparationBlocked("direct_label_layout_infeasible", "A complete inline label cannot fit inside the fixed frame; use an explicit legend or a larger figure.")
        target_x = width*.06 if side == "left" else width*.94
        near = min(points, key=lambda point: abs(point[0]-target_x))
        preferred = near[0] if side == "left" else near[0]-label_width
        preferred = min(limit_x, max(edge, preferred))
        candidates = {edge, limit_x, preferred, *(edge+(limit_x-edge)*i/20 for i in range(21))}
        best = None
        for x in sorted(candidates):
            forbidden = []
            for a, b, radius in segments:
                padding = gap+radius
                # Horizontal slab clipping yields all segment y extents over the
                # entire text width, including between original sample points.
                slab = clip_segment(a, b, [x-padding, -1e100, x+label_width+padding, 1e100])
                if slab is not None:
                    low, high = sorted((slab[0][1], slab[1][1]))
                    forbidden.append((low-padding-label_height, high+padding))
            for box in occupied:
                if x <= box[2]+gap and x+label_width >= box[0]-gap:
                    forbidden.append((box[1]-gap-label_height, box[3]+gap))
            merged: list[list[float]] = []
            for lo, hi in sorted(forbidden):
                if merged and lo <= merged[-1][1]:
                    merged[-1][1] = max(merged[-1][1], hi)
                else:
                    merged.append([lo, hi])
            positions = {edge, limit_y, min(limit_y, max(edge, near[1]))}
            positions.update(value for lo, hi in merged for value in (lo-1e-7, hi+1e-7) if edge <= value <= limit_y)
            for y in positions:
                if any(lo <= y <= hi for lo, hi in merged):
                    continue
                box = [x, y, x+label_width, y+label_height]
                if any(rectangle_distance(box, other) < gap for other in occupied):
                    continue
                score = (x-preferred)**2 + (y-near[1])**2
                candidate = (score, x, y)
                if best is None or candidate < best:
                    best = candidate
        if best is None:
            raise StudioPreparationBlocked("direct_label_layout_infeasible", "No complete inline-label placement clears every visible curve and label inside the fixed frame; choose a legend or larger frame.")
        _, x, y = best
        occupied.append([x, y, x+label_width, y+label_height])
        # The reserve box is larger than native glyphs. Its top-left/right
        # anchor is inset so actual text has the native overhang guard.
        xp = x+edge if side == "left" else x+label_width-edge
        yp = y+edge
        fraction = xp/width
        px = left+fraction*(right-left)
        py = top-yp/height*(top-bottom)
        anchors.append((10**px if xlog else px, 10**py if ylog else py))
    return anchors
