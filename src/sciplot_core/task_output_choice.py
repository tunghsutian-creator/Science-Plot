"""Detect output conflicts before planning; only explicit pre-creation choices resume."""

from pathlib import Path
from typing import Any

from sciplot_core.foundation.json_hashing import canonical_json_sha256
from sciplot_core.output_contract import resolve_user_output_layout
from sciplot_core.studio_core.project_query_paths import canonical_path
from sciplot_core.task_contract import TaskControlError
from sciplot_core.task_storage import task_location


def creation_output(state: dict[str, Any]) -> str | None:
    value = (state.get("output_selection") or {}).get("out", state["request"].get("out"))
    return str(value) if value is not None else None


def require_available_output(state: dict[str, Any]) -> bool:
    layout = resolve_user_output_layout(state["request"]["source"], requested_delivery_root=creation_output(state))
    occupied = [str(p) for p in (layout.delivery_root, layout.workspace_root) if p.exists()]
    if not occupied:
        return True
    question = {"field": "out", "reason_code": "output_exists", "occupied_paths": occupied,
                "source_sha256": state["source_sha256"],
                "message": "Choose a new out in this task, or inspect the existing task/project. Do not move or overwrite existing outputs. Native creation has not started."}
    question["question_id"] = canonical_json_sha256(question)
    state.update(status="needs_input", phase="output_choice", question=question)
    state.pop("blocker", None)
    return False


def accept_output_response(state: dict[str, Any], response: dict[str, Any]) -> None:
    if (state["request"]["action"] != "create" or state["status"] != "needs_input"
            or state["phase"] != "output_choice" or state.get("project")
            or set(response) != {"expected_question_id", "out"}
            or not isinstance(response.get("out"), str) or not response["out"].strip()):
        raise TaskControlError("invalid_task_response", "只能在建项前的 out 问题中选择新输出路径。")
    if response["expected_question_id"] != state["question"]["question_id"]:
        raise TaskControlError("stale_task_question", "输出选择对应旧问题，请使用当前 question_id。")
    out = str(canonical_path(Path(response["out"])))
    # Reuse task/source/output overlap guards before recording any change.
    try:
        task_location({**state["request"], "out": out}, Path(state["task_dir"]))
    except TaskControlError as exc:
        raise TaskControlError("invalid_task_response", str(exc)) from exc
    state.setdefault("output_choice_history", []).append({"question": state["question"], "response": response})
    state["output_selection"] = {"out": out}
    state.pop("question", None)
    state.update(status="running", phase="starting")
