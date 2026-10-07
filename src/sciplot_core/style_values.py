"""Pure physical-size grammar shared by ingress and native style validation."""

import math
import re
from typing import Any


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
