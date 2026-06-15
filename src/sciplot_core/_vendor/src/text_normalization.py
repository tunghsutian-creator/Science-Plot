from __future__ import annotations

import re
import unicodedata

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
_SI_PREFIXES = ("da", "y", "z", "a", "f", "p", "n", "u", "µ", "m", "c", "d", "h", "k", "M", "G", "T")


def _clean_text(text: str) -> str:
    return " ".join(text.strip().split())


def _unit_mathtext_source(text: str) -> str:
    normalized = unicodedata.normalize("NFKC", text or "")
    normalized = normalized.translate(_SUBSCRIPT_MAP).translate(_SUPERSCRIPT_MAP)
    normalized = normalized.replace("−", "-").replace("–", "-").replace("—", "-")
    normalized = normalized.replace("·", ".").replace("⋅", ".").replace("•", ".").replace("∙", ".")
    normalized = normalized.replace("*", ".")
    return _clean_text(normalized)


def _looks_like_unit_symbol(token: str) -> bool:
    lowered = token.replace("μ", "µ").lower()
    if lowered in _UNIT_BASE_TOKENS:
        return True
    for prefix in _SI_PREFIXES:
        candidate_prefix = prefix.lower()
        if lowered.startswith(candidate_prefix) and lowered[len(candidate_prefix) :] in _UNIT_BASE_TOKENS:
            return True
    return False


def _unit_token_parts(token: str) -> tuple[str, int | None] | None:
    match = re.fullmatch(r"(?P<base>[A-Za-zµμΩ°%]+)(?P<exp>(?:\^-?\d+)|(?:-?\d+))?", token)
    if match is None:
        return None
    base = match.group("base")
    if not _looks_like_unit_symbol(base):
        return None
    raw_exponent = match.group("exp")
    exponent = int(raw_exponent.lstrip("^")) if raw_exponent else None
    return base, exponent


def _format_unit_piece_mathtext(base: str, exponent: int | None) -> str:
    if exponent is None or exponent == 1:
        return base
    return f"{base}$^{{{exponent}}}$"


def _format_unit_token_mathtext(token: str) -> str:
    parts = _unit_token_parts(token)
    if parts is None:
        return token
    base, exponent = parts
    if exponent is None:
        return token
    return _format_unit_piece_mathtext(base, exponent)


def _format_generic_unit_mathtext(text: str) -> str:
    source = _unit_mathtext_source(text)
    tokens = [token for token in re.split(r"([/.\s]+)", source) if token]
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
            formatted.append(_format_unit_delimiter_mathtext(pending_delimiter))
        if parts is None:
            formatted.append(token)
        else:
            base, exponent = parts
            if denominator_depth:
                exponent = -(exponent if exponent is not None else 1)
            formatted.append(_format_unit_piece_mathtext(base, exponent))
        pending_delimiter = ""

    return "".join(formatted).replace(r"}$$\cdot$", r"}\cdot$")


def _format_unit_delimiter_mathtext(token: str) -> str:
    if "." in token:
        return r"$\cdot$"
    return token


def canonicalize_token(text: str) -> str:
    normalized = unicodedata.normalize("NFKC", text or "")
    normalized = normalized.translate(_SUBSCRIPT_MAP).translate(_SUPERSCRIPT_MAP)
    normalized = normalized.replace("℃", "°C")
    normalized = normalized.replace("（", "(").replace("）", ")")
    normalized = normalized.replace("【", "[").replace("】", "]")
    normalized = normalized.replace("·", ".").replace("⋅", ".").replace("•", ".").replace("∙", ".")
    normalized = normalized.replace("*", ".").replace("×", "x")
    normalized = normalized.replace("−", "-").replace("–", "-").replace("—", "-")
    normalized = _clean_text(normalized).lower()
    normalized = re.sub(r"\s*/\s*", "/", normalized)
    normalized = re.sub(r"\s*\.\s*", ".", normalized)
    normalized = re.sub(r"\s*-\s*", "-", normalized)
    normalized = re.sub(r"\s+", " ", normalized)
    return normalized.strip()


def _title_case_preserving_acronyms(text: str) -> str:
    words = text.split()
    titled: list[str] = []
    for word in words:
        if word.isupper() and len(word) <= 4:
            titled.append(word)
        else:
            titled.append(word[:1].upper() + word[1:])
    return " ".join(titled)


_LABEL_ALIASES = {
    "ω": "ω",
    "Ω": "ω",
    "σ": "σ",
    "γ": "γ",
    "angular frequency": "ω",
    "frequency": "ω",
    "storage modulus": "G'",
    "g'": "G'",
    "loss modulus": 'G"',
    'g"': 'G"',
    "loss factor": "tanδ",
    "tan delta": "tanδ",
    "tandelta": "tanδ",
    "complex viscosity": "|η*|",
    "complex viscocity": "|η*|",
    "time": "Time",
    "temperature": "Temperature",
    "shear stress": "σ",
    "stress": "σ",
    "shear strain": "γ",
    "strain": "Strain",
    "wavenumber": "Wavenumber",
    "wavenumbers": "Wavenumber",
    "chemical shift": "Chemical shift",
    "intensity": "Intensity",
    "transmittance": "Transmittance",
    "absorbance": "Absorbance",
    "heat flow": "Heat flow",
    "weight": "Weight",
    "mass": "Mass",
    "weight loss": "Weight loss",
    "mass loss": "Mass loss",
    "count": "Counts",
    "counts": "Counts",
    "2theta": "2θ",
    "2 theta": "2θ",
    "2θ": "2θ",
    "σ/σ0": r"$\sigma/\sigma_0$",
    "σ/σo": r"$\sigma/\sigma_0$",
    "sigma/sigma0": r"$\sigma/\sigma_0$",
    "sigma/sigmao": r"$\sigma/\sigma_0$",
    "tensile modulus": "Tensile modulus",
    "tensile strength": "Tensile strength",
}

