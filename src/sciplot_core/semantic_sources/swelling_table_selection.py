"""Select one structurally labeled swelling table without ranking its data."""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

import pandas as pd

from sciplot_core.foundation.text_values import clean_text as _clean_text
from sciplot_core.foundation.text_values import token as _token
from sciplot_core.semantic_sources.table_scanning import _axis_match
from sciplot_core.semantic_sources.table_source_files import is_workbook_source
from sciplot_core.source_tables import read_raw_table


_SWELLING_RESPONSE_HEADER = re.compile(
    r"^(?P<quantity>swelling\s+ratio|ai\s*/\s*a0|"
    r"normalized\s+projected\s+area)"
    r"(?:\s*(?:\((?P<paren>1|unitless|dimensionless)\)|"
    r"\[(?P<bracket>1|unitless|dimensionless)\]))?$",
    flags=re.IGNORECASE,
)

_TIME_UNIT_ALIASES = (
    ("s", frozenset({"s", "sec", "secs", "second", "seconds"})),
    ("min", frozenset({"min", "mins", "minute", "minutes"})),
    ("h", frozenset({"h", "hr", "hrs", "hour", "hours"})),
)


@dataclass(frozen=True)
class _LabeledSwellingTable:
    name: str
    raw: pd.DataFrame
    header_index: int
    pairs: tuple[tuple[int, int], ...]
    sample_column: int | None


def _canonical_time_unit(value: str) -> str | None:
    normalized = value.strip().casefold().replace("µ", "u")
    return next(
        (unit for unit, aliases in _TIME_UNIT_ALIASES if normalized in aliases),
        None,
    )


def _time_header_unit_evidence(value: object) -> tuple[str, str]:
    """Parse only the registered ``Time`` title and one exact unit suffix."""

    text = _clean_text(value)
    if text.casefold() == "time":
        return "missing", ""
    wrapped = re.fullmatch(
        r"time\s*(?:\(([^()]*)\)|\[([^\[\]]*)\])",
        text,
        flags=re.IGNORECASE,
    )
    naked = re.fullmatch(r"time\s+(\S+)", text, flags=re.IGNORECASE)
    match = wrapped or naked
    if match is None:
        return "unsupported", text
    declaration = next(group for group in match.groups() if group is not None)
    canonical = _canonical_time_unit(declaration)
    if canonical is None:
        return "unsupported", text
    return "supported", canonical


def _adjacent_time_unit_evidence(value: object) -> tuple[str, str]:
    """Accept only a pure unit token (optionally enclosed in brackets)."""

    text = _clean_text(value)
    if not text:
        return "missing", ""
    wrapped = re.fullmatch(r"\(([^()]*)\)|\[([^\[\]]*)\]", text)
    declaration = (
        next(group for group in wrapped.groups() if group is not None)
        if wrapped is not None
        else text
    )
    canonical = _canonical_time_unit(declaration)
    if canonical is None:
        return "missing", ""
    return "supported", canonical


def _swelling_time_conversion(
    header: object,
    adjacent_unit: object = None,
) -> tuple[str, float]:
    header_state, header_value = _time_header_unit_evidence(header)
    adjacent_state, adjacent_value = _adjacent_time_unit_evidence(adjacent_unit)
    for state, value in (
        (header_state, header_value),
        (adjacent_state, adjacent_value),
    ):
        if state in {"ambiguous", "unsupported"}:
            raise ValueError(
                f"Swelling time unit evidence {value!r} is {state}; expected "
                "s, min, or h."
            )
    evidence = tuple(
        value
        for state, value in (
            (header_state, header_value),
            (adjacent_state, adjacent_value),
        )
        if state == "supported"
    )
    if len(set(evidence)) > 1:
        raise ValueError(
            "Swelling time unit evidence conflicts between the selected header "
            "and adjacent unit row."
        )
    if not evidence:
        raise ValueError(
            "Swelling time unit is missing or unsupported in header "
            f"`{_clean_text(header)}`; expected s, min, or h."
        )
    source_unit = evidence[0]
    factors = {"s": 1.0 / 3600.0, "min": 1.0 / 60.0, "h": 1.0}
    return source_unit, factors[source_unit]


