"""Publish a complete private Studio candidate through one project generation."""

from __future__ import annotations

from copy import deepcopy
import json
import shutil
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Any

from sciplot_core.foundation.file_hashing import file_sha256
from sciplot_core.foundation.json_hashing import canonical_json_sha256
from sciplot_core.project_commands import NativeAdoption, ProjectCommands, ProjectMutation
from sciplot_core.project_commands.resources import PreparedFile
from sciplot_core.project_store import FileProjectStore
from sciplot_core.project_store.runtime import project_runtime
from sciplot_core.studio_core.project_command_scope import command_for_binding, project_store, source_versions, whole_memberships
from sciplot_core.studio_core.request_paths import _canonical_publish_paths


from sciplot_core.studio_core.publication_candidates import (
    relocate_candidate as relocate_candidate, _stage_tree as _stage_tree,
)


def _publication_store(project: Path) -> FileProjectStore:
    return project_store(project, create_delivery=True, with_snapshot=True)


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
    intent = {"document": repository.logical_path(document), "document_sha256": native_hash,
              "formats": formats or sorted({str(item["format"]) for item in exports or []}),
              "read_files": reads, "selected_read_witness": expected_binding}
    key = canonical_json_sha256({"kind": "studio_publish", "project_id": before["project_id"], "request": intent})
    app = ProjectCommands(repository)
    prior = app.query(key)
    if prior is not None:
        from sciplot_core.project_commands import ProjectCommand

        return dict(app.resume(ProjectCommand.from_payload(prior["metadata"]))["result"])
    run_relative = _next_run(before["files"])
    final_run = project / run_relative
    delivery_root = repository.locations.get("delivery", project / "delivery")
    from sciplot_core.delivery.package_transaction import (
        _package_snapshot, _preserve_finder_metadata, _protect_editable_documents,
    )

    delivery_before = _package_snapshot(delivery_root)
    writes: dict[str, bytes | Path | PreparedFile | None] = {}
    with TemporaryDirectory(prefix="sciplot-publication-") as temporary, project_runtime(repository):
        from sciplot_core.studio_core.project_command_scope import figure_read_state
        from sciplot_core.studio_core.project_query_paths import project_snapshot

        _, _, selected_figures = project_snapshot(project)
        external_sources: dict[str, str] = {}
        for figure in selected_figures:
            if figure["status"] == "ready":
                external_sources.update(figure_read_state(project, figure)["source_files"])
        binding["source_files"] = external_sources
        candidate = Path(temporary).resolve()
        run, primary, secondary, delivery = (candidate / name for name in ("run", "primary", "secondary", "delivery"))
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
        if _package_snapshot(delivery_root) != delivery_before:
            raise ValueError("The visible delivery changed during private publication preparation")
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
        # The authoritative registry and ZIP are made from these exact pending
        # bytes. Neither builder installs active files or publishes another head.
        registry = read_intake_project_manifest(project, store=repository)
        if registry is not None:
            updated = studio_run_registration(deepcopy(registry), manifest, studio_run=payload)
            writes.update(stage_intake_project_manifest(project, updated, store=repository,
                project_writes={name: value for name, value in writes.items() if not name.startswith("@")}))
        adoptions = []
        for name, actual in before.get("outside_changes", {}).items():
            if not name.endswith(".vsz") or not name.startswith("studio/") or actual is None:
                raise ValueError("Publication found unregistered outside changes beyond audited native documents")
            # Scientific verification above audited the exact current native
            # documents in this full publication; no generic drift bypass exists.
            writes[name] = project / name
            adoptions.append(NativeAdoption(name, reads[name], actual,
                canonical_json_sha256(manifest["result"]["scientific_data_verification"])))
        command = command_for_binding(repository, binding, kind="native_import" if adoptions else "publish",
            key=key, writes=list(writes), request=intent, native_adoptions=adoptions)
        result = app.execute(command, lambda: ProjectMutation(writes, payload,
            sources=source_versions(binding, store=repository),
            artifacts={"publication.json": json.dumps(manifest, ensure_ascii=False, allow_nan=False).encode()}))
        return {**result["result"], "project_command": {field: result[field]
            for field in ("command_id", "project_id", "generation", "phase")}}
