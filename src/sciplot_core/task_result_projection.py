"""Project task results and evidence without owning execution or durable state."""

from collections.abc import Callable
from copy import deepcopy
from pathlib import Path
from subprocess import TimeoutExpired
from typing import Any

from sciplot_core.task_error_feedback import short_error_message
from sciplot_core.task_storage import task_summary


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
    if result.get("status") == "blocked" and isinstance(result.get("task_dir"), str):
        # Full diagnostics are already durable. Only shorten narration, preserving
        # failed scientific evidence, current identities and the exact recovery step.
        result["diagnostics"] = {"path": str(Path(result["task_dir"]) / "task.json")}
        blocker = result.get("blocker")
        if isinstance(blocker, dict):
            for key in ("message", "recovery"):
                if isinstance(blocker.get(key), str):
                    blocker[key] = short_error_message(blocker[key])
        run = (result.get("result") or {}).get("studio_run")
        if isinstance(run, dict) and isinstance(run.get("failure_reason"), str):
            run["failure_reason"] = short_error_message(run["failure_reason"])
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


def current_task_result(state: dict[str, Any], *, inspect_project: Callable[[Path], dict[str, Any]]) -> dict[str, Any]:
    if "intent" in state["request"]:
        from sciplot_core.task_semantic_creation import current_result

        return current_result(state)
    summary = task_summary(state)
    if state.get("defer_creation_export") is True and "prepared_creation" in state:
        from sciplot_core.task_prepared_creation import require_prepared_current

        try:
            require_prepared_current(state)
        except (ValueError, OSError) as exc:
            summary.update(status="blocked", blocker={"reason_code": getattr(exc, "reason_code", "prepared_project_changed"),
                           "message": str(exc)}, next_step={"action": "resolve_prepared_conflict"})
        return summary
    if state.get("project"):
        try:
            current = inspect_project(Path(state["project"]))
            summary["current_project"] = {key: current[key] for key in (
                "project", "primary_figure_id", "figures", "source", "qa", "delivery",
                "ready_to_use", "readiness_evaluated", "document_authority", "live_gui_state_evaluated",
            ) if key in current}
            if (state["status"] == "complete" and (state.get("result", {}).get("studio_run") or {}).get("ready_to_use") is True
                    and all((current.get(key) or {}).get("current") is True for key in ("source", "qa", "delivery"))):
                summary["next_step"] = {
                    "action": "review_exports_and_deliver", "task": state["task_dir"],
                    "images": [item["path"] for figure in state["result"].get("figures", [])
                               for item in figure.get("exports", []) if item.get("format") == "tiff"],
                    "message": "Current source/QA/delivery were queried in this call. Review the exported images, then deliver; requery after later changes. No additional native preview or inspect is required for this unchanged result.",
                }
            elif (state["status"] == "complete"
                  and (state.get("result", {}).get("studio_run") or {}).get("ready_to_use") is True):
                summary["next_step"] = {
                    "action": "resolve_current_evidence", "task": state["task_dir"],
                    "evidence_gaps": [key for key in ("source", "qa", "delivery")
                                      if (current.get(key) or {}).get("current") is not True],
                    "message": "This call already inspected the current project. Resolve the missing or stale evidence in current_project; repeating inspect with unchanged files cannot repair it. Existing export paths remain in result.figures for visual review, not proof of current readiness. Do not regenerate data or re-export merely to replace an unknown source fingerprint with a claim of success.",
                }
        except (ValueError, OSError, RuntimeError, TimeoutExpired) as exc:
            summary["current_project"] = {"status": "unknown", "message": str(exc)}
    return summary
