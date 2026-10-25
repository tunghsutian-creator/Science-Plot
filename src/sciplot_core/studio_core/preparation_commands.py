"""Prepare Studio privately, then publish its complete captured mutation once."""

from __future__ import annotations

from collections.abc import Callable
import json
import os
from pathlib import Path
from typing import Any

from sciplot_core.foundation.json_hashing import canonical_json_sha256
from sciplot_core.foundation.source_locations import resolve_source_path
from sciplot_core.project_commands import MembershipRead, PreparedFile, PreparedSource, ProjectCommand, ProjectCommands, ProjectMutation
from sciplot_core.project_commands.resources import resource_key
from sciplot_core.project_store.io import read_file, sha
from sciplot_core.project_store.runtime import selected_project_store
from sciplot_core.studio_core.preparation_candidate import (
    StudioPreparationCandidate, require_preparation_candidate, studio_preparation_candidate,
)
from sciplot_core.terminal_source_binding import SealedTerminalSourceBinding


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
    from sciplot_core.studio_core.studio_prepare import prepare_studio_document

    resource_key(request_relative)
    if request_relative.startswith("@"):
        raise ValueError("A Studio request must be a member of this candidate project.")
    candidate.request_members.add(request_relative)
    target = candidate.project_dir / request_relative if request_target else candidate.project_dir
    return prepare_studio_document(target, delivery_root=delivery_root, rule_id=rule_id,
        template=template, project_name=project_name, regenerate_generated=regenerate_generated,
        figure_set_path_replacer=figure_set_path_replacer,
        _terminal_source_binding=_terminal_source_binding,
        _terminal_source_prepared=_terminal_source_prepared, _new_creation=_new_creation)


def audit_studio_candidate(candidate: StudioPreparationCandidate, payload: dict[str, Any]) -> tuple[list[dict[str, Any]], list[PreparedSource]]:
    """Audit real saved native bytes and freeze their exact scientific inputs."""
    from sciplot_core.source_coverage.document_audit import _audit_exact_document_data
    from sciplot_core.source_coverage.managed_documents import source_records

    require_preparation_candidate(candidate.project_dir)
    registry = payload.get("figure_set")
    figures = registry.get("figures", []) if isinstance(registry, dict) else [
        {"status": "ready", "document": payload["document"], "spec": str(candidate.project_dir / "studio/spec.json")}]
    audits, sources = [], {}
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
        unchanged = (payload.get("preserved_existing_document") is True and previous is not None
                     and sha(document.read_bytes()) == previous["sha256"]
                     and current_spec_hash == expected_spec_hash)
        if unchanged:
            audits.append({"kind": "sciplot_unchanged_native_preparation", "status": "not_evaluated",
                "reason": "exact_native_preimage_preserved", "sha256": previous["sha256"]})
            continue  # Metadata-only reuse neither executes nor certifies new science.
        else:
            audit, spec_payload = _audit_exact_document_data(document_path=document, spec_path=spec,
                check_presentation=payload.get("preserved_existing_document") is not True)
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
            known = [identity for identity, versions in candidate.snapshot["sources"].items()
                     if versions.get(expected, {}).get("locator") == literal]
            if len(known) > 1:
                raise ValueError("The native source literal has ambiguous project identities.")
            identity = known[0] if known else canonical_json_sha256(
                {"project_id": candidate.snapshot["project_id"], "locator": literal})[:32]
            sources[(identity, expected)] = PreparedSource(identity, literal, expected, data, (), mode)
    return audits, list(sources.values())


def prepare_studio_generation(project: Path, *, request_target: bool = False,
                              request_relative: str = "plot_request.json",
                              delivery_root: Path | None = None, rule_id: str | None = None,
                              template: str | None = None, project_name: str | None = None,
                              regenerate_generated: bool = False,
                              figure_set_path_replacer: Callable[[Path, Path], None] | None = None,
                              _terminal_source_binding: SealedTerminalSourceBinding | None = None,
                              _terminal_source_prepared: bool = False, _new_creation: bool = False) -> dict[str, Any]:
    """The sole active-project writer for every public preparation caller."""
    from sciplot_core.project_manifest import _manifest_store, read_intake_project_manifest, stage_intake_project_manifest

    root = project.expanduser().resolve(strict=True)
    selected = selected_project_store()
    store = selected if selected is not None and selected.root == root else _manifest_store(root)
    before = store.snapshot(import_legacy=True)
    with studio_preparation_candidate(store, snapshot=before) as candidate:
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
                              for prefix in ("", *("@" + name for name in sorted(store.locations)))])
        record = ProjectCommands(store).execute(command, lambda: ProjectMutation(writes, result,
            prepared_sources=tuple(sources), artifacts={"native-audits.json": json.dumps(audits, ensure_ascii=False, allow_nan=False).encode()}))
        return {**record["result"], "project_command": {field: record[field]
            for field in ("command_id", "command_digest", "project_id", "generation", "phase")}}
