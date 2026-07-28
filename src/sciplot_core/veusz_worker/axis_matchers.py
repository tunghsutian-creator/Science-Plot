"""Match exact-current axis and scalar-image records to their specifications."""

from __future__ import annotations

from typing import Any
from sciplot_core.veusz_worker.widget_bindings import (
    _distance_matches_pt,
    _numeric_setting_equal,
    _numeric_sequence_equal,
)


def _axis_record_matches_spec(
    record: dict[str, Any],
    axis_spec: dict[str, Any],
    *,
    axis_name: str,
) -> bool:
    bindings = record["bindings"]
    hidden = axis_spec.get("hidden") is True
    expected_ticks = (
        axis_spec.get("ticks")
        if isinstance(axis_spec.get("ticks"), list)
        and 1 < len(axis_spec["ticks"]) <= 12
        else []
    )
    expected_mode = str(axis_spec.get("mode") or "numeric")
    expected_log = axis_spec.get("scale") == "log"
    expected_direction = "vertical" if axis_name == "y" else "horizontal"
    ticks_visible = axis_spec.get("show_ticks") is not False and not hidden
    visibility_matches = all(
        bool(bindings[path]) is (not ticks_visible)
        for path in (
            "MajorTicks/hide",
            "MinorTicks/hide",
            "TickLabels/hide",
        )
    )
    label = str(axis_spec.get("label") or "")
    label_visibility_matches = (
        bool(bindings["Label/hide"])
        if hidden or not label
        else not bool(bindings["Label/hide"])
    )
    foreground = str(axis_spec["foreground_color"])
    return (
        record["name"] == axis_name
        and str(bindings["label"]) == label
        and str(bindings["direction"]) == expected_direction
        and str(bindings["mode"]) == expected_mode
        and bool(bindings["log"]) is expected_log
        and _numeric_setting_equal(bindings["min"], axis_spec.get("min"))
        and _numeric_setting_equal(bindings["max"], axis_spec.get("max"))
        and str(bindings["TickLabels/format"])
        == str(axis_spec.get("tick_format") or "Auto")
        and _numeric_sequence_equal(
            bindings["MajorTicks/manualTicks"],
            expected_ticks,
        )
        and _numeric_setting_equal(
            bindings["MinorTicks/number"],
            int(axis_spec.get("minor_tick_count") or 20),
        )
        and _numeric_sequence_equal(
            bindings["MinorTicks/manualTicks"],
            axis_spec.get("minor_ticks"),
        )
        and _distance_matches_pt(
            bindings["Label/size"],
            axis_spec["label_size_pt"],
        )
        and _distance_matches_pt(
            bindings["TickLabels/size"],
            axis_spec["tick_label_size_pt"],
        )
        and _distance_matches_pt(
            bindings["Line/width"],
            axis_spec["line_width_pt"],
        )
        and _distance_matches_pt(
            bindings["MajorTicks/width"],
            axis_spec["major_tick_width_pt"],
        )
        and _distance_matches_pt(
            bindings["MajorTicks/length"],
            axis_spec["major_tick_length_pt"],
        )
        and _distance_matches_pt(
            bindings["MinorTicks/width"],
            axis_spec["minor_tick_width_pt"],
        )
        and _distance_matches_pt(
            bindings["MinorTicks/length"],
            axis_spec["minor_tick_length_pt"],
        )
        and bool(bindings["Line/hide"]) is hidden
        and all(
            _numeric_setting_equal(bindings[path], 0)
            for path in (
                "Line/transparency",
                "MajorTicks/transparency",
                "MinorTicks/transparency",
            )
        )
        and all(
            str(bindings[path]) == foreground
            for path in (
                "Line/color",
                "Label/color",
                "TickLabels/color",
            )
        )
        and visibility_matches
        and label_visibility_matches
    )


def _scalar_image_matches_contract(
    record: dict[str, Any],
    *,
    data_name: str,
    visual: dict[str, Any],
) -> bool:
    bindings = record["bindings"]
    return (
        record["name"] == "field_image"
        and str(bindings["data"]) == data_name
        and _numeric_setting_equal(bindings["min"], visual["z_min"])
        and _numeric_setting_equal(bindings["max"], visual["z_max"])
        and str(bindings["colorScaling"]) == str(visual["zscale"])
        and str(bindings["colorMap"]) == str(visual["colormap_name"])
        and bool(bindings["colorInvert"]) is bool(visual["color_invert"])
        and str(bindings["mapping"]) == str(visual["field_mapping"])
        and str(bindings["drawMode"]) == str(visual["field_draw_mode"])
        and _numeric_setting_equal(
            bindings["transparency"],
            visual["field_transparency"],
        )
        and record["mark_channels"] == ["image"]
    )
