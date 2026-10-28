"""Prepare Studio privately, then publish its complete captured mutation once."""

from __future__ import annotations

from collections.abc import Callable
import json
import os
from pathlib import Path
from typing import Any

from sciplot_core.data_mapping.execution_directories import mapping_tree_reads, mapping_immutable_reads
from sciplot_core.foundation.json_hashing import canonical_json_sha256
from sciplot_core.foundation.source_locations import resolve_source_path
from sciplot_core.project_commands import MembershipRead, PreparedFile, PreparedSource, ProjectCommand, ProjectCommands, ProjectMutation
from sciplot_core.project_commands.resources import resource_key
from sciplot_core.project_store.io import read_file, sha
from sciplot_core.project_store import FileProjectStore, ProjectConflict
from sciplot_core.project_store.runtime import selected_project_store, logical_runtime_resource, project_runtime
from sciplot_core.studio_core.preparation_candidate import (
    StudioPreparationCandidate, require_preparation_candidate, studio_preparation_candidate,
)
from sciplot_core.terminal_source_binding import SealedTerminalSourceBinding
from sciplot_core.studio_core.preparation_original_sources import (
    capture_original_input, verify_original_ledger, original_tree_reads, checked_original_sources,
    source_identity_for_locator as source_identity_for_locator,
)
from sciplot_core.studio_core.preparation_source_runtime import current_preparation_runtime
from sciplot_core.data_mapping.execution_inputs import mapping_input_reads, mapping_execution_path, mapping_input_scope


def prepare_studio_candidate(candidate: StudioPreparationCandidate, *, request_target: bool = False,
                             request_relative: str = "plot_request.json",
                             delivery_root: Path | None = None, rule_id: str | None = None,
                             template: str | None = None, project_name: str | None = None,
                             regenerate_generated: bool = False,
                             figure_set_path_replacer: Callable[[Path, Path], None] | None = None,
                             _terminal_source_binding: SealedTerminalSourceBinding | None = None,
                             _terminal_source_prepared: bool = False, _new_creation: bool = False) -> dict[str, Any]:
    """Compose with an already held candidate; never import or publish a head."""
    require_preparation_candidate(candidate.project_dir)
    from sciplot_core.studio_core.studio_prepare_core import prepare_private_studio_project

    resource_key(request_relative)
    if request_relative.startswith("@"):
        raise ValueError("A Studio request must be a member of this candidate project.")
    candidate.request_members.add(request_relative)
    request = json.loads(candidate.read_member(request_relative).data)
    reference = request.get("data_mapping_execution")
    original = capture_original_input(request, base_dir=candidate.project_dir, snapshot=candidate.snapshot)
    if original is not None:
        candidate.original_inputs[request_relative] = original
    with mapping_input_reads(reference) as readset:
        if readset is not None:
            from sciplot_core.data_mapping.execution_loading import load_data_mapping_execution

            load_data_mapping_execution(readset.execution)
            readset.seal()
            candidate.mapping_inputs[readset.execution] = readset
        return prepare_private_studio_project(candidate, request_target=request_target, request_relative=request_relative,
            delivery_root=delivery_root, rule_id=rule_id,
            template=template, project_name=project_name, regenerate_generated=regenerate_generated,
            figure_set_path_replacer=figure_set_path_replacer,
            terminal_source_binding=_terminal_source_binding,
            terminal_source_prepared=_terminal_source_prepared, new_creation=_new_creation)


def _produced_resource(candidate: StudioPreparationCandidate, actual: Path, version: str, mode: int) -> str | None:
    if not (actual.is_relative_to(candidate.project_dir) or actual.is_relative_to(candidate.resources)):
        return None
    logical = logical_runtime_resource(actual, private_only=True)
    if logical is None or logical == ".":
        return None
    before = candidate.snapshot["files"].get(logical)
    if before is not None and before["sha256"] == version and before["mode"] == mode:
        return None
    if logical in candidate.snapshot.get("input_resources", []) or logical.split("/", 1)[0] in {"raw", "source"}:
        raise ValueError("An original scientific input cannot be declared as a produced output.")
    return logical


def _generated_preparation_sources(candidate: StudioPreparationCandidate) -> list[PreparedSource]:
    sources = []
    for relative, captured in candidate.generated_inputs.items():
        if candidate.read_member(relative) != captured:
            raise ProjectConflict("A generated preparation input changed after its producer completed.")
        actual = candidate.project_dir / relative
        literal, version = candidate.logical_path(str(actual)), sha(captured.data)
        produced = _produced_resource(candidate, actual, version, captured.mode)
        if produced is None:
            raise ProjectConflict("A generated preparation input lacks its exact new output resource.")
        identity = source_identity_for_locator(candidate.snapshot, literal)
        sources.append(PreparedSource(identity, literal, version, captured.data, (), captured.mode,
                                      produced_resource=produced))
    return sources


