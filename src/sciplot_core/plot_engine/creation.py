"""Creation delegates scientific decisions and execution to the existing task owner."""

from pathlib import Path
from typing import Any

from sciplot_core.studio_core.project_query_paths import canonical_path
from sciplot_core.studio_core.project_session import external_project_session
from sciplot_core.task_control import inspect_task, resume_task, start_task

from .errors import EngineError
from .backend import PlotCreator
from .creation_results import _result
from .storage import digest, read, transaction_path, write

def create(service: PlotCreator, request: dict[str, Any]) -> dict[str, Any]:
    from .contracts import validate_create

    request = validate_create(request)
    if "template_definition" in request:
        from .template_creation import create as create_from_template

        return create_from_template(service, request)
    source = canonical_path(Path(request["source"]))
    # Key validation also prevents unbounded or unhashable identifiers before allocation.
    key = request["idempotency_key"]
    parent = source.parent / ".sciplot_documents" / "creations"
    root = transaction_path(parent, key).parent
    canonical_path(root)
    root.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    task_request = {"version": 1, "action": "create", **{k: v for k, v in request.items() if k != "idempotency_key"}}
    task_request["source"] = str(source)
    with external_project_session(root):
        path = root / "creation.json"
        if path.exists():
            state = read(path)
            if state["request_hash"] != digest(request):
                raise EngineError("document_idempotency_conflict", "This creation key belongs to a different request.")
        else:
            state = {"request": request, "request_hash": digest(request), "task_request": task_request}
            write(path, state)
        task_root = root / "task"
        # start_task already has crash-safe task allocation; its owner handles pending stages.
        task = (inspect_task(task_root) if (task_root / "task.json").exists()
                else start_task(task_request, task_dir=task_root))
        return _result(service, root, state, task)


def decide_creation(service: PlotCreator, root: Path, request: dict[str, Any]) -> dict[str, Any]:
    from .contracts import validate_decide

    request = validate_decide(request)
    if set(request) != {"response"}:
        raise EngineError("document_invalid_decision", "Creation decisions use the current source-bound response.")
    with external_project_session(root):
        state = read(root / "creation.json")
        if state.get("template_runtime_version") == 1:
            from .template_creation import decide

            return decide(service, root, state, request)
        result = resume_task(root / "task", request["response"])
        return _result(service, root, state, result)
