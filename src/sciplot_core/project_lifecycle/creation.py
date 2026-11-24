"""Creation delegates scientific decisions and execution to the existing task owner."""

from collections.abc import Callable
from pathlib import Path
from .context import exists, prepare_namespace
from .ports import ProjectTargets

from .contracts import NormalizedCommand
from typing import Any

from sciplot_core.project_lifecycle.paths import canonical_path
from sciplot_core.project_lifecycle.context import external_project_session
from sciplot_core.task_control import inspect_task, resume_task, start_native_compatibility_creation, start_task

from sciplot_core.project_lifecycle.errors import EngineError
from sciplot_core.plot_engine.backend import PlotCreator
from sciplot_core.project_lifecycle.creation_results import _result
from sciplot_core.project_lifecycle.context import digest, read, write

def create(service: PlotCreator, request: dict[str, Any], *, targets: ProjectTargets,
           allow_new_legacy_template: bool = True) -> dict[str, Any]:
    from sciplot_core.plot_engine.contracts import validate_create

    request = validate_create(request)
    if "template_definition" in request:
        from sciplot_core.project_lifecycle.template_creation import create as create_from_template

        return create_from_template(service, request, targets=targets, allow_new=allow_new_legacy_template)
    source = canonical_path(Path(request["source"]))
    # Key validation also prevents unbounded or unhashable identifiers before allocation.
    key = request["idempotency_key"]
    root = targets.creation_root(source, key)
    if not exists(root / "creation.json"):
        from sciplot_core.foundation.research_destination import require_data_destination
        from sciplot_core.output_contract import resolve_user_output_layout
        layout = resolve_user_output_layout(source, requested_delivery_root=request.get("out"))
        for destination in (root, layout.delivery_root, layout.workspace_root):
            require_data_destination(destination)
    prepare_namespace(root)
    task_request = {"version": 1, "action": "create", **{k: v for k, v in request.items() if k != "idempotency_key"}}
    task_request["source"] = str(source)
    with external_project_session(root):
        path = root / "creation.json"
        if exists(path):
            state = read(path)
            if state["request_hash"] != digest(request):
                raise EngineError("document_idempotency_conflict", "This creation key belongs to a different request.")
        else:
            state = {"request": request, "request_hash": digest(request), "task_request": task_request,
                     "normalized_command": NormalizedCommand.create("create", request).to_payload(),
                     "raw_admission": "verified_managed_v1"}
            write(path, state)
        task_root = root / "task"
        # start_task already has crash-safe task allocation; its owner handles pending stages.
        if (task_root / "task.json").exists():
            task = inspect_task(task_root)
        elif state.get("raw_admission") != "verified_managed_v1":
            # Only a pre-upgrade outer receipt with no child may start here.
            task = start_native_compatibility_creation(task_request, task_dir=task_root, owned_namespace=root,
                                                       reason="historical_plot_create_receipt")
        else:
            task = start_task(task_request, task_dir=task_root, _owned_namespace=root)
        return _result(service, root, state, task)


def decide_creation(service: PlotCreator, root: Path, request: dict[str, Any], *,
                    template_owner: Callable[[], PlotCreator] | None = None) -> dict[str, Any]:
    from sciplot_core.plot_engine.contracts import validate_decide

    request = validate_decide(request)
    if set(request) != {"response"}:
        raise EngineError("document_invalid_decision", "Creation decisions use the current source-bound response.")
    with external_project_session(root):
        state = read(root / "creation.json")
        if state.get("template_runtime_version") == 1:
            from sciplot_core.project_lifecycle.template_creation import decide

            return decide(template_owner() if template_owner is not None else service, root, state, request)
        result = resume_task(root / "task", request["response"])
        return _result(service, root, state, result)
