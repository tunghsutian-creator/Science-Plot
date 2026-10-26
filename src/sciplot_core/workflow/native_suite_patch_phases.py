"""Admitted native inspection selects a no-op or one exact candidate command."""
from __future__ import annotations

from collections.abc import Callable
from copy import deepcopy
from pathlib import Path
from typing import Any

from sciplot_core.project_commands import ProjectCommands, ProjectMutation
from sciplot_core.project_store import FileProjectStore
from sciplot_core.workflow.native_suite_command_records import _key, _request
from sciplot_core.workflow.native_suite_generation import command_for, command_key, mutation, saved_command, suite_paths
from sciplot_core.workflow.native_suite_patch_contract import _changes, _check_identity
from sciplot_core.workflow.native_suite_objects import require_object
from sciplot_core.workflow.native_suite_runtime import suite_runtime

Capture = Callable[[dict[str, Any]], dict[str, Any]]
Prepare = Callable[[dict[str, Any], dict[str, Any], dict[str, Any], list[Any], list[Any], FileProjectStore], ProjectMutation]


def inspected_patch(context: dict[str, Any], request: dict[str, Any], store: FileProjectStore,
                    app: ProjectCommands, *, capture: Capture, prepare: Prepare) -> dict[str, Any]:
    """Both phases use this repository; the inspection never owns export writes."""
    from sciplot_core.workflow.rheology_tts_saved_state import _figure_folder

    original = {"adapter": "native_display_inspection", "figure_id": context["figure_id"], "request": request}
    inspection = saved_command(app, _key(context, request), original)
    if inspection is None:
        reads, _writes = suite_paths(Path(context["workspace"]), context["manifest"], (context["figure_id"],))
        audit = _figure_folder(Path(context["delivery"]), context["figure_id"]) / f"{context['figure_id']}.native-audit.json"
        inspection = command_for(store, "native_patch", _key(context, request), request=original,
            reads=[*reads, audit], writes=[], figure_id=context["figure_id"], expected_revision=request["base_revision"])

    def inspect() -> ProjectMutation:
        with suite_runtime(Path(context["workspace"])):
            captured = capture(require_object(Path(context["plot"])))
        _check_identity(captured, request)
        diff, native = _changes(captured, request)
        result = {"plot": context["plot"], "figure_id": context["figure_id"], "request": request,
            "scientific_hash": captured["scientific_hash"], "before_native_sha256": captured["presentation_hash"],
            "presentation_hash": captured["presentation_hash"], "revision": captured["revision"],
            "spec_sha256": captured["spec_sha256"], "sources": deepcopy(context["manifest"]["sources"]),
            "diff": diff, "native_changes": native, "captured": captured, "no_change": not diff}
        return mutation(store, {}, result, sources=result["sources"])

    observed = app.execute(inspection, inspect)
    if observed["phase"] != "complete" or observed["result"]["no_change"]:
        return observed
    # The inspection published a metadata generation. Bind the child to the
    # current host runtime while retaining its exact frozen read baseline.
    with suite_runtime(Path(context["workspace"])):
        return _candidate(require_object(Path(context["plot"])), request, observed, store, app, prepare)


def _candidate(context: dict[str, Any], request: dict[str, Any], observed: dict[str, Any],
               store: FileProjectStore, app: ProjectCommands, prepare: Prepare) -> dict[str, Any]:
    original = {**_request(context, request), "inspection": observed["command_digest"]}
    key = command_key("native_candidate", {"inspection": observed["command_digest"]})
    candidate = saved_command(app, key, original)
    if candidate is None:
        reads, writes = suite_paths(Path(context["workspace"]), context["manifest"], (context["figure_id"],), native_writes=True)
        candidate = command_for(store, "native_patch", key, request=original, reads=reads, writes=writes,
            figure_id=context["figure_id"], expected_revision=request["base_revision"], generation=observed["generation"])
    result = observed["result"]
    return app.preview(candidate, lambda: prepare(context, result["captured"], request,
        result["diff"], result["native_changes"], store))
