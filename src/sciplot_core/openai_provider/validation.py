"""Validate bounded text, loopback hosts, and redacted messages."""

from __future__ import annotations

import ipaddress


def _required_text(value: object, label: str, *, maximum: int) -> str:
    if not isinstance(value, str):
        raise ValueError(f"{label} must be a string.")
    text = value.strip()
    if not text:
        raise ValueError(f"{label} must be a non-empty string.")
    if len(text) > maximum:
        raise ValueError(f"{label} must contain at most {maximum} characters.")
    return text


def _free_text(value: object, label: str, *, maximum: int) -> str:
    if not isinstance(value, str):
        raise ValueError(f"{label} must be a string.")
    text = value.strip()
    if len(text) > maximum:
        raise ValueError(f"{label} must contain at most {maximum} characters.")
    return text


def _is_loopback(hostname: str | None) -> bool:
    if hostname is None:
        return False
    lowered = hostname.casefold().rstrip(".")
    if lowered == "localhost" or lowered.endswith(".localhost"):
        return True
    try:
        return ipaddress.ip_address(lowered).is_loopback
    except ValueError:
        return False


def _redact(value: object, *, secrets: tuple[str, ...]) -> str:
    text = str(value)
    for secret in secrets:
        if secret:
            text = text.replace(secret, "[REDACTED]")
    return text.replace("\r", " ").replace("\n", " ")[:1000]
