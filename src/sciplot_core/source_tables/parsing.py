"""Provide validation and coercion primitives for structured source tables."""

from __future__ import annotations

import math
import re
from typing import Any

import pandas as pd

SOURCE_NUMERIC_ENCODING_KEY = "source_numeric_encoding"
DECIMAL_ROUND_TRIP_ENCODING_V1 = "decimal_float64_round_trip_v1"
DECIMAL_ROUND_TRIP_ENCODING = "decimal_float64_round_trip_v2"
_DECIMAL = re.compile(r"[ \t\r\n\v\f]*([+-]?)([0-9]*)(?:\.([0-9]*))?(?:[eE]([ \t\r\n\v\f]*[+-]?[0-9]+))?[ \t\r\n\v\f]*\Z")
_POWERS_OF_TEN = tuple(float(f"1e{index}") for index in range(309))


def normalize_cell(value: Any) -> str:
    if value is None or isinstance(value, float) and pd.isna(value):
        return ""
    return str(value).strip()


def has_content(value: Any) -> bool:
    return normalize_cell(value) != ""


def row_has_content(row: pd.Series) -> bool:
    return any(has_content(value) for value in row.tolist())


def drop_fully_empty_columns(raw: pd.DataFrame) -> pd.DataFrame:
    keep_columns = [index for index in raw.columns if row_has_content(raw[index])]
    if not keep_columns:
        return raw.iloc[:, 0:0].copy()
    return raw.loc[:, keep_columns].copy()


def ensure_minimum_rows(
    raw: pd.DataFrame,
    minimum_rows: int,
    *,
    table_name: str,
) -> None:
    if raw.shape[0] < minimum_rows:
        raise ValueError(f"{table_name} must include at least {minimum_rows} rows.")


def ensure_header_row_content(
    raw: pd.DataFrame,
    row_index: int,
    *,
    row_name: str,
    table_name: str,
) -> None:
    if not row_has_content(raw.iloc[row_index]):
        raise ValueError(f"{table_name} is missing a valid {row_name}.")


def coerce_numeric_pair(
    pair: pd.DataFrame,
    *,
    column_numbers: tuple[int, int],
    table_name: str,
) -> pd.DataFrame:
    numeric_pair = pair.apply(coerce_numeric_series)
    has_x_values = numeric_pair.iloc[:, 0].notna().any()
    has_y_values = numeric_pair.iloc[:, 1].notna().any()
    if has_x_values != has_y_values:
        raise ValueError(
            f"{table_name} columns {column_numbers[0]} and {column_numbers[1]} "
            "must contain matching X/Y numeric data."
        )
    if not has_x_values and not has_y_values:
        mapped = (
            pair.map(has_content)
            if hasattr(pair, "map")
            else pair.applymap(has_content)
        )
        if bool(mapped.to_numpy().any()):
            raise ValueError(
                f"{table_name} columns {column_numbers[0]} and {column_numbers[1]} "
                "contain non-numeric values in the data region."
            )
        return numeric_pair.iloc[0:0].copy()
    numeric_pair.columns = ["x", "y"]
    numeric_pair = numeric_pair.dropna(how="all").dropna(subset=["x", "y"])
    if numeric_pair.empty:
        raise ValueError(
            f"{table_name} columns {column_numbers[0]} and {column_numbers[1]} "
            "contain incomplete X/Y rows."
        )
    return numeric_pair.reset_index(drop=True)


def coerce_numeric_series(values: pd.Series, *, encoding: str = DECIMAL_ROUND_TRIP_ENCODING,
                          compatibility_fused_digits: bool | None = True) -> pd.Series:
    """Round accepted decimal cells exactly; v2 refuses embedded NUL text.

    Sealed v1 keeps its original grammar, including the old NUL-prefix result.
    Neither encoding delegates recognition or decimal rounding to ambient pandas.
    The compatibility order affects only v1's old fallback; None reconstructs
    its later strict grammar. Valid ordinary decimals always round exactly.
    """
    if encoding not in (DECIMAL_ROUND_TRIP_ENCODING_V1, DECIMAL_ROUND_TRIP_ENCODING):
        raise ValueError("Unknown managed source numeric encoding.")
    return _coerce_numeric_series(values, encoding=encoding, fused_digits=None, compatibility_fused_digits=compatibility_fused_digits)


def coerce_legacy_numeric_series(values: pd.Series, *, fused_digits: bool = True) -> pd.Series:
    """Reconstruct the pre-versioned 17-digit parser, never current creation."""
    return _coerce_numeric_series(values, encoding=DECIMAL_ROUND_TRIP_ENCODING_V1, fused_digits=fused_digits)


def coerce_frame_numeric_series(values: pd.Series, frame: pd.DataFrame) -> pd.Series:
    if frame.attrs.get("sciplot_legacy_numeric_parser") is True:
        return coerce_legacy_numeric_series(values, fused_digits=frame.attrs.get("sciplot_legacy_fused_digits", True))
    return coerce_numeric_series(values, encoding=frame.attrs.get(SOURCE_NUMERIC_ENCODING_KEY, DECIMAL_ROUND_TRIP_ENCODING),
                                 compatibility_fused_digits=frame.attrs.get("sciplot_legacy_fused_digits", True))


