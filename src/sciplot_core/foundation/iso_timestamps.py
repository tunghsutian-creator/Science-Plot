"""Create and validate timezone-aware ISO-8601 contract timestamps."""

from __future__ import annotations

from datetime import UTC, datetime


def utc_now_iso() -> str:
    """Return the current UTC time in the repository's canonical text form."""

    return datetime.now(UTC).isoformat()


def require_zoned_iso_timestamp(value: object, label: str) -> str:
    """Validate a non-empty ISO-8601 timestamp with an explicit UTC offset."""

    if not isinstance(value, str):
        raise ValueError(f"{label} must be a string.")
    text = value.strip()
    if not text:
        raise ValueError(f"{label} must be a non-empty string.")
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError as exc:
        raise ValueError(f"{label} must be an ISO-8601 timestamp.") from exc
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError(f"{label} must include a timezone offset.")
    return text


__all__ = ["require_zoned_iso_timestamp", "utc_now_iso"]
