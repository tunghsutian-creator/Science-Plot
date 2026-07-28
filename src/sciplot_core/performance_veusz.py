"""Native Veusz document contract for material-performance comparisons."""

from __future__ import annotations

import math
import re
from datetime import UTC, datetime
from typing import Any

from sciplot_core._utils import json_safe
from sciplot_core.materials_rules import format_plot_text_units
from sciplot_core.performance_comparison import (
    PERFORMANCE_RADAR_TEMPLATE_ID,
    PERFORMANCE_SCATTER_TEMPLATE_ID,
)
from sciplot_core.policy import (
    FIXED_PUBLICATION_FRAME_POLICY,
    PERFORMANCE_RADAR_AXIS_LABEL_SIZE_PT,
    PERFORMANCE_RADAR_GUIDE_COLOR,
    PERFORMANCE_RADAR_GUIDE_LINE_WIDTH_PT,
    PERFORMANCE_RADAR_RING_TRANSPARENCY,
    PERFORMANCE_RADAR_SPOKE_TRANSPARENCY,
    PERFORMANCE_REFERENCE_PANEL_WIDTH_MM,
    UNIFIED_AXIS_LINEWIDTH_PT,
    UNIFIED_FONT_FAMILY,
    UNIFIED_FONT_SIZE_PT,
    UNIFIED_FOREGROUND_COLOR,
    UNIFIED_LEGEND_FONT_SIZE_PT,
    UNIFIED_LEGEND_KEY_LENGTH_MM,
    UNIFIED_LINE_WIDTH_PT,
    UNIFIED_MARKER_LINE_WIDTH_PT,
    UNIFIED_MARKER_SIZE_PT,
    UNIFIED_MINOR_TICK_LENGTH_PT,
    UNIFIED_MINOR_TICK_WIDTH_PT,
    UNIFIED_TICK_LENGTH_PT,
    UNIFIED_TICK_WIDTH_PT,
)

_RADAR_AXIS_LIMIT = 1.12
_RADAR_LABEL_HORIZONTAL_RADIUS_LEFT = 0.78
_RADAR_LABEL_HORIZONTAL_RADIUS_RIGHT = 1.06
_RADAR_LABEL_VERTICAL_RADIUS = 1.15
_RADAR_ENDPOINT_LABEL_RADIUS = 1.06
_RADAR_RING_LEVELS = (0.25, 0.50, 0.75, 1.00)
_RADAR_FIVE_AXIS_ANGLES = (90.0, 162.0, 234.0, 306.0, 18.0)
_RADAR_FIVE_AXIS_TITLE_X_MM = (28.75, 9.0, 13.8, 46.2, 51.9)
_RADAR_FIVE_AXIS_TITLE_CENTRE_Y_MM = (2.9, 13.4, 48.4, 48.4, 13.4)
_RADAR_FIVE_AXIS_TITLE_LINE_STEP_MM = 2.6
_RADAR_FIVE_AXIS_ENDPOINT_OFFSETS_MM = (1.7, 2.0, 2.7, 2.7, 2.7)
_LEGEND_PAIRED_SLOT_OFFSET_MM = 22.0


def _pt(value: float) -> str:
    return f"{float(value):g}pt"


def _cm_from_mm(value: float) -> str:
    return f"{float(value) / 10.0:g}cm"


def _literal_text(value: object) -> str:
    text = format_plot_text_units(value).replace("\\", "\ue000")
    text = re.sub(r"([_\^\[\]\{\}])", r"\\\1", text)
    return text.replace("\ue000", "{\\backslash}")


def _style_payload(margins: dict[str, Any]) -> dict[str, Any]:
    return {
        "font_family": UNIFIED_FONT_FAMILY,
        "font_size_pt": UNIFIED_FONT_SIZE_PT,
        "legend_font_size_pt": UNIFIED_LEGEND_FONT_SIZE_PT,
        "axis_linewidth_pt": UNIFIED_AXIS_LINEWIDTH_PT,
        "tick_width_pt": UNIFIED_TICK_WIDTH_PT,
        "tick_length_pt": UNIFIED_TICK_LENGTH_PT,
        "minor_tick_width_pt": UNIFIED_MINOR_TICK_WIDTH_PT,
        "minor_tick_length_pt": UNIFIED_MINOR_TICK_LENGTH_PT,
        "line_width_pt": UNIFIED_LINE_WIDTH_PT,
        "line_alpha": 0.92,
        "marker_alpha": 0.95,
        "marker_size_pt": UNIFIED_MARKER_SIZE_PT,
        "marker_line_width_pt": UNIFIED_MARKER_LINE_WIDTH_PT,
        "axes_labelpad_pt": 2.0,
        "xtick_major_pad_pt": 1.4,
        "ytick_major_pad_pt": 1.4,
        "legend_frameon": False,
        "margins_mm": {
            side: float(margins[side])
            for side in ("left", "right", "bottom", "top")
        },
    }


def _axis_payload(
    *,
    label: str,
    minimum: float,
    maximum: float,
    hidden: bool,
) -> dict[str, Any]:
    return {
        "label": label,
        "scale": "linear",
        "tick_format": "Auto",
        "minor_tick_count": 20,
        "minor_ticks": [],
        "min": float(minimum),
        "max": float(maximum),
        "ticks": [],
        "reverse": False,
        "foreground_color": UNIFIED_FOREGROUND_COLOR,
        "label_size_pt": UNIFIED_FONT_SIZE_PT,
        "tick_label_size_pt": UNIFIED_FONT_SIZE_PT,
        "line_width_pt": UNIFIED_AXIS_LINEWIDTH_PT,
        "major_tick_width_pt": UNIFIED_TICK_WIDTH_PT,
        "major_tick_length_pt": UNIFIED_TICK_LENGTH_PT,
        "minor_tick_width_pt": UNIFIED_MINOR_TICK_WIDTH_PT,
        "minor_tick_length_pt": UNIFIED_MINOR_TICK_LENGTH_PT,
        "mode": "numeric",
        "show_ticks": not hidden,
        "hidden": hidden,
    }


