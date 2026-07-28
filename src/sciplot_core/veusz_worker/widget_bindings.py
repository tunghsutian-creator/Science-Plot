"""Inspect visible Veusz widgets, settings, and dataset bindings."""

from __future__ import annotations

import math
import re
from typing import Any
from sciplot_core.policy import (
    UNIFIED_LINE_WIDTH_PT,
    UNIFIED_MARKER_LINE_WIDTH_PT,
    UNIFIED_MARKER_SIZE_PT,
)
from sciplot_core.veusz_worker.numeric_evidence import (
    _exact_numeric_token,
)


def _node_is_visible(node: Any) -> bool:
    ancestor = node
    while ancestor is not None:
        settings = getattr(ancestor, "settings", None)
        setting_map = getattr(settings, "setdict", {})
        hide = setting_map.get("hide")
        if hide is not None and bool(hide.val):
            return False
        ancestor = getattr(ancestor, "parent", None)
    return True


def _setting_value(settings: Any, path: str, default: Any = None) -> Any:
    current = settings
    parts = path.split("/")
    for index, part in enumerate(parts):
        setting_map = getattr(current, "setdict", {})
        item = setting_map.get(part)
        if item is None:
            return default
        if index == len(parts) - 1:
            return getattr(item, "val", default)
        current = item
    return default


def _distance_is_positive(value: object) -> bool:
    if isinstance(value, int | float):
        return math.isfinite(float(value)) and float(value) > 0.0
    match = re.search(
        r"[-+]?(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][-+]?\d+)?",
        str(value or ""),
    )
    if match is None:
        # A live Veusz reference resolves to a positive stylesheet default.
        return bool(value)
    return float(match.group(0)) > 0.0


def _distance_matches_mm(value: object, expected_mm: object) -> bool:
    match = re.fullmatch(
        r"\s*([-+]?(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][-+]?\d+)?)"
        r"\s*(mm|cm|in|pt)\s*",
        str(value or ""),
        flags=re.IGNORECASE,
    )
    if match is None:
        return False
    factors = {
        "mm": 1.0,
        "cm": 10.0,
        "in": 25.4,
        "pt": 25.4 / 72.0,
    }
    actual_mm = float(match.group(1)) * factors[match.group(2).casefold()]
    try:
        expected = float(expected_mm)
    except (TypeError, ValueError):
        return False
    return math.isclose(
        actual_mm,
        expected,
        rel_tol=0.0,
        abs_tol=1e-9,
    )


def _distance_matches_pt(value: object, expected_pt: object) -> bool:
    try:
        expected_mm = float(expected_pt) * 25.4 / 72.0
    except (TypeError, ValueError):
        return False
    return _distance_matches_mm(value, expected_mm)


def _style_channel_visible(settings: Any, group: str) -> bool:
    return (
        _setting_value(settings, f"{group}/hide", False) is not True
        and int(_setting_value(settings, f"{group}/transparency", 0) or 0) < 100
    )


def _visible_mark_channels(node: Any) -> list[str]:
    settings = getattr(node, "settings", None)
    widget_type = str(getattr(node, "typename", ""))
    channels: list[str] = []
    if widget_type == "xy":
        if _style_channel_visible(settings, "PlotLine") and _distance_is_positive(
            _setting_value(
                settings,
                "PlotLine/width",
                f"{UNIFIED_LINE_WIDTH_PT:g}pt",
            )
        ):
            channels.append("line")
        marker = str(_setting_value(settings, "marker", "none") or "none")
        marker_visible = (
            marker != "none"
            and _distance_is_positive(
                _setting_value(
                    settings,
                    "markerSize",
                    f"{UNIFIED_MARKER_SIZE_PT:g}pt",
                )
            )
            and (
                _style_channel_visible(settings, "MarkerFill")
                or (
                    _style_channel_visible(settings, "MarkerLine")
                    and _distance_is_positive(
                        _setting_value(
                            settings,
                            "MarkerLine/width",
                            f"{UNIFIED_MARKER_LINE_WIDTH_PT:g}pt",
                        )
                    )
                )
            )
        )
        if marker_visible:
            channels.append("marker")
        for group, channel in (
            ("FillBelow", "fill_below"),
            ("FillAbove", "fill_above"),
        ):
            if _style_channel_visible(settings, group):
                channels.append(channel)
    elif widget_type == "boxplot":
        fill_fraction = float(_setting_value(settings, "fillfraction", 0.0) or 0.0)
        if fill_fraction > 0.0 and _style_channel_visible(settings, "Fill"):
            channels.append("box_fill")
        for group, channel in (
            ("Border", "box_border"),
            ("Whisker", "box_whisker"),
        ):
            if _style_channel_visible(settings, group) and _distance_is_positive(
                _setting_value(
                    settings,
                    f"{group}/width",
                    f"{UNIFIED_LINE_WIDTH_PT:g}pt",
                )
            ):
                channels.append(channel)
    elif widget_type == "image":
        if int(_setting_value(settings, "transparency", 0) or 0) < 100:
            channels.append("image")
    return channels


