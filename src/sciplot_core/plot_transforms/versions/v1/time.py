"""Frozen literal time-unit identities; no conversion inference."""
TIME_UNITS = frozenset({"ms", "s", "min", "h"})


def canonical_unit_token(unit: str) -> str:
    """Remove unit delimiters, never infer missing units or scientific quantity."""
    token = unit.strip()
    if len(token) >= 2 and (token[0], token[-1]) in {("[", "]"), ("(", ")")}:
        token = token[1:-1].strip()
    return "C" if token == "°C" else token
