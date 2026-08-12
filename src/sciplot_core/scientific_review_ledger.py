"""Select reviewable scientific-transform payloads from persisted ledgers."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any


_BLOCKING_LEDGER_STATUSES = {
    "blocked",
    "failed",
    "incomplete_lineage",
    "pending_runtime",
}
_BLOCKING_STEP_STATUSES = {"blocked", "failed"}


def scientific_transform_review_input_from_ledger(
    ledger: object,
) -> tuple[dict[str, Any], str | None, str | None] | None:
    """Return payload plus its persisted ledger and step statuses."""

    selected = _scientific_transform_step_from_ledger(ledger)
    if selected is None:
        return None
    step, payload = selected
    ledger_status = (
        _optional_text(ledger.get("status")) if isinstance(ledger, Mapping) else None
    )
    step_status = _optional_text(step.get("confirmation_status"))
    return payload, ledger_status, step_status


def scientific_transform_ledger_blocker(
    ledger_status: str | None,
    step_status: str | None,
) -> tuple[str, str] | None:
    """Return the persisted subject and status that block review, if any."""

    if ledger_status in _BLOCKING_LEDGER_STATUSES:
        return "ledger", ledger_status
    if step_status in _BLOCKING_STEP_STATUSES:
        return "transform step", step_status
    return None


def scientific_transform_payload_from_ledger(
    ledger: object,
) -> dict[str, Any] | None:
    """Find the newest scientific-transform payload in an existing ledger."""

    selected = _scientific_transform_step_from_ledger(ledger)
    return selected[1] if selected is not None else None


def _scientific_transform_step_from_ledger(
    ledger: object,
) -> tuple[Mapping[str, object], dict[str, Any]] | None:
    if not isinstance(ledger, Mapping):
        return None
    steps = ledger.get("steps")
    if not isinstance(steps, list):
        return None
    for step in reversed(steps):
        if not isinstance(step, Mapping):
            continue
        parameters = step.get("parameters")
        if not isinstance(parameters, Mapping):
            continue
        payload = parameters.get("scientific_transform")
        if isinstance(payload, Mapping):
            return step, dict(payload)
    return None


def _optional_text(value: object) -> str | None:
    return value.strip() if isinstance(value, str) and value.strip() else None


__all__ = [
    "scientific_transform_ledger_blocker",
    "scientific_transform_payload_from_ledger",
    "scientific_transform_review_input_from_ledger",
]
