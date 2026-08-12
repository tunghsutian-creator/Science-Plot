"""Normalize scientific labels and units found in imported source tables."""

from __future__ import annotations

import math
import re
import unicodedata

from sciplot_core.source_tables.text_aliases import (
    LABEL_ALIASES_SOURCE,
    UNIT_ALIASES_SOURCE,
)


_SUBSCRIPT_MAP = str.maketrans("₀₁₂₃₄₅₆₇₈₉₊₋₍₎", "0123456789+-()")
_SUPERSCRIPT_MAP = str.maketrans("⁰¹²³⁴⁵⁶⁷⁸⁹⁺⁻⁽⁾", "0123456789+-()")
_UNIT_BASE_TOKENS = frozenset(
    {
        "%",
        "a",
        "bar",
        "c",
        "cd",
        "ev",
        "f",
        "g",
        "gy",
        "h",
        "hz",
        "j",
        "k",
        "kat",
        "l",
        "lx",
        "m",
        "min",
        "mol",
        "n",
        "ohm",
        "pa",
        "rad",
        "s",
        "sv",
        "t",
        "v",
        "w",
        "wb",
        "wh",
        "ω",
    }
)
_SI_PREFIXES = (
    "da",
    "y",
    "z",
    "a",
    "f",
    "p",
    "n",
    "u",
    "µ",
    "m",
    "c",
    "d",
    "h",
    "k",
    "M",
    "G",
    "T",
)


def clean_source_text(text: object) -> str:
    """Collapse surrounding and repeated whitespace in a source-table cell."""

    if text is None or isinstance(text, float) and math.isnan(text):
        return ""
    return " ".join(str(text or "").strip().split())


def canonicalize_token(text: object) -> str:
    """Build a case-insensitive token while preserving scientific symbols."""

    normalized = unicodedata.normalize("NFKC", str(text or ""))
    normalized = normalized.translate(_SUBSCRIPT_MAP).translate(_SUPERSCRIPT_MAP)
    normalized = normalized.replace("℃", "°C")
    normalized = normalized.replace("（", "(").replace("）", ")")
    normalized = normalized.replace("【", "[").replace("】", "]")
    normalized = (
        normalized.replace("·", ".")
        .replace("⋅", ".")
        .replace("•", ".")
        .replace("∙", ".")
    )
    normalized = normalized.replace("*", ".").replace("×", "x")
    normalized = normalized.replace("−", "-").replace("–", "-").replace("—", "-")
    normalized = clean_source_text(normalized).lower()
    normalized = re.sub(r"\s*/\s*", "/", normalized)
    normalized = re.sub(r"\s*\.\s*", ".", normalized)
    normalized = re.sub(r"\s*-\s*", "-", normalized)
    return re.sub(r"\s+", " ", normalized).strip()


LABEL_ALIASES = {
    canonicalize_token(key): value for key, value in LABEL_ALIASES_SOURCE.items()
}
UNIT_ALIASES = {
    canonicalize_token(key): value for key, value in UNIT_ALIASES_SOURCE.items()
}


def _title_case_preserving_acronyms(text: str) -> str:
    words = text.split()
    return " ".join(
        word if word.isupper() and len(word) <= 4 else word[:1].upper() + word[1:]
        for word in words
    )


def _unit_mathtext_source(text: str) -> str:
    normalized = unicodedata.normalize("NFKC", text or "")
    normalized = normalized.translate(_SUBSCRIPT_MAP).translate(_SUPERSCRIPT_MAP)
    normalized = normalized.replace("−", "-").replace("–", "-").replace("—", "-")
    normalized = (
        normalized.replace("·", ".")
        .replace("⋅", ".")
        .replace("•", ".")
        .replace("∙", ".")
        .replace("*", ".")
    )
    return clean_source_text(normalized)


def _looks_like_unit_symbol(token: str) -> bool:
    lowered = token.replace("μ", "µ").lower()
    if lowered in _UNIT_BASE_TOKENS:
        return True
    return any(
        lowered.startswith(prefix.lower())
        and lowered[len(prefix) :] in _UNIT_BASE_TOKENS
        for prefix in _SI_PREFIXES
    )


