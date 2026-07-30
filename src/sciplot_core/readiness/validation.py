"""Validate closed JSON values, timestamps, and canonical hashes."""

from __future__ import annotations

from typing import Any
from sciplot_core.foundation.json_hashing import canonical_json_sha256
from sciplot_core.foundation.iso_timestamps import (
    require_zoned_iso_timestamp,
    utc_now_iso,
)

from sciplot_core.readiness.constants import (
    _HASH_PATTERN,
)


_now = utc_now_iso


def _required_text(
    value: object,
    label: str,
    *,
    maximum: int = 2048,
) -> str:
    if not isinstance(value, str):
        raise ValueError(f"{label} must be text.")
    text = value.strip()
    if not text:
        raise ValueError(f"{label} cannot be empty.")
    if len(text) > maximum:
        raise ValueError(f"{label} exceeds {maximum} characters.")
    return text


def _required_bool(value: object, label: str) -> bool:
    if not isinstance(value, bool):
        raise ValueError(f"{label} must be a JSON boolean.")
    return value


def _required_int(value: object, label: str, *, minimum: int = 0) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise ValueError(f"{label} must be an integer.")
    if value < minimum:
        raise ValueError(f"{label} must be at least {minimum}.")
    return value


def _required_hash(value: object, label: str) -> str:
    text = _required_text(value, label, maximum=64).casefold()
    if not _HASH_PATTERN.fullmatch(text):
        raise ValueError(f"{label} must be a lowercase SHA-256 digest.")
    return text


def _timestamp(value: object, label: str) -> str:
    text = _required_text(value, label, maximum=128)
    return require_zoned_iso_timestamp(text, label)


def _closed_object(
    payload: object,
    *,
    label: str,
    expected: frozenset[str],
) -> dict[str, Any]:
    if not isinstance(payload, dict):
        raise ValueError(f"{label} must be an object.")
    keys = {str(key) for key in payload}
    missing = sorted(expected - keys)
    extra = sorted(keys - expected)
    if missing or extra:
        detail = []
        if missing:
            detail.append(f"missing: {', '.join(missing)}")
        if extra:
            detail.append(f"unsupported: {', '.join(extra)}")
        raise ValueError(f"{label} has invalid fields ({'; '.join(detail)}).")
    return {str(key): value for key, value in payload.items()}


def _text_list(
    value: object,
    label: str,
    *,
    maximum_items: int = 128,
    maximum_text: int = 2048,
) -> tuple[str, ...]:
    if not isinstance(value, list):
        raise ValueError(f"{label} must be a list.")
    if len(value) > maximum_items:
        raise ValueError(f"{label} exceeds {maximum_items} items.")
    return tuple(
        _required_text(item, f"{label}[{index}]", maximum=maximum_text)
        for index, item in enumerate(value)
    )


def _canonical_sha256(payload: object) -> str:
    return canonical_json_sha256(payload)
