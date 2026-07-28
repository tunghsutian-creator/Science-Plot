"""Match colorbar, shape, and direct-label visual contracts."""

from __future__ import annotations

from typing import Any
from sciplot_core.veusz_worker.widget_bindings import (
    _distance_matches_mm,
    _distance_matches_pt,
    _numeric_setting_equal,
    _numeric_sequence_equal,
)


def _colorbar_record_matches_contract(
    record: dict[str, Any],
    *,
    scalar: dict[str, Any],
    visual: dict[str, Any],
) -> bool:
    bindings = record["bindings"]
    direction = str(visual["colorbar_direction"]).strip().casefold()
    if direction not in {"horizontal", "vertical"}:
        direction = "horizontal"
    if visual["colorbar_manual_position"] is True:
        horz_position = "manual"
        vert_position = "manual"
        horz_manual = visual["colorbar_horz_manual"]
        vert_manual = visual["colorbar_vert_manual"]
    elif direction == "horizontal":
        horz_position = "right"
        vert_position = "top"
        horz_manual = 0.0
        vert_manual = 0.0
    else:
        horz_position = "manual"
        vert_position = "manual"
        horz_manual = visual["colorbar_horz_manual"]
        vert_manual = visual["colorbar_vert_manual"]
    z_ticks = (
        list(visual["z_ticks"])
        if isinstance(visual["z_ticks"], list) and 1 < len(visual["z_ticks"]) <= 12
        else []
    )
    foreground = str(visual["colorbar_foreground_color"])
    return (
        record["name"] == "field_colorbar"
        and str(bindings["label"]) == str(scalar.get("z_label") or "Z")
        and str(bindings["widgetName"]) == "field_image"
        and _numeric_setting_equal(bindings["min"], visual["z_min"])
        and _numeric_setting_equal(bindings["max"], visual["z_max"])
        and str(bindings["direction"]) == direction
        and str(bindings["horzPosn"]) == horz_position
        and str(bindings["vertPosn"]) == vert_position
        and _numeric_setting_equal(bindings["horzManual"], horz_manual)
        and _numeric_setting_equal(bindings["vertManual"], vert_manual)
        and _distance_matches_mm(
            bindings["width"],
            visual["colorbar_width_mm"],
        )
        and _distance_matches_mm(
            bindings["height"],
            visual["colorbar_height_mm"],
        )
        and str(bindings["TickLabels/format"]) == str(visual["z_tick_format"])
        and _numeric_sequence_equal(
            bindings["MajorTicks/manualTicks"],
            z_ticks,
        )
        and _distance_matches_pt(
            bindings["Label/size"],
            visual["colorbar_label_size_pt"],
        )
        and _distance_matches_pt(
            bindings["TickLabels/size"],
            visual["colorbar_tick_label_size_pt"],
        )
        and _distance_matches_pt(
            bindings["Line/width"],
            visual["colorbar_line_width_pt"],
        )
        and _distance_matches_pt(
            bindings["Border/width"],
            visual["colorbar_border_width_pt"],
        )
        and _distance_matches_pt(
            bindings["MajorTicks/width"],
            visual["colorbar_major_tick_width_pt"],
        )
        and _distance_matches_pt(
            bindings["MajorTicks/length"],
            visual["colorbar_major_tick_length_pt"],
        )
        and _distance_matches_pt(
            bindings["MinorTicks/width"],
            visual["colorbar_minor_tick_width_pt"],
        )
        and _distance_matches_pt(
            bindings["MinorTicks/length"],
            visual["colorbar_minor_tick_length_pt"],
        )
        and all(
            not bool(bindings[path])
            for path in (
                "Label/hide",
                "TickLabels/hide",
                "MajorTicks/hide",
                "MinorTicks/hide",
                "Line/hide",
                "Border/hide",
            )
        )
        and all(
            _numeric_setting_equal(bindings[path], 0)
            for path in (
                "Line/transparency",
                "Border/transparency",
                "MajorTicks/transparency",
                "MinorTicks/transparency",
            )
        )
        and all(
            str(bindings[path]) == foreground
            for path in (
                "Line/color",
                "Border/color",
                "Label/color",
                "TickLabels/color",
            )
        )
    )


def _rect_record_matches_contract(
    record: dict[str, Any],
    *,
    expected: dict[str, Any],
) -> bool:
    bindings = record["bindings"]
    return (
        record["path"] == expected["path"]
        and record["name"] == expected["name"]
        and str(bindings["positioning"]) == expected["positioning"]
        and _numeric_sequence_equal(bindings["xPos"], expected["xPos"])
        and _numeric_sequence_equal(bindings["yPos"], expected["yPos"])
        and _numeric_sequence_equal(bindings["width"], expected["width"])
        and _numeric_sequence_equal(bindings["height"], expected["height"])
        and bool(bindings["clip"]) is bool(expected["clip"])
        and str(bindings["Fill/color"]) == expected["fill_color"]
        and bool(bindings["Fill/hide"]) is bool(expected["fill_hide"])
        and _numeric_setting_equal(
            bindings["Fill/transparency"],
            expected["fill_transparency"],
        )
        and bool(bindings["Border/hide"]) is bool(expected["border_hide"])
    )


