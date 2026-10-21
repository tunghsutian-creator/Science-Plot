"""Recommend actions for failed required checks."""

from __future__ import annotations

from typing import Any


def _next_actions(required_failures: list[dict[str, Any]]) -> list[str]:
    if not required_failures:
        return [
            "Use task capabilities, then task start/resume for external-AI plotting, column choices, source updates, and delivery.",
            "Use Open_in_SciPlot.command for manual adjustments, then Save and update delivery; Open_in_Veusz.command remains the advanced and portable-copy fallback.",
            "Use assisted repair only when the deterministic result reports a blocking state.",
        ]
    actions: list[str] = []
    failed_ids = {str(check["id"]) for check in required_failures}
    if "pyqt6" in failed_ids:
        actions.append("Install the PyQt6 Studio dependency in this Python environment.")
    if "veusz_vendor" in failed_ids:
        actions.append("Restore the vendored Veusz source tree.")
    if "veusz_qt_runtime" in failed_ids:
        runtime_detail = next(
            str(check.get("detail") or "")
            for check in required_failures
            if check["id"] == "veusz_qt_runtime"
        )
        if runtime_detail.startswith("PyQt6/Qt runtime cannot load"):
            actions.append(
                "Repair the PyQt6/Qt runtime shared-library load in this Python "
                "environment before checking or rebuilding Veusz native helpers."
            )
        elif runtime_detail != "PyQt6 is not importable.":
            actions.append(
                "Build the vendored Veusz native helpers for this Python/PyQt6/Qt runtime; "
                "check the optional Qt 6 qmake, sip-build, and C++ source-build diagnostics."
            )
    if "python_version" in failed_ids:
        actions.append("Use Python 3.11 or newer.")
    if "ready_rules" in failed_ids:
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