def _expanded_axis_bounds(
    payload: dict[str, Any],
    request: dict[str, Any],
    *,
    axis: str,
) -> tuple[float, float]:
    bounds = payload[f"{axis}_bounds"]
    minimum = float(bounds[0])
    maximum = float(bounds[1])
    if payload["layout"]["legend_uses_reserved_panel"]:
        return minimum, maximum
    options = _performance_render_options(payload, request)
    requested_minimum = options.get(f"{axis}_min")
    requested_maximum = options.get(f"{axis}_max")
    if isinstance(requested_minimum, int | float) and math.isfinite(
        float(requested_minimum)
    ):
        minimum = min(minimum, float(requested_minimum))
    if isinstance(requested_maximum, int | float) and math.isfinite(
        float(requested_maximum)
    ):
        maximum = max(maximum, float(requested_maximum))
    return minimum, maximum


def _performance_render_options(
    payload: dict[str, Any],
    request: dict[str, Any],
) -> dict[str, Any]:
    options = (
        dict(request.get("render_options"))
        if isinstance(request.get("render_options"), dict)
        else {}
    )
    resolved = payload.get("inside_legend_render_options")
    if isinstance(resolved, dict):
        options.update(resolved)
    return options


def _inside_legend_contract(
    payload: dict[str, Any],
    request: dict[str, Any],
) -> dict[str, Any]:
    use_reserved_panel = bool(
        payload["layout"]["legend_uses_reserved_panel"]
    )
    if use_reserved_panel:
        return {
            "show": False,
            "mode": "reserved_reference_panel",
            "outside_legend": False,
            "reference_panel_used": True,
        }
    options = _performance_render_options(payload, request)
    return {
        "show": True,
        "mode": str(options.get("legend_position") or "inside_best"),
        "columns": 1,
        "presentation_kind": "performance_group_summary",
        "outside_legend": False,
        "reference_panel_used": False,
        "horz_position": options.get("legend_horz_position"),
        "vert_position": options.get("legend_vert_position"),
        "horz_manual": options.get("legend_horz_manual"),
        "vert_manual": options.get("legend_vert_manual"),
        "placement_diagnostics": options.get(
            "_legend_placement_diagnostics"
        ),
    }


def _radar_cartesian(
    angles_degrees: list[float],
    radii: list[float],
    *,
    x_scale: float,
) -> tuple[list[float], list[float]]:
    x_values = [
        float(radius) * math.cos(math.radians(float(angle))) * x_scale
        for angle, radius in zip(angles_degrees, radii, strict=True)
    ]
    y_values = [
        float(radius) * math.sin(math.radians(float(angle)))
        for angle, radius in zip(angles_degrees, radii, strict=True)
    ]
    return x_values, y_values


def performance_series_records(payload: dict[str, Any]) -> list[dict[str, Any]]:
    """Return the exact data-bound XY inventory used by Studio and audits."""

    template = str(payload["template"])
    plot_width, plot_height = (
        float(value) for value in payload["layout"]["plot_region_mm"]
    )
    x_scale = plot_height / plot_width
    records: list[dict[str, Any]] = []
    for index, item in enumerate(payload["series"], start=1):
        if template == PERFORMANCE_SCATTER_TEMPLATE_ID:
            x_values = [float(value) for value in item["x_values"]]
            y_values = [float(value) for value in item["y_values"]]
            plot_line_hide = True
        else:
            x_values, y_values = _radar_cartesian(
                [float(value) for value in item["angles_degrees"]],
                [float(value) for value in item["radii"]],
                x_scale=x_scale,
            )
            plot_line_hide = item["role"] == "reference"
        expected_channels = ["marker"] if plot_line_hide else ["line", "marker"]
        records.append(
            {
                "name": f"series_{index}",
                "label": str(item["label"]),
                "legend_key": str(item["label"]),
                "x_name": f"performance_x_{index}",
                "y_name": f"performance_y_{index}",
                "x_values": x_values,
                "y_values": y_values,
                "error_values": [],
                "color": str(item["color"]),
                "line_width_pt": UNIFIED_LINE_WIDTH_PT,
                "line_style": "solid",
                "marker": str(item["marker"]),
                "marker_size_pt": UNIFIED_MARKER_SIZE_PT,
                "marker_thin_factor": 1,
                "marker_fill_color": str(item["marker_fill_color"]),
                "presentation_kind": (
                    "performance_scatter_material"
                    if template == PERFORMANCE_SCATTER_TEMPLATE_ID
                    else "performance_radar_material"
                ),
                "plot_line_hide": plot_line_hide,
                "marker_line_hide": False,
                "raw_points_visible": True,
                "expected_mark_channels": expected_channels,
                "source_artifacts": [
                    {
                        "path": str(payload["source"]),
                        "sha256": str(payload["source_sha256"]),
                    }
                ],
            }
        )
    return records