def _coerce_numeric_series(values: pd.Series, *, encoding: str, fused_digits: bool | None,
                           compatibility_fused_digits: bool | None = True) -> pd.Series:
    if pd.api.types.is_numeric_dtype(values.dtype):
        return pd.to_numeric(values, errors="coerce")
    prepared = [_numeric_text(value, encoding=encoding, fused_digits=fused_digits,
                              compatibility_fused_digits=compatibility_fused_digits) for value in values]
    numeric = pd.to_numeric(pd.Series(prepared, index=values.index, name=values.name, dtype=object), errors="coerce")
    if pd.api.types.is_float_dtype(numeric.dtype):
        numeric = pd.Series([
            _numeric_text(value, encoding=encoding, fused_digits=fused_digits,
                          compatibility_fused_digits=compatibility_fused_digits, floating=True)
            if isinstance(value, (str, bytes)) else number
            for value, number in zip(values, numeric, strict=True)
        ], index=values.index, name=values.name, dtype=numeric.dtype)
    if isinstance(values.dtype, pd.StringDtype) and values.dtype.na_value is pd.NA:
        nullable = {"i": "Int64", "u": "UInt64", "f": "Float64"}.get(numeric.dtype.kind)
        if nullable:
            numeric = numeric.astype(nullable)
    return numeric


def _numeric_text(value: Any, *, encoding: str, fused_digits: bool | None,
                   compatibility_fused_digits: bool | None = True, floating: bool = False) -> Any:
    if not isinstance(value, (str, bytes)):
        return value
    if isinstance(value, bytes):
        try:
            value = value.decode("ascii")
        except UnicodeDecodeError:
            return math.nan
    if "\x00" in value:
        if encoding == DECIMAL_ROUND_TRIP_ENCODING or compatibility_fused_digits is None:
            return math.nan
        token = value.partition("\x00")[0]
    else:
        token = value
    match = _DECIMAL.fullmatch(token)
    if match is None or not (match[2] or match[3]):
        return float(token) if token.casefold() in {"inf", "+inf", "-inf", "infinity", "+infinity", "-infinity"} else math.nan
    if not floating and "." not in token and "e" not in token.casefold() and "\x00" not in value:
        magnitude = token.strip().lstrip("+-").lstrip("0") or "0"
        if len(magnitude) <= 20:
            integer = int(magnitude) * (-1 if token.strip().startswith("-") else 1)
            if -(2**63) <= integer < 2**64:
                return integer
    if fused_digits is not None:
        return _legacy_decimal(match, fused_digits=fused_digits)
    if encoding == DECIMAL_ROUND_TRIP_ENCODING and match[4] is not None:
        return float(f"{match[1]}{match[2]}.{match[3] or ''}e{match[4].strip()}")
    try:
        return float(value)
    except (ValueError, OverflowError):
        if compatibility_fused_digits is None:
            return math.nan
        return _legacy_decimal(match, fused_digits=compatibility_fused_digits is not False)


def _legacy_decimal(match: re.Match[str], *, fused_digits: bool) -> float:
    """Retain pandas 3.0.6 precise_xstrtod's accumulation and scaling.

    Source: pandas v3.0.6, pandas/_libs/src/parser/tokenizer.c, BSD-3-Clause.
    Copyright (c) 2002, Michael Ringgaard. See docs/THIRD_PARTY_NOTICES.md.
    Algorithm expressed in Python; the two
    IEEE binary64 evaluation orders are candidates only for exact saved audits.
    """
    integer, fractional = match[2], match[3] or ""
    number = 0.0
    for digit in (integer + fractional)[:17]:
        number = float(int(number) * 10 + int(digit)) if fused_digits else number * 10.0 + int(digit)
    exponent = max(len(integer) - 17, 0) - min(len(fractional), max(17 - len(integer), 0))
    if match[1] == "-":
        number = -number
    power = (match[4] or "0").strip()
    # strtol saturated huge exponents. Only the closed scaling ranges matter.
    magnitude = power.lstrip("+-").lstrip("0") or "0"
    exponent += (int(magnitude) if len(magnitude) < 19 else 10000) * (-1 if power.startswith("-") else 1)
    if exponent > 308:
        return math.copysign(math.inf, number) if number else 0.0
    if exponent > 0:
        return number * _POWERS_OF_TEN[exponent]
    if exponent < -616:
        return 0.0
    if exponent < -308:
        return number / _POWERS_OF_TEN[-308 - exponent] / _POWERS_OF_TEN[308]
    return number / _POWERS_OF_TEN[-exponent]


def coerce_axis_series(values: pd.Series) -> pd.Series:
    numeric = coerce_numeric_series(values)
    if numeric.notna().all():
        return numeric
    return values.map(normalize_cell)


def looks_numeric(value: Any) -> bool:
    try:
        float(normalize_cell(value))
    except ValueError:
        return False
    return True


__all__ = [
    "coerce_axis_series",
    "coerce_numeric_pair",
    "coerce_numeric_series",
    "drop_fully_empty_columns",
    "ensure_header_row_content",
    "ensure_minimum_rows",
    "has_content",
    "looks_numeric",
    "normalize_cell",
    "row_has_content",
]
