"""Convert Veusz geometry and distance settings to stable physical measurements."""

from __future__ import annotations

from typing import Any


def _rounded(value: object, digits: int = 6) -> float:
    return round(float(value), digits)


def _bounds_mm(bounds: object, *, dpi: float = 72.0) -> list[float] | None:
    if not isinstance(bounds, tuple | list) or len(bounds) != 4:
        return None
    return [_rounded(float(value) / dpi * 25.4) for value in bounds]


def _setting_hidden(settings: Any) -> bool:
    hide = settings.setdict.get("hide")
    transparency = settings.setdict.get("transparency")
    return bool(hide is not None and hide.val) or bool(
        transparency is not None and float(transparency.val) >= 100.0
    )


def _distance_pt(setting: Any, helper: Any) -> float | None:
    try:
        from veusz.setting import Distance

        if not isinstance(setting, Distance):
            return None
        points = Distance.convertDistance(helper, str(setting.val)) / float(
            helper.pixperpt
        )
    except (TypeError, ValueError, ZeroDivisionError):
        return None
    return _rounded(points)


def _distance_value_pt(value: object, helper: Any) -> float | None:
    try:
        from veusz.setting import Distance

        points = Distance.convertDistance(helper, str(value)) / float(helper.pixperpt)
    except (TypeError, ValueError, ZeroDivisionError):
        return None
    return _rounded(points)
