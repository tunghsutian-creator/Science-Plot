"""Stable Impact figure IDs and route-compatible filenames."""

import re
import unicodedata

from sciplot_core.foundation.json_hashing import canonical_json_sha256
from sciplot_core.foundation.path_names import slug


def stable_impact_figure_id(condition: str) -> str:
    """Return an order-independent, ASCII-safe identity for one sheet label."""

    normalized = unicodedata.normalize("NFKC", str(condition)).casefold().strip()
    compact = re.sub(r"\s+", "", normalized)
    token = re.sub(r"[^a-z0-9]+", "_", compact).strip("_")
    if token and normalized == token:
        return f"impact_{token}"
    digest = canonical_json_sha256(normalized, allow_nan=False)[:10]
    return f"impact_{token or 'condition'}_{digest}"


def _legacy_autoplot_impact_stems(conditions: list[str]) -> list[str]:
    """Retain current Workflow filenames while IDs become route-independent."""

    return _stable_compatibility_stems(
        [
            (f"impact_{slug(str(condition).replace(' ', ''))}", condition)
            for condition in conditions
        ]
    )


def _legacy_studio_impact_stems(conditions: list[str]) -> list[str]:
    """Retain current Studio document filenames for existing source labels."""

    bases: list[tuple[str, str]] = []
    for order, condition in enumerate(conditions, start=1):
        token = (
            re.sub(r"[^a-z0-9]+", "_", str(condition).casefold()).strip("_")
            or f"condition_{order}"
        )
        bases.append((f"impact_{token}", condition))
    return _stable_compatibility_stems(bases)


def _stable_compatibility_stems(
    bases: list[tuple[str, str]],
) -> list[str]:
    counts = {
        base: sum(1 for value, _identity in bases if value == base) for base, _ in bases
    }
    return [
        (
            base
            if counts[base] == 1
            else f"{base}_{canonical_json_sha256(identity, allow_nan=False)[:8]}"
        )
        for base, identity in bases
    ]
