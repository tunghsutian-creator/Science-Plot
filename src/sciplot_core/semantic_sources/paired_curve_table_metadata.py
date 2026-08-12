"""Read generic axis and sample metadata around paired-curve headers."""

from __future__ import annotations

import re

from sciplot_core.foundation.text_values import clean_text, token


_HEADER_UNIT_RE = re.compile(r"(?:\(([^()]*)\)|\[([^\[\]]*)\])\s*$")


def axis_match(value: object, aliases: tuple[str, ...]) -> bool:
    text = clean_text(value).casefold()
    value_token = token(value)
    for alias in aliases:
        alias_text = alias.casefold()
        alias_token = token(alias)
        if alias_text and (text == alias_text or alias_text in text):
            return True
        if alias_token and (value_token == alias_token or alias_token in value_token):
            return True
    return False


def looks_like_unit(value: object) -> bool:
    raw = clean_text(value)
    if raw == "PA":
        return False
    if "%" in raw:
        return True
    value_token = token(value)
    if not value_token:
        return False
    return value_token in {
        "c",
        "degc",
        "s",
        "sec",
        "min",
        "h",
        "pa",
        "kpa",
        "mpa",
        "gpa",
        "cm1",
        "nm1",
        "au",
        "abs",
        "degree",
        "count",
        "百分比",
        "kjm2",
        "kjm²",
        "jm",
        "j",
    } or value_token in {"", "1"}


def explicit_header_unit(value: object) -> str:
    """Return a terminal parenthesized/bracketed unit only when unit-shaped."""

    match = _HEADER_UNIT_RE.search(clean_text(value))
    if match is None:
        return ""
    candidate = clean_text(next(group for group in match.groups() if group is not None))
    return candidate if looks_like_unit(candidate) else ""


def curve_axis_unit(
    header_value: object,
    adjacent_value: object,
    *,
    header_index: int,
    unit_index: int,
    default: str,
) -> tuple[str, str, int | None, str]:
    adjacent = clean_text(adjacent_value).strip("[]")
    if adjacent:
        return adjacent, "detected_from_adjacent_unit_row", unit_index, adjacent
    header = explicit_header_unit(header_value)
    if header:
        return header, "detected_from_header", header_index, header
    return default, "default_due_to_missing_unit_row", None, ""


def preceding_pair_sample(
    value: object,
    *,
    axis_aliases: tuple[str, ...],
) -> str:
    """Return one sample label declared in the x cell above a paired header."""

    label = clean_text(value)
    if (
        not label
        or (looks_like_unit(label) and len(token(label)) <= 5)
        or axis_match(label, axis_aliases)
        or _looks_numeric(label)
    ):
        return ""
    return label


def _looks_numeric(value: str) -> bool:
    compact = value.replace("\u00a0", "").replace("\u202f", "").replace(" ", "")
    try:
        float(compact.replace(",", ""))
    except ValueError:
        return False
    return True


__all__ = [
    "axis_match",
    "curve_axis_unit",
    "explicit_header_unit",
    "looks_like_unit",
    "preceding_pair_sample",
]
