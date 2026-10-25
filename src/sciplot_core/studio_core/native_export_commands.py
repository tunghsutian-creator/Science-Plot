"""Exact selected-figure export without writing active files during rendering."""

from __future__ import annotations

from copy import deepcopy
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Any

from sciplot_core.foundation.json_hashing import canonical_json_sha256
from sciplot_core.project_commands import ProjectCommand, ProjectCommands, ProjectMutation
from sciplot_core.project_commands.resources import PreparedFile
from sciplot_core.project_store.runtime import project_runtime
from sciplot_core.studio_core.project_command_scope import (
    adopt_saved_native, command_for_binding, project_command_runtime, project_store, source_versions,
)
from sciplot_core.studio_core.project_query import resolve_project_figure
from sciplot_core.studio_core.export_projection import export_projection


@project_command_runtime
def export_saved_native(document: Path, *, formats: list[str], audit_spec_path: Path | None,
                        standalone_receipt: bool = False) -> dict[str, Any]:
    from sciplot_core.studio_core.export_execution import export_studio_document

    selected = resolve_project_figure(document)
    project = Path(selected["project"])
    repository = project_store(project)
    binding = adopt_saved_native(project, selected)
    request = {"figure_id": selected["figure_id"], "document": repository.logical_path(document),
               "formats": formats, "standalone_receipt": standalone_receipt, "input_files": binding["files"],
               "projected_reads": binding["projected_reads"], "source_files": binding["source_files"]}
    key = canonical_json_sha256({"kind": "native_export", "project_id": binding["project_id"], "request": request})
    app = ProjectCommands(repository)
    prior = app.query(key)
    if prior is not None:
        return export_projection(app.resume(ProjectCommand.from_payload(prior["metadata"])), repository)
    destination = (document.parent / "exports" / ("" if selected["primary"] else document.stem) if standalone_receipt
                   else project / "studio/exports" / ("" if selected["primary"] else "figure_set"))
    with TemporaryDirectory(prefix="sciplot-native-export-") as temporary, project_runtime(repository):
        private = Path(temporary) / "artifacts"
        candidate = export_studio_document(document, formats=formats, output_dir=private / "figures" if standalone_receipt else private,
                                            audit_spec_path=audit_spec_path)
        payload = deepcopy(candidate)
        writes: dict[str, bytes | Path | PreparedFile | None] = {}
        if standalone_receipt:
            from sciplot_core.studio_core.standalone_receipt import publish_standalone_export_receipt

            payload["standalone_export"] = publish_standalone_export_receipt(document_path=document,
                requested_formats=formats, exports=candidate["exports"], artifact_root=private,
                export_document_sha256=candidate["document_sha256"])
        from sciplot_core.studio_core.project_publication_commands import _stage_tree, relocate_candidate

        payload = relocate_candidate(payload, {private: destination})
        _stage_tree(private, repository.logical_path(destination), writes, {private: destination})
        artifacts = {}
        log = payload.pop("stderr_log", None)
        if log is not None:
            artifacts["native_export_stderr.log"] = Path(log)
        command = command_for_binding(repository, binding, kind="native_export", key=key,
                                      writes=list(writes), request=request)
        record = app.execute(command, lambda: ProjectMutation(writes, payload,
            sources=source_versions(binding, store=repository), artifacts=artifacts))
        return export_projection(record, repository)