def _performance_polygons(payload: dict[str, Any]) -> list[dict[str, Any]]:
    polygons: list[dict[str, Any]] = []
    legend_rows = (
        _legend_layout(payload)[1]
        if payload["layout"]["legend_uses_reserved_panel"]
        else []
    )
    for row in legend_rows:
        index = int(row["index"])
        item = row["item"]
        y_position = float(row["y"])
        page_width, page_height = (
            float(value) for value in payload["layout"]["page_size_mm"]
        )
        center_x = float(row["marker_x"])
        radius_x = 0.8 / page_width
        radius_y = 0.8 / page_height
        normalized = _marker_polygon(str(item["marker"]))
        polygons.append(
            {
                "name": f"performance_legend_marker_{index}",
                "role": "material_index_marker",
                "parent": "page",
                "positioning": "relative",
                "x_axis": "x",
                "y_axis": "y",
                "xPos": [
                    center_x + radius_x * float(point[0])
                    for point in normalized
                ],
                "yPos": [
                    y_position + radius_y * float(point[1])
                    for point in normalized
                ],
                "line_color": str(item["color"]),
                "line_width_pt": UNIFIED_MARKER_LINE_WIDTH_PT,
                "line_style": "solid",
                "line_transparency": 0,
                "line_hide": False,
                "fill_color": str(item["marker_fill_color"]),
                "fill_transparency": 0,
                "fill_hide": False,
                "material": str(item["material"]),
            }
        )
    if payload["template"] == PERFORMANCE_SCATTER_TEMPLATE_ID:
        for index, envelope in enumerate(payload["envelopes"], start=1):
            polygons.append(
                {
                    "name": f"performance_envelope_{index}",
                    "role": str(
                        envelope.get("role", "observed_sample_extent")
                    ),
                    "parent": "graph",
                    "positioning": "axes",
                    "x_axis": "x",
                    "y_axis": "y",
                    "xPos": [float(value) for value in envelope["x_values"]],
                    "yPos": [float(value) for value in envelope["y_values"]],
                    "line_color": str(envelope["line_color"]),
                    "line_width_pt": UNIFIED_LINE_WIDTH_PT,
                    "line_style": "solid",
                    "line_transparency": int(envelope["line_transparency"]),
                    "line_hide": bool(envelope.get("line_hide", False)),
                    "fill_color": str(envelope["fill_color"]),
                    "fill_transparency": int(envelope["fill_transparency"]),
                    "fill_hide": False,
                    "members": list(envelope["members"]),
                    "group": str(envelope["group"]),
                    "interpretation": str(
                        envelope.get(
                            "interpretation",
                            "Observed extent with deterministic visual "
                            "padding; not a confidence region.",
                        )
                    ),
                }
            )
        return polygons

    plot_width, plot_height = (
        float(value) for value in payload["layout"]["plot_region_mm"]
    )
    x_scale = plot_height / plot_width
    for ring_index, radius in enumerate(_RADAR_RING_LEVELS, start=1):
        angles = [
            *[float(value) for value in payload["angles_degrees"]],
            float(payload["angles_degrees"][0]),
        ]
        radii = [radius] * len(angles)
        x_values, y_values = _radar_cartesian(
            angles,
            radii,
            x_scale=x_scale,
        )
        polygons.append(
            {
                "name": f"performance_radar_ring_{ring_index}",
                "role": "radar_grid_ring",
                "parent": "graph",
                "positioning": "axes",
                "x_axis": "x",
                "y_axis": "y",
                "xPos": x_values,
                "yPos": y_values,
                "line_color": PERFORMANCE_RADAR_GUIDE_COLOR,
                "line_width_pt": PERFORMANCE_RADAR_GUIDE_LINE_WIDTH_PT,
                "line_style": "dashed",
                "line_transparency": PERFORMANCE_RADAR_RING_TRANSPARENCY,
                "line_hide": False,
                "fill_color": "white",
                "fill_transparency": 100,
                "fill_hide": True,
                "score": radius,
            }
        )
    for index, item in enumerate(payload["series"], start=1):
        if item["filled_polygon"] is not True:
            continue
        x_values, y_values = _radar_cartesian(
            [float(value) for value in item["angles_degrees"]],
            [float(value) for value in item["radii"]],
            x_scale=x_scale,
        )
        polygons.append(
            {
                "name": f"performance_radar_sample_fill_{index}",
                "role": "sample_score_polygon",
                "parent": "graph",
                "positioning": "axes",
                "x_axis": "x",
                "y_axis": "y",
                "xPos": x_values,
                "yPos": y_values,
                "line_color": str(item["color"]),
                "line_width_pt": UNIFIED_LINE_WIDTH_PT,
                "line_style": "solid",
                "line_transparency": 0,
                "line_hide": False,
                "fill_color": str(
                    item.get("polygon_fill_color", item["color"])
                ),
                "fill_transparency": int(item["fill_transparency"]),
                "fill_hide": False,
                "material": str(item["label"]),
            }
        )
    return polygons


def _marker_polygon(marker: str) -> list[tuple[float, float]]:
    marker = str(marker).strip().casefold()
    if marker == "circle":
        return [
            (
                math.cos(2.0 * math.pi * index / 24.0),
                math.sin(2.0 * math.pi * index / 24.0),
            )
            for index in range(24)
        ]
    if marker in {"ellipsehorz", "ellipsevert"}:
        x_scale = 1.25 if marker == "ellipsehorz" else 0.72
        y_scale = 0.72 if marker == "ellipsehorz" else 1.25
        return [
            (
                x_scale * math.cos(2.0 * math.pi * index / 24.0),
                y_scale * math.sin(2.0 * math.pi * index / 24.0),
            )
            for index in range(24)
        ]
    if marker == "square":
        return [(-1.0, -1.0), (1.0, -1.0), (1.0, 1.0), (-1.0, 1.0)]
    if marker == "diamond":
        return [(0.0, 1.2), (1.0, 0.0), (0.0, -1.2), (-1.0, 0.0)]
    if marker in {"triangle", "triangledown"}:
        sign = 1.0 if marker == "triangle" else -1.0
        return [
            (0.0, 1.2 * sign),
            (-1.05, -0.75 * sign),
            (1.05, -0.75 * sign),
        ]
    if marker in {"triangleleft", "triangleright"}:
        sign = -1.0 if marker == "triangleleft" else 1.0
        return [
            (1.2 * sign, 0.0),
            (-0.75 * sign, -1.05),
            (-0.75 * sign, 1.05),
        ]
    if marker in {"pentagon", "hexagon", "octogon"}:
        count = {"pentagon": 5, "hexagon": 6, "octogon": 8}[marker]
        return [
            (
                math.cos(math.pi / 2.0 + 2.0 * math.pi * index / count),
                math.sin(math.pi / 2.0 + 2.0 * math.pi * index / count),
            )
            for index in range(count)
        ]
    if marker == "star4":
        return [
            (
                (1.0 if index % 2 == 0 else 0.43)
                * math.cos(math.pi / 2.0 + math.pi * index / 4.0),
                (1.0 if index % 2 == 0 else 0.43)
                * math.sin(math.pi / 2.0 + math.pi * index / 4.0),
            )
            for index in range(8)
        ]
    if marker == "star":
        return [
            (
                (1.0 if index % 2 == 0 else 0.43)
                * math.cos(math.pi / 2.0 + math.pi * index / 5.0),
                (1.0 if index % 2 == 0 else 0.43)
                * math.sin(math.pi / 2.0 + math.pi * index / 5.0),
            )
            for index in range(10)
        ]
    plus = [
        (-0.32, -1.0),
        (0.32, -1.0),
        (0.32, -0.32),
        (1.0, -0.32),
        (1.0, 0.32),
        (0.32, 0.32),
        (0.32, 1.0),
        (-0.32, 1.0),
        (-0.32, 0.32),
        (-1.0, 0.32),
        (-1.0, -0.32),
        (-0.32, -0.32),
    ]
    if marker == "cross":
        cosine = math.sqrt(0.5)
        return [
            (
                x_value * cosine - y_value * cosine,
                x_value * cosine + y_value * cosine,
            )
            for x_value, y_value in plus
        ]
    return plus


