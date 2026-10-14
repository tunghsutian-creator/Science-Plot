"""Build scatter and radar label contracts."""

from __future__ import annotations

import math
import unicodedata
from typing import Any
from sciplot_core.performance_comparison import (
    PERFORMANCE_RADAR_TEMPLATE_ID,
    PerformanceComparisonError,
)
from sciplot_core.policy import (
    PERFORMANCE_RADAR_AXIS_LABEL_SIZE_PT,
    UNIFIED_LEGEND_FONT_SIZE_PT,
)

from sciplot_core.performance_veusz.style import (
    _RADAR_AXIS_LIMIT,
    _RADAR_LABEL_HORIZONTAL_RADIUS_LEFT,
    _RADAR_LABEL_HORIZONTAL_RADIUS_RIGHT,
    _RADAR_LABEL_VERTICAL_RADIUS,
    _RADAR_ENDPOINT_LABEL_RADIUS,
    _RADAR_FIVE_AXIS_ANGLES,
    _RADAR_FIVE_AXIS_TITLE_X_MM,
    _RADAR_FIVE_AXIS_TITLE_CENTRE_Y_MM,
    _RADAR_FIVE_AXIS_TITLE_LINE_STEP_MM,
    _RADAR_FIVE_AXIS_ENDPOINT_OFFSETS_MM,
)

from sciplot_core.performance_veusz.legend_layout import (
    _label_contract,
    _legend_layout,
)


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
        if payload.get("radar_display"):
            labels.extend(_radar_interpretation_labels(payload))
            physical_labels = _physical_radar_labels(payload)
            if physical_labels is not None:
                labels.extend(physical_labels)
                return labels
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
                    y_offset = (len(label_lines) - 1 - line_index) * label_line_spacing
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
                        x=(cosine * x_scale * horizontal_radius),
                        y=(sine * _RADAR_LABEL_VERTICAL_RADIUS + y_offset),
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
                    x=(cosine * x_scale * _RADAR_ENDPOINT_LABEL_RADIUS),
                    y=sine * _RADAR_ENDPOINT_LABEL_RADIUS,
                    align=(
                        "right"
                        if cosine > 0.25
                        else "left"
                        if cosine < -0.25
                        else "centre"
                    ),
                    valign=(
                        "top" if sine > 0.25 else "bottom" if sine < -0.25 else "centre"
                    ),
                    text_size_pt=PERFORMANCE_RADAR_AXIS_LABEL_SIZE_PT,
                    clip=False,
                )
            )
    return labels


def _radar_interpretation_labels(payload: dict[str, Any]) -> list[dict[str, Any]]:
    width, height = map(float, payload["layout"]["page_size_mm"])
    panel_width = float(payload["layout"]["plot_panel_size_mm"][0])
    return [
        _label_contract(
            name=f"performance_radar_note_{index}",
            label=str(note), parent="page", positioning="relative",
            x=(panel_width + 4.5) / width,
            y=1.0 - (36.0 + (index - 1) * _RADAR_FIVE_AXIS_TITLE_LINE_STEP_MM) / height,
            text_size_pt=PERFORMANCE_RADAR_AXIS_LABEL_SIZE_PT,
        )
        for index, note in enumerate(payload["radar_display"]["notes"], start=1)
    ]


def _wrapped_radar_lines(label: str, width_mm: float) -> list[str]:
    """Conservatively wrap Latin/CJK text, retaining every source character.

    The native artifact QA remains the authority for actual font bounds.
    Wrapping uses a physical budget at the fixed 6 pt size, never a smaller font.
    """
    result: list[str] = []
    # Width estimates intentionally leave room for the native font and arrows.
    def width(text: str) -> float:
        return sum(
            2.15 if unicodedata.east_asian_width(char) in {"W", "F"}
            else 1.65 if char in "WM↑↓"
            else 0.95
            for char in text
        )
    for paragraph in label.splitlines() or [""]:
        remaining = paragraph
        while width(remaining) > width_mm:
            split_at = 1
            while split_at < len(remaining) and width(remaining[:split_at + 1]) <= width_mm:
                split_at += 1
            space_at = remaining.rfind(" ", 0, split_at + 1)
            if space_at > 0:
                split_at = space_at
            result.append(remaining[:split_at].rstrip())
            remaining = remaining[split_at:].lstrip()
        result.append(remaining)
    return result


