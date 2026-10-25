"""Pure style values shared by semantic contracts and native style validation."""

import math
import re
from typing import Any

from sciplot_core.policy.frame_export import DEFAULT_LINE_STYLE_SEQUENCE


_LINE_STYLE_ALIASES = {"dash": "dashed", "dot": "dotted"}
LINE_STYLE_VALUES = (*DEFAULT_LINE_STYLE_SEQUENCE, *_LINE_STYLE_ALIASES)


def normalize_line_style(value: Any) -> str:
    """Use the existing visible native patterns, retaining historical IR aliases."""
    if not isinstance(value, str):
        raise ValueError("Use a supported visible line style.")
    pattern = _LINE_STYLE_ALIASES.get(value, value)
    if pattern not in DEFAULT_LINE_STYLE_SEQUENCE:
        raise ValueError("Use a supported visible line style.")
    return pattern


PHYSICAL_SIZE_UNITS = ("pt", "mm", "cm", "in", "inch")
_PHYSICAL_SIZE = re.compile(r"\s*(\d+(?:\.\d*)?|\.\d+)\s*(pt|mm|cm|in|inch)\s*")


def normalize_physical_size(value: Any) -> str:
    """Remove accepted whitespace only; retain the exact numeric lexeme and unit."""
    match = _PHYSICAL_SIZE.fullmatch(str(value))
    if match is None or not 0 < float(match[1]) < math.inf:
        raise ValueError("Use a positive physical size with pt, mm, cm, in or inch, such as 0.7pt.")
    return match[1] + match[2]


def validate_physical_size(value: Any) -> None:
    normalize_physical_size(value)


def physical_size_points(value: str) -> float:
    """Resolve a validated physical size with the existing exact unit factors."""
    normalized = normalize_physical_size(value)
    match = re.fullmatch(r"([0-9.]+)(pt|mm|cm|in|inch)", normalized)
    assert match is not None
    return float(match[1]) * {"pt": 1, "mm": 72 / 25.4, "cm": 72 / 2.54, "in": 72, "inch": 72}[match[2]]


def managed_color(value: str) -> str:
    """Resolve the existing v1 Managed names/hex contract, without native IO."""
    from sciplot_core.plot_document.errors import fail

    colors = {"black": "#000000", "white": "#ffffff", "red": "#ff0000", "blue": "#0000ff",
              "green": "#008000", "gray": "#808080", "grey": "#808080", "yellow": "#ffff00"}
    result = colors.get(value.casefold(), value)
    if not re.fullmatch(r"#[0-9a-fA-F]{6}([0-9a-fA-F]{2})?", result):
        fail("managed_color_unresolved", "Use an explicit hexadecimal color in the managed theme.", "/presentation/objects", "resolved_color")
    return result.lower()
