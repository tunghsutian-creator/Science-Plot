"""Managed creation persists scientific authority before building disposable native files."""

from pathlib import Path
from typing import Any

from sciplot_core.plot_ir import create_managed_document
from sciplot_core.studio_core.project_query_paths import canonical_path
from sciplot_core.studio_core.project_session import external_project_session

from .backend import PlotBackend
from .errors import EngineError
from .exports import export_head
from .managed_resolution import resolve_science, resolved_metadata
from .managed_state import make_binding
from .storage import commit, digest, load_head, read, write


def create_managed(request: dict[str, Any], backend: PlotBackend) -> dict[str, Any]:
    sources = request["data_binding"]["data_sources"]
    if not sources:
        raise EngineError("managed_source_required", "Managed creation requires explicit original data sources.")
    source = canonical_path(Path(sources[0]["path"]))
    identifier = "plot:" + digest([str(source.parent), request["idempotency_key"]])[:24]
    root = source.parent / ".sciplot_documents" / "managed" / digest(request["idempotency_key"])
    output = canonical_path(Path(request["out"])) if "out" in request else source.parent / (source.stem + "_SciPlot") / identifier.replace(":", "_")
    if output == source or output == source.parent or output in source.parents or output == root:
        raise EngineError("managed_output_conflict", "Select a distinct managed output directory beside the source.")
    root.parent.mkdir(parents=True, exist_ok=True)
    with external_project_session(root):
        path = root / "managed-creation.json"
        if path.exists():
            state = read(path)
            if state["request_hash"] != digest(request):
                raise EngineError("document_idempotency_conflict", "This creation key belongs to a different managed request.")
        else:
            if output.exists() and any(output.iterdir()):
                raise EngineError("managed_output_conflict", "The selected output directory already contains files.")
            document = create_managed_document(request["template_definition"], request["data_binding"],
                                               plot_id=identifier, theme=request.get("theme"))
            document = resolved_metadata(document, rule_id=request["rule_id"], executors=request.get("scientific_executors", {}))
            state = {"request_hash": digest(request), "request": request, "document": document,
                     "output": str(output), "phase": "resolving"}
            write(path, state)
        if not (root / "head.json").exists():
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
        return result
