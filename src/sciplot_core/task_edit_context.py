"""Read current saved-edit inputs together without allocating or resuming a task."""

from pathlib import Path
from typing import Any

from sciplot_core.doctor import doctor_payload
from sciplot_core.studio_core.annotation_operations import require_edit_source_current
from sciplot_core.studio_core.control_results import compact_result
from sciplot_core.studio_core.project_query import inspect_project
from sciplot_core.studio_core.project_query_paths import canonical_path
from sciplot_core.task_capabilities import edit_context_capabilities
from sciplot_core.task_contract import TaskControlError
from sciplot_core.task_storage import load_task, task_path, task_summary


def edit_context(target: Path, *, operations: list[str], figure_id: str | None = None) -> dict[str, Any]:
    """Compose existing read owners; readiness, review and export stay separate."""
    capabilities = edit_context_capabilities(operations)
    path = canonical_path(target)
    root = task_path(path)
    if path.name == "task.json" or (root / "task.json").is_file():
        state = load_task(root)
        if state["status"] not in {"complete", "cancelled"}:
            current_task = task_summary(state)
            return {"kind": "sciplot_task_edit_context", "version": 1, "status": "blocked",
                    "reason_code": "unfinished_task", "current_task": current_task,
                    "next_step": current_task["next_step"],
                    "message": "Continue the existing task; its current review or recovery must finish before a new edit."}
        if not state.get("project"):
            raise TaskControlError("task_has_no_project", "This task has no saved project to edit.")
        path = Path(state["project"])
        figure_id = figure_id or state["request"].get("figure_id")

    runtime = doctor_payload()
    doctor = {"kind": runtime["kind"], "status": runtime["status"],
              "failed_checks": [item for item in runtime["checks"] if item.get("status") != "passed"]}
    if runtime["status"] != "ready":
        return {"kind": "sciplot_task_edit_context", "version": 1, "status": "blocked",
                "reason_code": "runtime_not_ready", "doctor": doctor,
                "next_step": {"action": "repair_runtime", "next_actions": runtime.get("next_actions", [])}}

    names = set(capabilities["operation_names"])
    annotations = bool(names & {"add_annotation", "add_reference_line", "add_peak_label",
                                "remove_annotation", "update_annotation"})
    axes = bool(names & {"add_annotation", "add_reference_line", "add_peak_label",
                         "update_annotation", "set_axis_range"})
    current = inspect_project(
        path, figure_id=figure_id, native=bool(names & {"set_style", "add_peak_label"}),
        include_annotations=annotations, include_axes=axes,
    )
    require_edit_source_current(current)
    if "objects" in current["selected_figure"]:
        current = compact_result(current)
    selected = current["selected_figure"]
    result: dict[str, Any] = {"kind": "sciplot_task_edit_context", "version": 1, "status": "ok",
              "doctor": doctor, "capabilities": capabilities,
              "current_project": {key: current[key] for key in (
                  "project", "source", "qa", "delivery", "ready_to_use", "readiness_evaluated",
                  "document_authority", "live_gui_state_evaluated")},
              "selected_figure": selected,
              "request_template": {"version": 1, "action": "edit", "project": current["project"],
                                   "figure_id": selected["figure_id"],
                                   "expected_document_sha256": selected["document_sha256"],
                                   "operations": []},
              "next_step": {"action": "fill_operations_then_start",
                            "cli": "task start --request REQUEST_JSON_FILE --json",
                            "message": "Fill request_template.operations with the complete authorized batch, using only selected schemas and current targets. Review the returned candidate image and scientific audit, then resume with its response_template. No additional Doctor, capability or inspect call is needed for this unchanged context."}}
    if "add_peak_label" in names:
        result["next_step"]["peak_evidence"] = "A peak label still requires a current source-bound candidate from project peaks; do not infer a candidate from image coordinates."
    return result
