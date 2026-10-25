"""Named Studio port for an exact-audited native/spec style rollback set."""

from __future__ import annotations

from pathlib import Path
from typing import Any
from tempfile import TemporaryDirectory

from sciplot_core.foundation.file_hashing import file_sha256
from sciplot_core.foundation.json_io import atomic_write_json
from sciplot_core.project_commands import ProjectCommands, ProjectMutation
from sciplot_core.project_store import FileProjectStore, ResourceRoot
from sciplot_core.foundation.json_hashing import canonical_json_sha256
from sciplot_core.studio_core.context import _project_context_for_document
from sciplot_core.studio_core.project_command_scope import command_for_binding, project_store
from sciplot_core.studio_core.persistence import stage_veusz_document
from sciplot_core.veusz_worker.spec_audit import audit_spec_data


def stage_transferred_style_pair(document: Any, target: Path, spec_path: Path,
                                 spec: dict[str, Any], *, output_document: Path,
                                 output_spec: Path, input_hashes: dict[str, str]) -> dict[str, Any]:
    """Produce exclusive private candidates without creating a project authority."""
    with TemporaryDirectory(prefix="sciplot-style-preview-") as folder:
        staged_spec = Path(folder) / "candidate.spec.json"
        atomic_write_json(staged_spec, spec)

        def validate(path: Path, **_kwargs: Any) -> bool:
            return str(audit_spec_data(path, staged_spec, check_presentation=True)["status"]) == "passed"

        stage = stage_veusz_document(document, Path(folder) / target.name, staged_validator=validate)
        staged_document = Path(stage["staged"])
        if not stage["reopen_validated"] or any(file_sha256(Path(path)) != digest
                                               for path, digest in input_hashes.items()):
            raise ValueError("Style-transfer inputs or private audit changed before freezing")
        with output_document.open("xb") as stream:
            stream.write(staged_document.read_bytes())
        with output_spec.open("xb") as stream:
            stream.write(staged_spec.read_bytes())
        output_document.chmod(target.stat().st_mode & 0o777)
        output_spec.chmod(spec_path.stat().st_mode & 0o777)
    return {"status": "passed", "reopen_validated": True,
            "document_sha256": file_sha256(output_document), "spec_sha256": file_sha256(output_spec)}


def save_transferred_style_pair(document: Any, target: Path, spec_path: Path,
                                spec: dict[str, Any], *, input_hashes: dict[str, str]) -> dict[str, Any]:
    temporary = TemporaryDirectory(prefix="sciplot-style-pair-")
    staged_spec = Path(temporary.name) / "candidate.spec.json"
    staged_document: Path | None = None
    context = _project_context_for_document(target)
    if context is not None:
        project = context["project_dir"]
        repository = project_store(project)
        from sciplot_core.studio_core.project_query import resolve_project_figure
        from sciplot_core.studio_core.project_command_scope import figure_binding

        selected = resolve_project_figure(target)
        if Path(selected["spec"]).resolve() != spec_path.resolve():
            raise ValueError("Style transfer requires the selected native figure's exact companion")
        binding = figure_binding(project, selected, store=repository)
    else:
        # A standalone pair may live beside unrelated files. Its sidecar owns
        # only these two exact members and never imports the containing tree.
        project = target.parent / (".sciplot-pair-" + canonical_json_sha256(str(target.resolve()))[:16])
        project.mkdir(exist_ok=True)
        if spec_path.parent != target.parent:
            raise ValueError("A standalone native/spec pair must share one parent")
        repository = FileProjectStore(project, locations={"pair": ResourceRoot(target.parent,
            members=(target.name, spec_path.name))})
    snapshot = repository.snapshot(import_legacy=True)
    if context is None:
        binding = {"project_id": snapshot["project_id"], "generation": snapshot["generation"], "files": {}}
    external = dict(binding.get("source_files", {}))
    for value, digest in input_hashes.items():
        path = Path(value)
        if path.is_relative_to(project) or (context is None and path in {target, spec_path}):
            binding["files"][repository.logical_path(path)] = digest
        else:
            external[value] = digest
    binding["source_files"] = external
    try:
        atomic_write_json(staged_spec, spec)

        def validate(path: Path, **_kwargs: Any) -> bool:
            return str(audit_spec_data(path, staged_spec, check_presentation=True)["status"]) == "passed"

        stage = stage_veusz_document(document, Path(temporary.name) / target.name, staged_validator=validate)
        staged_document = Path(stage["staged"])
        staged_document.chmod(target.stat().st_mode & 0o777)
        if spec_path.exists():
            staged_spec.chmod(spec_path.stat().st_mode & 0o777)
        if not stage["reopen_validated"]:
            raise ValueError("Transferred native/spec pair did not pass its staged exact audit.")
        if any(file_sha256(Path(path)) != digest for path, digest in input_hashes.items()):
            raise ValueError("Style-transfer input changed before pair installation.")
        from sciplot_core.studio_core.project_command_scope import source_versions

        writes = {repository.logical_path(target): staged_document, repository.logical_path(spec_path): staged_spec}
        request = {"target": repository.logical_path(target), "spec": spec,
                   "input_files": binding["files"], "external_inputs": external}
        key = canonical_json_sha256({"kind": "native_style_pair", "project_id": binding["project_id"], "request": request})
        command = command_for_binding(repository, binding, kind="style", key=key,
                                       writes=list(writes), request=request)
        committed = ProjectCommands(repository).execute(command,
            lambda: ProjectMutation(writes, {"status": "passed"}, sources=source_versions(binding, store=repository)))
        return {"kind": "sciplot_native_spec_style_pair", "status": "passed", "reopen_validated": True,
                "document_sha256": file_sha256(target), "spec_sha256": file_sha256(spec_path),
                "project_command": {name: committed[name] for name in ("command_id", "phase", "project_id", "generation")}}
    finally:
        staged_spec.unlink(missing_ok=True)
        if staged_document is not None:
            staged_document.unlink(missing_ok=True)
        temporary.cleanup()
