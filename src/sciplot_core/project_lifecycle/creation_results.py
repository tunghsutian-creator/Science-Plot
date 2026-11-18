"""Current-evidence projection shared by ordinary and template creation."""

from pathlib import Path
from typing import Any

from sciplot_core.task_control import inspect_task
from sciplot_core.task_result_projection import compact_task_result

from sciplot_core.plot_engine.backend import PlotOpener
from sciplot_core.project_lifecycle.context import write


def _result(service: PlotOpener, root: Path, state: dict[str, Any], task: dict[str, Any]) -> dict[str, Any]:
    if task["status"] == "complete" and task.get("project") and "current_project" not in task:
        task = inspect_task(root / "task")
    state["task_result"] = task
    write(root / "creation.json", state)
    if "source_plan" in task:
        return _managed_result(root, task)
    if task["status"] == "complete" and task.get("project"):
        current = task.get("current_project") or {}
        gaps = [key for key in ("source", "qa", "delivery") if (current.get(key) or {}).get("current") is not True]
        if (task.get("result", {}).get("studio_run") or {}).get("ready_to_use") is not True:
            gaps.append("completed_export")
        if gaps:
            return _stale_result(root, task, gaps)
        plot = service.open(Path(task["project"]))
        if plot.get("kind") == "sciplot_legacy_plot" and plot.get("status") == "opened" and plot.get("read_only") is True:
            return {"kind": "sciplot_plot_creation", "status": "complete", "plot": plot["document"]["path"],
                    "project": task["project"], "document": plot["document"],
                    "plot_type": "LegacyPlot", "read_only": True, "new_features_require_conversion": True,
                    "conversion": plot["conversion"], "creation_evidence": str(root / "creation.json"),
                    "ready_to_use": True, "current_evidence": {key: current[key] for key in ("source", "qa", "delivery")},
                    "figures": task["result"].get("figures", []), "delivery": task.get("next_step"),
                    "next_step": {"action": "deliver"}}
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


def _managed_result(root: Path, task: dict[str, Any]) -> dict[str, Any]:
    reply: dict[str, Any] = {"kind": "sciplot_plot_creation", "status": task["status"], "plot": str(root),
             "plot_type": "ManagedPlot", "ready_to_use": False, "creation_evidence": str(root / "creation.json")}
    compact = compact_task_result(task)
    current = task.get("current_project") or {}
    next_step = compact.get("next_step") or {}
    if task.get("ready_to_use") is True and current.get("status") == "current":
        export = task["result"]
        return {**reply, **{key: current[key] for key in ("plot", "plot_id", "revision", "coverage", "authority")},
                "ready_to_use": True, "read_only": False, "project": task["project"],
                "plot_objects": export["plot_objects"], "exports": export["exports"],
                "analysis_metrics": task.get("analysis_metrics", []), "delivery": task.get("next_step"),
                "current_evidence": {"source_plan": task["source_plan"], "export": current["export_current"]},
                "next_step": {"action": "deliver"}}
    if task.get("blocker"):
        reply["blocker"] = compact.get("blocker")
    elif task.get("question"):
        reply["question"] = compact.get("question")
    reply["next_step"] = {"action": "plot.decide", "plot": str(root), "task_continuation": next_step}
    if task["status"] in {"running", "blocked"} and not task.get("question"):
        reply["next_step"]["request"] = {"response": {"retry": True}}
    return reply


def _stale_result(root: Path, task: dict[str, Any], gaps: list[str], *, plot: dict[str, Any] | None = None) -> dict[str, Any]:
    return {"kind": "sciplot_plot_creation", "status": "blocked", "creation_status": "complete",
            "plot": (plot or {}).get("plot") or str(root), "project": task["project"], "ready_to_use": False,
            "creation_evidence": str(root / "creation.json"),
            "blocker": {"reason_code": "document_creation_evidence_stale",
                        "message": "Creation completed, but current source, native or delivery evidence is missing or changed.",
                        "evidence_gaps": gaps},
            "next_step": {"action": "resolve_current_evidence", "evidence_gaps": gaps}}