def audit_studio_candidate(candidate: StudioPreparationCandidate, payload: dict[str, Any], *,
                           check_presentation: bool | None = None) -> tuple[list[dict[str, Any]], list[PreparedSource]]:
    """Audit real saved native bytes and freeze their exact scientific inputs."""
    from sciplot_core.source_coverage.document_audit import _audit_exact_document_data
    from sciplot_core.source_coverage.managed_documents import source_records

    require_preparation_candidate(candidate.project_dir)
    if check_presentation is not None and type(check_presentation) is not bool:
        raise ValueError("A native audit must select its presentation scope explicitly.")
    presentation = (payload.get("preserved_existing_document") is not True
                    if check_presentation is None else check_presentation)
    registry = payload.get("figure_set")
    figures = registry.get("figures", []) if isinstance(registry, dict) else [
        {"status": "ready", "document": payload["document"], "spec": str(candidate.project_dir / "studio/spec.json")}]
    audits, sources = [], {}
    for generated_source in _generated_preparation_sources(candidate):
        sources[(generated_source.source_id, generated_source.version)] = generated_source
    for baseline_source in candidate.mapping_baseline_sources:
        sources[(baseline_source.source_id, baseline_source.version)] = baseline_source
    for relative in candidate.request_members:
        request = json.loads(candidate.read_member(relative).data)
        reference = request.get("data_mapping_execution")
        if reference and str(mapping_execution_path(reference)) not in candidate.mapping_inputs:
            raise ProjectConflict("A mapped native candidate lacks its original execution read set.")
    for readset in candidate.mapping_inputs.values():
        for prepared_input in readset.prepared_sources(candidate.snapshot):
            sources[(prepared_input.source_id, prepared_input.version)] = prepared_input
    for figure in figures:
        if figure.get("status") != "ready":
            continue
        document, spec = Path(figure["document"]), Path(figure["spec"])
        if not document.is_relative_to(candidate.project_dir) or not spec.is_relative_to(candidate.project_dir):
            raise ValueError("A private Studio audit cannot select an active or foreign figure.")
        logical_document = document.relative_to(candidate.project_dir).as_posix()
        previous = candidate.snapshot["files"].get(logical_document)
        previous_spec = candidate.snapshot["files"].get(spec.relative_to(candidate.project_dir).as_posix())
        current_spec_hash = sha(spec.read_bytes()) if spec.is_file() else None
        expected_spec_hash = previous_spec["sha256"] if previous_spec is not None else None
        unchanged = (check_presentation is None and payload.get("preserved_existing_document") is True and previous is not None
                     and sha(document.read_bytes()) == previous["sha256"]
                     and current_spec_hash == expected_spec_hash)
        if unchanged:
            audits.append({"kind": "sciplot_unchanged_native_preparation", "status": "not_evaluated",
                "reason": "exact_native_preimage_preserved", "sha256": previous["sha256"]})
            continue  # Metadata-only reuse neither executes nor certifies new science.
        else:
            reference = json.loads(candidate.read_member("plot_request.json").data).get("data_mapping_execution")
            audit_readset = candidate.mapping_inputs.get(str(mapping_execution_path(reference))) if reference else None
            with mapping_input_scope(audit_readset):
                audit, spec_payload = _audit_exact_document_data(document_path=document, spec_path=spec,
                    check_presentation=presentation)
            from sciplot_core.studio_core.current_layout_review import segmented_summary_legend

            if presentation and segmented_summary_legend(spec_payload):
                from sciplot_core.studio_core.review_artifacts import _current_layout_issues
                from sciplot_core.studio_render.models import StudioPreparationBlocked

                native_document = audit.get("document")
                native_layout = ({**native_document, "segmented_legend_geometry": audit.get("segmented_legend_geometry")}
                    if isinstance(native_document, dict) else {})
                critical = [item for item in _current_layout_issues(spec_payload, document_path=document,
                    native_audit=native_layout) if item.get("severity") == "critical"]
                if critical:
                    raise StudioPreparationBlocked("generated_native_layout_invalid",
                        "Generated native layout must pass before preparation publication: "
                        + ", ".join(sorted({str(item["id"]) for item in critical})))
            audits.append(audit)
        for source, expected in source_records(spec_payload).items():
            literal = str(source)
            actual = resolve_source_path(literal, expected_sha256=expected)
            fd = os.open(actual.parent, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
            try:
                data, mode = read_file(fd, actual.name)
            finally:
                os.close(fd)
            if sha(data) != expected:
                raise ValueError("The private Studio scientific input changed after its native audit.")
            identity = source_identity_for_locator(candidate.snapshot, literal)
            sources[(identity, expected)] = PreparedSource(identity, literal, expected, data, (), mode,
                produced_resource=_produced_resource(candidate, actual, expected, mode))
    if any(item.get("status") != "not_evaluated" for item in audits):
        for original in candidate.original_inputs.values():
            for item in original.prepared:
                sources[(item.source_id, item.version)] = item
        for relative in candidate.request_members:
            verify_original_ledger(json.loads(candidate.read_member(relative).data), candidate.original_inputs.values(),
                                   prepared_sources=sources.values(), mapping_inputs=candidate.mapping_inputs.values())
    return audits, list(sources.values())


def _preflight_observed_native(store: FileProjectStore, before: dict[str, Any]) -> None:
    """Report represented presentation conflicts before private clone admission.

    This does not admit outside bytes. Only a changed existing primary native
    with its unchanged canonical spec reaches the existing scientific audit.
    The ordinary candidate/generation guards still reject all outside changes.
    """
    changes = before.get("outside_changes", {})
    if (set(changes) != {"studio/document.vsz"} or changes["studio/document.vsz"] is None
            or "studio/spec.json" not in before["files"]):
        return
    from sciplot_core.studio_core.categorical_display_preflight import require_categorical_display_current
    from sciplot_core.project_store.membership import require_memberships

    with store._locked() as (io, current):
        require_memberships(io, before, current, {"metadata": {"read_memberships": [
            MembershipRead.capture(before["files"], prefix).to_payload()
            for prefix in ("", *("@" + key for key in sorted(store.locations)))
        ]}})
    spec = store.projection_path("studio/spec.json")
    if sha(spec.read_bytes()) != before["files"]["studio/spec.json"]["sha256"]:
        raise ProjectConflict("The observed native presentation has a changed canonical specification.")
    with project_runtime(store, generation=before["generation"]):
        require_categorical_display_current(store.root / "studio/document.vsz", spec)


def prepare_studio_generation(project: Path, *, request_target: bool = False,
                              request_relative: str = "plot_request.json",
                              delivery_root: Path | None = None, rule_id: str | None = None,
                              template: str | None = None, project_name: str | None = None,
                              regenerate_generated: bool = False,
                              figure_set_path_replacer: Callable[[Path, Path], None] | None = None,
                              _terminal_source_binding: SealedTerminalSourceBinding | None = None,
                              _terminal_source_prepared: bool = False, _new_creation: bool = False) -> dict[str, Any]:
    """The sole active-project writer for every public preparation caller."""
    from sciplot_core.project_manifest import read_intake_project_manifest, stage_intake_project_manifest
    from sciplot_core.project_host_factory import project_store

    root = project.expanduser().resolve(strict=True)
    selected = selected_project_store()
    store = selected if selected is not None and selected.root == root else project_store(root, with_snapshot=True)
    before = store.snapshot(import_legacy=True)
    _preflight_observed_native(store, before)
    with current_preparation_runtime(store, before) as verify_sources, studio_preparation_candidate(store, snapshot=before) as candidate:
        payload = prepare_studio_candidate(candidate, request_target=request_target, request_relative=request_relative, delivery_root=delivery_root,
            rule_id=rule_id, template=template, project_name=project_name,
            regenerate_generated=regenerate_generated, figure_set_path_replacer=figure_set_path_replacer,
            _terminal_source_binding=_terminal_source_binding,
            _terminal_source_prepared=_terminal_source_prepared, _new_creation=_new_creation)
        audits, sources = audit_studio_candidate(candidate, payload)
        candidate.finalize()
        result = candidate.project_payload(payload)
        writes = candidate.capture()
        manifest = read_intake_project_manifest(candidate.project_dir)
        if manifest is not None:
            writes.update({name: data if data is None or isinstance(data, PreparedFile) else PreparedFile(data, 0o644)
                           for name, data in stage_intake_project_manifest(root, manifest, store=store, project_writes=writes).items()})
        reads = {name: entry["sha256"] for name, entry in before["files"].items()}
        for name in writes:
            reads.setdefault(name, None)
        request = {"family": "studio_preparation", "rule_id": rule_id, "template": template,
                   "project_name": project_name, "regenerate_generated": regenerate_generated,
                   "request_target": request_target, "request_relative": request_relative,
                   "prepared_files": {name: sha(value.data) if value is not None else None for name, value in writes.items()}}
        key = canonical_json_sha256({"project_id": before["project_id"], "generation": before["generation"], "request": request})
        command = ProjectCommand.create("figure_set", key, project_id=before["project_id"],
            expected_generation=before["generation"], read_set=reads, write_set=sorted(writes), request=request,
            read_memberships=[MembershipRead.capture(before["files"], prefix)
                              for prefix in ("", *("@" + name for name in sorted(store.locations)))],
            source_trees=original_tree_reads(candidate.original_inputs.values(),
                mapping_tree_reads(candidate.mapping_inputs.values(), candidate.mapping_baseline_trees)))
        verify_sources()
        record = ProjectCommands(store).execute(command, lambda: ProjectMutation(writes, result,
            prepared_sources=checked_original_sources(candidate.original_inputs.values(), sources), input_reads=mapping_immutable_reads(candidate.snapshot, candidate.mapping_inputs.values(), candidate.mapping_baseline_roles),
            artifacts={"native-audits.json": json.dumps(audits, ensure_ascii=False, allow_nan=False).encode()}))
        return {**record["result"], "project_command": {field: record[field]
            for field in ("command_id", "command_digest", "project_id", "generation", "phase")}}
