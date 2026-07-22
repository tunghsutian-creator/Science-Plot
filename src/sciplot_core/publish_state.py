from __future__ import annotations

from typing import Any


PUBLISH_GATE_REPORT_KIND = "sciplot_publish_gate_report"
PUBLISH_GATE_REPORT_VERSION = 1

READY_STATE = "ready"
RULE_REPAIR_STATE = "needs_rule_repair"
HUMAN_CONFIRMATION_STATE = "needs_human_confirmation"
_PRESERVED_BLOCKING_STATES = {RULE_REPAIR_STATE, HUMAN_CONFIRMATION_STATE}


def build_publish_state(
    *,
    qa: object,
    package_contract: object,
    delivery_package: object,
    delivery_verification: object | None = None,
    prerequisite_state: object | None = None,
) -> dict[str, Any]:
    """Derive the final manifest state from explicit publication gates.

    The function is deliberately filesystem-free: package construction,
    delivery copying, and exact-current verification stay with their existing
    owners.  Callers pass the resulting records here so Workflow and Studio
    cannot disagree about what ``ready_to_use`` means.
    """

    qa_payload = qa if isinstance(qa, dict) else {}
    package_payload = package_contract if isinstance(package_contract, dict) else {}
    delivery_payload = delivery_package if isinstance(delivery_package, dict) else {}
    gates = {
        "qa_passed": qa_payload.get("status") == "passed",
        "package_contract_complete": package_payload.get("complete") is True,
        "delivery_package_complete": delivery_payload.get("complete") is True,
    }
    if delivery_verification is not None:
        verification_payload = (
            delivery_verification if isinstance(delivery_verification, dict) else {}
        )
        gates["delivery_verification_passed"] = (
            verification_payload.get("passed") is True
        )
    if prerequisite_state is not None:
        gates["prerequisite_state_ready"] = prerequisite_state == READY_STATE

    failed_gates = [gate_id for gate_id, passed in gates.items() if not passed]
    ready_to_use = not failed_gates
    if ready_to_use:
        state = READY_STATE
    elif prerequisite_state in _PRESERVED_BLOCKING_STATES:
        state = str(prerequisite_state)
    else:
        state = RULE_REPAIR_STATE
    return {
        "state": state,
        "ready_to_use": ready_to_use,
        "publish_gates": {
            "kind": PUBLISH_GATE_REPORT_KIND,
            "version": PUBLISH_GATE_REPORT_VERSION,
            "status": "passed" if ready_to_use else "failed",
            "passed": ready_to_use,
            "gates": gates,
            "failed_gates": failed_gates,
        },
    }


__all__ = ["build_publish_state"]