def _line_record_matches_contract(
    record: dict[str, Any],
    *,
    expected: dict[str, Any],
) -> bool:
    bindings = record["bindings"]
    return (
        record["path"] == expected["path"]
        and record["name"] == expected["name"]
        and str(bindings["positioning"]) == expected["positioning"]
        and str(bindings["xAxis"]) == expected["x_axis"]
        and str(bindings["yAxis"]) == expected["y_axis"]
        and str(bindings["mode"]) == expected["mode"]
        and _numeric_sequence_equal(bindings["xPos"], expected["xPos"])
        and _numeric_sequence_equal(bindings["yPos"], expected["yPos"])
        and _numeric_sequence_equal(bindings["xPos2"], expected["xPos2"])
        and _numeric_sequence_equal(bindings["yPos2"], expected["yPos2"])
        and bool(bindings["clip"]) is bool(expected["clip"])
        and not bool(bindings["hide"])
        and str(bindings["Line/color"]) == expected["line_color"]
        and _distance_matches_pt(
            bindings["Line/width"],
            expected["line_width_pt"],
        )
        and str(bindings["Line/style"]) == expected["line_style"]
        and _numeric_setting_equal(
            bindings["Line/transparency"],
            expected["line_transparency"],
        )
        and bool(bindings["Line/hide"]) is bool(expected["line_hide"])
        and str(bindings["arrowleft"]) == expected["arrow_left"]
        and str(bindings["arrowright"]) == expected["arrow_right"]
        and bool(bindings["Fill/hide"]) is bool(expected["fill_hide"])
    )


def _polygon_record_matches_contract(
    record: dict[str, Any],
    *,
    expected: dict[str, Any],
) -> bool:
    bindings = record["bindings"]
    return (
        record["path"] == expected["path"]
        and record["name"] == expected["name"]
        and str(bindings["positioning"]) == expected["positioning"]
        and str(bindings["xAxis"]) == expected["x_axis"]
        and str(bindings["yAxis"]) == expected["y_axis"]
        and _numeric_sequence_equal(bindings["xPos"], expected["xPos"])
        and _numeric_sequence_equal(bindings["yPos"], expected["yPos"])
        and not bool(bindings["hide"])
        and str(bindings["Line/color"]) == expected["line_color"]
        and _distance_matches_pt(
            bindings["Line/width"],
            expected["line_width_pt"],
        )
        and str(bindings["Line/style"]) == expected["line_style"]
        and _numeric_setting_equal(
            bindings["Line/transparency"],
            expected["line_transparency"],
        )
        and bool(bindings["Line/hide"]) is bool(expected["line_hide"])
        and str(bindings["Fill/color"]) == expected["fill_color"]
        and _numeric_setting_equal(
            bindings["Fill/transparency"],
            expected["fill_transparency"],
        )
        and bool(bindings["Fill/hide"]) is bool(expected["fill_hide"])
    )


def _direct_label_record_matches_contract(
    record: dict[str, Any],
    *,
    expected: dict[str, Any],
) -> bool:
    bindings = record["bindings"]
    return (
        record["path"] == expected["path"]
        and record["name"] == expected["name"]
        and str(bindings["label"]) == str(expected["literal_label"])
        and str(bindings["positioning"]) == expected["positioning"]
        and str(bindings["xAxis"]) == expected["x_axis"]
        and str(bindings["yAxis"]) == expected["y_axis"]
        and _numeric_sequence_equal(bindings["xPos"], [expected["x"]])
        and _numeric_sequence_equal(bindings["yPos"], [expected["y"]])
        and str(bindings["alignHorz"]) == expected["align"]
        and str(bindings["alignVert"]) == expected["valign"]
        and _numeric_setting_equal(
            bindings["angle"],
            expected["angle_degrees"],
        )
        and _distance_matches_pt(
            bindings["margin"],
            expected["margin_pt"],
        )
        and bool(bindings["clip"]) is bool(expected["clip"])
        and _distance_matches_pt(
            bindings["Text/size"],
            expected["text_size_pt"],
        )
        and str(bindings["Text/color"]) == expected["text_color"]
        and bool(bindings["Text/hide"]) is bool(expected["text_hide"])
        and str(bindings["Background/color"]) == expected["background_color"]
        and _numeric_setting_equal(
            bindings["Background/transparency"],
            expected["background_transparency"],
        )
        and bool(bindings["Background/hide"]) is bool(expected["background_hide"])
        and str(bindings["Border/color"]) == expected["border_color"]
        and _distance_matches_pt(
            bindings["Border/width"],
            expected["border_width_pt"],
        )
        and str(bindings["Border/style"]) == expected["border_style"]
        and _numeric_setting_equal(
            bindings["Border/transparency"],
            expected["border_transparency"],
        )
        and bool(bindings["Border/hide"]) is bool(expected["border_hide"])
    )
