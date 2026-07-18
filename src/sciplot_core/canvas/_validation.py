from __future__ import annotations

import math
from typing import Any


def reject_unknown_keys(
    payload: dict[str, Any],
    allowed: set[str],
    *,
    label: str,
) -> None:
    unexpected = [key for key in payload if key not in allowed]
    if unexpected:
        raise ValueError(f"{label} contains unsupported fields: {unexpected!r}")


def require_json_object(value: Any, *, label: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise ValueError(f"{label} must be an object.")
    return value


def require_json_list(value: Any, *, label: str) -> list[Any]:
    if not isinstance(value, list):
        raise ValueError(f"{label} must be a list.")
    return value


def require_json_bool(value: Any, *, label: str) -> bool:
    if type(value) is not bool:
        raise ValueError(f"{label} must be a boolean.")
    return value


def require_json_int(value: Any, *, label: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise ValueError(f"{label} must be an integer.")
    return value


def require_json_number(value: Any, *, label: str) -> float:
    if isinstance(value, bool) or not isinstance(value, int | float):
        raise ValueError(f"{label} must be a number.")
    number = float(value)
    if not math.isfinite(number):
        raise ValueError(f"{label} must be finite.")
    return number


__all__ = [
    "reject_unknown_keys",
    "require_json_bool",
    "require_json_int",
    "require_json_list",
    "require_json_number",
    "require_json_object",
]
