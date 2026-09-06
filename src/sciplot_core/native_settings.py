"""Materialize the shared native catalog and validate optimistic setting edits."""

from __future__ import annotations

import math
import re
from typing import Any

from sciplot_core.foundation.json_values import json_safe
from sciplot_core.setting_catalog import specs_for_object_type

# This is an authority subset, not a second field catalog. Labels, types and
# limits continue to come from the same specs used by the native inspector.
_SAFE_SUFFIXES = {
    "axis": frozenset({"Label/size", "Label/bold", "TickLabels/size"}),
    "xy": frozenset({"PlotLine/color", "PlotLine/width"}),
    "key": frozenset({
        "Text/size", "columns", "horzPosn", "vertPosn", "horzManual", "vertManual",
    }),
}


def _ordinary_curve(document: Any, widget: Any) -> bool:
    def value(suffix: str) -> Any:
        return document.resolveSettingPath(None, f"{widget.path}/{suffix}").get()

    try:
        if not value("xData") or not value("yData") or value("Color/points"):
            return False
        return not any(
            str(getattr(child, "typename", "")) == "colorbar"
            for child in getattr(getattr(widget, "parent", None), "children", [])
        )
    except (ValueError, AttributeError):
        return False


def editable_fields(
    document: Any, widget: Any, *, safe_only: bool = False
) -> list[dict[str, Any]]:
    """Return native values and editor metadata without importing Qt or a GUI."""
    object_type = str(widget.typename)
    allowed = _SAFE_SUFFIXES.get(object_type, frozenset())
    if safe_only and object_type == "xy" and not _ordinary_curve(document, widget):
        allowed = frozenset()
    fields: list[dict[str, Any]] = []
    for spec in specs_for_object_type(object_type):
        if spec.read_only or (safe_only and spec.suffix not in allowed):
            continue
        path = f"{widget.path}/{spec.suffix}"
        try:
            setting = document.resolveSettingPath(None, path)
        except ValueError:
            continue
        fields.append({
            "field_id": spec.field_id, "section": spec.section, "label": spec.label,
            "setting_path": path, "editor": spec.editor,
            "current_value": json_safe(setting.get()),
            "choices": [str(choice) for choice in getattr(setting, "vallist", ())],
            "minimum": spec.minimum, "maximum": spec.maximum,
            "help_text": spec.help_text or str(getattr(setting, "descr", "") or ""),
        })
    return fields


def _bounded_style_value(capability: dict[str, Any], value: Any) -> None:
    editor = capability["editor"]
    if editor == "boolean" and not isinstance(value, bool):
        raise ValueError("A boolean setting requires true or false.")
    if editor in {"integer", "number"}:
        if isinstance(value, bool) or not isinstance(value, int | float):
            raise ValueError("A numeric setting requires a finite number.")
        if not math.isfinite(value) or (editor == "integer" and int(value) != value):
            raise ValueError("The numeric setting value is invalid.")
        for bound, sign in (("minimum", -1), ("maximum", 1)):
            limit = capability.get(bound)
            if limit is not None and sign * value > sign * limit:
                raise ValueError(f"The setting exceeds its {bound}.")
    elif editor == "choice" and value not in capability["choices"]:
        raise ValueError("The setting value is outside its advertised choices.")
    elif editor == "distance":
        match = re.fullmatch(r"\s*(\d+(?:\.\d*)?|\.\d+)\s*(pt|mm|cm|in|inch)\s*", str(value))
        if match is None or not 0 < float(match[1]) < math.inf:
            raise ValueError("Use a positive physical size, such as 8pt or 0.3mm.")
    elif editor == "color":
        from PyQt6.QtGui import QColor

        color = QColor(value) if isinstance(value, str) else QColor()
        if not color.isValid() or color.alpha() != 255:
            raise ValueError("Use an opaque native color name or RGB hex value.")


def validate_native_setting(
    document: Any, capability: dict[str, Any], *, expected_value: Any,
    value: Any, safe_only: bool = False,
) -> tuple[Any, Any]:
    """Check the exact advertised value before native normalization; never mutate."""
    path = str(capability["setting_path"])
    setting = document.resolveSettingPath(None, path)
    current = json_safe(setting.get())
    if current != json_safe(expected_value) or current != capability["current_value"]:
        raise ValueError(f"{path} no longer has its expected value")
    if safe_only:
        _bounded_style_value(capability, value)
    return current, setting.normalize(value)
