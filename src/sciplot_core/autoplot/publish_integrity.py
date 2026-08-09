"""Verify manifest publication integrity."""

from __future__ import annotations

from typing import Any

from sciplot_core.foundation.json_values import json_safe
from sciplot_core.publish_state import build_publish_state

from sciplot_core.autoplot.contracts import (
    _VALID_STATES,
)


def _manifest_publish_integrity(manifest: dict[str, Any]) -> dict[str, Any]:
    one_step_value = manifest.get("one_step")
    manifest_one_step = one_step_value if isinstance(one_step_value, dict) else {}
    qa_value = manifest.get("qa")
    qa = qa_value if isinstance(qa_value, dict) else {}
    package_contract_value = manifest.get("package_contract")
    package_contract = (
        package_contract_value if isinstance(package_contract_value, dict) else {}
    )
    delivery_package_value = manifest.get("delivery_package")
    delivery_package = (
        delivery_package_value if isinstance(delivery_package_value, dict) else {}
    )
    expected = build_publish_state(
        qa=qa,
        package_contract=package_contract,
        delivery_package=delivery_package,
        prerequisite_state=manifest_one_step.get("state"),
        resolved_figure_plan=manifest.get("resolved_figure_plan"),
    )
    publish_gates_value = manifest.get("publish_gates")
    recorded_gates = (
        publish_gates_value if isinstance(publish_gates_value, dict) else {}
    )
    recorded_state = str(manifest.get("state") or "").strip()
    recorded_ready = manifest.get("ready_to_use")
    checks = {
        "state_recorded": recorded_state in _VALID_STATES,
        "ready_to_use_recorded": type(recorded_ready) is bool,
        "state_matches_gates": recorded_state == expected["state"],
        "ready_to_use_matches_gates": (
            type(recorded_ready) is bool and recorded_ready is expected["ready_to_use"]
        ),
        "publish_gates_match": recorded_gates == expected["publish_gates"],
    }
    return {
        "valid": all(checks.values()),
        "checks": checks,
        "recorded_state": recorded_state,
        "recorded_ready_to_use": recorded_ready,
        "recorded_publish_gates": json_safe(recorded_gates),
        "expected": json_safe(expected),
        "package_contract_complete": package_contract.get("complete") is True,
    }
