"""Canonical states shared by deterministic automation and publication gates."""

from __future__ import annotations

from typing import Final, Literal, TypeGuard


AutomationState = Literal[
    "ready",
    "needs_human_confirmation",
    "needs_rule_repair",
]

READY_STATE: Final[AutomationState] = "ready"
HUMAN_CONFIRMATION_STATE: Final[AutomationState] = "needs_human_confirmation"
RULE_REPAIR_STATE: Final[AutomationState] = "needs_rule_repair"

VALID_AUTOMATION_STATES: Final[frozenset[str]] = frozenset(
    {
        READY_STATE,
        HUMAN_CONFIRMATION_STATE,
        RULE_REPAIR_STATE,
    }
)


def is_automation_state(value: object) -> TypeGuard[AutomationState]:
    """Return whether a value is one of the closed automation states."""

    return isinstance(value, str) and value in VALID_AUTOMATION_STATES


def fail_closed_automation_state(value: object) -> AutomationState:
    """Return a validated state or the repair state for invalid input."""

    return value if is_automation_state(value) else RULE_REPAIR_STATE


__all__ = [
    "AutomationState",
    "HUMAN_CONFIRMATION_STATE",
    "READY_STATE",
    "RULE_REPAIR_STATE",
    "VALID_AUTOMATION_STATES",
    "fail_closed_automation_state",
    "is_automation_state",
]
