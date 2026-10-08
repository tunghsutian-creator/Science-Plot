"""Durable template creation delegates source mapping, native work and retries."""

from copy import deepcopy
from pathlib import Path
from typing import Any

from sciplot_core.studio_core.project_query_paths import canonical_path
from sciplot_core.studio_core.project_session import external_project_session
from sciplot_core.task_control import inspect_task, resume_task, start_task
from sciplot_core.task_prepared_creation import require_prepared_current
from sciplot_core.task_storage import load_task

from .backend import PlotCreator
from .errors import EngineError
from .storage import digest, read, transaction_path, write
from .template_creation_binding import prepare, presentation_changes


class _TemplateOpener:
    def __init__(self, service: PlotCreator, state: dict[str, Any]) -> None:
        self.service, self.state = service, state

    def open(self, target: Path, figure_id: str | None = None) -> dict[str, Any]:
        request = self.state["request"]
        recipe = {key: deepcopy(request[key]) for key in ("template_definition", "data_binding", "theme", "rule_id") if key in request}
        identities = {slot["sample"]: slot["series_id"] for slot in request["data_binding"]["slots"].values()}
        return self.service.open_created(target, series_ids=identities, recipe=recipe, figure_id=figure_id)


def _annotate(root: Path, state: dict[str, Any], result: dict[str, Any]) -> dict[str, Any]:
    request = state["request"]
    return {**result, "creation_evidence": str(root / "creation.json"),
            "template_id": request["template_definition"]["template_id"],
            "binding_sha256": digest(request["data_binding"]),
            **({"theme_id": request["theme"]["theme_id"]} if "theme" in request else {})}


def _apply(service: PlotCreator, root: Path, state: dict[str, Any]) -> dict[str, Any]:
    # Frozen patch ownership survives a saved native edit with export still pending.
    # Do not re-enter creation readiness or compute a new patch after that commit.
    result = service.patch(Path(state["plot"]), state["template_patch"])
    state["template_result"] = result
    write(root / "creation.json", state)
    return _annotate(root, state, result)


def _export(service: PlotCreator, root: Path, state: dict[str, Any]) -> dict[str, Any]:
    result = service.export(Path(state["plot"]))
    state["template_result"] = result
    write(root / "creation.json", state)
    return _annotate(root, state, result)


def _open_prepared(service: PlotCreator, root: Path, state: dict[str, Any], task: dict[str, Any]) -> dict[str, Any]:
    prepared = load_task(root / "task")
    project = Path(task["project"])
    with external_project_session(project):
        require_prepared_current(prepared)
        result = _TemplateOpener(service, state).open(project)
        require_prepared_current(prepared)
    if result["status"] != "current":
        raise EngineError("prepared_project_changed", "The prepared project was not current at semantic adoption.")
    return result


def _continue(service: PlotCreator, root: Path, state: dict[str, Any], task: dict[str, Any]) -> dict[str, Any]:
    from .creation_results import _result

    if task["status"] == "complete" and (task.get("result") or {}).get("kind") == "sciplot_project_prepared_result":
        state["task_result"] = task
        write(root / "creation.json", state)
        result = _open_prepared(service, root, state, task)
    else:
        result = _result(_TemplateOpener(service, state), root, state, task)
        if result["status"] != "complete":
            return _annotate(root, state, result)
    state["plot"] = result["plot"]
    changes = presentation_changes(state["desired"], result)
    if not changes:
        state["template_export_only"] = True
        write(root / "creation.json", state)
        return _export(service, root, state)
    state["template_patch"] = {"plot_id": result["plot_id"], "base_revision": result["revision"],
                               "idempotency_key": "template:" + digest(state["request"]["idempotency_key"]),
                               "intent_class": "presentation", "changes": changes}
    write(root / "creation.json", state)
    return _apply(service, root, state)


def create(service: PlotCreator, request: dict[str, Any]) -> dict[str, Any]:
    source, task_request, desired = prepare(request)
    root = transaction_path(source.parent / ".sciplot_documents/creations", request["idempotency_key"]).parent
    canonical_path(root)
    root.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    with external_project_session(root):
        path = root / "creation.json"
        if path.exists():
            state = read(path)
            if state["request_hash"] != digest(request):
                raise EngineError("document_idempotency_conflict", "This creation key belongs to another frozen template or data binding.")
        else:
            state = {"request": request, "request_hash": digest(request), "task_request": task_request,
                     "desired": desired, "template_runtime_version": 1}
            write(path, state)
        if "template_patch" in state:
            return _apply(service, root, state)
        if state.get("template_export_only") is True:
            return _export(service, root, state)
        task_root = root / "task"
        task = (inspect_task(task_root) if (task_root / "task.json").exists()
                else start_task(task_request, task_dir=task_root, defer_creation_export=True))
        if task["status"] == "blocked" and task.get("phase") == "prepared":
            task = resume_task(task_root, {"retry": True})
        return _continue(service, root, state, task)


def decide(service: PlotCreator, root: Path, state: dict[str, Any], request: dict[str, Any]) -> dict[str, Any]:
    if "template_patch" in state:
        raise EngineError("template_presentation_decision", "Continue the saved semantic plot transaction, not its completed source creation.",
                          action="plot.decide", plot=state["plot"])
    response = request["response"]
    if set(response) - {"out", "expected_question_id", "retry"}:
        raise EngineError("template_binding_immutable", "This creation binds explicit original columns, units and samples. A different scientific binding needs its own creation key.",
                          action="correct_binding_request")
    prepare(state["request"])  # Recheck original source bytes before resuming a decision.
    task = resume_task(root / "task", response)
    return _continue(service, root, state, task)
