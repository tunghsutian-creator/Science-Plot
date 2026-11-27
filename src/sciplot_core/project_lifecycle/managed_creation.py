"""Managed creation persists scientific authority before building disposable native files."""

from collections.abc import Callable, Iterator
from contextlib import contextmanager
from pathlib import Path

from .context import exists, prepare_namespace, has_head, require_empty_output
from .targets import ManagedCreationLocation

from .contracts import AuthorityMode, NormalizedCommand
from typing import Any

from sciplot_core.plot_ir import create_managed_document
from sciplot_core.host_grants import admit_document_executors
from sciplot_core.source_tables.read_session import with_table_reads
from sciplot_core.project_lifecycle.context import external_project_session

from sciplot_core.plot_engine.backend import PlotBackend
from sciplot_core.project_lifecycle.errors import EngineError
from sciplot_core.plot_engine.current_unit_admission import admit_current_units
from sciplot_core.project_lifecycle.exports import export_head
from sciplot_core.plot_engine.external_mutation import authority_status
from sciplot_core.plot_engine.managed_resolution import resolve_science, resolved_metadata
from sciplot_core.plot_engine.managed_state import ManagedPreparation, prepare_binding
from sciplot_core.plot_engine.object_operations import plot_object_handle
from sciplot_core.project_lifecycle.context import commit, digest, load_head, read, write


def new_managed_member(request: dict[str, Any], plot_id: str) -> dict[str, Any]:
    """Admit one member's template, data binding, and host executors."""
    document = create_managed_document(request["template_definition"], request["data_binding"],
                                       plot_id=plot_id, theme=request.get("theme"))
    executors = admit_document_executors(document, request.get("scientific_executors", {}))
    return resolved_metadata(document, rule_id=request["rule_id"], executors=executors)


def bind_managed_member(
    root: Path, document: dict[str, Any], output: Path, *, already_resolved: bool = False,
    checkpoint: Callable[[dict[str, Any], dict[str, Any]], None] | None = None,
) -> tuple[dict[str, Any], ManagedPreparation]:
    """Prepare canonical science and IR; the caller owns the commit boundary."""
    if not already_resolved:
        document, evidence = resolve_science(root, document)
        if checkpoint is not None:
            checkpoint(document, evidence)
    return document, prepare_binding(root, document, output=output)


@with_table_reads
def create_managed(request: dict[str, Any], backend: PlotBackend, *, location: ManagedCreationLocation) -> dict[str, Any]:
    with committed_managed_creation(request, location=location) as head:
        result = export_head(location.root, head, backend)
        result.update({"plot_type": "ManagedPlot", "ir_hash": head["binding"]["ir_hash"],
                       "creation_evidence": str(location.root / "managed-creation.json")})
        result["plot_objects"] = [plot_object_handle(result, document=head["document"],
                                                    authority=authority_status("ManagedPlot"))]
        return result


@contextmanager
def committed_managed_creation(request: dict[str, Any], *, location: ManagedCreationLocation) -> Iterator[dict[str, Any]]:
    """Resolve and bind the canonical revision, then yield inside the creation lease."""
    root, output, identifier = location.root, location.output, location.plot_id
    path = root / "managed-creation.json"
    initial = None
    if not exists(path):
        # New requests cannot allocate a journal or reserve execution by declaring
        # their own executable, permissions or alternate host configuration.
        initial = new_managed_member(request, identifier)
    prepare_namespace(root)
    with external_project_session(root):
        if exists(path):
            state = read(path)
            if state["request_hash"] != digest(request):
                raise EngineError("document_idempotency_conflict", "This creation key belongs to a different managed request.")
        else:
            from sciplot_core.project_store.io import STORE

            from .managed_store_target import MANAGED_STORE_CLAIM

            # Standalone and Store bootstrap use the same source/key root and
            # lease; an older wire cannot race a second HEAD into that root.
            if any(path.exists() or path.is_symlink() for path in (root / MANAGED_STORE_CLAIM, root / STORE)):
                raise EngineError("document_idempotency_conflict", "This key belongs to a Store-backed creation; retry its original request.")
            require_empty_output(output)
            if initial is None:
                raise EngineError("document_state_changed", "The existing creation state disappeared; inspect it rather than starting new work.")
            document = initial
            admit_current_units(root, document)
            state = {"request_hash": digest(request), "request": request, "document": document,
                     "output": str(output), "phase": "resolving",
                     "normalized_command": NormalizedCommand.create("create", request, authority=AuthorityMode.MANAGED).to_payload()}
            write(path, state)
        if not has_head(root):
            def checkpoint(resolved: dict[str, Any], evidence: dict[str, Any]) -> None:
                state.update({"document": resolved, "resolution": evidence, "phase": "resolved"})
                write(path, state)

            document, prepared = bind_managed_member(root, state["document"], output,
                already_resolved=state["phase"] != "resolving", checkpoint=checkpoint)
            commit(root, document, prepared.binding, "managed_creation")
            state["phase"] = "committed"
            write(path, state)
        yield load_head(root)
