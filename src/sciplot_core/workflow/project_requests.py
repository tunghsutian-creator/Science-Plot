"""Compose recognized project runs with the single project publication owner."""

from __future__ import annotations

from collections.abc import Callable
from contextlib import ExitStack
from copy import deepcopy
from dataclasses import replace
import json
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import TYPE_CHECKING, Any
from uuid import uuid4

from sciplot_core.data_mapping.execution_directories import mapping_tree_reads, mapping_immutable_reads
from sciplot_core.foundation.file_hashing import file_sha256
from sciplot_core.foundation.json_hashing import canonical_json_sha256
from sciplot_core.project_commands import PreparedFile, ProjectCommand, ProjectCommands, ProjectMutation
from sciplot_core.project_manifest import read_intake_project_manifest, stage_intake_project_manifest
from sciplot_core.project_store import FileProjectStore
from sciplot_core.studio_core.preparation_original_sources import original_tree_reads, checked_original_sources


if TYPE_CHECKING:
    from sciplot_core.plan_preview import PlanPreviewResolution
    from sciplot_core.studio_core.preparation_candidate import StudioPreparationCandidate


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


def _same_legacy_science(candidate: StudioPreparationCandidate, previous: dict[str, Any],
                         manifest: dict[str, Any]) -> bool:
    """Prove this compatibility replacement belongs to the last committed delivery."""
    store, snapshot = candidate.store, candidate.snapshot
    try:
        last = previous["last_run"]
        prior_output = store.logical_path(Path(last["output"]))
        before = json.loads(store.read_bytes(prior_output + "/manifest.json",
                                             generation=snapshot["generation"]))
        if before["delivery_package"] != previous["delivery_package"]:
            return False
        # Opening a legacy run in Studio can add these mirrors to the canonical
        # request. Compare the executed selection and actual plotted tables below.
        mirrors = {"output", "delivery_output", "review_notes", "series_order",
                   "study_model", "publication_intent", "transform_ledger"}
        for field in ("request", "source_request"):
            old, new = before[field], manifest[field]
            if not isinstance(old, dict) or not isinstance(new, dict) or not old.get("input"):
                return False
            if ({k: v for k, v in old.items() if k not in mirrors}
                    != {k: v for k, v in new.items() if k not in mirrors}):
                return False
        old_data = [row["sha256"] for row in before["delivery_package"]["data_csvs"]]
        new_data = [row["sha256"] for row in manifest["delivery_package"]["data_csvs"]]
        if not old_data or not all(old_data) or old_data != new_data:
            return False
        if any(before[key] != manifest[key] for key in ("route", "final_recipe")):
            return False
        if any(before["semantic"].get(key) != manifest["semantic"].get(key) for key in ("rule_id", "template")):
            return False
        if any(result.get(key) is not None for result in (before, manifest)
               for key in ("data_mapping_application", "cleanup_application")):
            # Without a relocatable approved transformation identity the legacy
            # exception does not authorize replacing a complete delivery.
            return False
        old_raw, new_raw = before["raw_archive"], manifest["raw_archive"]
        kind = old_raw["kind"]
        if kind != new_raw["kind"] or kind not in {"file", "directory"}:
            return False
        old_path = store.logical_path(Path(old_raw["path"]))
        new_path = store.logical_path(Path(candidate.logical_path(new_raw["path"])))
        new_output = store.logical_path(Path(candidate.logical_path(manifest["output"])))
        if not old_path.startswith(prior_output + "/raw/") or not new_path.startswith(new_output + "/raw/"):
            return False
        new_copy = candidate.resource_path(new_path)
        if kind == "file":
            original_hash = snapshot["files"][old_path]["sha256"]
            return isinstance(original_hash, str) and file_sha256(new_copy) == original_hash
        prefix = old_path + "/"
        old_members = {name[len(prefix):]: entry["sha256"] for name, entry in snapshot["files"].items()
                       if name.startswith(prefix)}
        return bool(old_members) and old_members == {
            path.relative_to(new_copy).as_posix(): file_sha256(path)
            for path in new_copy.rglob("*") if path.is_file()
        }
    except (KeyError, OSError, TypeError, ValueError):
        return False


