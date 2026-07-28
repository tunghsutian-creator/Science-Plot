"""Resolve Veusz color settings to concrete RGB audit records."""

from __future__ import annotations

from typing import Any

from sciplot_core.veusz_audit.measurements import _rounded


def _resolved_rgb(
    document: Any, value: object, *, widget: Any, helper: Any
) -> dict[str, Any] | None:
    name = str(value or "").strip()
    if not name:
        return None
    if name.casefold() == "auto":
        try:
            index = int(helper.autoColorIndex((widget, 0))) + 1
            name = str(document.evaluate.colors.getIndex(index))
        except Exception:
            return None
    try:
        color = document.evaluate.colors.get(name)
    except Exception:
        return None
    if color is None or not color.isValid():
        return None
    rgb = [_rounded(color.redF()), _rounded(color.greenF()), _rounded(color.blueF())]
    return {
        "source": str(value),
        "resolved_name": name,
        "hex": color.name().upper(),
        "rgb": rgb,
        "alpha": _rounded(color.alphaF()),
    }


def _group_color(
    document: Any, group: Any, *, widget: Any, helper: Any
) -> dict[str, Any] | None:
    setting = group.setdict.get("color") if group is not None else None
    return (
        _resolved_rgb(document, setting.val, widget=widget, helper=helper)
        if setting is not None
        else None
    )
