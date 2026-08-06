"""Shared scalar validators for immutable figure-plan models."""

from __future__ import annotations

import re


FIGURE_ID_PATTERN = re.compile(r"[a-z0-9][a-z0-9_]*")
ARTIFACT_STEM_PATTERN = re.compile(
    r"[A-Za-z0-9\u4e00-\u9fff][A-Za-z0-9._\-\u4e00-\u9fff]*"
)


def required_text(value: object, *, label: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{label} must be a non-empty string.")
    return value.strip()


def optional_text(value: object, *, label: str) -> str | None:
    if value is None:
        return None
    return required_text(value, label=label)


def text_tuple(value: object, *, label: str) -> tuple[str, ...]:
    if not isinstance(value, tuple | list):
        raise ValueError(f"{label} must be a list of strings.")
    return tuple(
        required_text(item, label=f"{label}[{index}]")
        for index, item in enumerate(value)
    )


__all__ = [
    "ARTIFACT_STEM_PATTERN",
    "FIGURE_ID_PATTERN",
    "optional_text",
    "required_text",
    "text_tuple",
]
