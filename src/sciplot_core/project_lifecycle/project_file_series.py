"""Save one original XY change in an exact existing project-file figure."""
from pathlib import Path
from collections.abc import Callable
from typing import Any

from sciplot_core.data_mapping.original_tables import source_table_snapshot
from sciplot_core.foundation.canonical_paths import canonical_path
from sciplot_core.foundation.json_hashing import canonical_json_sha256
from sciplot_core.foundation.writer_lease import WriterLeaseBusy, WriterLeaseChanged
from sciplot_core.plot_document.schema import closed
from sciplot_core.plot_document.validation import validate_wire
from sciplot_core.plot_engine.backend import PlotBackend
from sciplot_core.plot_engine.append_source_regions import append_source_candidates
from sciplot_core.plot_engine.current_unit_admission import prepare_current_update
from sciplot_core.plot_engine.managed_source_append import append_targets
from sciplot_core.project_store.errors import ProjectConflict
from sciplot_core.project_store.runtime import project_runtime
from sciplot_core.source_tables.read_session import with_table_reads

from .admission import admitted
from .attachment_admission import scientific_sources
from .context import repository_scope, transaction_path
from .errors import EngineError
from .head_observation import observe_plot_head
from .journal_identity import saved_command
from .patch_execution import execute_patch
from .ports import ProjectRepository
from .project_file import ProjectFileSaveUnconfirmed
from .project_file_summary import project_file_figure
from .repository_router import ComposedProjectRepository

def project_file_series_schema(*, replace: bool = False) -> dict[str, Any]:
    string = {"type": "string", "minLength": 1}
    index = {"type": "integer", "minimum": 0}
    proof = {"type": "string", "pattern": "^[0-9a-f]{64}$"}
    schema = closed({
        "plot_id": string, "base_revision": index, "expected_generation": string,
        "source": {**string, "pattern": "^/"}, "mode": {"enum": ["plan", "apply"]},
        "sheet": string, "x_column": index, "y_column": index,
        **({"replace_layer": string} if replace else {"sample": string, "label": string}),
        "plan_id": proof, "source_sha256": proof,
    }, ["plot_id", "base_revision", "expected_generation", "source", "mode",
        "x_column", "y_column", "replace_layer" if replace else "sample"])
    schema["allOf"] = [{"if": {"properties": {"mode": {"const": "apply"}}},
                        "then": {"required": ["plan_id", "source_sha256"]}}]
    return schema


def _identity(request: dict[str, Any], project_id: str, source_sha256: str) -> str:
    return canonical_json_sha256([project_id, source_sha256, {key: value for key, value in request.items()
                                if key not in {"mode", "plan_id", "source_sha256"}}])


def _saved(owner: Any, plan_id: str, *, replace: bool) -> dict[str, Any] | None:
    root = owner.attachment.root
    path = transaction_path(root, "archive-series:" + plan_id)
    with owner.query_scope(root):
        if not owner.exists(path):
            return None
        transaction = owner.read(path)
        command = saved_command(transaction)
        expected = "source.sha256" if replace else "source.append"
        if (command is None or command.kind != "patch" or transaction["phase"] != "complete"
                or transaction["request"]["changes"][0]["property"] != expected):
            raise EngineError("project_file_series_unconfirmed", "Reopen the project before retrying this series.",
                              action="inspect_project_file")
        document: dict[str, Any] = transaction["document"]
        accepted = owner.load_revision(root, document["revision"])["document"]
        if any(document[key] != accepted[key] for key in ("plot_id", "scientific_hash", "presentation_hash")):
            raise EngineError("project_file_series_unconfirmed", "The recorded series is not a saved revision of this project.",
                              action="inspect_project_file")
        return document


def _patch(request: dict[str, Any], document: dict[str, Any], root: Path,
           project_id: str) -> tuple[dict[str, Any], str, str, dict[str, Any]]:
    if document["scientific"]["provenance"]["managed"].get("rule_id") != "ordinary_xy":
        raise EngineError("project_file_series_unsupported", "Choose a saved ordinary XY figure for adding a source series.")
    targets = append_targets(document, root=root)
    if len(targets) != 1:
        raise EngineError("project_file_series_unsupported", "Choose an ordinary XY figure with one unambiguous original-value view.")
    path = Path(request["source"])
    sheet = request.get("sheet")
    snapshot = source_table_snapshot(path, rule_id="ordinary_xy", sheets=[sheet] if sheet is not None else None)
    if snapshot is None:
        raise EngineError("managed_append_source_unsupported", "Choose an original CSV, TSV or Excel table.")
    sha = snapshot["file_sha256"]
    if request.get("source_sha256", sha) != sha:
        raise EngineError("managed_append_source_changed", "The original table changed after it was planned. Plan against its current bytes.")
    indices = {request["x_column"], request["y_column"]}
    candidates = append_source_candidates(snapshot)
    matches = [candidate for candidate in candidates if indices <= {column["index"] for column in candidate["columns"]}]
    # Generic ordinary input can contain adjacent blocks with identical bounds
    # and metadata. A physical sheet/region, not a candidate label, owns rows.
    selections = {canonical_json_sha256(item["table_selection"]): item["table_selection"] for item in matches}
    if len(selections) != 1:
        raise EngineError("managed_append_table_ambiguous", "Choose the exact worksheet and original physical X and Y columns.",
                          action="select_source_columns", candidates=candidates[:32])
    selection = next(iter(selections.values()))
    plan_id = _identity(request, project_id, sha)
    if "replace_layer" in request:
        from .project_file_series_replacement import replacement_change

        change = replacement_change(request, document, root, snapshot, selection)
    else:
        curve = {"sample": request["sample"], "x_column_index": request["x_column"], "y_column_index": request["y_column"],
                 **({"label": request["label"]} if "label" in request else {})}
        value = {"source": {"path": str(path), "sha256": sha,
                            "source_id": "raw:added:" + plan_id[:24], "table_selection": selection},
                 "curves": [curve]}
        change = {"op": "set", "target": [next(iter(targets))], "property": "source.append", "value": value}
    return {"plot_id": document["plot_id"], "base_revision": document["revision"],
            "idempotency_key": "archive-series:" + plan_id, "intent_class": "scientific",
            "changes": [change]}, plan_id, sha, selection