def _performance_lines(payload: dict[str, Any]) -> list[dict[str, Any]]:
    if payload["template"] != PERFORMANCE_RADAR_TEMPLATE_ID:
        return []
    plot_width, plot_height = (
        float(value) for value in payload["layout"]["plot_region_mm"]
    )
    x_scale = plot_height / plot_width
    lines: list[dict[str, Any]] = []
    for index, angle in enumerate(payload["angles_degrees"], start=1):
        radians = math.radians(float(angle))
        lines.append(
            {
                "name": f"performance_radar_spoke_{index}",
                "positioning": "axes",
                "x_axis": "x",
                "y_axis": "y",
                "mode": "point-to-point",
                "xPos": [0.0],
                "yPos": [0.0],
                "xPos2": [math.cos(radians) * x_scale],
                "yPos2": [math.sin(radians)],
                "clip": True,
                "hide": False,
                "line_color": PERFORMANCE_RADAR_GUIDE_COLOR,
                "line_width_pt": PERFORMANCE_RADAR_GUIDE_LINE_WIDTH_PT,
                "line_style": "solid",
                "line_transparency": PERFORMANCE_RADAR_SPOKE_TRANSPARENCY,
                "line_hide": False,
                "arrow_left": "none",
                "arrow_right": "none",
                "fill_hide": True,
            }
        )
    return lines


def _label_contract(
    *,
    name: str,
    label: str,
    parent: str,
    positioning: str,
    x: float,
    y: float,
    align: str = "left",
    valign: str = "centre",
    text_size_pt: float = UNIFIED_LEGEND_FONT_SIZE_PT,
    text_color: str = UNIFIED_FOREGROUND_COLOR,
    clip: bool = False,
) -> dict[str, Any]:
    return {
        "name": name,
        "label": label,
        "parent": parent,
        "positioning": positioning,
        "x_axis": "x",
        "y_axis": "y",
        "x": float(x),
        "y": float(y),
        "align": align,
        "valign": valign,
        "angle_degrees": 0.0,
        "margin_pt": 0.0,
        "clip": clip,
        "text_size_pt": float(text_size_pt),
        "text_color": text_color,
        "text_hide": False,
        "background_color": "white",
        "background_transparency": 0,
        "background_hide": True,
        "border_color": UNIFIED_FOREGROUND_COLOR,
        "border_width_pt": UNIFIED_AXIS_LINEWIDTH_PT,
        "border_style": "solid",
        "border_transparency": 0,
        "border_hide": True,
    }


def _legend_layout(
    payload: dict[str, Any],
) -> tuple[
    list[dict[str, Any]],
    list[dict[str, Any]],
    dict[int, float],
]:
    headings: list[dict[str, Any]] = []
    rows: list[dict[str, Any]] = []
    legend_items = [
        item for item in payload["legend_items"] if isinstance(item, dict)
    ]
    indexed_items = list(enumerate(legend_items, start=1))
    page_width = float(payload["layout"]["page_size_mm"][0])
    plot_panel_width = float(
        payload["layout"]["plot_panel_size_mm"][0]
    )
    heading_inset_mm = 4.5
    column_count = max(
        int(payload["layout"].get("legend_column_count") or 1),
        1,
    )
    bottoms: dict[int, float] = {}
    for column in range(1, column_count + 1):
        column_items = [
            (index, item)
            for index, item in indexed_items
            if int(item.get("legend_column") or 1) == column
        ]
        if not column_items:
            continue
        grouped_items: list[
            tuple[str, list[tuple[int, dict[str, Any]]]]
        ] = []
        for index, item in column_items:
            group = str(item.get("legend_group") or "").strip()
            if not grouped_items or grouped_items[-1][0] != group:
                grouped_items.append((group, []))
            grouped_items[-1][1].append((index, item))
        group_count = len(grouped_items)
        group_gap = 0.018
        group_layouts: list[
            tuple[str, list[tuple[int, dict[str, Any]]], int]
        ] = []
        for group, group_items in grouped_items:
            capacities = {
                max(
                    1,
                    min(
                        int(item.get("legend_items_per_row") or 1),
                        2,
                    ),
                )
                for _, item in group_items
            }
            if len(capacities) != 1:
                raise ValueError(
                    f"Legend group {group!r} has conflicting "
                    "LegendItemsPerRow values."
                )
            items_per_row = capacities.pop()
            group_layouts.append((group, group_items, items_per_row))
        item_row_count = sum(
            math.ceil(len(group_items) / items_per_row)
            for _, group_items, items_per_row in group_layouts
        )
        slot_count = max(item_row_count + group_count, 1)
        available = 0.88 - 0.10 - group_gap * max(group_count - 1, 0)
        row_step = min(0.078, available / float(slot_count))
        column_offset_mm = (
            PERFORMANCE_REFERENCE_PANEL_WIDTH_MM
            * float(column - 1)
        )
        heading_x = (
            plot_panel_width + heading_inset_mm + column_offset_mm
        ) / page_width
        marker_x = (
            plot_panel_width + heading_inset_mm + 0.8 + column_offset_mm
        ) / page_width
        text_x = (
            plot_panel_width + heading_inset_mm + 4.0 + column_offset_mm
        ) / page_width
        current_y = 0.88
        paired_slot_offset = _LEGEND_PAIRED_SLOT_OFFSET_MM / page_width
        for group_index, (
            group,
            group_items,
            items_per_row,
        ) in enumerate(group_layouts):
            if group_index:
                current_y -= group_gap
            headings.append(
                {
                    "column": column,
                    "group": group,
                    "x": heading_x,
                    "y": current_y,
                }
            )
            current_y -= row_step
            for row_start in range(0, len(group_items), items_per_row):
                row_items = group_items[
                    row_start : row_start + items_per_row
                ]
                for subcolumn, (index, item) in enumerate(row_items):
                    offset = paired_slot_offset * float(subcolumn)
                    rows.append(
                        {
                            "index": index,
                            "column": column,
                            "subcolumn": subcolumn + 1,
                            "item": item,
                            "marker_x": marker_x + offset,
                            "text_x": text_x + offset,
                            "y": current_y,
                            "row_step": row_step,
                        }
                    )
                current_y -= row_step
        bottoms[column] = current_y
    return headings, rows, bottoms


