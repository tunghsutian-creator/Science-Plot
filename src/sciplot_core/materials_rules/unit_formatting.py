"""Normalize and format scientific unit factors and products."""

from __future__ import annotations

import re
from sciplot_core.policy import (
    SCIENTIFIC_UNIT_FACTOR_SEPARATOR,
)

from sciplot_core.materials_rules.unit_data import (
    _DIMENSIONLESS_EXPRESSION_LABELS,
    _UNIT_WHOLE_ALIASES,
    _SUPERSCRIPT_DIGITS,
    _PLAIN_SUPERSCRIPTS,
    _SUPERSCRIPT_CHARACTERS,
    _UNIT_BASE_SYMBOLS,
    _UNIT_PREFIXES,
    _UNIT_EXPONENT_RE,
)


def _unicode_exponent(value: int) -> str:
    return str(value).translate(_SUPERSCRIPT_DIGITS)


def _split_unit_factor_exponent(
    value: object,
    *,
    allow_plain_power: bool,
) -> tuple[str, int]:
    factor = str(value or "").strip()
    match = _UNIT_EXPONENT_RE.fullmatch(factor)
    if match is not None:
        exponent_text = next(group for group in match.groups()[1:] if group is not None)
        if all(character in _SUPERSCRIPT_CHARACTERS for character in exponent_text):
            exponent_text = exponent_text.translate(_PLAIN_SUPERSCRIPTS)
        return match.group(1), int(exponent_text.replace("−", "-"))
    if allow_plain_power:
        plain = re.fullmatch(r"(.+?)([23])", factor)
        if plain is not None and _is_known_unit_symbol(plain.group(1)):
            return plain.group(1), int(plain.group(2))
    return factor, 1


def _normalize_unit_symbol(value: object) -> str:
    symbol = str(value or "").strip()
    return _UNIT_WHOLE_ALIASES.get(symbol, symbol)


def _format_unit_factor(
    value: object,
    *,
    invert: bool = False,
    allow_plain_power: bool = False,
) -> str:
    symbol, exponent = _split_unit_factor_exponent(
        value,
        allow_plain_power=allow_plain_power,
    )
    symbol = _normalize_unit_symbol(symbol)
    resolved_exponent = -exponent if invert else exponent
    return (
        symbol
        if resolved_exponent == 1
        else f"{symbol}{_unicode_exponent(resolved_exponent)}"
    )


def _format_existing_unit_product(value: object) -> str:
    text = str(value or "").strip()
    if not text:
        return ""
    parts = re.split(r"(\s+|[·⋅×*])", text)
    formatted: list[str] = []
    for part in parts:
        if not part:
            continue
        if part.isspace() or part in {"·", "⋅", "×", "*"}:
            formatted.append(part)
        else:
            formatted.append(_format_unit_factor(part, allow_plain_power=True))
    return "".join(formatted)


def _denominator_unit_factors(value: object) -> list[str]:
    text = str(value or "").strip().strip("()[]{} ")
    return [factor for factor in re.split(r"(?:\s+|[·⋅×*])", text) if factor]


def _is_known_unit_symbol(value: object) -> bool:
    symbol = _normalize_unit_symbol(value)
    if symbol in _UNIT_BASE_SYMBOLS:
        return True
    if symbol.casefold() in {
        "a.u.",
        "au",
        "degc",
        "fraction",
        "mins",
        "sec",
        "seconds",
    }:
        return True
    return any(
        symbol.startswith(prefix) and symbol[len(prefix) :] in _UNIT_BASE_SYMBOLS
        for prefix in _UNIT_PREFIXES
        if len(symbol) > len(prefix)
    )


def _is_known_unit_factor(value: object) -> bool:
    factor = str(value or "").strip()
    symbol, _exponent = _split_unit_factor_exponent(
        factor,
        allow_plain_power=True,
    )
    return _is_known_unit_symbol(symbol)


def _looks_like_unit_solidus_expression(value: object) -> bool:
    text = str(value or "").strip().strip("()[] ")
    if "/" not in text or "\\" in text or "_" in text:
        return False
    slash_parts = [part.strip() for part in text.split("/")]
    if len(slash_parts) < 2 or any(not part for part in slash_parts):
        return False
    factors: list[str] = []
    for part in slash_parts:
        factors.extend(_denominator_unit_factors(part))
    return bool(factors) and all(
        factor == "1" or _is_known_unit_factor(factor) for factor in factors
    )


def looks_like_unit_expression(value: object) -> bool:
    """Return whether *value* is one recognized scientific unit expression."""

    candidate = str(value or "").strip().strip("[]() ")
    if not candidate:
        return False
    if candidate in _UNIT_WHOLE_ALIASES:
        return True
    if _is_known_unit_factor(candidate) or _looks_like_unit_solidus_expression(
        candidate
    ):
        return True
    factors = _denominator_unit_factors(candidate)
    return len(factors) > 1 and all(_is_known_unit_factor(factor) for factor in factors)


def format_unit_label(unit: str) -> str:
    """Return the global scientific display form for one unit expression.

    Input recognition remains compatible with instrument solidus notation,
    while every display/output unit uses a product and negative exponents.
    Dimensionless mathematical ratios are expressions, not units, and retain
    their division operator.
    """

    text = str(unit or "").strip()
    if not text:
        return ""
    if text in _DIMENSIONLESS_EXPRESSION_LABELS:
        return _DIMENSIONLESS_EXPRESSION_LABELS[text]
    if text in _UNIT_WHOLE_ALIASES:
        return _UNIT_WHOLE_ALIASES[text]
    if "/" not in text:
        return _format_existing_unit_product(text)

    slash_parts = [part.strip() for part in text.split("/")]
    numerator = _format_existing_unit_product(slash_parts[0])
    factors = [] if numerator == "1" else [numerator]
    for denominator in slash_parts[1:]:
        factors.extend(
            _format_unit_factor(
                factor,
                invert=True,
                allow_plain_power=True,
            )
            for factor in _denominator_unit_factors(denominator)
        )
    return SCIENTIFIC_UNIT_FACTOR_SEPARATOR.join(factor for factor in factors if factor)
