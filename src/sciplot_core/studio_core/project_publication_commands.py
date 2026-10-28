"""Publish a complete private Studio candidate through one project generation."""

from __future__ import annotations

from copy import deepcopy
from collections.abc import Iterator
from contextlib import ExitStack, contextmanager
from dataclasses import replace
import json
import os
import shutil
import stat
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Any

from sciplot_core.foundation.file_hashing import file_sha256
from sciplot_core.foundation.json_hashing import canonical_json_sha256
from sciplot_core.project_commands import NativeAdoption, ProjectCommands, ProjectMutation
from sciplot_core.project_commands.resources import PreparedFile
from sciplot_core.project_store import FileProjectStore, ResourceRoot
from sciplot_core.project_store.runtime import project_runtime
from sciplot_core.studio_core.preparation_source_runtime import current_preparation_runtime
from sciplot_core.studio_core.project_command_scope import command_for_binding, project_store, source_versions, whole_memberships
from sciplot_core.studio_core.request_paths import _canonical_publish_paths
from sciplot_core.data_mapping.execution_inputs import mapping_input_reads
from sciplot_core.data_mapping.execution_loading import load_data_mapping_execution


from sciplot_core.studio_core.publication_candidates import (
    relocate_candidate as relocate_candidate, _stage_tree as _stage_tree,
)


def _publication_store(project: Path) -> FileProjectStore:
    return project_store(project, with_snapshot=True)


def _delivery_identity(root: Path) -> dict[Path, tuple[int, int, int] | None]:
    from sciplot_core.foundation.canonical_paths import canonical_path

    canonical_path(root)
    result: dict[Path, tuple[int, int, int] | None] = {}
    for path in (root, *root.parents):
        try:
            info = path.lstat()
        except FileNotFoundError:
            result[path] = None
        else:
            if not stat.S_ISDIR(info.st_mode):
                raise ValueError("The visible delivery requires ordinary directory ancestors")
            result[path] = (info.st_dev, info.st_ino, info.st_mode)
    return result