def _performance_labels(payload: dict[str, Any]) -> list[dict[str, Any]]:
    labels: list[dict[str, Any]] = []
    if payload["layout"]["legend_uses_reserved_panel"]:
        headings, rows, _ = _legend_layout(payload)
        for heading_item in headings:
            group = str(heading_item["group"])
            labels.append(
                _label_contract(
                    name=(
                        "performance_legend_heading_"
                        f"{int(heading_item['column'])}_"
                        f"{len(labels) + 1}"
                    ),
                    label=group,
                    parent="page",
                    positioning="relative",
                    x=float(heading_item["x"]),
                    y=float(heading_item["y"]),
                    text_size_pt=UNIFIED_LEGEND_FONT_SIZE_PT,
                )
            )
        for row in rows:
            index = int(row["index"])
            item = row["item"]
            citation = str(item.get("citation") or "").strip()
            display = str(item.get("label") or item["material"])
            if citation and bool(item.get("append_citation", True)):
                display = f"{display} - {citation}"
            labels.append(
                _label_contract(
                    name=f"performance_legend_text_{index}",
                    label=display,
                    parent="page",
                    positioning="relative",
                    x=float(row["text_x"]),
                    y=float(row["y"]),
                )
            )
    if payload["template"] == PERFORMANCE_RADAR_TEMPLATE_ID:
        five_axis_labels = _five_axis_radar_labels(payload)
        if five_axis_labels is not None:
            labels.extend(five_axis_labels)
            return labels
        plot_width, plot_height = (
            float(value) for value in payload["layout"]["plot_region_mm"]
        )
        x_scale = plot_height / plot_width
        label_line_spacing = (
            PERFORMANCE_RADAR_AXIS_LABEL_SIZE_PT
            * 1.15
            * (25.4 / 72.0)
            * (2.0 * _RADAR_AXIS_LIMIT / plot_height)
        )
        for index, (angle, label) in enumerate(
            zip(payload["angles_degrees"], payload["axis_labels"], strict=True),
            start=1,
        ):
            radians = math.radians(float(angle))
            cosine = math.cos(radians)
            sine = math.sin(radians)
            align = "left" if cosine > 0.25 else "right" if cosine < -0.25 else "centre"
            valign = "bottom" if sine > 0.25 else "top" if sine < -0.25 else "centre"
            horizontal_radius = (
                _RADAR_LABEL_HORIZONTAL_RADIUS_RIGHT
                if cosine > 0.25
                else _RADAR_LABEL_HORIZONTAL_RADIUS_LEFT
                if cosine < -0.25
                else 1.0
            )
            label_lines = str(label).splitlines() or [""]
            for line_index, label_line in enumerate(label_lines):
                if len(label_lines) == 1:
                    y_offset = 0.0
                elif sine > 0.25:
                    y_offset = (
                        len(label_lines) - 1 - line_index
                    ) * label_line_spacing
                elif sine < -0.25:
                    y_offset = -line_index * label_line_spacing
                else:
                    y_offset = (
                        (len(label_lines) - 1) / 2.0 - line_index
                    ) * label_line_spacing
                labels.append(
                    _label_contract(
                        name=(
                            f"performance_radar_axis_label_{index}"
                            if len(label_lines) == 1
                            else (
                                f"performance_radar_axis_label_{index}"
                                f"_line_{line_index + 1}"
                            )
                        ),
                        label=label_line,
                        parent="graph",
                        positioning="axes",
                        x=(
                            cosine
                            * x_scale
                            * horizontal_radius
                        ),
                        y=(
                            sine * _RADAR_LABEL_VERTICAL_RADIUS
                            + y_offset
                        ),
                        align=align,
                        valign=valign,
                        text_size_pt=PERFORMANCE_RADAR_AXIS_LABEL_SIZE_PT,
                        clip=False,
                    )
                )
        endpoint_labels = payload.get("axis_endpoint_labels") or []
        for index, (angle, endpoint_label) in enumerate(
            zip(
                payload["angles_degrees"],
                endpoint_labels,
                strict=True,
            ),
            start=1,
        ):
            radians = math.radians(float(angle))
            cosine = math.cos(radians)
            sine = math.sin(radians)
            labels.append(
                _label_contract(
                    name=f"performance_radar_axis_endpoint_label_{index}",
                    label=str(endpoint_label),
                    parent="graph",
                    positioning="axes",
                    x=(
                        cosine
                        * x_scale
                        * _RADAR_ENDPOINT_LABEL_RADIUS
                    ),
                    y=sine * _RADAR_ENDPOINT_LABEL_RADIUS,
                    align=(
                        "right"
                        if cosine > 0.25
                        else "left"
                        if cosine < -0.25
                        else "centre"
                    ),
                    valign=(
                        "top"
                        if sine > 0.25
                        else "bottom"
                        if sine < -0.25
                        else "centre"
                    ),
                    text_size_pt=PERFORMANCE_RADAR_AXIS_LABEL_SIZE_PT,
                    clip=False,
                )
            )
    return labels


