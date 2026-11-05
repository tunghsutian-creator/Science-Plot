"""Read-only publication witness for an audited, human-saved native figure."""

from pathlib import Path
import stat
from typing import Any

from sciplot_core.project_commands.resources import FigureReadWitness
from sciplot_core.project_commands.read_projections import projection_digest
from sciplot_core.studio_core.project_command_scope import figure_read_witness, project_store


def observed_figure_read_witness(
    project: Path, selected: dict[str, Any],
) -> tuple[dict[str, Any], FigureReadWitness]:
    """Read one existing generation's native-only adoption eligibility.

    No native worker, attachment or publication runs here. Source resolution
    retains the active runtime's existing immutable-history cache behavior.
    """
    repository = project_store(project)
    before = repository.snapshot()
    document = Path(selected["document"])
    logical = repository.logical_path(document)
    registered = before["files"].get(logical)
    if registered is None:
        raise ValueError("The selected native figure has unregistered outside changes: unknown native member")
    witness = figure_read_witness(project, selected)
    reads = witness.to_read_state_payload()
    observed = reads["project_files"][logical]
    if (selected.get("document_sha256", observed) != observed
            or selected.get("spec_sha256", reads["project_files"][repository.logical_path(Path(selected["spec"]))])
            != reads["project_files"][repository.logical_path(Path(selected["spec"]))]):
        raise ValueError("The selected native or spec revision changed while capturing its read witness")
    if stat.S_IMODE(document.stat().st_mode) != registered["mode"]:
        raise ValueError("The observed native figure changed its registered permissions")
    for name, digest in reads["project_files"].items():
        entry = before["files"].get(name, {})
        if stat.S_IMODE((repository.root / name).stat().st_mode) != entry.get("mode"):
            raise ValueError("The observed native read witness changed its registered permissions")
        if name != logical and entry.get("sha256") != digest:
            raise ValueError("Observed native import cannot change source, spec, or request")
    for read in reads["projected_reads"]:
        if (stat.S_IMODE((repository.root / read["resource"]).stat().st_mode)
                != before["files"].get(read["resource"], {}).get("mode")):
            raise ValueError("The observed native membership changed its registered permissions")
        registered_projection = projection_digest(repository.read_bytes(read["resource"], generation=before["generation"]),
            kind=read["kind"], key=read["key"])
        if registered_projection != read["sha256"]:
            raise ValueError("Observed native import cannot change selected figure membership")
    return before, witness


def observed_figure_read_state(
    project: Path, selected: dict[str, Any],
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Compatibility projection; actual observation has one typed owner."""
    before, witness = observed_figure_read_witness(project, selected)
    return before, witness.to_read_state_payload()


def observed_figure_binding(
    project: Path, selected: dict[str, Any], audit: dict[str, Any],
) -> dict[str, Any]:
    """Keep the registered CAS baseline separate from exact audited native bytes."""
    repository = project_store(project)
    before, witness = observed_figure_read_witness(project, selected)
    reads = witness.to_read_state_payload()
    logical = repository.logical_path(Path(selected["document"]))
    registered = before["files"][logical]
    observed = reads["project_files"][logical]
    if selected.get("document_sha256") != observed:
        raise ValueError("The observed native figure is not the exact registered member")
    if observed != registered["sha256"] and (
        audit.get("status") != "passed" or audit.get("document_sha256") != observed
        or audit.get("spec_sha256") != reads["project_files"][repository.logical_path(Path(selected["spec"]))]
    ):
        raise ValueError("Observed native import requires the exact passed native and spec audit")
    canonical = FigureReadWitness(
        files=tuple(sorted({**dict(witness.files), logical: registered["sha256"]}.items())),
        source_files=witness.source_files, projected_reads=witness.projected_reads)
    return {"project_id": before["project_id"], "generation": before["generation"],
            **canonical.to_binding_fields()}