_UNIT_ALIASES = {
    "mpa": "MPa",
    "pa": "Pa",
    "kpa": "kPa",
    "gpa": "GPa",
    "ppm": "ppm",
    "[ppm]": "ppm",
    "a.u.": "a.u.",
    "a.u": "a.u.",
    "au": "a.u.",
    "arb. units": "a.u.",
    "arbitrary units": "a.u.",
    "count": "counts",
    "counts": "counts",
    "[count]": "counts",
    "[counts]": "counts",
    "rad/s": r"rad$\cdot$s$^{-1}$",
    "rad.s-1": r"rad$\cdot$s$^{-1}$",
    "rad.s^-1": r"rad$\cdot$s$^{-1}$",
    "rad s-1": r"rad$\cdot$s$^{-1}$",
    "rad s^-1": r"rad$\cdot$s$^{-1}$",
    "rad.s−1": r"rad$\cdot$s$^{-1}$",
    "rad s−1": r"rad$\cdot$s$^{-1}$",
    "mpa.s": r"mPa$\cdot$s",
    "mpa s": r"mPa$\cdot$s",
    "mpa/s": r"MPa$\cdot$s$^{-1}$",
    "N m": "N·m",
    "N.m": "N·m",
    "N·m": "N·m",
    "newton meter": "N·m",
    "newton metre": "N·m",
    "pa.s": r"Pa$\cdot$s",
    "pa s": r"Pa$\cdot$s",
    "cm-1": r"cm$^{-1}$",
    "cm^-1": r"cm$^{-1}$",
    "cm−1": r"cm$^{-1}$",
    "1/cm": r"cm$^{-1}$",
    "[cm-1]": r"cm$^{-1}$",
    "[cm^-1]": r"cm$^{-1}$",
    "degc": "°C",
    "°c": "°C",
    "celsius": "°C",
    "degree": "°",
    "degrees": "°",
    "[s]": "s",
    "s": "s",
    "[%]": "%",
    "%": "%",
    "wt%": "%",
    "mass %": "%",
    "weight %": "%",
    "[pa]": "Pa",
    "[mpa]": "MPa",
    "[kpa]": "kPa",
    "[gpa]": "GPa",
}

LABEL_ALIASES = {canonicalize_token(key): value for key, value in _LABEL_ALIASES.items()}
UNIT_ALIASES = {canonicalize_token(key): value for key, value in _UNIT_ALIASES.items()}


def _lookup_user_rule(kind: str, canonical: str) -> str | None:
    try:
        from src.scientific_text_rules import lookup_scientific_text_rule

        return lookup_scientific_text_rule(kind, canonical)
    except Exception:
        return None


def normalize_label_without_user_rules(text: str) -> str:
    cleaned = _clean_text(text or "")
    if not cleaned:
        return ""
    canonical = canonicalize_token(cleaned)
    if canonical in LABEL_ALIASES:
        return LABEL_ALIASES[canonical]
    return _title_case_preserving_acronyms(cleaned)


def normalize_label(text: str) -> str:
    cleaned = _clean_text(text or "")
    if not cleaned:
        return ""
    canonical = canonicalize_token(cleaned)
    if user_value := _lookup_user_rule("label", canonical):
        return user_value
    return normalize_label_without_user_rules(cleaned)


def normalize_unit_without_user_rules(text: str) -> str:
    cleaned = _clean_text(text or "")
    if not cleaned:
        return ""
    canonical = canonicalize_token(cleaned)
    if canonical in UNIT_ALIASES:
        return UNIT_ALIASES[canonical]
    # Preserve bracketed unknown units like [N] -> N when safe.
    if cleaned.startswith("[") and cleaned.endswith("]") and len(cleaned) > 2:
        cleaned = _clean_text(cleaned[1:-1])
    return _format_generic_unit_mathtext(cleaned)


def normalize_unit(text: str) -> str:
    cleaned = _clean_text(text or "")
    if not cleaned:
        return ""
    canonical = canonicalize_token(cleaned)
    if user_value := _lookup_user_rule("unit", canonical):
        return user_value
    return normalize_unit_without_user_rules(cleaned)


def slugify_label(text: str) -> str:
    normalized = normalize_label(text)
    canonical = canonicalize_token(normalized)
    canonical = canonical.replace("$", "")
    canonical = canonical.replace("\\sigma", "sigma")
    canonical = canonical.replace("\\eta", "eta")
    canonical = canonical.replace("\\cdot", "")
    canonical = canonical.replace("|", "")
    canonical = canonical.replace('"', "")
    canonical = canonical.replace("'", "")
    canonical = canonical.replace("δ", "delta")
    canonical = canonical.replace("η", "eta")
    canonical = canonical.replace("ω", "omega")
    canonical = canonical.replace("σ", "sigma")
    canonical = canonical.replace("γ", "gamma")
    canonical = canonical.replace("θ", "theta")
    canonical = canonical.replace("/", "_")
    canonical = canonical.replace(".", "_")
    canonical = canonical.replace("-", "_")
    canonical = re.sub(r"[^a-z0-9_]+", "_", canonical)
    canonical = re.sub(r"_+", "_", canonical).strip("_")
    return canonical or "value"
