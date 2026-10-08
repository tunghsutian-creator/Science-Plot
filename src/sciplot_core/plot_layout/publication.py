"""Publication layout checks distinguish geometry from measured native text."""

from __future__ import annotations

import math
from typing import Any

Rect = list[float]


def _contains(outer: Rect, inner: Rect, tolerance: float = 0.0) -> bool:
    return (inner[0] >= outer[0] - tolerance and inner[1] >= outer[1] - tolerance
            and inner[0] + inner[2] <= outer[0] + outer[2] + tolerance
            and inner[1] + inner[3] <= outer[1] + outer[3] + tolerance)


def _overlap(first: Rect, second: Rect, tolerance: float = 0.0) -> bool:
    return (min(first[0] + first[2], second[0] + second[2]) - max(first[0], second[0]) > tolerance
            and min(first[1] + first[3], second[1] + second[3]) - max(first[1], second[1]) > tolerance)


def _issue(code: str, semantic_id: str, **details: Any) -> dict[str, Any]:
    return {"code": code, "semantic_id": semantic_id, **details}


def _report(hard: list[dict[str, Any]], soft: list[dict[str, Any]], checks: list[str], *, native: bool) -> dict[str, Any]:
    return {"kind": "sciplot_figure_layout_qa", "schema_version": 1,
            "status": "failed" if hard else "passed", "hard": hard, "soft": soft,
            "checks": checks, "native_text_checked": native,
            "journal_compliance_established": False}


