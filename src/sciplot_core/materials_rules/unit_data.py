"""Declare canonical unit symbols, aliases, prefixes, and parsing tokens."""

from __future__ import annotations

import re
from dataclasses import dataclass


@dataclass(frozen=True)
class UnitRule:
    source: str
    target: str
    factor: float = 1.0
    offset: float = 0.0


_UNIT_RULES = {
    ("Pa", "kPa"): UnitRule("Pa", "kPa", 1e-3),
    ("Pa", "MPa"): UnitRule("Pa", "MPa", 1e-6),
    ("Pa", "GPa"): UnitRule("Pa", "GPa", 1e-9),
    ("kPa", "Pa"): UnitRule("kPa", "Pa", 1e3),
    ("MPa", "Pa"): UnitRule("MPa", "Pa", 1e6),
    ("GPa", "Pa"): UnitRule("GPa", "Pa", 1e9),
    ("mPa.s", "Pa.s"): UnitRule("mPa.s", "Pa.s", 1e-3),
    ("Pa.s", "mPa.s"): UnitRule("Pa.s", "mPa.s", 1e3),
    ("ms", "s"): UnitRule("ms", "s", 1e-3),
    ("min", "s"): UnitRule("min", "s", 60.0),
    ("h", "s"): UnitRule("h", "s", 3600.0),
    ("s", "min"): UnitRule("s", "min", 1 / 60.0),
    ("s", "h"): UnitRule("s", "h", 1 / 3600.0),
    ("K", "C"): UnitRule("K", "C", 1.0, -273.15),
    ("C", "K"): UnitRule("C", "K", 1.0, 273.15),
    ("fraction", "%"): UnitRule("fraction", "%", 100.0),
    ("%", "fraction"): UnitRule("%", "fraction", 0.01),
    ("nm", "um"): UnitRule("nm", "um", 1e-3),
    ("um", "nm"): UnitRule("um", "nm", 1e3),
    ("um", "mm"): UnitRule("um", "mm", 1e-3),
    ("mm", "um"): UnitRule("mm", "um", 1e3),
    ("A^-1", "nm^-1"): UnitRule("A^-1", "nm^-1", 10.0),
    ("nm^-1", "A^-1"): UnitRule("nm^-1", "A^-1", 0.1),
}


_DIMENSIONLESS_EXPRESSION_LABELS = {
    "G/G0": "$G(t)/G_0$",
    "sigma/sigma0": "$\\sigma/\\sigma_0$",
    "$\\sigma/\\sigma_0$": "$\\sigma/\\sigma_0$",
    "\\sigma/\\sigma_{0}": "\\sigma/\\sigma_{0}",
    "σ/σ₀": "σ/σ₀",
    "G′/G′ₘ": "G′/G′ₘ",
    "\\italic{G}′/\\italic{G}′_{m}": "\\italic{G}′/\\italic{G}′_{m}",
}


_UNIT_WHOLE_ALIASES = {
    "A^-1": "Å⁻¹",
    "A$^{-1}$": "Å⁻¹",
    "C": "°C",
    "Pa.s": "Pa·s",
    "mPa.s": "mPa·s",
    "um": "µm",
    "μm": "µm",
    "µm": "µm",
}


_SUPERSCRIPT_DIGITS = str.maketrans(
    {
        "0": "⁰",
        "1": "¹",
        "2": "²",
        "3": "³",
        "4": "⁴",
        "5": "⁵",
        "6": "⁶",
        "7": "⁷",
        "8": "⁸",
        "9": "⁹",
        "+": "⁺",
        "-": "⁻",
        "−": "⁻",
    }
)


_PLAIN_SUPERSCRIPTS = str.maketrans(
    {
        "⁰": "0",
        "¹": "1",
        "²": "2",
        "³": "3",
        "⁴": "4",
        "⁵": "5",
        "⁶": "6",
        "⁷": "7",
        "⁸": "8",
        "⁹": "9",
        "⁺": "+",
        "⁻": "-",
    }
)


_SUPERSCRIPT_CHARACTERS = "⁰¹²³⁴⁵⁶⁷⁸⁹⁺⁻"


_UNIT_BASE_SYMBOLS = frozenset(
    {
        "%",
        "1",
        "A",
        "Bq",
        "C",
        "Da",
        "F",
        "Gy",
        "H",
        "Hz",
        "J",
        "K",
        "L",
        "N",
        "Pa",
        "S",
        "Sv",
        "T",
        "V",
        "W",
        "Wb",
        "bar",
        "cd",
        "count",
        "counts",
        "d",
        "degree",
        "eV",
        "g",
        "h",
        "kat",
        "lm",
        "lx",
        "m",
        "min",
        "mol",
        "rad",
        "rpm",
        "s",
        "sr",
        "Å",
        "Ω",
        "°C",
        "°F",
    }
)


_UNIT_PREFIXES = (
    "da",
    "Y",
    "Z",
    "E",
    "P",
    "T",
    "G",
    "M",
    "k",
    "h",
    "d",
    "c",
    "m",
    "µ",
    "μ",
    "u",
    "n",
    "p",
    "f",
    "a",
    "z",
    "y",
)


_UNIT_EXPONENT_RE = re.compile(
    rf"^(.*?)(?:"
    rf"\$\^\{{([+\-−]?\d+)\}}\$"
    rf"|\^\{{([+\-−]?\d+)\}}"
    rf"|\^([+\-−]?\d+)"
    rf"|([{_SUPERSCRIPT_CHARACTERS}]+)"
    rf")$"
)


_UNIT_TEXT_EDGE_PUNCTUATION = frozenset("\"'“”‘’,;:")


_PLOT_TEXT_TOKEN_RE = re.compile(r"\S+")


_BRACKET_PAIRS = {"(": ")", "[": "]"}


_BRACKET_OPEN_BY_CLOSE = {close: open_ for open_, close in _BRACKET_PAIRS.items()}
