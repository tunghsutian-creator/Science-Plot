"""Resolve original Impact strength units without changing measured values."""

import re

from sciplot_core.foundation.text_values import clean_text as _clean_text
from sciplot_core.semantic_sources.models import _ImpactDataValidationError


def _canonical_impact_unit(value: object) -> str | None:
    text = _clean_text(value)
    if not text:
        return None
    compact = (
        text.casefold()
        .replace("²", "2")
        .replace("^", "")
        .replace("−", "-")
        .replace("⁻", "-")
    )
    compact = compact.replace("{", "").replace("}", "")
    if len(compact) >= 2 and (compact[0], compact[-1]) in {("(", ")"), ("[", "]")}:
        compact = compact[1:-1].strip()
    # The readers retain the numbers: only exact spelling identities may be
    # relabelled. A different area prefix requires a real conversion contract.
    if re.fullmatch(r"kj\s*/\s*(?:m2|\(m2\))|kj(?:\s+|\s*[·*]\s*)m-2", compact):
        return "kJ/m2"
    return None


def _is_impact_metric(metric: str) -> bool:
    """The shared wide-column identity predicate; callers retain normalization."""
    return metric == "re" or "impact" in metric or "冲击" in metric


def _validated_impact_unit(values: list[object]) -> str:
    explicit = [_clean_text(value) for value in values if _clean_text(value)]
    if not explicit:
        raise _ImpactDataValidationError(
            "Impact strength unit is missing; include an explicit kJ/m2 unit "
            "in the metric header, unit row, or unit column."
        )
    unknown = [value for value in explicit if _canonical_impact_unit(value) is None]
    if unknown:
        raise _ImpactDataValidationError(
            "Impact strength units must resolve to kJ/m2; unsupported values: "
            + ", ".join(sorted(set(unknown)))
        )
    return "kJ/m2"


def _impact_unit_candidate_from_header(header: str) -> str | None:
    compact = header.casefold()
    if "kj" in compact:
        suffix = header[compact.index("kj"):].strip()
        if _canonical_impact_unit(suffix) is not None:
            return suffix
    bracketed = re.search(r"\(([^)]+)\)|\[([^\]]+)\]", header)
    if bracketed:
        candidate = next((group for group in bracketed.groups() if group), "")
        return candidate.strip() or None
    if "kj" in compact:
        return header[compact.index("kj"):].strip()
    if any(token in compact for token in ("kj", "mpa", "gpa", "j/", "m²", "m2", "m^2")):
        return header
    return None
