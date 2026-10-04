"""Resolved presentation fields shared by initial native audit and style edits."""

from __future__ import annotations

from copy import deepcopy
import math
from typing import Any

from sciplot_core.policy import CATEGORICAL_BAR_LINE_WIDTH_PT
from sciplot_core.rheology_tts_errors import native_error_fields
from sciplot_core.studio_core.series_encoding_contract import series_encoding_from_spec
from sciplot_core.studio_core.series_request import _veusz_literal_text
from sciplot_core.studio_core.veusz_axis_apply import _apply_key_position
from sciplot_core.studio_core.veusz_units import _alpha_to_transparency, _pt
from sciplot_core.veusz_worker.widget_bindings import _distance_matches_pt


def _field(
    value: Any,
    kind: str = "exact",
    *,
    setting: str | None = None,
    indices: tuple[int, ...] = (),
) -> dict[str, Any]:
    return {"value": value, "kind": kind, "setting": setting, "indices": indices}


def native_series_fields(
    item: dict[str, Any], panel: dict[str, Any]
) -> dict[str, dict[str, Any]]:
    """Resolve real Veusz settings from the frozen series encoding, never data."""
    errors = {
        name: _field(value, kind)
        for name, (value, kind) in native_error_fields(item).items()
    }
    if item["kind"] == "bar":
        return {**_bar_fields(item, panel), **errors}
    encoding = series_encoding_from_spec(item, style=panel["style"])
    line, marker = encoding["line"], encoding["marker"]
    return {
        "key": _field(_veusz_literal_text(item["legend_key"])),
        "hide": _field(False),
        "PlotLine/hide": _field(not line["visible"]),
        "PlotLine/color": _field(line["color"], "color"),
        "PlotLine/style": _field(line["style"], "token"),
        "PlotLine/width": _field(float(line["width_pt"]), "points"),
        "PlotLine/transparency": _field(_alpha_to_transparency(float(line["alpha"]))),
        "marker": _field(marker["shape"], "token"),
        "markerSize": _field(float(marker["size_pt"]), "points"),
        "thinfactor": _field(max(1, int(marker["thin_factor"]))),
        "MarkerFill/hide": _field(
            marker["shape"] == "none" or not marker["fill_visible"]
        ),
        "MarkerFill/color": _field(marker["fill_color"], "color"),
        "MarkerFill/transparency": _field(
            _alpha_to_transparency(float(marker["fill_alpha"]))
        ),
        "MarkerLine/hide": _field(
            marker["shape"] == "none" or not marker["line_visible"]
        ),
        "MarkerLine/color": _field(marker["line_color"], "color"),
        "MarkerLine/width": _field(float(marker["line_width_pt"]), "points"),
        "MarkerLine/transparency": _field(
            _alpha_to_transparency(float(marker["line_alpha"]))
        ),
        "ErrorBarLine/hide": _field(True),
        **errors,
    }


def _bar_fields(
    item: dict[str, Any], panel: dict[str, Any]
) -> dict[str, dict[str, Any]]:
    positions = item["x_values"]
    axis = panel["axes"]["x"]
    spacing = (
        float(axis["max"]) - float(axis["min"])
        if len(positions) == 1
        else min(abs(b - a) for a, b in zip(positions[:-1], positions[1:], strict=True))
    )
    if spacing <= 0:
        raise ValueError("Bar positions must have nonzero separation.")
    fields = {
        "keys": _field((item["legend_key"],)),
        "hide": _field(False),
        "direction": _field("vertical", "token"),
        "mode": _field("grouped", "token"),
        "barfill": _field(float(item["bar_width"]) / spacing, "number"),
        "groupfill": _field(1.0, "number"),
        "errorstyle": _field("none", "token"),
    }
    fill = (
        "solid",
        item["color"],
        False,
        0,
        CATEGORICAL_BAR_LINE_WIDTH_PT,
        "solid",
        5.0,
        "white",
        0,
        True,
    )
    outline = ("solid", CATEGORICAL_BAR_LINE_WIDTH_PT, item["color"], True)
    for setting, values, colors, points in (
        ("BarFill/fills", fill, {1, 7}, {4, 6}),
        ("BarLine/lines", outline, {2}, {1}),
    ):
        for index, value in enumerate(values):
            kind = (
                "color" if index in colors else "points" if index in points else "exact"
            )
            fields[f"{setting}[0][{index}]"] = _field(
                value, kind, setting=setting, indices=(0, index)
            )
    return fields


