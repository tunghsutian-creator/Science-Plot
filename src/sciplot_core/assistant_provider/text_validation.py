"""Validate canonical text, identifiers, timestamps, and payload hashes."""

from __future__ import annotations

from typing import Any
from uuid import UUID

from sciplot_core.foundation.json_hashing import canonical_json_sha256
from sciplot_core.foundation.iso_timestamps import (
    require_zoned_iso_timestamp,
    utc_now_iso,
)
from sciplot_core.assistant_provider.contracts import (
    _SAFE_PROVIDER_ID,
    _SHA256,
)

_timestamp = require_zoned_iso_timestamp
_now = utc_now_iso


def _required_text(
    value: object,
    label: str,
    *,
    maximum: int | None = None,
) -> str:
    if not isinstance(value, str):
        raise ValueError(f"{label} must be a string.")
    text = value.strip()
    if not text:
        raise ValueError(f"{label} must be a non-empty string.")
    if maximum is not None and len(text) > maximum:
        raise ValueError(f"{label} must contain at most {maximum} characters.")
    return text


def _optional_text(
    value: object,
    label: str,
    *,
    maximum: int | None = None,
) -> str | None:
    if value is None:
        return None
    return _required_text(value, label, maximum=maximum)


def _free_text(
    value: object,
    label: str,
    *,
    maximum: int,
) -> str:
    if not isinstance(value, str):
        raise ValueError(f"{label} must be a string.")
    text = value.strip()
    if len(text) > maximum:
        raise ValueError(f"{label} must contain at most {maximum} characters.")
    return text


def _uuid_text(value: object, label: str) -> str:
    text = _required_text(value, label)
    try:
        parsed = UUID(text)
    except ValueError as exc:
        raise ValueError(f"{label} must be a UUID.") from exc
    if str(parsed) != text.casefold():
        raise ValueError(f"{label} must use canonical UUID text.")
    return str(parsed)


def _provider_id(value: object, label: str = "provider_id") -> str:
    text = _required_text(value, label)
    if _SAFE_PROVIDER_ID.fullmatch(text) is None:
        raise ValueError(
            f"{label} must use 1-96 ASCII letters, digits, dot, underscore, or dash."
        )
    return text


def _sha256(value: object, label: str) -> str:
    digest = _required_text(value, label).casefold()
    if _SHA256.fullmatch(digest) is None:
        raise ValueError(f"{label} must be a lowercase SHA-256 digest.")
    return digest


def canonical_payload_sha256(payload: dict[str, Any]) -> str:
    return canonical_json_sha256(payload, allow_nan=False)
