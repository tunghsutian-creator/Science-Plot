"""An internal source/native checkpoint for template creation before publication."""

from pathlib import Path
from contextlib import contextmanager
from collections.abc import Iterator
from typing import Any

from sciplot_core.foundation.source_tree import source_tree_sha256
from sciplot_core.studio_core.project_query_paths import canonical_path
from sciplot_core.studio_core.source_update_commit import file_inventory
from sciplot_core.task_contract import TaskControlError
from sciplot_core.task_storage import save_task
from sciplot_core.task_prepared_store import prepared_store, capture, require


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
    store = prepared_store(project)
    if store is not None:
        require(store, checkpoint)
    elif checkpoint.get('store_binding') is not None or not project.is_dir() or file_inventory(project) != checkpoint["files"]:
        raise TaskControlError("prepared_project_changed", "The prepared native project changed before template adoption; preserve it and resolve the conflict.")


@contextmanager
def prepared_admission(state: dict[str, Any]) -> Iterator[None]:
    """Share host Store selection; each read/publication owns its short lease.

    A native child must never run under an independent lifetime project EX.
    The complete original resource/source guards run before and after adoption.
    """
    if not is_prepared(state):
        require_prepared_current(state)
    project = Path(state['prepared_creation']['project'])
    store = prepared_store(project)
    if store is None:
        from sciplot_core.studio_core.project_session import external_project_session

        with external_project_session(project):
            require_prepared_current(state)
            yield
            require_prepared_current(state)
    else:
        from sciplot_core.project_store.runtime import project_runtime

        require_prepared_current(state)
        with project_runtime(store):
            yield
        require_prepared_current(state)


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
    store = prepared_store(project)
    files, binding = capture(store) if store is not None else (file_inventory(project), None)
    state["prepared_creation"] = {"project": str(project), "source_sha256": state["source_sha256"], "files": files,
                                  **({'store_binding': binding} if binding is not None else {})}
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
