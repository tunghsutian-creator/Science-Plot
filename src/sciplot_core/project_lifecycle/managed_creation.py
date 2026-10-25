"""Managed creation persists scientific authority before building disposable native files."""

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
from sciplot_core.plot_engine.managed_state import make_binding
from sciplot_core.plot_engine.object_operations import plot_object_handle
from sciplot_core.project_lifecycle.context import commit, digest, load_head, read, write


@with_table_reads
def create_managed(request: dict[str, Any], backend: PlotBackend, *, location: ManagedCreationLocation) -> dict[str, Any]:
    root, output, identifier = location.root, location.output, location.plot_id
    path = root / "managed-creation.json"
    initial = None
    if not exists(path):
        # New requests cannot allocate a journal or reserve execution by declaring
        # their own executable, permissions or alternate host configuration.
        initial = create_managed_document(request["template_definition"], request["data_binding"],
                                          plot_id=identifier, theme=request.get("theme"))
        executors = admit_document_executors(initial, request.get("scientific_executors", {}))
        initial = resolved_metadata(initial, rule_id=request["rule_id"], executors=executors)
    prepare_namespace(root)
    with external_project_session(root):
        if exists(path):
            state = read(path)
            if state["request_hash"] != digest(request):
                raise EngineError("document_idempotency_conflict", "This creation key belongs to a different managed request.")
        else:
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
            if state["phase"] == "resolving":
                document, evidence = resolve_science(root, state["document"])
                state.update({"document": document, "resolution": evidence, "phase": "resolved"})
                write(path, state)
            document = state["document"]
            binding = make_binding(root, document, output=output)
            commit(root, document, binding, "managed_creation")
            state["phase"] = "committed"
            write(path, state)
        head = load_head(root)
        result = export_head(root, head, backend)
        result.update({"plot_type": "ManagedPlot", "ir_hash": head["binding"]["ir_hash"],
                       "creation_evidence": str(path)})
        result["plot_objects"] = [plot_object_handle(result, document=head["document"],
                                                    authority=authority_status("ManagedPlot"))]
        return result
