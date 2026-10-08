"""An internal source/native checkpoint for template creation before publication."""

from pathlib import Path
from typing import Any

from sciplot_core.foundation.source_tree import source_tree_sha256
from sciplot_core.studio_core.project_query_paths import canonical_path
from sciplot_core.studio_core.source_update_commit import file_inventory
from sciplot_core.task_contract import TaskControlError
from sciplot_core.task_storage import save_task


def is_prepared(state: dict[str, Any]) -> bool:
    return state.get("defer_creation_export") is True and isinstance(state.get("prepared_creation"), dict)


def require_prepared_current(state: dict[str, Any]) -> None:
    if not is_prepared(state):
        raise TaskControlError("prepared_creation_missing", "This task has no completed native preparation checkpoint.")
    checkpoint = state["prepared_creation"]
    source = canonical_path(Path(state["request"]["source"]))
    if source_tree_sha256(source) != checkpoint["source_sha256"]:
        raise TaskControlError("source_changed", "The original source changed after native preparation; do not rebuild or adopt this checkpoint.")
    project = canonical_path(Path(checkpoint["project"]))
    if not project.is_dir() or file_inventory(project) != checkpoint["files"]:
        raise TaskControlError("prepared_project_changed", "The prepared native project changed before template adoption; preserve it and resolve the conflict.")


def checkpoint_prepared(root: Path, state: dict[str, Any], prepared: dict[str, Any]) -> None:
    project = canonical_path(Path(prepared["project_dir"]))
    source = canonical_path(Path(state["request"]["source"]))
    if source_tree_sha256(source) != state["source_sha256"]:
        raise TaskControlError("source_changed", "The original source changed during native preparation.")
    for key in ("document", "request"):
        path = canonical_path(Path(prepared[key]))
        if not path.is_file() or not path.is_relative_to(project):
            raise TaskControlError("prepared_project_invalid", "The prepared native document and request must exist within their bound project.")
    state["project"] = str(project)
    state["prepared_creation"] = {"project": str(project), "source_sha256": state["source_sha256"],
                                  "files": file_inventory(project)}
    state["result"] = {"kind": "sciplot_project_prepared_result", "version": 1, "status": "prepared",
                       **{key: prepared[key] for key in ("project_dir", "document", "request")},
                       "ready_to_use": False, "export_performed": False,
                       "prepared_evidence": {"path": str(root / "task.json"), "json_pointer": "/prepared_creation"}}
    complete_prepared(root, state)


def complete_prepared(root: Path, state: dict[str, Any]) -> None:
    require_prepared_current(state)
    state.update(status="complete", phase="prepared")
    state.pop("blocker", None)
    save_task(root, state)