def native_legend_position_fields(mode: Any) -> dict[str, dict[str, Any]]:
    """Capture the shared native key-position resolver without duplicating its map."""
    fields = {}

    class Collector:
        def Set(self, name: str, value: Any) -> None:
            fields[name] = _field(value)

    _apply_key_position(Collector(), str(mode))
    return fields


def field_matches(actual: Any, field: dict[str, Any]) -> bool:
    expected, kind = field["value"], field["kind"]
    if kind == "points":
        return _distance_matches_pt(actual, expected)
    if kind == "color":
        from PyQt6.QtGui import QColor

        a, b = QColor(str(actual)), QColor(str(expected))
        if a.isValid() and b.isValid():
            return a.rgba() == b.rgba()
        return str(actual).strip().casefold() == str(expected).strip().casefold()
    if kind == "token":
        return str(actual).strip().casefold() == str(expected).strip().casefold()
    if kind == "number":
        return math.isclose(
            float(actual), float(expected), rel_tol=1e-12, abs_tol=1e-12
        )
    return actual == expected


def expected_fields_equal(first: dict[str, Any], second: dict[str, Any]) -> bool:
    actual = _pt(first["value"]) if first["kind"] == "points" else first["value"]
    return field_matches(actual, second)


def read_native_field(interface: Any, name: str, field: dict[str, Any]) -> Any:
    value = interface.Get(field["setting"] or name)
    for index in field["indices"]:
        value = value[index]
    return value


def set_native_field(interface: Any, name: str, field: dict[str, Any]) -> None:
    value = _pt(field["value"]) if field["kind"] == "points" else field["value"]
    setting = field["setting"] or name
    indices = field["indices"]
    if not indices:
        interface.Set(setting, value)
        return
    current = deepcopy(interface.Get(setting))

    def replace_at(container: Any, position: int) -> Any:
        items = list(container)
        index = indices[position]
        items[index] = (
            value
            if position + 1 == len(indices)
            else replace_at(items[index], position + 1)
        )
        return tuple(items) if isinstance(container, tuple) else items

    interface.Set(setting, replace_at(current, 0))


def audit_series_presentation(
    interface: Any, item: dict[str, Any], panel: dict[str, Any], path: str
) -> dict[str, Any]:
    fields = native_series_fields(item, panel)
    records = _audit_fields(interface, fields)
    return {
        "widget_path": path,
        "series_name": item["name"],
        "kind": item["kind"],
        "fields": records,
        "matches": all(record["matches"] for record in records),
    }


def _audit_fields(interface: Any, fields: dict) -> list[dict]:
    records = []
    for name, field in fields.items():
        actual = read_native_field(interface, name, field)
        records.append(
            {
                "field": name,
                "expected": field["value"],
                "actual": actual,
                "comparison": field["kind"],
                "matches": field_matches(actual, field),
            }
        )
    return records


def audit_legend_presentation(interface: Any, panel: dict) -> dict:
    path = f"/page1/{panel['id']}"
    expected = bool(panel["legend"])
    exists = "key1" in interface.GetChildren(path)
    records = [
        {
            "field": "exists",
            "expected": expected,
            "actual": exists,
            "comparison": "exact",
            "matches": expected == exists,
        }
    ]
    if expected and exists:
        interface.To(f"{path}/key1")
        records.extend(
            _audit_fields(
                interface,
                {
                    "hide": _field(False),
                    **native_legend_position_fields(panel["legend"]),
                },
            )
        )
    return {
        "widget_path": f"{path}/key1",
        "fields": records,
        "matches": all(record["matches"] for record in records),
    }
