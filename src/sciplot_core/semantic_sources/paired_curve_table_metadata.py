"""Read generic axis and sample metadata around paired-curve headers."""

from __future__ import annotations

import re

from sciplot_core.foundation.text_values import clean_text, token
from sciplot_core.materials_rules.unit_formatting import (
    looks_like_unit_expression,
)


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
    if looks_like_unit_expression(raw):
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
        "counts",
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
    paired_value: object,
    *,
    axis_aliases: tuple[str, ...],
) -> str:
    """Return one sample label declared only in the x cell above a pair."""

    label = clean_text(value)
    if (
        not label
        or clean_text(paired_value)
        or _is_axis_header(label, axis_aliases)
        or _looks_numeric(label)
    ):
        return ""
    return label


def resolve_adjacent_pair_row_roles(
    rows: tuple[tuple[int, tuple[object, ...]], ...],
    *,
    pairs: tuple[tuple[int, int], ...],
    axis_aliases: tuple[str, ...],
) -> tuple[int | None, int | None, dict[int, str]]:
    """Resolve distinct unit/sample rows from paired-column structure."""

    sample_rows: dict[int, dict[int, str]] = {}
    unit_rows: list[int] = []
    for row_index, values in rows:
        samples = {
            x_index: _adjacent_pair_sample(
                values[x_index],
                values[y_index],
                axis_aliases=axis_aliases,
            )
            for x_index, y_index in pairs
        }
        if samples and all(samples.values()):
            sample_rows[row_index] = samples
        cells = tuple(values[column] for pair in pairs for column in pair)
        nonempty_cells = tuple(cell for cell in cells if clean_text(cell))
        if (
            nonempty_cells
            and not all(_looks_numeric(clean_text(cell)) for cell in nonempty_cells)
            and any(looks_like_unit(cell) for cell in nonempty_cells)
        ):
            unit_rows.append(row_index)

    assignments = [
        (unit_row, sample_row)
        for unit_row in unit_rows
        for sample_row in sample_rows
        if unit_row != sample_row
    ]
    if len(assignments) > 1:
        raise ValueError("Ambiguous adjacent paired-curve unit/sample row roles.")
    if len(assignments) == 1:
        unit_row, sample_row = assignments[0]
        return unit_row, sample_row, sample_rows[sample_row]
    if set(unit_rows).intersection(sample_rows):
        raise ValueError("Ambiguous adjacent paired-curve unit/sample row roles.")
    if len(unit_rows) > 1 or len(sample_rows) > 1:
        raise ValueError("Ambiguous adjacent paired-curve unit/sample row roles.")
    unit_row = unit_rows[0] if unit_rows else None
    sample_row = next(iter(sample_rows), None)
    return unit_row, sample_row, sample_rows.get(sample_row, {})


def _adjacent_pair_sample(
    value: object,
    paired_value: object,
    *,
    axis_aliases: tuple[str, ...],
) -> str:
    label = clean_text(value)
    if (
        not label
        or label != clean_text(paired_value)
        or _is_axis_header(label, axis_aliases)
        or _looks_numeric(label)
    ):
        return ""
    return label


def _is_axis_header(value: object, aliases: tuple[str, ...]) -> bool:
    value_token = token(value)
    return bool(value_token) and any(
        value_token == token(alias) for alias in aliases if token(alias)
    )


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
    "resolve_adjacent_pair_row_roles",
]