def structural_publication_qa(layout: dict[str, Any], *,
                             annotations: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    """Check solved rectangles and anchors; this does not establish text fitting."""
    hard: list[dict[str, Any]] = []
    soft: list[dict[str, Any]] = []
    canvas = [0.0, 0.0, float(layout["width_mm"]), float(layout["height_mm"])]
    panels = layout["panels"]
    lookup = {panel["view_id"]: panel for panel in panels}
    for index, panel in enumerate(panels):
        for key in ("cell_mm", "plot_mm"):
            rectangle = panel[key]
            if len(rectangle) != 4 or any(not math.isfinite(value) for value in rectangle) or min(rectangle[2:]) <= 0:
                hard.append(_issue("nonpositive_panel_dimensions", panel["view_id"], rectangle=key))
            elif not _contains(canvas, rectangle, 1e-7):
                hard.append(_issue("panel_outside_canvas", panel["view_id"], rectangle=key))
        if not _contains(panel["cell_mm"], panel["plot_mm"], 1e-7):
            hard.append(_issue("plot_outside_panel", panel["view_id"]))
        for other in panels[index + 1:]:
            if _overlap(panel["cell_mm"], other["cell_mm"], 1e-7):
                hard.append(_issue("panel_overlap", panel["view_id"], other_id=other["view_id"]))
            if _overlap(panel["plot_mm"], other["plot_mm"], 1e-7):
                hard.append(_issue("plot_area_overlap", panel["view_id"], other_id=other["view_id"]))
            if panel["column"] == other["column"] and (abs(panel["plot_mm"][0] - other["plot_mm"][0]) > 1e-7
                    or abs(panel["plot_mm"][2] - other["plot_mm"][2]) > 1e-7):
                soft.append(_issue("inconsistent_aligned_plot_areas", panel["view_id"], other_id=other["view_id"]))
    for annotation in annotations or []:
        if not annotation.get("visible", True):
            continue
        position = annotation.get("position_mm")
        if position is None:
            continue
        frame = annotation.get("coordinate_space", annotation.get("space", "figure"))
        allowed = canvas if frame == "figure" else lookup[annotation["view_id"]]["plot_mm"]
        if not _contains(allowed, [position[0], position[1], 0.0, 0.0], 1e-7):
            hard.append(_issue("annotation_outside_view" if frame != "figure" else "annotation_outside_canvas", annotation["id"]))
    area = sum(panel["plot_mm"][2] * panel["plot_mm"][3] for panel in panels)
    if canvas[2] * canvas[3] > 0 and area / (canvas[2] * canvas[3]) < 0.30:
        soft.append(_issue("excessive_whitespace", "figure:main", plot_area_fraction=area / (canvas[2] * canvas[3])))
    return _report(hard, soft, ["positive_panel_dimensions", "panel_canvas_bounds", "panel_overlap",
                              "plot_area_overlap", "annotation_anchor_bounds", "aligned_plot_areas", "whitespace"], native=False)


def native_publication_qa(layout: dict[str, Any], observations: list[dict[str, Any]], *,
                          expected_text_ids: list[str] | None = None,
                          data_points: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    """Evaluate actual renderer bounds collected before canvas clipping.

    Rectangles use top-left millimetres. A 0.30 mm tolerance covers native device
    rounding; conceptual rectangles and PDF extraction cannot substitute here.
    """
    structural = structural_publication_qa(layout)
    hard, soft = structural["hard"], structural["soft"]
    canvas = [0.0, 0.0, float(layout["width_mm"]), float(layout["height_mm"])]
    lookup = {panel["view_id"]: panel for panel in layout["panels"]}
    if not observations and (expected_text_ids is None or expected_text_ids):
        hard.append(_issue("native_text_measurements_missing", "figure:main"))
    seen = {item["semantic_id"] for item in observations}
    for semantic_id in expected_text_ids or []:
        if semantic_id not in seen:
            hard.append(_issue("expected_text_not_measured", semantic_id))
    usable = []
    for item in observations:
        semantic_id, role, bounds = item["semantic_id"], item["role"], item["bounds_mm"]
        if len(bounds) != 4 or any(not math.isfinite(value) for value in bounds) or min(bounds[2:]) < 0:
            hard.append(_issue("invalid_native_text_bounds", semantic_id))
            continue
        usable.append(item)
        if not _contains(canvas, bounds, 0.30):
            hard.append(_issue("text_outside_canvas", semantic_id, role=role, bounds_mm=bounds))
        panel = lookup.get(item.get("view_id"))
        allowed = item.get("allowed_bounds_mm")
        if allowed is None and panel is not None:
            allowed = panel["plot_mm"] if role in {"annotation", "legend"} else panel["cell_mm"]
        if allowed is not None and not _contains(allowed, bounds, 0.30):
            code = {"axis_label": "axis_label_clipping", "tick_label": "tick_label_clipping",
                    "legend": "legend_outside_allowed_bounds", "annotation": "annotation_outside_view"}.get(role, "text_outside_reserved_bounds")
            hard.append(_issue(code, semantic_id, bounds_mm=bounds, allowed_bounds_mm=allowed))
    for index, first in enumerate(usable):
        for second in usable[index + 1:]:
            if first["semantic_id"] == second["semantic_id"] or not _overlap(first["bounds_mm"], second["bounds_mm"], 0.30):
                continue
            # Glyph bounding boxes overlap deterministically; legibility remains
            # a soft judgement because sparse glyphs can share empty box space.
            soft.append(_issue("text_collision", first["semantic_id"], other_id=second["semantic_id"]))
    if data_points is not None:
        for item in usable:
            if item["role"] not in {"legend", "annotation"}:
                continue
            count = sum(1 for point in data_points if point.get("view_id") == item.get("view_id")
                        and _contains(item["bounds_mm"], [point["x_mm"], point["y_mm"], 0.0, 0.0]))
            if count:
                soft.append(_issue("text_data_collision", item["semantic_id"], overlapping_point_count=count))
    report = _report(hard, soft, structural["checks"] + ["text_canvas_bounds", "axis_label_bounds",
        "tick_label_bounds", "legend_bounds", "annotation_text_bounds", "text_collision"], native=bool(observations))
    report["observation_count"] = len(observations)
    report["data_collision_checked"] = data_points is not None
    report["limitations"] = ["Bounds cannot establish journal compliance or guarantee visual legibility.",
                              "Font metrics and glyph pixels depend on the installed rendering environment."]
    if data_points is None:
        report["limitations"].append("Legend/annotation data collision was not evaluated without native point geometry.")
    return report
