"""Verify manifest publication integrity."""

from __future__ import annotations

from typing import Any
from sciplot_core.foundation.json_values import json_safe
from sciplot_core.publish_state import build_publish_state

from sciplot_core.autoplot.contracts import (
    _VALID_STATES,
)


def _manifest_publish_integrity(manifest: dict[str, Any]) -> dict[str, Any]:
    manifest_one_step = (
        manifest.get("one_step") if isinstance(manifest.get("one_step"), dict) else {}
    )
    qa = manifest.get("qa") if isinstance(manifest.get("qa"), dict) else {}
    package_contract = (
        manifest.get("package_contract")
        if isinstance(manifest.get("package_contract"), dict)
        else {}
    )
    delivery_package = (
        manifest.get("delivery_package")
        if isinstance(manifest.get("delivery_package"), dict)
        else {}
    )
    expected = build_publish_state(
        qa=qa,
        package_contract=package_contract,
        delivery_package=delivery_package,
        prerequisite_state=manifest_one_step.get("state"),
    )
    recorded_gates = (
        manifest.get("publish_gates")
        if isinstance(manifest.get("publish_gates"), dict)
        else {}
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