def _header_candidate(
    name: str,
    raw: pd.DataFrame,
    header_index: int,
) -> _LabeledSwellingTable | None:
    headers = raw.iloc[header_index].tolist()
    time_columns = [
        index for index, header in enumerate(headers) if _axis_match(header, ("time",))
    ]
    pairs: list[tuple[int, int]] = []
    for position, x_index in enumerate(time_columns):
        stop = (
            time_columns[position + 1]
            if position + 1 < len(time_columns)
            else raw.shape[1]
        )
        responses = [
            y_index
            for y_index in range(x_index + 1, stop)
            if _swelling_response_header_match(headers[y_index])
        ]
        if len(responses) > 1:
            raise ValueError(
                f"Swelling source table {name!r} has multiple response headers "
                "for one labeled Time column."
            )
        if responses:
            pairs.append((x_index, responses[0]))
    if not pairs:
        return None
    sample_column = next(
        (
            index
            for index, value in enumerate(headers)
            if _token(value) in {"sample", "samplename"}
        ),
        None,
    )
    return _LabeledSwellingTable(
        name=name,
        raw=raw,
        header_index=header_index,
        pairs=tuple(pairs),
        sample_column=sample_column,
    )


def _swelling_response_unit_evidence(
    header: object,
    adjacent_unit: object = None,
) -> dict[str, str]:
    header_text = _clean_text(header)
    adjacent_text = _clean_text(adjacent_unit)
    header_match = _SWELLING_RESPONSE_HEADER.fullmatch(header_text)
    if header_match is None:
        raise ValueError(
            f"Swelling response header {header_text!r} is not an explicit "
            "supported swelling-ratio quantity."
        )
    adjacent_token = _token(adjacent_text)
    if adjacent_text and adjacent_token not in {"1", "unitless", "dimensionless"}:
        raise ValueError(
            f"Swelling response has unsupported adjacent unit {adjacent_text!r}; "
            "expected dimensionless identity."
        )
    header_unit = next(
        (
            value
            for value in (header_match.group("paren"), header_match.group("bracket"))
            if value is not None
        ),
        "",
    )
    explicit = bool(header_unit or adjacent_token)
    return {
        "source_unit": "1",
        "canonical_unit": "1",
        "method": (
            "explicit_dimensionless_declaration"
            if explicit
            else "selected_dimensionless_ratio_quantity_identity"
        ),
        "value": adjacent_text if adjacent_token else (header_unit or header_text),
        "quantity": _clean_text(header_match.group("quantity")),
    }


def _is_explicit_swelling_unit_row(
    *,
    x_header: object,
    y_header: object,
    x_cell: object,
    y_cell: object,
) -> bool:
    """Recognize only a complete adjacent time/ratio unit declaration."""

    if _adjacent_time_unit_evidence(x_cell)[0] != "supported" or _token(
        y_cell
    ) not in {
        "1",
        "unitless",
        "dimensionless",
    }:
        return False
    _swelling_time_conversion(x_header, x_cell)
    _swelling_response_unit_evidence(y_header, y_cell)
    return True


def _matching_tables(source: Path) -> list[_LabeledSwellingTable]:
    if is_workbook_source(source):
        with pd.ExcelFile(source) as workbook:
            raw_tables = [
                (
                    f"{source.stem}:{sheet_name}",
                    workbook.parse(
                        sheet_name,
                        header=None,
                        keep_default_na=False,
                    ),
                )
                for sheet_name in workbook.sheet_names
            ]
    else:
        raw_tables = [
            (
                source.stem,
                read_raw_table(source, preserve_na_tokens=True),
            )
        ]
    matches: list[_LabeledSwellingTable] = []
    for name, raw in raw_tables:
        candidates = [
            candidate
            for row_index in range(raw.shape[0])
            if (candidate := _header_candidate(name, raw, row_index)) is not None
        ]
        if len(candidates) > 1:
            raise ValueError(
                f"Swelling source table {name!r} contains {len(candidates)} "
                "matching labeled headers; exactly one is required."
            )
        matches.extend(candidates)
    return matches


def _swelling_response_header_match(value: object) -> bool:
    return _SWELLING_RESPONSE_HEADER.fullmatch(_clean_text(value)) is not None


__all__ = [
    "_LabeledSwellingTable",
    "_is_explicit_swelling_unit_row",
    "_matching_tables",
    "_swelling_response_unit_evidence",
    "_swelling_time_conversion",
]
