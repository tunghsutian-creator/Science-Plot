"""Recommend actions for failed required checks."""

from __future__ import annotations

from typing import Any


def _next_actions(required_failures: list[dict[str, Any]]) -> list[str]:
    if not required_failures:
        return [
            "Use the Studio daily entrypoint for deterministic plotting and delivery.",
            "Use Open_in_Veusz.command when the generated document needs manual correction.",
            "Use assisted repair only when the deterministic result reports a blocking state.",
        ]
    actions: list[str] = []
    failed_ids = {str(check["id"]) for check in required_failures}
    if {"pyqt6", "veusz_vendor", "veusz_qt_runtime"} & failed_ids:
        actions.append(
            "Install the Studio dependencies and verify the vendored Veusz runtime."
        )
    if "python_version" in failed_ids:
        actions.append("Use Python 3.11 or newer.")
    if {"ready_rules", "ready_rule_fixtures"} & failed_ids:
        actions.append(
            "Keep automatic plotting limited to fixture-backed ready material rules."
        )
    if "validated_envelopes" in failed_ids:
        actions.append(
            "Re-run ready-rule real-data acceptance and certify the current "
            "deterministic rule contracts before returning ready_to_use."
        )
    if "publication_foundation" in failed_ids:
        actions.append(
            "Restore the single-panel publication profile, lineage contracts, "
            "and artifact QA."
        )
    if "style_template_contract" in failed_ids:
        actions.append(
            "Resolve template-private style or implementation drift before "
            "returning the runtime to daily use."
        )
    if not actions:
        actions.append("Fix the failed required checks before normal use.")
    return actions