def _physical_radar_labels(payload: dict[str, Any]) -> list[dict[str, Any]] | None:
    """Readable axis text in the existing 60 x 55 mm four/five-axis slots."""
    angles = [float(value) for value in payload["angles_degrees"]]
    layout = payload["layout"]
    if layout["plot_panel_size_mm"] != [60.0, 55.0]:
        return None
    if angles == [90.0, 180.0, 270.0, 0.0]:
        # Side titles use the corner whitespace above the cardinal endpoints;
        # a long wrapped title centred on a spoke would obscure its raw value.
        slots = [(28.75, 2.9, 48.0), (8.7, 13.4, 16.0),
                 (28.75, 50.0, 48.0), (51.0, 13.4, 17.0)]
    elif tuple(angles) == _RADAR_FIVE_AXIS_ANGLES:
        slots = list(zip(_RADAR_FIVE_AXIS_TITLE_X_MM,
                         _RADAR_FIVE_AXIS_TITLE_CENTRE_Y_MM,
                         (48.0, 18.0, 25.0, 25.0, 18.0), strict=True))
    else:
        return None
    width, height = map(float, layout["page_size_mm"])
    labels: list[dict[str, Any]] = []
    for index, (label, (x_mm, centre_y_mm, budget_mm)) in enumerate(
        zip(payload["axis_labels"], slots, strict=True), start=1
    ):
        lines = _wrapped_radar_lines(str(label), budget_mm)
        first_y = centre_y_mm - (len(lines) - 1) * _RADAR_FIVE_AXIS_TITLE_LINE_STEP_MM / 2.0
        last_y = first_y + (len(lines) - 1) * _RADAR_FIVE_AXIS_TITLE_LINE_STEP_MM
        side_title = centre_y_mm == 13.4
        if first_y < 1.0 or last_y > 54.0 or (side_title and len(lines) > 5):
            raise PerformanceComparisonError(
                "performance_radar_label_space_insufficient",
                f"Radar axis {index} label does not fit the fixed physical slots "
                "at 6 pt; provide a shorter DisplayLabel while retaining Unit.",
            )
        for line_index, line in enumerate(lines, start=1):
            labels.append(_label_contract(
                name=(f"performance_radar_axis_label_{index}" if len(lines) == 1
                      else f"performance_radar_axis_label_{index}_line_{line_index}"),
                label=line, parent="page", positioning="relative",
                x=x_mm / width,
                y=1.0 - (first_y + (line_index - 1) * _RADAR_FIVE_AXIS_TITLE_LINE_STEP_MM) / height,
                align="centre", text_size_pt=PERFORMANCE_RADAR_AXIS_LABEL_SIZE_PT,
            ))
    margins = layout["graph_margins_mm"]
    plot_width, plot_height = map(float, layout["plot_region_mm"])
    centre_x = float(margins["left"]) + plot_width / 2.0
    centre_y = float(margins["top"]) + plot_height / 2.0
    radius = plot_height / (2.0 * _RADAR_AXIS_LIMIT)
    offsets = _RADAR_FIVE_AXIS_ENDPOINT_OFFSETS_MM if len(angles) == 5 else (1.3,) * 4
    for index, (angle, endpoint, offset) in enumerate(
        zip(angles, payload["axis_endpoint_labels"], offsets, strict=True), start=1
    ):
        theta = math.radians(angle)
        labels.append(_label_contract(
            name=f"performance_radar_axis_endpoint_label_{index}",
            label=str(endpoint), parent="page", positioning="relative",
            x=(centre_x + math.cos(theta) * (radius + offset)) / width,
            y=1.0 - (centre_y - math.sin(theta) * (radius + offset)) / height,
            align="centre", text_size_pt=PERFORMANCE_RADAR_AXIS_LABEL_SIZE_PT,
        ))
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
    page_width, page_height = (float(value) for value in layout["page_size_mm"])
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
    if len(split_labels[0]) > 2 or any(len(lines) > 3 for lines in split_labels[1:]):
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
            y_mm = first_y_mm + ((line_index - 1) * _RADAR_FIVE_AXIS_TITLE_LINE_STEP_MM)
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
    plot_width, plot_height = (float(value) for value in layout["plot_region_mm"])
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
