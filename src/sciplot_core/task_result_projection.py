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


def _selected_publication(
    current: dict[str, Any], state: dict[str, Any]
) -> tuple[dict[str, Any] | None, bool]:
    """Keep the current package and the task's recorded run distinct."""
    receipt = state["result"]
    selected_id = state["request"].get("figure_id") or (state.get("edit_outcome") or {}).get("figure_id")
    if selected_id is None and state["request"]["action"] == "edit":
        selected_id = current.get("primary_figure_id")
    historical = {item["figure_id"]: item for item in receipt.get("figures", [])
                  if item.get("figure_id") and (selected_id is None or item["figure_id"] == selected_id)}
    value = current["delivery"].get("publication")
    if not historical or not value:
        return None, False
    figures = [item for item in value["figures"] if item["figure_id"] in historical]
    if {item["figure_id"] for item in figures} != historical.keys():
        return None, False
    publication = {**value, "figures": figures}

    def export_keys(figure: dict[str, Any]) -> set[tuple[str, str]]:
        return {(item["format"], item["path"]) for item in figure.get("exports", [])}

    matches = (
        receipt["studio_run"].get("manifest") == publication["manifest"]
        and all(
            export_keys(figure) == export_keys(historical[figure["figure_id"]])
            and historical[figure["figure_id"]].get("document_sha256", figure["document_sha256"])
            == figure["document_sha256"]
            for figure in figures
        )
    )
    return publication, matches


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
            if (state["status"] == "complete"
                    and (state.get("result", {}).get("studio_run") or {}).get("ready_to_use") is True):
                gaps = [key for key in ("source", "qa", "delivery") if (current.get(key) or {}).get("current") is not True]
                publication, matches = (None, False) if gaps else _selected_publication(current, state)
                if matches and publication is not None:
                    summary["next_step"] = {
                        "action": "review_exports_and_deliver", "task": state["task_dir"],
                        "publication": publication,
                        "images": [item["path"] for figure in publication["figures"]
                                   for item in figure["exports"] if item["format"] in {"tiff", "tiff_300"}],
                        "message": "Review the verified exports for the saved revisions shown here, then deliver.",
                    }
                else:
                    historical = not gaps
                    summary["next_step"] = {
                        "action": "resolve_current_evidence", "task": state["task_dir"],
                        "evidence_gaps": gaps or ["task_publication"],
                        **({"current_publication": publication} if publication is not None else {}),
                        "message": (
                            "The task receipt does not match a verified publication of the selected current revisions. "
                            "Use only the separately identified current publication, if present; the task's export paths "
                            "are historical locators and may now contain different bytes."
                            if historical else
                            "This call already inspected the current project. Resolve the missing or stale evidence in "
                            "current_project; repeating inspect with unchanged files cannot repair it. The task's export "
                            "paths are historical locators, not proof of current readiness."
                        ),
                    }
        except (ValueError, OSError, RuntimeError, TimeoutExpired) as exc:
            summary["current_project"] = {"status": "unknown", "message": str(exc)}
    return summary
