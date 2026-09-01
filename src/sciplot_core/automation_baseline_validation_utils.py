"""Primitive closed-field checks shared by R0 baseline validators."""

from __future__ import annotations

import re
from collections.abc import Mapping
from typing import Any


_SHA256 = re.compile(r"[0-9a-f]{64}")


def validate_fixed_mapping(
    payload: object, expected: frozenset[str], label: str
) -> Mapping[str, Any]:
    if not isinstance(payload, Mapping):
        raise ValueError(f"Automation baseline {label} must be an object.")
    require_fields(payload, expected, label=f"automation {label}")
    return payload


def require_fields(
    payload: Mapping[str, Any], expected: frozenset[str], *, label: str
) -> None:
    actual = set(payload)
    if actual != expected:
        missing = sorted(expected - actual)
        unknown = sorted(actual - expected)
        raise ValueError(f"{label} fields are invalid; missing={missing}, unknown={unknown}.")


def require_sha256(value: object, *, label: str) -> None:
    if not isinstance(value, str) or _SHA256.fullmatch(value) is None:
        raise ValueError(f"Automation baseline {label} must be a lowercase SHA-256.")


def same_typed_json_value(actual: object, expected: object) -> bool:
    """Compare JSON values without Python's bool/int numeric equivalence."""

    if isinstance(expected, Mapping):
        return isinstance(actual, Mapping) and set(actual) == set(expected) and all(
            same_typed_json_value(actual[key], value)
            for key, value in expected.items()
        )
    if isinstance(expected, list):
        return type(actual) is list and len(actual) == len(expected) and all(
            same_typed_json_value(item, value)
            for item, value in zip(actual, expected, strict=True)
        )
    return type(actual) is type(expected) and actual == expected


__all__ = [
    "require_fields",
    "require_sha256",
    "same_typed_json_value",
    "validate_fixed_mapping",
]