def _unit_token_parts(token: str) -> tuple[str, int | None] | None:
    match = re.fullmatch(
        r"(?P<base>[A-Za-zµμΩ°%]+)(?P<exp>(?:\^-?\d+)|(?:-?\d+))?",
        token,
    )
    if match is None or not _looks_like_unit_symbol(match.group("base")):
        return None
    raw_exponent = match.group("exp")
    exponent = int(raw_exponent.lstrip("^")) if raw_exponent else None
    return match.group("base"), exponent


def _format_unit_piece(base: str, exponent: int | None) -> str:
    if exponent is None or exponent == 1:
        return base
    return f"{base}$^{{{exponent}}}$"


def _format_generic_unit(text: str) -> str:
    tokens = [
        token for token in re.split(r"([/.\s]+)", _unit_mathtext_source(text)) if token
    ]
    formatted: list[str] = []
    denominator_depth = 0
    pending_delimiter = ""
    for token in tokens:
        if re.fullmatch(r"[/.\s]+", token):
            if "/" in token:
                denominator_depth += token.count("/")
                pending_delimiter = "."
            elif "." in token:
                pending_delimiter = "."
            else:
                pending_delimiter = " "
            continue
        parts = _unit_token_parts(token)
        if pending_delimiter and formatted:
            formatted.append(
                r"$\cdot$" if "." in pending_delimiter else pending_delimiter
            )
        if parts is None:
            formatted.append(token)
        else:
            base, exponent = parts
            if denominator_depth:
                exponent = -(exponent if exponent is not None else 1)
            formatted.append(_format_unit_piece(base, exponent))
        pending_delimiter = ""
    return "".join(formatted).replace(r"}$$\cdot$", r"}\cdot$")


def normalize_label(text: object) -> str:
    """Return the canonical display label for one imported header cell."""

    cleaned = clean_source_text(text)
    if not cleaned:
        return ""
    return LABEL_ALIASES.get(
        canonicalize_token(cleaned),
        _title_case_preserving_acronyms(cleaned),
    )


def normalize_unit(text: object) -> str:
    """Return the compatibility display form for one imported unit cell."""

    cleaned = clean_source_text(text)
    if not cleaned:
        return ""
    canonical = canonicalize_token(cleaned)
    if canonical in UNIT_ALIASES:
        return UNIT_ALIASES[canonical]
    if cleaned.startswith("[") and cleaned.endswith("]") and len(cleaned) > 2:
        cleaned = clean_source_text(cleaned[1:-1])
    return _format_generic_unit(cleaned)


def _slugify_token(text: object) -> str:
    canonical = canonicalize_token(text)
    replacements = {
        r"\sigma": "sigma",
        r"\eta": "eta",
        r"\cdot": "",
        "δ": "delta",
        "η": "eta",
        "ω": "omega",
        "σ": "sigma",
        "γ": "gamma",
        "θ": "theta",
        "/": "_",
        ".": "_",
        "-": "_",
    }
    canonical = canonical.replace("$", "").replace("|", "")
    canonical = canonical.replace('"', "").replace("'", "")
    for source, target in replacements.items():
        canonical = canonical.replace(source, target)
    canonical = re.sub(r"[^a-z0-9_]+", "_", canonical)
    return re.sub(r"_+", "_", canonical).strip("_") or "value"


def slugify_label(text: object) -> str:
    """Convert a presentation-normalized label to a stable filename token."""

    return _slugify_token(normalize_label(text))


def slugify_canonical_label(text: object) -> str:
    """Build an identifier from canonical source meaning, without display aliases."""

    return _slugify_token(clean_source_text(text))


__all__ = [
    "LABEL_ALIASES",
    "UNIT_ALIASES",
    "canonicalize_token",
    "clean_source_text",
    "normalize_label",
    "normalize_unit",
    "slugify_canonical_label",
    "slugify_label",
]
