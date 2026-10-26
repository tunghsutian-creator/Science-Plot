"""Compose recognized project runs with the single project publication owner."""

from collections.abc import Callable
from contextlib import ExitStack
from copy import deepcopy
from dataclasses import replace
import json
import shutil
from pathlib import Path
from typing import Any
from uuid import uuid4

from sciplot_core.data_mapping.execution_directories import mapping_tree_reads, mapping_immutable_reads
from sciplot_core.foundation.json_hashing import canonical_json_sha256
from sciplot_core.project_commands import PreparedFile, ProjectCommand, ProjectCommands, ProjectMutation
from sciplot_core.project_manifest import read_intake_project_manifest, stage_intake_project_manifest
from sciplot_core.project_store import FileProjectStore


def recognized_project(request_path: Path) -> bool:
    """Use the selected request's exact root; never discover through raw/output paths."""
    if request_path.name != "plot_request.json":
        return False
    project = request_path.parent
    return (project / ".sciplot_store/head.json").is_file() or read_intake_project_manifest(project) is not None


def _binding(store: FileProjectStore) -> dict[str, Any]:
    from sciplot_core.studio_core.project_command_scope import whole_memberships

    snapshot = store.snapshot(import_legacy=True)
    if snapshot["outside_changes"]:
        raise ValueError("Unregistered outside changes must be resolved before regenerating a project.")
    return {"project_id": snapshot["project_id"], "generation": snapshot["generation"],
            "files": {name: entry["sha256"] for name, entry in snapshot["files"].items()},
            "read_memberships": whole_memberships(store, snapshot)}


def _publication_store(project: Path) -> FileProjectStore:
    from sciplot_core.studio_core.project_command_scope import project_store

    return project_store(project, create_delivery=True, with_snapshot=True, create_output=True)


def next_project_run(project: Path) -> Path:
    """Choose an uncreated slot; publication, not discovery, owns its members."""
    index = 1
    while (project / "runs" / f"run_{index:03d}").exists():
        index += 1
    return project / "runs" / f"run_{index:03d}"


