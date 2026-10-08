"""Current-evidence projection shared by ordinary and template creation."""

from pathlib import Path
from typing import Any

from sciplot_core.task_control import inspect_task
from sciplot_core.task_result_projection import compact_task_result

from .backend import PlotOpener
from .storage import write


def _result(service: PlotOpener, root: Path, state: dict[str, Any], task: dict[str, Any]) -> dict[str, Any]:
    if task["status"] == "complete" and task.get("project") and "current_project" not in task:
        task = inspect_task(root / "task")
    state["task_result"] = task
    write(root / "creation.json", state)
    if task["status"] == "complete" and task.get("project"):
        current = task.get("current_project") or {}
        gaps = [key for key in ("source", "qa", "delivery") if (current.get(key) or {}).get("current") is not True]
        if (task.get("result", {}).get("studio_run") or {}).get("ready_to_use") is not True:
            gaps.append("completed_export")
        if gaps:
            return _stale_result(root, task, gaps)
        plot = service.open(Path(task["project"]))
        if plot.get("status") != "current":
            return _stale_result(root, task, ["semantic_document"], plot=plot)
        return {"kind": "sciplot_plot_creation", "status": "complete", "plot": plot["plot"],
                "plot_id": plot["plot_id"], "revision": plot["revision"], "coverage": plot["coverage"],
                "objects": plot["objects"], "creation_evidence": str(root / "creation.json"),
                "ready_to_use": True, "current_evidence": {key: current[key] for key in ("source", "qa", "delivery")},
                "delivery": task.get("next_step"), "next_step": {"action": "deliver"}}
    compact = compact_task_result(task)
    result = {"kind": "sciplot_plot_creation", "status": task["status"], "plot": str(root),
              "creation_evidence": str(root / "creation.json")}
    if task["status"] == "blocked":
        result.update({"blocker": compact.get("blocker"),
                       "diagnostics": {"path": str(root / "creation.json"), "json_pointer": "/task_result"},
                       "next_step": {key: value for key, value in (compact.get("next_step") or {}).items()
                                     if key not in {"task", "cli", "cli_argv"}}})
    else:
        result.update({"question": compact.get("question"),
                       "next_step": {"action": "plot.decide", "task_continuation": compact.get("next_step")}})
    return result


def _stale_result(root: Path, task: dict[str, Any], gaps: list[str], *, plot: dict[str, Any] | None = None) -> dict[str, Any]:
    return {"kind": "sciplot_plot_creation", "status": "blocked", "creation_status": "complete",
            "plot": plot["plot"] if plot else str(root), "project": task["project"], "ready_to_use": False,
            "creation_evidence": str(root / "creation.json"),
            "blocker": {"reason_code": "document_creation_evidence_stale",
                        "message": "Creation completed, but current source, native or delivery evidence is missing or changed.",
                        "evidence_gaps": gaps},
            "next_step": {"action": "resolve_current_evidence", "evidence_gaps": gaps}}