def _create_delivery_root(root: Path, expected: dict[Path, tuple[int, int, int] | None]) -> tuple[int, int, int]:
    """After successful QA, create only the exact previously absent namespace."""
    if _delivery_identity(root) != expected or expected[root] is not None:
        raise ValueError("The visible delivery root changed before publication admission")
    ancestor = next(path for path, identity in expected.items() if identity is not None)
    descriptor = os.open(ancestor, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    installed = dict(expected)
    try:
        info = os.fstat(descriptor)
        if (info.st_dev, info.st_ino, info.st_mode) != expected[ancestor]:
            raise ValueError("The visible delivery ancestor changed during publication admission")
        current = ancestor
        for name in root.relative_to(ancestor).parts:
            os.mkdir(name, mode=0o755, dir_fd=descriptor)
            following = os.open(name, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=descriptor)
            os.close(descriptor)
            descriptor = following
            current = current / name
            info = os.fstat(descriptor)
            installed[current] = (info.st_dev, info.st_ino, info.st_mode)
        if _delivery_identity(root) != installed:
            raise ValueError("The created delivery root lost its exact directory identity")
        return (info.st_dev, info.st_ino, info.st_mode)
    finally:
        os.close(descriptor)


@contextmanager
def _admit_delivery_root(repository: FileProjectStore, root: Path, before: dict[str, Any],
                         identity: dict[Path, tuple[int, int, int] | None], *,
                         missing: frozenset[str]) -> Iterator[FileProjectStore]:
    """Extend host capabilities only after QA and the original read guards pass."""
    if "delivery" in repository.locations or root.is_relative_to(repository.root):
        yield repository
        return
    from sciplot_core.project_store.membership import require_memberships

    current = repository.snapshot()
    if (current["generation"] != before["generation"] or current["outside_changes"] != before["outside_changes"]
            or current["outside_metadata"] != before["outside_metadata"]):
        raise ValueError("The project changed before delivery root admission")
    with repository._locked() as (io, current):
        require_memberships(io, before, current, {"metadata": {
            "read_memberships": whole_memberships(repository, before)}}, missing=missing)
    created = _create_delivery_root(root, identity)
    locations = {key: ResourceRoot(path, repository.location_members[key])
                 for key, path in repository.locations.items()}
    locations["delivery"] = ResourceRoot(root)
    selected = FileProjectStore(repository.root, locations=locations, namespace_backups=repository.namespace_backups)
    with selected._locked() as (io, _current):
        info = os.fstat(io.root_fds["delivery"])
        if (info.st_dev, info.st_ino, info.st_mode) != created:
            raise ValueError("The delivery root changed before its Core identity was captured")
        selected.snapshot()  # Preserve the original generation and every existing root identity.
        yield selected


def _next_run(files: dict[str, Any]) -> str:
    index = 1
    while any(name.startswith(f"runs/studio_{index:03d}/") for name in files):
        index += 1
    return f"runs/studio_{index:03d}"


def publish_project_exports(*, project_dir: Path, request_path: Path, document_path: Path,
                            exports: list[dict[str, Any]] | None = None,
                            export_document_sha256: str | None = None,
                            formats: list[str] | None = None,
                            expected_binding: dict[str, Any] | None = None,
                            primary_native_audit: dict[str, Any] | None = None) -> dict[str, Any]:
    """Render privately, then CAS all run/delivery/registry/snapshot bytes together."""
    from sciplot_core.project_manifest import read_intake_project_manifest, stage_intake_project_manifest
    from sciplot_core.studio_core.native_export_adapter import export_studio_document
    from sciplot_core.studio_core.publication_prepare import prepare_studio_export_run
    from sciplot_core.studio_core.registry_writes import studio_run_registration

    project, request, document = _canonical_publish_paths(project_dir=project_dir,
        request_path=request_path, document_path=document_path)
    repository = _publication_store(project)
    before = repository.snapshot(import_legacy=True)
    from sciplot_core.project_store.generated_outputs import discover, pending_barrier
    app = ProjectCommands(repository)
    pending_barrier(app, list(before["files"]), document=repository.logical_path(document))
    before = repository.snapshot()
    missing = discover(repository, [name for name, actual in before.get("outside_changes", {}).items() if actual is None])
    missing_names = {item.resource for item in missing}
    reads = {name: entry["sha256"] for name, entry in before["files"].items()}
    binding = {"project_id": before["project_id"], "generation": before["generation"], "files": reads,
               "read_memberships": whole_memberships(repository, before)}
    if expected_binding is not None:
        if expected_binding["project_id"] != before["project_id"] or any(
                reads.get(name) != digest for name, digest in expected_binding["files"].items()):
            raise ValueError("The native publication's selected read witness is stale")
        binding["projected_reads"] = expected_binding.get("projected_reads", [])
    native_hash = file_sha256(document)
    if export_document_sha256 is not None and export_document_sha256 != native_hash:
        raise ValueError("The publication native revision is stale")
    intent: dict[str, Any] = {"document": repository.logical_path(document), "document_sha256": native_hash,
              "formats": formats or sorted({str(item["format"]) for item in exports or []}),
              "read_files": reads, "selected_read_witness": expected_binding}
    if missing:
        intent.update(missing_outputs=[item.to_payload() for item in missing], output_generation=before["generation"])
    key = canonical_json_sha256({"kind": "studio_publish", "project_id": before["project_id"], "request": intent})
    prior = app.query(key)
    if prior is not None:
        from sciplot_core.project_commands import ProjectCommand

        return dict(app.resume(ProjectCommand.from_payload(prior["metadata"]))["result"])
    run_relative = _next_run(before["files"])
    final_run = project / run_relative
    canonical_request = json.loads(repository.read_bytes(repository.logical_path(request), generation=before["generation"]))
    from sciplot_core.output_contract import requested_delivery_root

    delivery_root = repository.locations.get("delivery", project / "delivery" if
        (project / ".sciplot_store/local_locations.json").exists() else
        requested_delivery_root({"request": canonical_request}, run_output=project))
    from sciplot_core.delivery.package_transaction import (
        _package_snapshot, _preserve_finder_metadata, _protect_editable_documents,
    )

    delivery_before = _package_snapshot(delivery_root)
    delivery_identity = _delivery_identity(delivery_root)
    writes: dict[str, bytes | Path | PreparedFile | None] = {}
    with TemporaryDirectory(prefix="sciplot-publication-") as temporary, \
            project_runtime(repository, generation=before["generation"]), \
            mapping_input_reads(canonical_request.get("data_mapping_execution")) as mapping_reads, \
            current_preparation_runtime(repository, before) as verify_sources, ExitStack() as publication_scope:
        if mapping_reads is not None:
            load_data_mapping_execution(mapping_reads.execution)
            mapping_reads.seal()
        from sciplot_core.studio_core.project_command_scope import figure_read_state
        from sciplot_core.studio_core.project_query_paths import project_snapshot

        _, primary_figure_id, selected_figures = project_snapshot(project)
        external_sources: dict[str, str] = {}
        for figure in selected_figures:
            if figure["status"] == "ready":
                external_sources.update(figure_read_state(project, figure)["source_files"])
        binding["source_files"] = external_sources
        candidate = Path(temporary).resolve()
        run = candidate / final_run.name
        primary, secondary, delivery = (candidate / name for name in ("primary", "secondary", "delivery"))
        run.mkdir()
        if exports is None:
            from sciplot_core.studio_core.registry_state import _veusz_spec_path
            from sciplot_core.studio_core.categorical_display_preflight import require_categorical_display_current

            require_categorical_display_current(document, _veusz_spec_path(document))
            exported = export_studio_document(document, formats=formats or [], output_dir=primary,
                                               audit_spec_path=_veusz_spec_path(document))
            exports = exported["exports"]
            primary_native_audit = exported.get("document_audit")
        payload = prepare_studio_export_run(project_dir=project, request_path=request, document_path=document,
            exports=exports, export_document_sha256=native_hash, primary_native_audit=primary_native_audit,
            output_dir=run, secondary_output_dir=secondary, delivery_dir=delivery, delivery_root=delivery_root)
        payload["document_sha256"] = native_hash
        payload["figure_set"] = {"primary_figure_id": primary_figure_id, "figures": selected_figures}
        delivery_complete = payload["delivery_package"].get("complete") is True
        if delivery_complete:
            _protect_editable_documents(delivery_root, delivery)
            if delivery_root.exists():
                _preserve_finder_metadata(delivery_root, delivery)
        else:
            failed_delivery = run / "failed_delivery"
            shutil.move(str(delivery), failed_delivery)
            payload = relocate_candidate(payload, {delivery: failed_delivery})
            value = relocate_candidate(json.loads((run / "manifest.json").read_text()), {delivery: failed_delivery})
            (run / "manifest.json").write_text(json.dumps(value, ensure_ascii=False, indent=2))
        if (_delivery_identity(delivery_root) != delivery_identity
                or _package_snapshot(delivery_root) != delivery_before):
            raise ValueError("The visible delivery changed during private publication preparation")
        verify_sources()
        verify_publication_sources = verify_sources
        if delivery_complete:
            repository = publication_scope.enter_context(_admit_delivery_root(repository, delivery_root, before,
                delivery_identity, missing=frozenset(missing_names)))
            publication_scope.enter_context(project_runtime(repository, generation=before["generation"]))
            verify_publication_sources = publication_scope.enter_context(current_preparation_runtime(repository, before))
            app = ProjectCommands(repository)
            binding["read_memberships"] = whole_memberships(repository, before)
        roots = {run: final_run, primary: project / "studio/exports",
                 secondary: project / "studio/exports/figure_set", delivery: delivery_root}
        payload = relocate_candidate(payload, roots)
        manifest = relocate_candidate(json.loads((run / "manifest.json").read_text()), roots)
        _stage_tree(run, run_relative, writes, roots)
        if primary.exists():
            _stage_tree(primary, "studio/exports", writes, roots)
        if secondary.exists():
            _stage_tree(secondary, "studio/exports/figure_set", writes, roots)
        delivery_prefix = "@delivery" if "delivery" in repository.locations else "delivery"
        if delivery_complete:
            writes.update({name: None for name in reads if name.startswith(delivery_prefix + "/")})
            _stage_tree(delivery, delivery_prefix, writes, roots)
        adoptions = []
        for name, actual in before.get("outside_changes", {}).items():
            if name in missing_names:
                continue  # Only the same authenticated typed absence is admitted by Core again below.
            if not name.endswith(".vsz") or not name.startswith("studio/") or actual is None:
                raise ValueError("Publication found unregistered outside changes beyond audited native documents")
            # Scientific verification above audited the exact current native
            # documents in this full publication; no generic drift bypass exists.
            writes[name] = project / name
            adoptions.append(NativeAdoption(name, reads[name], actual,
                canonical_json_sha256(manifest["result"]["scientific_data_verification"])))
        # The authoritative registry and ZIP consume the same audited native
        # overlay as the one final command; neither builder publishes a head.
        registry = read_intake_project_manifest(project, store=repository)
        if registry is not None:
            updated = studio_run_registration(deepcopy(registry), manifest, studio_run=payload)
            writes.update(stage_intake_project_manifest(project, updated, store=repository,
                project_writes={name: value for name, value in writes.items() if not name.startswith("@")},
                native_adoptions=adoptions))
        command = command_for_binding(repository, binding, kind="native_import" if adoptions else "publish",
            key=key, writes=list(writes), request=intent, native_adoptions=adoptions, missing_outputs=missing)
        if mapping_reads is not None:
            from sciplot_core.data_mapping.execution_directories import mapping_live_trees

            command = replace(command, source_trees=mapping_live_trees(mapping_reads))
        verify_publication_sources()
        mapping_sources = mapping_reads.prepared_sources(before) if mapping_reads is not None else ()
        result = app.execute(command, lambda: ProjectMutation(writes, payload,
            sources=source_versions(binding, store=repository),
            prepared_sources=mapping_sources,
            input_reads=mapping_reads.input_reads(before) if mapping_reads is not None else (),
            artifacts={"publication.json": json.dumps(manifest, ensure_ascii=False, allow_nan=False).encode()}))
        if mapping_reads is not None:
            mapping_reads.publication_complete(result)
        return {**result["result"], "project_command": {field: result[field]
            for field in ("command_id", "project_id", "generation", "phase")}}