def _five_axis_radar_labels(
    payload: dict[str, Any],
) -> list[dict[str, Any]] | None:
    angles = [float(value) for value in payload["angles_degrees"]]
    axis_labels = [str(value) for value in payload["axis_labels"]]
    endpoint_labels = [
        str(value) for value in payload.get("axis_endpoint_labels") or []
    ]
    layout = payload["layout"]
    page_width, page_height = (
        float(value) for value in layout["page_size_mm"]
    )
    plot_panel_width, plot_panel_height = (
        float(value) for value in layout["plot_panel_size_mm"]
    )
    if (
        len(angles) != 5
        or len(axis_labels) != 5
        or len(endpoint_labels) != 5
        or not all(
            math.isclose(actual, expected)
            for actual, expected in zip(
                angles,
                _RADAR_FIVE_AXIS_ANGLES,
                strict=True,
            )
        )
        or not math.isclose(plot_panel_width, 60.0)
        or not math.isclose(plot_panel_height, 55.0)
    ):
        return None
    split_labels = [label.splitlines() or [""] for label in axis_labels]
    if len(split_labels[0]) > 2 or any(
        len(lines) > 3 for lines in split_labels[1:]
    ):
        return None

    labels: list[dict[str, Any]] = []
    for axis_index, (lines, x_mm, centre_y_mm) in enumerate(
        zip(
            split_labels,
            _RADAR_FIVE_AXIS_TITLE_X_MM,
            _RADAR_FIVE_AXIS_TITLE_CENTRE_Y_MM,
            strict=True,
        ),
        start=1,
    ):
        first_y_mm = centre_y_mm - (
            (len(lines) - 1) * _RADAR_FIVE_AXIS_TITLE_LINE_STEP_MM / 2.0
        )
        for line_index, line in enumerate(lines, start=1):
            y_mm = first_y_mm + (
                (line_index - 1) * _RADAR_FIVE_AXIS_TITLE_LINE_STEP_MM
            )
            labels.append(
                _label_contract(
                    name=(
                        f"performance_radar_axis_label_{axis_index}"
                        if len(lines) == 1
                        else (
                            f"performance_radar_axis_label_{axis_index}"
                            f"_line_{line_index}"
                        )
                    ),
                    label=line,
                    parent="page",
                    positioning="relative",
                    x=x_mm / page_width,
                    y=1.0 - y_mm / page_height,
                    align="centre",
                    valign="centre",
                    text_size_pt=PERFORMANCE_RADAR_AXIS_LABEL_SIZE_PT,
                    clip=False,
                )
            )

    margins = layout["graph_margins_mm"]
    plot_width, plot_height = (
        float(value) for value in layout["plot_region_mm"]
    )
    graph_left_mm = float(margins["left"])
    graph_top_mm = float(margins["top"])
    centre_x_mm = graph_left_mm + plot_width / 2.0
    centre_y_mm = graph_top_mm + plot_height / 2.0
    radar_radius_mm = plot_height / (2.0 * _RADAR_AXIS_LIMIT)
    for axis_index, (angle, endpoint_label, endpoint_offset_mm) in enumerate(
        zip(
            angles,
            endpoint_labels,
            _RADAR_FIVE_AXIS_ENDPOINT_OFFSETS_MM,
            strict=True,
        ),
        start=1,
    ):
        radians = math.radians(angle)
        endpoint_radius_mm = radar_radius_mm + endpoint_offset_mm
        x_mm = centre_x_mm + math.cos(radians) * endpoint_radius_mm
        y_mm = centre_y_mm - math.sin(radians) * endpoint_radius_mm
        labels.append(
            _label_contract(
                name=f"performance_radar_axis_endpoint_label_{axis_index}",
                label=endpoint_label,
                parent="page",
                positioning="relative",
                x=x_mm / page_width,
                y=1.0 - y_mm / page_height,
                align="centre",
                valign="centre",
                text_size_pt=PERFORMANCE_RADAR_AXIS_LABEL_SIZE_PT,
                clip=False,
            )
        )
    return labels


