"""Small transport receipts; durable state and scientific questions stay complete."""

from copy import deepcopy
from typing import Any


def compact_task_result(payload: dict[str, Any]) -> dict[str, Any]:
    if payload.get("kind") != "sciplot_task":
        return payload
    result = deepcopy(payload)
    # Keep pending questions, review images, audits, errors and revision bindings.
    # They may require judgment; size alone cannot make them safe to suppress.
    next_step = result.get("next_step")
    if isinstance(next_step, dict):
        next_step.pop("task", None)  # Same exact reference is already in task_dir.
    timing = result.get("local_timing")
    if isinstance(timing, dict):
        timing.pop("last_call_phases_seconds", None)
    if result.get("status") != "complete":
        return result
    if result.get("profile") is None:
        result.pop("profile", None)
        result.pop("profile_unavailable", None)
    current = result.get("current_project")
    if isinstance(current, dict):
        current.pop("project", None)
        for figure in current.get("figures", []):
            for key in ("spec", "spec_sha256"):
                figure.pop(key, None)
        for key in ("source", "qa", "delivery"):
            evidence = current.get(key)
            # Uncertain/stale evidence remains intact, including failed checks.
            if (isinstance(evidence, dict) and evidence.get("current") is True
                    and evidence.get("status") == "current" and not evidence.get("error")
                    and not evidence.get("failed_checks")):
                current[key] = {name: value for name, value in evidence.items() if name in {
                    "status", "current", "scope", "scientific_audit_evaluated", "path",
                }}
    receipt = result.get("result")
    if isinstance(receipt, dict) and receipt.get("kind") in {
        "sciplot_project_creation_result", "sciplot_project_export_result",
    }:
        for key in ("version", "project_dir", "request"):
            receipt.pop(key, None)
        if (isinstance(current, dict) and current.get("figures")
                and isinstance(next_step, dict) and next_step.get("action") == "review_exports_and_deliver"):
            receipt.pop("figures", None)
            receipt.pop("document", None)
        run = receipt.get("studio_run")
        if isinstance(run, dict):
            run.pop("manifest", None)
    return result
