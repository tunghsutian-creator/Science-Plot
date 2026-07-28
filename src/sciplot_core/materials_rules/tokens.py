"""Normalize scientific labels and match metric headers without domain side effects."""

from __future__ import annotations

import re
from sciplot_core.foundation.text_values import token as _utils_token


def normalize_token(value: object) -> str:
    result = _utils_token(value)
    return result or "\ufffd"


def _metric_header_matches(value: object, tokens: tuple[str, ...]) -> bool:
    header = normalize_token(value)
    for token in tokens:
        normalized = normalize_token(token)
        if not normalized or normalized == "\ufffd":
            continue
        if len(normalized) < 3:
            if header == normalized or re.fullmatch(
                rf"{re.escape(normalized)}\d+",
                header,
            ):
                return True
        elif normalized in header:
            return True
    return False