def build_performance_veusz_spec(
    *,
    payload: dict[str, Any],
    request: dict[str, Any],
    transform_steps: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Build the exact-current native Veusz spec for one comparison figure."""

    template = str(payload["template"])
    layout = payload["layout"]
    margins = layout["graph_margins_mm"]
    style = _style_payload(margins)
    if template == PERFORMANCE_SCATTER_TEMPLATE_ID:
        x_minimum, x_maximum = _expanded_axis_bounds(
            payload,
            request,
            axis="x",
        )
        y_minimum, y_maximum = _expanded_axis_bounds(
            payload,
            request,
            axis="y",
        )
        axes = {
            "x": _axis_payload(
                label=str(payload["x_label"]),
                minimum=x_minimum,
                maximum=x_maximum,
                hidden=False,
            ),
            "y": _axis_payload(
                label=str(payload["y_label"]),
                minimum=y_minimum,
                maximum=y_maximum,
                hidden=False,
            ),
        }
    elif template == PERFORMANCE_RADAR_TEMPLATE_ID:
        axes = {
            "x": _axis_payload(
                label="",
                minimum=-_RADAR_AXIS_LIMIT,
                maximum=_RADAR_AXIS_LIMIT,
                hidden=True,
            ),
            "y": _axis_payload(
                label="",
                minimum=-_RADAR_AXIS_LIMIT,
                maximum=_RADAR_AXIS_LIMIT,
                hidden=True,
            ),
        }
    else:
        raise ValueError(f"Unsupported performance template: {template}")
    render_options = {
        **_performance_render_options(payload, request),
        "size": "x".join(
            f"{float(value):g}" for value in layout["page_size_mm"]
        ),
    }
    performance = {
        **json_safe(payload),
        "polygons": _performance_polygons(payload),
        "lines": _performance_lines(payload),
        "labels": _performance_labels(payload),
        "radar_coordinate_model": (
            {
                "kind": "cartesian_physical_circle",
                "x_compensation": (
                    float(layout["plot_region_mm"][1])
                    / float(layout["plot_region_mm"][0])
                ),
                "axis_limit": _RADAR_AXIS_LIMIT,
                "declared_normalized_radius": [0.0, 1.0],
            }
            if template == PERFORMANCE_RADAR_TEMPLATE_ID
            else None
        ),
    }
    return {
        "kind": "sciplot_veusz_plot_spec",
        "version": 1,
        "created_at": datetime.now(UTC).isoformat(),
        "render_engine": "veusz",
        "qa_target": "veusz_export",
        "template": template,
        "source_request": json_safe(request),
        "render_options": json_safe(render_options),
        "size_mm": [float(value) for value in layout["page_size_mm"]],
        "frame_alignment": {
            "status": "locked",
            "margin_mode": FIXED_PUBLICATION_FRAME_POLICY.margin_mode,
            "outside_legend_allowed": False,
            "layout_kind": layout["kind"],
            "plot_panel_size_mm": layout["plot_panel_size_mm"],
            "reference_panel_size_mm": layout["legend_panel_size_mm"],
            "plot_region_mm": layout["plot_region_mm"],
            "margins_mm": style["margins_mm"],
        },
        "autofixes_applied": [],
        "visual_extent_axis_clearance": {},
        "layout_issues": [],
        "visual_data_transforms": json_safe(
            payload.get("visual_data_transforms", [])
        ),
        "terminal_transform_steps": json_safe(transform_steps or []),
        "provenance": {"veusz": "vendored_native_document"},
        "style": style,
        "axes": axes,
        "legend": _inside_legend_contract(payload, request),
        "categorical": None,
        "scalar_field": None,
        "reference_guides": [],
        "series": performance_series_records(payload),
        "direct_labels": [],
        "performance_comparison": performance,
    }


def performance_polygon_contracts(spec: dict[str, Any]) -> list[dict[str, Any]]:
    performance = spec.get("performance_comparison")
    if not isinstance(performance, dict):
        return []
    return [
        dict(item)
        for item in performance.get("polygons", [])
        if isinstance(item, dict)
    ]


def performance_line_contracts(spec: dict[str, Any]) -> list[dict[str, Any]]:
    performance = spec.get("performance_comparison")
    if not isinstance(performance, dict):
        return []
    return [
        dict(item)
        for item in performance.get("lines", [])
        if isinstance(item, dict)
    ]


def performance_label_contracts(spec: dict[str, Any]) -> list[dict[str, Any]]:
    performance = spec.get("performance_comparison")
    if not isinstance(performance, dict):
        return []
    return [
        dict(item)
        for item in performance.get("labels", [])
        if isinstance(item, dict)
    ]


def _add_label(interface: Any, item: dict[str, Any]) -> None:
    interface.Add("label", name=item["name"], autoadd=False)
    interface.To(item["name"])
    interface.Set("positioning", item["positioning"])
    interface.Set("xAxis", item["x_axis"])
    interface.Set("yAxis", item["y_axis"])
    interface.Set("xPos", [float(item["x"])])
    interface.Set("yPos", [float(item["y"])])
    interface.Set("label", _literal_text(item["label"]))
    interface.Set("alignHorz", item["align"])
    interface.Set("alignVert", item["valign"])
    interface.Set("angle", float(item["angle_degrees"]))
    interface.Set("margin", _pt(float(item["margin_pt"])))
    interface.Set("clip", bool(item["clip"]))
    interface.Set("hide", False)
    interface.Set("Text/size", _pt(float(item["text_size_pt"])))
    interface.Set("Text/color", item["text_color"])
    interface.Set("Text/hide", bool(item["text_hide"]))
    interface.Set("Background/color", item["background_color"])
    interface.Set(
        "Background/transparency",
        int(item["background_transparency"]),
    )
    interface.Set("Background/hide", bool(item["background_hide"]))
    interface.Set("Border/color", item["border_color"])
    interface.Set("Border/width", _pt(float(item["border_width_pt"])))
    interface.Set("Border/style", item["border_style"])
    interface.Set("Border/transparency", int(item["border_transparency"]))
    interface.Set("Border/hide", bool(item["border_hide"]))
    interface.To("..")


def _add_axis(
    interface: Any,
    *,
    name: str,
    axis: dict[str, Any],
    style: dict[str, Any],
) -> None:
    interface.Add("axis", name=name, autoadd=False)
    interface.To(name)
    interface.Set("label", format_plot_text_units(axis["label"]))
    if name == "y":
        interface.Set("direction", "vertical")
    interface.Set("autoMirror", False)
    interface.Set("outerticks", True)
    hidden = bool(axis.get("hidden"))
    foreground = str(axis["foreground_color"])
    interface.Set("Line/color", foreground)
    interface.Set("Line/width", _pt(float(axis["line_width_pt"])))
    interface.Set("Line/hide", hidden)
    interface.Set("Line/transparency", 0)
    interface.Set("MajorTicks/width", _pt(float(axis["major_tick_width_pt"])))
    interface.Set("MajorTicks/length", _pt(float(axis["major_tick_length_pt"])))
    interface.Set("MajorTicks/hide", hidden)
    interface.Set("MajorTicks/transparency", 0)
    interface.Set("MinorTicks/width", _pt(float(axis["minor_tick_width_pt"])))
    interface.Set("MinorTicks/length", _pt(float(axis["minor_tick_length_pt"])))
    interface.Set("MinorTicks/number", int(axis["minor_tick_count"]))
    interface.Set("MinorTicks/hide", hidden)
    interface.Set("MinorTicks/transparency", 0)
    interface.Set("Label/size", _pt(float(axis["label_size_pt"])))
    interface.Set("Label/color", foreground)
    interface.Set("Label/hide", hidden or not bool(axis["label"]))
    interface.Set("Label/offset", _pt(float(style["axes_labelpad_pt"])))
    interface.Set("TickLabels/size", _pt(float(axis["tick_label_size_pt"])))
    interface.Set("TickLabels/color", foreground)
    interface.Set("TickLabels/format", axis["tick_format"])
    interface.Set("TickLabels/hide", hidden)
    interface.Set(
        "TickLabels/offset",
        _pt(
            float(
                style[
                    "xtick_major_pad_pt"
                    if name == "x"
                    else "ytick_major_pad_pt"
                ]
            )
        ),
    )
    interface.Set("min", float(axis["min"]))
    interface.Set("max", float(axis["max"]))
    interface.To("..")


def _apply_inside_key_position(interface: Any, legend: dict[str, Any]) -> None:
    mode = str(legend.get("mode") or "inside_best").strip().casefold()
    horz_position = legend.get("horz_position")
    vert_position = legend.get("vert_position")
    if mode == "manual" or horz_position is not None or vert_position is not None:
        horz = str(horz_position or "manual")
        vert = str(vert_position or "manual")
        interface.Set("horzPosn", horz)
        interface.Set("vertPosn", vert)
        if horz == "manual":
            interface.Set(
                "horzManual",
                float(
                    legend["horz_manual"]
                    if legend.get("horz_manual") is not None
                    else 0.5
                ),
            )
        if vert == "manual":
            interface.Set(
                "vertManual",
                float(
                    legend["vert_manual"]
                    if legend.get("vert_manual") is not None
                    else 0.5
                ),
            )
        return
    if mode in {"upper_right", "top_right"}:
        interface.Set("horzPosn", "right")
        interface.Set("vertPosn", "top")
        return
    if mode in {"upper_left", "top_left"}:
        interface.Set("horzPosn", "left")
        interface.Set("vertPosn", "top")
        return
    if mode in {"lower_left", "bottom_left"}:
        interface.Set("horzPosn", "left")
        interface.Set("vertPosn", "bottom")
        return
    interface.Set("horzPosn", "right")
    interface.Set("vertPosn", "bottom")


def _add_inside_key(
    interface: Any,
    legend: dict[str, Any],
    style: dict[str, Any],
) -> None:
    if not bool(legend.get("show")):
        return
    interface.Add("key", name="key1", autoadd=False)
    interface.To("key1")
    interface.Set("title", "")
    interface.Set("Text/size", _pt(float(style["legend_font_size_pt"])))
    interface.Set(
        "keyLength",
        f"{UNIFIED_LEGEND_KEY_LENGTH_MM / 10.0:.2f}cm",
    )
    interface.Set("marginSize", 0.15)
    interface.Set("columns", int(legend.get("columns") or 1))
    _apply_inside_key_position(interface, legend)
    interface.Set("Background/hide", not bool(style["legend_frameon"]))
    interface.Set("Border/hide", not bool(style["legend_frameon"]))
    interface.To("..")


def _add_xy_series(
    interface: Any,
    item: dict[str, Any],
    style: dict[str, Any],
) -> None:
    interface.Add("xy", name=item["name"], autoadd=False)
    interface.To(item["name"])
    interface.Set("xData", item["x_name"])
    interface.Set("yData", item["y_name"])
    interface.Set("key", _literal_text(item["legend_key"]))
    interface.Set("ErrorBarLine/hide", True)
    interface.Set("PlotLine/color", item["color"])
    interface.Set("PlotLine/style", item["line_style"])
    interface.Set("PlotLine/width", _pt(float(item["line_width_pt"])))
    interface.Set("PlotLine/transparency", 8)
    interface.Set("PlotLine/hide", bool(item["plot_line_hide"]))
    interface.Set("marker", item["marker"])
    interface.Set("markerSize", _pt(float(item["marker_size_pt"])))
    interface.Set("MarkerFill/color", item["marker_fill_color"])
    interface.Set("MarkerFill/transparency", 5)
    interface.Set("MarkerFill/hide", False)
    interface.Set("MarkerLine/color", item["color"])
    interface.Set(
        "MarkerLine/width",
        _pt(float(style["marker_line_width_pt"])),
    )
    interface.Set("MarkerLine/transparency", 5)
    interface.Set("MarkerLine/hide", False)
    interface.To("..")


def _add_polygon(interface: Any, item: dict[str, Any]) -> None:
    interface.Add("polygon", name=item["name"], autoadd=False)
    interface.To(item["name"])
    interface.Set("positioning", item["positioning"])
    interface.Set("xAxis", item["x_axis"])
    interface.Set("yAxis", item["y_axis"])
    interface.Set("xPos", item["xPos"])
    interface.Set("yPos", item["yPos"])
    interface.Set("hide", False)
    interface.Set("Line/color", item["line_color"])
    interface.Set("Line/width", _pt(float(item["line_width_pt"])))
    interface.Set("Line/style", item["line_style"])
    interface.Set("Line/transparency", int(item["line_transparency"]))
    interface.Set("Line/hide", bool(item["line_hide"]))
    interface.Set("Fill/color", item["fill_color"])
    interface.Set("Fill/transparency", int(item["fill_transparency"]))
    interface.Set("Fill/hide", bool(item["fill_hide"]))
    interface.To("..")


def _add_line(interface: Any, item: dict[str, Any]) -> None:
    interface.Add("line", name=item["name"], autoadd=False)
    interface.To(item["name"])
    interface.Set("positioning", item["positioning"])
    interface.Set("xAxis", item["x_axis"])
    interface.Set("yAxis", item["y_axis"])
    interface.Set("mode", item["mode"])
    interface.Set("xPos", item["xPos"])
    interface.Set("yPos", item["yPos"])
    interface.Set("xPos2", item["xPos2"])
    interface.Set("yPos2", item["yPos2"])
    interface.Set("clip", bool(item["clip"]))
    interface.Set("hide", False)
    interface.Set("Line/color", item["line_color"])
    interface.Set("Line/width", _pt(float(item["line_width_pt"])))
    interface.Set("Line/style", item["line_style"])
    interface.Set("Line/transparency", int(item["line_transparency"]))
    interface.Set("Line/hide", bool(item["line_hide"]))
    interface.Set("arrowleft", item["arrow_left"])
    interface.Set("arrowright", item["arrow_right"])
    interface.Set("Fill/hide", bool(item["fill_hide"]))
    interface.To("..")


def apply_performance_veusz_spec(interface: Any, spec: dict[str, Any]) -> None:
    """Materialize the native editable document from the closed spec."""

    style = spec["style"]
    size_mm = spec["size_mm"]
    for item in spec["series"]:
        interface.ImportString(
            f"{item['x_name']}(numeric)",
            "\n".join(f"{float(value):.12g}" for value in item["x_values"]),
        )
        interface.ImportString(
            f"{item['y_name']}(numeric)",
            "\n".join(f"{float(value):.12g}" for value in item["y_values"]),
        )
    interface.Set("StyleSheet/Font/font", style["font_family"])
    interface.Set("StyleSheet/Font/size", _pt(float(style["font_size_pt"])))
    interface.Set("StyleSheet/Line/width", _pt(float(style["line_width_pt"])))
    interface.Set("width", f"{float(size_mm[0]):g}mm")
    interface.Set("height", f"{float(size_mm[1]):g}mm")
    interface.Add("page", name="page1", autoadd=False)
    interface.To("page1")
    interface.Set("width", f"{float(size_mm[0]):g}mm")
    interface.Set("height", f"{float(size_mm[1]):g}mm")
    interface.Set("Background/color", "white")
    interface.Set("Background/hide", False)
    labels = performance_label_contracts(spec)
    polygons = performance_polygon_contracts(spec)
    for label in labels:
        if label["parent"] == "page":
            _add_label(interface, label)
    for item in polygons:
        if item.get("parent") == "page":
            _add_polygon(interface, item)
    interface.Add("graph", name="graph1", autoadd=False)
    interface.To("graph1")
    interface.Set("Border/hide", True)
    margins = style["margins_mm"]
    interface.Set("leftMargin", _cm_from_mm(float(margins["left"])))
    interface.Set("rightMargin", _cm_from_mm(float(margins["right"])))
    interface.Set("topMargin", _cm_from_mm(float(margins["top"])))
    interface.Set("bottomMargin", _cm_from_mm(float(margins["bottom"])))
    _add_axis(interface, name="x", axis=spec["axes"]["x"], style=style)
    _add_axis(interface, name="y", axis=spec["axes"]["y"], style=style)
    _add_inside_key(interface, spec["legend"], style)
    for label in labels:
        if label["parent"] == "graph":
            _add_label(interface, label)
    for item in spec["series"]:
        _add_xy_series(interface, item, style)
    for item in polygons:
        if item.get("parent") != "page":
            _add_polygon(interface, item)
    for item in performance_line_contracts(spec):
        _add_line(interface, item)
    interface.To("..")
    interface.To("..")


__all__ = [
    "apply_performance_veusz_spec",
    "build_performance_veusz_spec",
    "performance_label_contracts",
    "performance_line_contracts",
    "performance_polygon_contracts",
    "performance_series_records",
]
