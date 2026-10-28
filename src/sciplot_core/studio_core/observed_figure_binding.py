"""Read-only publication witness for an audited, human-saved native figure."""

from pathlib import Path
import stat
from typing import Any

from sciplot_core.project_commands.read_projections import projection_digest
from sciplot_core.studio_core.project_command_scope import figure_read_state, project_store


def observed_figure_binding(
    project: Path, selected: dict[str, Any], audit: dict[str, Any],
) -> dict[str, Any]:
    """Keep the registered CAS baseline separate from observed native bytes.

    This does not adopt a save. The existing publication owner can adopt the
    exact audited native only after the semantic review has been accepted.
    """
    repository = project_store(project)
    before = repository.snapshot()
    reads = figure_read_state(project, selected)
    document = Path(selected["document"])
    logical = repository.logical_path(document)
    registered = before["files"].get(logical)
    observed = reads["project_files"][logical]
    if registered is None or selected["document_sha256"] != observed:
        raise ValueError("The observed native figure is not the exact registered member")
    if stat.S_IMODE(document.stat().st_mode) != registered["mode"]:
        raise ValueError("The observed native figure changed its registered permissions")
    for name, digest in reads["project_files"].items():
        if name != logical and before["files"].get(name, {}).get("sha256") != digest:
            raise ValueError("Observed native import cannot change source, spec, or request")
    for read in reads["projected_reads"]:
        registered_projection = projection_digest(repository.read_bytes(read["resource"], generation=before["generation"]),
            kind=read["kind"], key=read["key"])
        if registered_projection != read["sha256"]:
            raise ValueError("Observed native import cannot change selected figure membership")
    if observed != registered["sha256"] and (
        audit.get("status") != "passed" or audit.get("document_sha256") != observed
        or audit.get("spec_sha256") != reads["project_files"][repository.logical_path(Path(selected["spec"]))]
    ):
        raise ValueError("Observed native import requires the exact passed native and spec audit")
    return {"project_id": before["project_id"], "generation": before["generation"],
        "files": {**reads["project_files"], logical: registered["sha256"]},
        "projected_reads": reads["projected_reads"], "source_files": reads["source_files"]}