def _normalized_setting_value(value: Any) -> Any:
    if isinstance(value, list | tuple):
        return [
            float(item) if isinstance(item, int | float) else str(item)
            for item in value
        ]
    if isinstance(value, int | float):
        return float(value)
    return str(value or "")


def _settings_snapshot(settings: Any, *, prefix: str = "") -> dict[str, Any]:
    snapshot: dict[str, Any] = {}
    for name, item in getattr(settings, "setdict", {}).items():
        path = f"{prefix}/{name}" if prefix else str(name)
        nested = getattr(item, "setdict", None)
        if isinstance(nested, dict):
            snapshot.update(_settings_snapshot(item, prefix=path))
        else:
            snapshot[path] = _normalized_setting_value(getattr(item, "val", None))
    return snapshot


def _dataset_setting_bindings(settings: Any, *, prefix: str = "") -> dict[str, Any]:
    bindings: dict[str, Any] = {}
    for name, item in getattr(settings, "setdict", {}).items():
        path = f"{prefix}/{name}" if prefix else str(name)
        nested = getattr(item, "setdict", None)
        if isinstance(nested, dict):
            bindings.update(_dataset_setting_bindings(item, prefix=path))
            continue
        setting_type = str(getattr(item, "typename", ""))
        if not setting_type.startswith("dataset"):
            continue
        value = getattr(item, "val", None)
        normalized = _normalized_setting_value(value)
        if normalized is None or normalized == "" or normalized == []:
            continue
        bindings[path] = normalized
    return bindings


def _visible_data_bindings(
    loaded_document: Any,
    *,
    widget_type: str,
    setting_names: tuple[str, ...],
) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []

    def collect(path: str, node: Any) -> None:
        if str(getattr(node, "typename", "")) != widget_type:
            return
        if not _node_is_visible(node):
            return
        settings = getattr(node, "settings", None)
        bindings: dict[str, Any] = {}
        for setting_name in setting_names:
            bindings[setting_name] = _normalized_setting_value(
                _setting_value(settings, setting_name)
            )
        records.append(
            {
                "path": str(path),
                "name": str(getattr(node, "name", "")),
                "bindings": bindings,
                "dataset_bindings": _dataset_setting_bindings(settings),
                "mark_channels": _visible_mark_channels(node),
            }
        )

    loaded_document.walkNodes(collect, nodetypes=("widget",))
    return records


def _numeric_setting_equal(actual: object, expected: object) -> bool:
    if expected is None:
        return str(actual or "").strip().casefold() in {
            "",
            "auto",
            "none",
        }
    try:
        return _exact_numeric_token(actual) == _exact_numeric_token(expected)
    except (TypeError, ValueError):
        return False


def _numeric_sequence_equal(actual: object, expected: object) -> bool:
    actual_values = actual if isinstance(actual, list | tuple) else []
    expected_values = expected if isinstance(expected, list | tuple) else []
    if len(actual_values) != len(expected_values):
        return False
    return all(
        _numeric_setting_equal(actual_value, expected_value)
        for actual_value, expected_value in zip(
            actual_values,
            expected_values,
            strict=True,
        )
    )
