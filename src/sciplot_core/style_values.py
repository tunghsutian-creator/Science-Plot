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
