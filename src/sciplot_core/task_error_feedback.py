"""Bounded transport errors; complete diagnostic text remains local and inspectable."""

from __future__ import annotations

import json
import os
from copy import deepcopy
from pathlib import Path
import tempfile
from typing import Any

MESSAGE_LIMIT = 360


def short_error_message(message: str) -> str:
    """Bound narration, never the structured scientific fields that explain it."""
    return message if len(message) <= MESSAGE_LIMIT else message[:MESSAGE_LIMIT - 1] + "…"


def exception_feedback(exc: Exception, *, summary: str | None = None) -> dict[str, Any]:
    """Preserve long pre-task failures privately instead of discarding their tail."""
    message = str(exc) or type(exc).__name__
    display = message if summary is None else summary
    result: dict[str, Any] = {"message": short_error_message(display)}
    # A transport may already carry the original owner's saved diagnostics.
    # Preserve that reference even when its human-readable message is short.
    existing_diagnostics = getattr(exc, "diagnostics", None)
    if isinstance(existing_diagnostics, dict):
        result["diagnostics"] = deepcopy(existing_diagnostics)
    field = getattr(exc, "field", None)
    if field:
        result["field"] = "/" + str(field).lstrip("/")
    issues = getattr(exc, "issues", None)
    if isinstance(issues, list) and issues and getattr(exc, "repair", None) is None:
        result["issues"] = deepcopy(issues[:8])
        if len(issues) > 8:
            result["issues"].append({"remaining_issue_count": len(issues) - 8})
    if len(display) <= MESSAGE_LIMIT:
        return result
    diagnostic = existing_diagnostics or getattr(exc, "_sciplot_diagnostic", None)
    if diagnostic is None:
        name: str | None = None
        try:
            descriptor, name = tempfile.mkstemp(prefix="sciplot-error-", suffix=".json")
            with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
                json.dump({"exception_type": type(exc).__name__,
                           "reason_code": getattr(exc, "reason_code", None),
                           "message": message}, stream, ensure_ascii=False)
            diagnostic = {"path": str(Path(name).resolve()), "json_pointer": "/message"}
            exc.__dict__["_sciplot_diagnostic"] = diagnostic
        except Exception as error:
            if name is not None:
                try:
                    Path(name).unlink(missing_ok=True)
                except OSError:
                    pass
            # Diagnostic storage is auxiliary: never replace the original failure
            # or silently lose its tail when a full local copy cannot be written.
            return {**result, "message": message,
                    "diagnostics_unavailable": short_error_message(str(error))}
        except BaseException:
            if name is not None:
                try:
                    Path(name).unlink(missing_ok=True)
                except OSError:
                    pass
            raise
    result["diagnostics"] = diagnostic
    return result


_SAVED_WORK_REASONS = {
    "saved_work_not_found": "No saved plot matched the source in the searched folders.",
    "saved_work_selection_required": "More than one possible target was found, or the search could not be completed.",
    "selected_target_not_discovered": "The requested target is not in the current search results.",
    "figure_selection_mismatch": "The selected plot does not contain the requested figure ID.",
    "source_changed_during_continuation": "The source became unreadable or changed during the search.",
    "source_revision_required": "The saved plot requires an explicit source revision.",
    "legacy_conversion_required": "The saved figure is read-only until a separate copy is converted.",
    "invalid_search_root": "The search location is not a project or data folder.",
    "search_scope_too_broad": "The search scope is too broad.",
}
_SAVED_WORK_STEPS = {
    "find_saved_work_again": "Check the source path and its read access, then search the project folder again.",
    "select_saved_target": "Choose the exact project and figure from the local results.",
    "inspect_selected_conflict": "Open the selected project again and check its current revision.",
    "plot.open": "Open the selected figure and review its local result.",
    "resolve_saved_authority": "Inspect the selected saved plot and its local continuation instructions.",
    "task.start": "Review the source revision using the instructions in the local result.",
    "fill_operations_then_start": "Use the local result to make an explicit edit on the current figure.",
}


def shareable_saved_work_summary(result: dict[str, Any]) -> dict[str, Any]:
    """Render fixed public text, never an error message or any part of its evidence."""
    observed = result.get("status")
    if observed == "current":
        status, code, message = "current", "saved_work_current", "The selected saved figure is current."
    else:
        status = "needs_selection" if observed == "needs_selection" else "blocked"
        reason = result.get("reason_code")
        code = reason if isinstance(reason, str) and reason in _SAVED_WORK_REASONS else "saved_work_unavailable"
        message = _SAVED_WORK_REASONS.get(code, "SciPlot could not confirm a current saved figure.")
    step = result.get("next_step")
    action = step.get("action") if isinstance(step, dict) else None
    if not isinstance(action, str) or action not in _SAVED_WORK_STEPS:
        action = "find_saved_work_again" if code in {"invalid_search_root", "search_scope_too_broad"} else "inspect_local_result"
    return {"kind": "sciplot_shareable_diagnostic", "version": 1, "workflow": "saved_work_continuation",
            "status": status, "reason_code": code, "message": message,
            "next_step": {"action": action, "message": _SAVED_WORK_STEPS.get(
                action, "Run the same command without --shareable-diagnostic to inspect the local details.")}}
