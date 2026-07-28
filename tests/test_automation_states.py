from __future__ import annotations

from sciplot_core.automation_states import (
    HUMAN_CONFIRMATION_STATE,
    READY_STATE,
    RULE_REPAIR_STATE,
    VALID_AUTOMATION_STATES,
    fail_closed_automation_state,
    is_automation_state,
)
from sciplot_core.autoplot.contracts import _VALID_STATES
from sciplot_core import one_step
from sciplot_core import publish_state


def test_automation_states_have_one_closed_owner() -> None:
    assert VALID_AUTOMATION_STATES == {
        "ready",
        "needs_human_confirmation",
        "needs_rule_repair",
    }
    assert _VALID_STATES is VALID_AUTOMATION_STATES
    assert one_step.READY_STATE == READY_STATE
    assert one_step.HUMAN_CONFIRMATION_STATE == HUMAN_CONFIRMATION_STATE
    assert one_step.RULE_REPAIR_STATE == RULE_REPAIR_STATE
    assert publish_state.READY_STATE == READY_STATE
    assert publish_state.HUMAN_CONFIRMATION_STATE == HUMAN_CONFIRMATION_STATE
    assert publish_state.RULE_REPAIR_STATE == RULE_REPAIR_STATE


def test_automation_state_validation_fails_closed() -> None:
    assert is_automation_state("ready") is True
    assert is_automation_state("editing") is False
    assert fail_closed_automation_state("needs_human_confirmation") == (
        "needs_human_confirmation"
    )
    assert fail_closed_automation_state("unknown") == "needs_rule_repair"
    assert fail_closed_automation_state(None) == "needs_rule_repair"
