"""Adopt an audited saved Legacy native through the sole project command writer."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from sciplot_core.foundation.file_hashing import file_sha256
from sciplot_core.foundation.json_hashing import canonical_json_sha256
from sciplot_core.project_commands import NativeAdoption, ProjectCommands, ProjectMutation
from sciplot_core.studio_core import native_scientific_audit
from sciplot_core.studio_core.observed_figure_binding import observed_figure_binding
from sciplot_core.studio_core.project_command_scope import (
    command_for_binding, figure_binding, figure_read_state, project_store, source_versions,
)


def adopt_saved_native(project: Path, selected: dict[str, Any], *,
                       expected_binding: dict[str, Any] | None = None) -> dict[str, Any]:
    """Register one audited Legacy save; retain an explicit mutation's read witness."""
    repository = project_store(project)
    reads = figure_read_state(project, selected)
    before = repository.snapshot(import_legacy=True)
    document = Path(selected["document"])
    logical = repository.logical_path(document)
    expected = before["files"].get(logical, {}).get("sha256")
    observed = file_sha256(document)
    if (selected.get("document_sha256", observed) != observed
            or selected.get("spec_sha256", reads["project_files"][repository.logical_path(Path(selected["spec"]))])
            != reads["project_files"][repository.logical_path(Path(selected["spec"]))]):
        raise ValueError("The selected saved native or specification revision is stale")
    if expected_binding is not None and (
        expected_binding["project_id"] != before["project_id"]
        or expected_binding["files"] != reads["project_files"]
        or expected_binding.get("projected_reads", []) != reads["projected_reads"]
        or expected_binding.get("source_files", {}) != reads["source_files"]
    ):
        raise ValueError("The saved native baseline changed before mutation admission")
    if expected == observed:
        return figure_binding(project, selected, store=repository)
    if expected is None:
        raise ValueError("An unknown native member cannot be adopted as a saved Legacy figure")
    audit = native_scientific_audit.audit_edited_document(document, Path(selected["spec"]))
    if audit.get("document_sha256") != observed:
        raise ValueError("The saved Legacy native audit does not bind these exact observed bytes")
    binding = observed_figure_binding(project, {**selected, "document_sha256": observed}, audit)
    audit_hash = canonical_json_sha256(audit)
    request = {"family": "saved_legacy_native", "resource": logical,
               "before_sha256": expected, "observed_sha256": observed, "audit_sha256": audit_hash}
    key = canonical_json_sha256({"project_id": before["project_id"], "request": request})
    command = command_for_binding(repository, binding, kind="native_import", key=key, writes=[logical], request=request,
        native_adoptions=[NativeAdoption(logical, expected, observed, audit_hash)])
    ProjectCommands(repository).execute(command, lambda: ProjectMutation({logical: document}, request,
        sources=source_versions(binding, store=repository), artifacts={"audit.json": json.dumps(audit, ensure_ascii=False).encode()}))
    return figure_binding(project, selected, store=repository)