def run_project_request(request_path: Path, request: dict[str, Any], *,
                        execute: Callable[..., dict[str, Any]], classifier: Callable[..., dict[str, Any]],
                        new_creation: bool, previous_request: dict[str, Any] | None) -> dict[str, Any]:
    """Prepare analysis/native/delivery privately, then publish the complete project once."""
    from sciplot_core.output_contract import requested_delivery_root
    from sciplot_core.studio_core.preparation_candidate import studio_preparation_candidate
    from sciplot_core.studio_core.preparation_commands import prepare_studio_candidate, audit_studio_candidate
    from sciplot_core.studio_core.project_command_scope import command_for_binding
    from sciplot_core.workflow.run_projection import _project_manifest_after_run
    from sciplot_core.workflow.request_io import _resolve_request_path
    from sciplot_core.workflow.project_results import project_workflow_result
    from sciplot_core.workflow.errors import WorkflowIntervention
    from sciplot_core.workflow.project_failures import publish_intervention
    from sciplot_core.workflow.project_output import private_run_output
    from sciplot_core.delivery.package_transaction import _package_snapshot, _preserve_finder_metadata, _protect_editable_documents

    project = request_path.parent
    store = _publication_store(project)
    baseline = _binding(store)
    output = _resolve_request_path(request.get("output"), base_dir=project, field="output").absolute()
    output_name = store.logical_path(output / "manifest.json").rpartition("/")[0]
    if not output_name:
        raise ValueError("A project run requires its own output directory below or outside the project root.")
    delivery = requested_delivery_root({"request": request}, run_output=output).absolute()
    delivery_name = store.logical_path(delivery / "delivery_manifest.json").rpartition("/")[0]
    delivery_before = _package_snapshot(delivery)
    intent = {"workflow_request": request, "output": output_name, "new_creation": new_creation,
              "previous_request": previous_request, "read_generation": baseline["generation"]}
    key = "workflow:" + canonical_json_sha256({"project_id": baseline["project_id"], "intent": intent})
    app = ProjectCommands(store)
    prior = app.query(key)
    if prior is not None:
        return dict(app.resume(ProjectCommand.from_payload(prior["metadata"]))["result"])
    snapshot = store.snapshot()
    if snapshot["generation"] != baseline["generation"]:
        raise ValueError("The selected project changed before private preparation.")
    with studio_preparation_candidate(store, snapshot=snapshot) as candidate, ExitStack() as mapping_scope:
        private_request = candidate.project_dir / request_path.name
        candidate.write_request(deepcopy(request))
        from sciplot_core.data_mapping.execution_inputs import mapping_input_reads
        from sciplot_core.data_mapping.execution_loading import load_data_mapping_execution

        mapping_reads = mapping_scope.enter_context(mapping_input_reads(request.get("data_mapping_execution")))
        if mapping_reads is not None:
            load_data_mapping_execution(mapping_reads.execution)
            candidate.mapping_inputs[mapping_reads.execution] = mapping_reads
        private_output = candidate.resource_path((output_name + "/" if output_name else "") + "manifest.json").parent
        private_delivery = candidate.resource_path((delivery_name + "/" if delivery_name else "") + "delivery_manifest.json").parent
        try:
            with private_run_output(candidate, output_name):
                manifest = execute(request_path=private_request, source_request=deepcopy(request),
                    base_dir=candidate.project_dir, output_dir=private_output, classifier=classifier,
                    new_creation=new_creation, previous_request=previous_request,
                    staged_delivery=(private_delivery, delivery), update_project=False)
        except WorkflowIntervention as exc:
            publish_intervention(candidate, baseline=baseline, output=output_name, intent=intent, error=str(exc))
            raise
        delivery_complete = manifest.get("delivery_package", {}).get("complete") is True
        if delivery_complete:
            _protect_editable_documents(delivery, private_delivery)
            if delivery.exists():
                _preserve_finder_metadata(delivery, private_delivery)
        else:
            failed = private_output / "failed_delivery" / uuid4().hex
            failed.parent.mkdir(parents=True, exist_ok=True)
            shutil.move(str(private_delivery), failed)
            def failed_location(path: str) -> str:
                old, new = str(private_delivery), str(failed)
                return new + path[len(old):] if path == old or path.startswith(old + "/") else path
            manifest = project_workflow_result(manifest, failed_location)
        if _package_snapshot(delivery) != delivery_before:
            raise ValueError("The visible delivery changed during private workflow preparation.")
        prepared = prepare_studio_candidate(candidate, regenerate_generated=new_creation, _new_creation=new_creation)
        audits, sources = audit_studio_candidate(candidate, prepared)
        manifest = project_workflow_result(manifest, candidate.logical_path)
        (private_output / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
        candidate.finalize()
        writes: dict[str, bytes | PreparedFile | None] = dict(candidate.capture())
        if delivery_complete:
            writes = {**{name: None for name in baseline["files"] if name.startswith(delivery_name + "/")}, **writes}
        updated = read_intake_project_manifest(candidate.project_dir)
        if updated is not None:
            updated = _project_manifest_after_run(updated, manifest)
            writes.update(stage_intake_project_manifest(project, updated, store=store,
                project_writes={name: value for name, value in writes.items() if not name.startswith("@")}))
        command = command_for_binding(store, baseline, kind="publish", key=key, writes=list(writes), request=intent)
        command = replace(command, source_trees=mapping_tree_reads(candidate.mapping_inputs.values(), candidate.mapping_baseline_trees))
        record = app.execute(command, lambda: ProjectMutation(writes, manifest, prepared_sources=tuple(sources),
            input_reads=mapping_immutable_reads(candidate.snapshot, candidate.mapping_inputs.values(), candidate.mapping_baseline_roles),
            artifacts={"native-audits.json": json.dumps(audits, ensure_ascii=False, allow_nan=False).encode()}))
        if mapping_reads is not None:
            mapping_reads.publication_complete(record)
        return dict(record["result"])


def commit_completed_project_run(request_path: Path, manifest: dict[str, Any]) -> None:
    """Compatibility registration enters the same complete private preparation."""
    from sciplot_core.studio_core.preparation_candidate import studio_preparation_candidate
    from sciplot_core.studio_core.preparation_commands import prepare_studio_candidate, audit_studio_candidate
    from sciplot_core.studio_core.project_command_scope import command_for_binding
    from sciplot_core.workflow.run_projection import _project_manifest_after_run

    project = request_path.parent
    if read_intake_project_manifest(project) is None:
        return
    store = _publication_store(project)
    baseline = _binding(store)
    with studio_preparation_candidate(store) as candidate:
        prepared = prepare_studio_candidate(candidate)
        audits, sources = audit_studio_candidate(candidate, prepared)
        updated = read_intake_project_manifest(candidate.project_dir)
        if updated is None:
            raise ValueError("The private completed-run candidate lost its original project manifest.")
        updated = _project_manifest_after_run(updated, manifest)
        candidate.finalize()
        writes: dict[str, bytes | PreparedFile | None] = dict(candidate.capture())
        writes.update(stage_intake_project_manifest(project, updated, store=store,
            project_writes={name: value for name, value in writes.items() if not name.startswith("@")}))
        intent = {"completed_run": manifest, "read_generation": baseline["generation"]}
        key = "workflow-register:" + canonical_json_sha256(intent)
        command = command_for_binding(store, baseline, kind="publish", key=key, writes=list(writes), request=intent)
        command = replace(command, source_trees=mapping_tree_reads(candidate.mapping_inputs.values(), candidate.mapping_baseline_trees))
        ProjectCommands(store).execute(command, lambda: ProjectMutation(writes, {}, prepared_sources=tuple(sources),
            input_reads=mapping_immutable_reads(candidate.snapshot, candidate.mapping_inputs.values(), candidate.mapping_baseline_roles),
            artifacts={"native-audits.json": json.dumps(audits, ensure_ascii=False, allow_nan=False).encode()}))