def run_project_request(request_path: Path, request: dict[str, Any], *,
                        execute: Callable[..., dict[str, Any]], classifier: Callable[..., dict[str, Any]],
                        new_creation: bool, previous_request: dict[str, Any] | None,
                        observed_plan: PlanPreviewResolution | None = None) -> dict[str, Any]:
    """Prepare analysis/native/delivery privately, then publish the complete project once."""
    from sciplot_core.output_contract import requested_delivery_root
    from sciplot_core.studio_core.preparation_candidate import studio_preparation_candidate
    from sciplot_core.studio_core.preparation_commands import prepare_studio_candidate, audit_studio_candidate
    from sciplot_core.studio_core.project_command_scope import command_for_binding
    from sciplot_core.workflow.run_projection import _project_manifest_after_run
    from sciplot_core.workflow.project_results import _write_one_step_status
    from sciplot_core.workflow.request_io import _resolve_request_path
    from sciplot_core.workflow.project_results import project_workflow_result
    from sciplot_core.workflow.errors import WorkflowIntervention
    from sciplot_core.workflow.project_failures import publish_intervention
    from sciplot_core.workflow.project_output import archive_failed_delivery, install_private_delivery, private_run_output
    from sciplot_core.delivery.package_transaction import _package_snapshot, _preserve_finder_metadata, protect_delivery_replacement

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
    with ExitStack() as mapping_scope:
        verify_sources = None
        if not new_creation and observed_plan is None and "studio/spec.json" in snapshot["files"]:
            canonical = json.loads(store.read_bytes(request_path.name, generation=snapshot["generation"]))
            if all(canonical.get(field) == request.get(field) for field in ("input", "data_mapping_execution")):
                # Use the same exact source authority as reopening the current
                # Studio document; the candidate does not infer a live version.
                from sciplot_core.studio_core.preparation_source_runtime import current_preparation_runtime

                verify_sources = mapping_scope.enter_context(current_preparation_runtime(store, snapshot))
        candidate = mapping_scope.enter_context(studio_preparation_candidate(store, snapshot=snapshot))
        private_request = candidate.project_dir / request_path.name
        candidate.write_request(deepcopy(request))
        from sciplot_core.data_mapping.execution_inputs import mapping_input_reads
        from sciplot_core.data_mapping.execution_loading import load_data_mapping_execution

        selection = request.get("data_mapping_execution")
        original = (_resolve_request_path(request.get("input"), base_dir=candidate.project_dir, field="input")
                    if selection and observed_plan is not None else None)
        mapping_reads = mapping_scope.enter_context(mapping_input_reads(selection, expected_source=original))
        if mapping_reads is not None:
            load_data_mapping_execution(mapping_reads.execution)
            candidate.mapping_inputs[mapping_reads.execution] = mapping_reads
        private_output = candidate.resource_path((output_name + "/" if output_name else "") + "manifest.json").parent
        private_delivery = candidate.resource_path((delivery_name + "/" if delivery_name else "") + "delivery_manifest.json").parent
        # Bind the delivery identity to an existing private root even on the
        # first run. The separate stage still owns every newly rendered member.
        private_delivery.mkdir(parents=True, exist_ok=True)
        # This is the committed registry copied into this exact private snapshot,
        # not a guessed manifest discovered from the visible delivery's shell.
        previous_registry = read_intake_project_manifest(candidate.project_dir)
        previous_delivery = previous_registry.get("delivery_package") if previous_registry is not None else None
        # The package verifier sees only this run, not a mix with the mounted prior delivery.
        stage = Path(mapping_scope.enter_context(TemporaryDirectory(prefix="delivery-", dir=candidate.resources.parent)))
        try:
            with private_run_output(candidate, output_name):
                manifest = execute(request_path=private_request, source_request=deepcopy(request),
                    base_dir=candidate.project_dir, output_dir=private_output, classifier=classifier,
                    new_creation=new_creation, previous_request=previous_request,
                    staged_delivery=(stage, delivery), update_project=False,
                    **({"previous_delivery": previous_delivery} if previous_delivery is not None else {}),
                    **({"observed_plan": observed_plan} if observed_plan is not None else {}))
        except WorkflowIntervention as exc:
            publish_intervention(candidate, baseline=baseline, output=output_name, intent=intent, error=str(exc))
            raise
        if _package_snapshot(delivery) != delivery_before:
            raise ValueError("The visible delivery changed during private workflow preparation.")
        delivery_record = manifest.get("delivery_package", {})
        if (previous_delivery is not None and previous_delivery.get("complete") is True
                and manifest.get("ready_to_use") is False):
            state = manifest["state"]
            failed_gates = manifest["publish_gates"]["failed_gates"]
            previous_step = (previous_registry or {}).get("one_step") or {}
            current_step = manifest.get("one_step") or {}
            # An exact repeat of an already non-autonomous legacy delivery
            # can refresh its exports without relabeling it ready.
            same_legacy_readiness = (delivery_record.get("complete") is True
                and failed_gates == ["prerequisite_state_ready"]
                and "needs_rule_repair" == state == previous_step.get("state") == current_step.get("state")
                and bool(previous_step.get("state_reasons"))
                and previous_step["state_reasons"] == current_step.get("state_reasons")
                and _same_legacy_science(candidate, previous_registry or {}, manifest))
            if not same_legacy_readiness:
                gates = ", ".join(failed_gates)
                raise ValueError(f"Project rerun is not ready ({state}: {gates}). The previous delivery was kept.")
        if delivery_record.get("complete") is True:
            namespace, _, relative = delivery_name.partition("/")
            delivery_namespace = namespace[1:] if namespace.startswith("@") else ""
            locator = snapshot["locators"].get(delivery_namespace)
            original = Path(locator) / (relative if delivery_namespace else delivery_name) if locator is not None else None
            protect_delivery_replacement(delivery, stage,
                before=delivery_before, previous_record=previous_delivery, recorded_root=original)
            if delivery.exists():
                _preserve_finder_metadata(delivery, stage)
            install_private_delivery(stage, private_delivery)
            delivery_result = private_delivery
        else:
            delivery_result = private_output / "failed_delivery" / uuid4().hex
            archive_failed_delivery(stage, delivery_result, delivery_record)
        prepared = prepare_studio_candidate(candidate, regenerate_generated=new_creation, _new_creation=new_creation,
            _scientific_source=observed_plan.scientific_source if observed_plan is not None else None)
        audits, sources = audit_studio_candidate(candidate, prepared)
        def workflow_location(path: str) -> str:
            if path == str(stage) or path.startswith(str(stage) + "/"):
                path = str(delivery_result) + path[len(str(stage)):]
            return candidate.logical_path(path)
        manifest = project_workflow_result(manifest, workflow_location)
        # The public status must describe the same committed paths as the run
        # manifest, not the disposable delivery image prepared by the worker.
        if isinstance(manifest.get("one_step"), dict):
            _write_one_step_status(private_output, manifest["one_step"])
        (private_output / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
        candidate.finalize()
        # Capture omits byte-identical members and records authorized retirements as None.
        writes: dict[str, bytes | PreparedFile | None] = dict(candidate.capture())
        updated = read_intake_project_manifest(candidate.project_dir)
        if updated is not None:
            updated = _project_manifest_after_run(updated, manifest)
            writes.update(stage_intake_project_manifest(project, updated, store=store,
                project_writes={name: value for name, value in writes.items() if not name.startswith("@")}))
        command = command_for_binding(store, baseline, kind="publish", key=key, writes=list(writes), request=intent)
        command = replace(command, source_trees=original_tree_reads(candidate.original_inputs.values(),
            mapping_tree_reads(candidate.mapping_inputs.values(), candidate.mapping_baseline_trees)))
        if verify_sources is not None:
            verify_sources()
        record = app.execute(command, lambda: ProjectMutation(writes, manifest, prepared_sources=checked_original_sources(candidate.original_inputs.values(), sources),
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
        command = replace(command, source_trees=original_tree_reads(candidate.original_inputs.values(),
            mapping_tree_reads(candidate.mapping_inputs.values(), candidate.mapping_baseline_trees)))
        ProjectCommands(store).execute(command, lambda: ProjectMutation(writes, {}, prepared_sources=checked_original_sources(candidate.original_inputs.values(), sources),
            input_reads=mapping_immutable_reads(candidate.snapshot, candidate.mapping_inputs.values(), candidate.mapping_baseline_roles),
            artifacts={"native-audits.json": json.dumps(audits, ensure_ascii=False, allow_nan=False).encode()}))