def _result(status: str, session: Any, document: dict[str, Any], generation: str,
            *, replace: bool, **details: Any) -> dict[str, Any]:
    target, plot = str(session.path), document["plot_id"]
    kind = "sciplot_project_file_replace_series_source" if replace else "sciplot_project_file_add_series"
    return {"kind": kind, "version": 1, "status": status,
            "project_file": target, "project_id": session.project_id, "generation": generation,
            **{key: document[key] for key in ("plot_id", "revision", "scientific_hash", "presentation_hash")},
            "next_step": {"action": "project.open", "arguments": {"target": target, "figure_id": plot,
                                                                   "description": {"scope": "summary"}}},
            **details}


@with_table_reads
def add_project_file_series(path: Path, request: dict[str, Any], *, repository: ProjectRepository,
                            capabilities: dict[str, Any] | None, backend: PlotBackend,
                            decide: Callable[[Path, dict[str, Any]], dict[str, Any]], replace: bool = False) -> dict[str, Any]:
    """Plan against exact source bytes, then save the audited scientific delta."""
    validate_wire(request, project_file_series_schema(replace=replace), code="project_file_series_invalid_request")
    request = {**request, "source": str(canonical_path(Path(request["source"])))}
    with project_file_figure(path, request["plot_id"], exact_plot_id=True) as (session, opened_owner, before):
        root = opened_owner.attachment.root
        apply = request["mode"] == "apply"
        if apply:
            plan_id = _identity(request, session.project_id, request["source_sha256"])
            if plan_id != request["plan_id"]:
                raise EngineError("project_file_series_plan_changed", "Plan again for this exact figure, source and column selection.")
            published = _saved(opened_owner, plan_id, replace=replace)
            if published is not None:
                return _result("already_saved", session, published, session.opened_generation, replace=replace, saved=True)
        if (before["revision"] != request["base_revision"]
                or session.opened_generation != request["expected_generation"]):
            raise EngineError("project_file_series_revision_conflict", "Reopen the exact figure and plan against its current revision and project generation.",
                              action="inspect_project_file", current_revision=before["revision"],
                              current_generation=session.opened_generation)
        with project_runtime(session.store), repository_scope(repository, capabilities=capabilities):
            # The path-bound backend and transaction writer must share one
            # archive attachment and invocation-local source declarations.
            if not isinstance(repository, ComposedProjectRepository):
                raise EngineError("project_file_series_unsupported", "Adding a series requires the composed Managed runtime.")
            owner = repository.select(opened_owner.attachment)
            with owner.lease(root):
                patch, plan_id, sha, selection = _patch(request, before, root, session.project_id)
                with scientific_sources(owner, patch):
                    if not apply:
                        _, diff, _, _ = prepare_current_update(root, before, patch)
                        return _result("ready", session, before, session.opened_generation, replace=replace, saved=False,
                                       selection={**diff[0]["after"], **({"table_selection": selection,
                                           "layer_id": request["replace_layer"], "x_column": request["x_column"],
                                           "y_column": request["y_column"]} if replace else {})},
                                       apply_request={**request, "mode": "apply", "plan_id": plan_id, "source_sha256": sha})
                    # A confirmed exact source plan still requires the normal
                    # native scientific audit before acceptance.
                    with admitted(root, "patch", patch):
                        prepared = execute_patch(root, patch, backend, defer_export=True)
            if prepared.get("status") != "needs_review":
                raise EngineError("project_file_series_not_saved", "The series change did not pass native preview; the file was not replaced.",
                                  native_error=(prepared.get("error") or {}).get("reason_code"))
            edited = decide(root, {"decision_id": prepared["decision_id"],
                                           "base_revision": before["revision"], "accept": True})
        if edited.get("status") != "complete":
            raise EngineError("project_file_series_not_saved", "The series change did not pass native commit; the file was not replaced.",
                              native_error=(edited.get("error") or {}).get("reason_code"))
        head = observe_plot_head(root, owner=owner)
        if head is None or head["document"]["revision"] != before["revision"] + 1:
            raise EngineError("project_file_series_not_saved", "The private transaction did not advance the selected figure by one revision.")
        # The lease may materialize the prior archive's derivative locally.
        # It is not evidence for this deferred revision; keep the historical
        # Store member and remove only the disposable runtime copy.
        owner.runtime_path(root / "export-cache.json").unlink(missing_ok=True)
        generation = session.store.snapshot()["generation"]
        try:
            session.save(expected_generation=generation)
        except ProjectFileSaveUnconfirmed as exc:
            raise EngineError("project_file_save_unconfirmed", "Retry this exact request to check whether the series was saved.",
                              action="retry_same_request") from exc
        except (ProjectConflict, WriterLeaseBusy, WriterLeaseChanged) as exc:
            raise EngineError("project_file_save_conflict", "The project changed before save; this request did not replace it.",
                              action="inspect_project_file") from exc
        return _result("saved", session, head["document"], generation, replace=replace, saved=True)
