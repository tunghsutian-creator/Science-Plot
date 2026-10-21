"""Read existing project authorities for bounded saved-work discovery."""

from pathlib import Path
from typing import Any

from sciplot_core.foundation.file_hashing import existing_file_sha256
from sciplot_core.foundation.json_hashing import canonical_json_sha256
from sciplot_core.plot_engine.backend_router import BackendRouter
from sciplot_core.plot_engine.current import changed_inputs
from sciplot_core.plot_engine.managed_state import read_canonical
from sciplot_core.plot_engine.storage import active, document_root, load_head
from sciplot_core.plot_backends.veusz import VeuszBackend
from sciplot_core.studio_core.project_query import inspect_project
from sciplot_core.studio_core.project_query_paths import bound_delivery_project, canonical_path, read_object
from sciplot_core.studio_core.delivery_target import resolve_delivery_target


def source_relation(recorded: Path, expected: str | None, source: Path,
                    source_sha256: str | None) -> str | None:
    if recorded == source:
        return "recorded_path"
    if expected and source_sha256 and expected == source_sha256:
        return "same_content_other_path"
    return None


def record_path(value: Any, *, base: Path | None = None) -> Path:
    if not isinstance(value, str) or not value.strip() or "\x00" in value:
        raise ValueError("Recorded paths must be nonempty strings without NUL bytes.")
    path = Path(value).expanduser()
    if not path.is_absolute():
        if base is None:
            raise ValueError("Task and document identities require absolute recorded paths.")
        path = base / path
    return canonical_path(path)


def document_evidence(root: Path) -> dict[str, Any]:
    """Use the document owner, including content seals and native mutation guards."""
    head_sha = existing_file_sha256(root / "head.json")
    head = load_head(root)
    doc, binding = head["document"], head["binding"]
    # A copied authority must not silently operate on the original absolute binding.
    if doc.get("plot_type") == "ManagedPlot" and record_path(binding["root"]) != root:
        raise ValueError("The copied or moved document still binds another authority root.")
    for group in ("files", "source_trees", "scientific_content_files"):
        for name in binding.get(group, {}):
            record_path(name)
    for group in binding["fingerprint"].values():
        for name in group:
            record_path(name)
    for name in binding.get("scientific_content_files", {}):
        record_path(name)
    if doc.get("plot_type") == "ManagedPlot":
        for name in ("canonical_document", "document", "ir_path", "output"):
            record_path(binding[name])
        if read_canonical(binding) != doc:
            raise ValueError("The canonical model differs from its sealed document revision.")
    backend = BackendRouter(VeuszBackend())
    try:
        changed = changed_inputs(backend, binding)
    finally:
        backend.close()
    pending = active(root)
    pending = pending if pending and pending["phase"] not in {"complete", "rejected"} else None
    native_continuation: dict[str, Any] | None = None
    if doc.get("plot_type", "LegacyPlot") == "LegacyPlot" and changed and pending is None:
        project = record_path(binding["project"])
        document, spec = record_path(binding["document"]), record_path(binding["spec"])
        if document_root(project, binding["figure_id"]) == root and set(changed) <= {str(document), str(spec)}:
            from sciplot_core.studio_core.document_edit_commit import applied_native_edit_chain

            try:
                chain = applied_native_edit_chain(project, figure_id=binding["figure_id"],
                    document=document, spec=spec, baseline_files=binding["fingerprint"]["files"])
                if chain:
                    native_continuation = {"current": True, "authority": "saved_vsz",
                        "operation_ids": chain, "document_sha256": existing_file_sha256(document),
                        "spec_sha256": existing_file_sha256(spec), "native_audit_evaluated": False}
            except (OSError, ValueError, TypeError, KeyError) as exc:
                native_continuation = {"current": False, "authority": "saved_vsz", "error": str(exc)}
    if existing_file_sha256(root / "head.json") != head_sha:
        raise ValueError("The document revision changed during discovery.")
    return {"plot": str(root), "plot_id": doc["plot_id"], "revision": doc["revision"],
            "plot_type": doc.get("plot_type", "LegacyPlot"),
            "scientific_hash": doc["scientific_hash"], "presentation_hash": doc["presentation_hash"],
            "changed_inputs": changed, "current": not changed and pending is None,
            **({"native_continuation": native_continuation} if native_continuation is not None else {}),
            "pending": {"phase": pending["phase"], "idempotency_key": pending["request"]["idempotency_key"]} if pending else None,
            "data_sources": doc["scientific"]["data_sources"],
            "project": binding.get("project"), "figure_id": binding.get("figure_id")}


def project_evidence(project: Path, source: Path, source_sha256: str | None,
                     *, receipt_sha256: str | None = None,
                     receipt_source: Path | None = None) -> dict[str, Any] | None:
    request = read_object(project / "plot_request.json")
    recorded = record_path(request.get("input"), base=project)
    expected = (request.get("resolved_figure_plan") or {}).get("source_sha256")
    mapping = request.get("data_mapping_plan_binding")
    if isinstance(mapping, dict) and record_path(mapping.get("original_input"), base=project) == recorded:
        # FigurePlan seals the selected effective table. Discovery searches the
        # original source, whose distinct tree seal belongs to the mapping.
        expected = mapping.get("original_input_sha256")
    relation = source_relation(recorded, expected, source, source_sha256)
    matched_sha = expected
    if relation is None and receipt_source is not None:
        relation = source_relation(receipt_source, receipt_sha256, source, source_sha256)
        if relation:
            recorded, matched_sha = receipt_source, receipt_sha256
    if relation is None and source.is_file() and source_sha256:
        # Ordinary preparation retains exact raw snapshots in study_model while
        # input/plan identity belongs to its prepared source directory. The raw
        # file seal is existing provenance, not a filename or approximate match.
        actual = existing_file_sha256(source)
        for sample in (request.get("study_model") or {}).get("samples", []):
            for replicate in sample.get("replicates", []):
                raw = replicate.get("source_file") or {}
                if raw.get("sha256") and raw["sha256"] == actual:
                    recorded = record_path(raw["raw_path"])
                    relation, matched_sha = "same_content_other_path", source_sha256
                    break
    if relation is None:
        return None
    query = inspect_project(project, native=False)
    documents = []
    for figure in query["figures"]:
        root = document_root(project, figure["figure_id"])
        if (root / "head.json").exists():
            documents.append(document_evidence(root))
    source_current = query["source"]["current"]
    selected_source_current = source_sha256 == matched_sha if source_sha256 and matched_sha else None
    stale = [item for item in documents if not item["current"]
             and not (item.get("native_continuation") or {}).get("current")]
    delivery_owner = None
    visible_conflict = False
    delivery_path = (query.get("delivery") or {}).get("path")
    delivery_root = record_path(delivery_path, base=project) if isinstance(delivery_path, str) else None
    if delivery_root is not None and delivery_root.is_dir():
        try:
            delivery_owner = bound_delivery_project(delivery_root)
        except (OSError, ValueError, TypeError, KeyError):
            pass
        if delivery_owner == project:
            try:
                resolve_delivery_target(delivery_root)
            except (OSError, ValueError, TypeError, KeyError):
                visible_conflict = True
    state = ("source_revision_required" if source_current is False or selected_source_current is False else
             "visible_edits_require_recovery" if visible_conflict else
             "source_evidence_missing" if source_current is None else
             "document_conflict" if stale else
             "project_output_conflict" if delivery_owner is not None and delivery_owner != project else "saved_project")
    figures = [{key: item[key] for key in ("figure_id", "title", "document", "document_sha256",
                "spec", "spec_sha256")} for item in query["figures"]]
    identity = {"request_sha256": query["request_sha256"], "figures": figures,
                "documents": documents, "source": query["source"]}
    return {"target": str(project), "kind": "project", "state": state,
            "source_relation": relation, "recorded_source": str(recorded),
            "recorded_source_sha256": matched_sha,
            "project_input": str(record_path(request.get("input"), base=project)),
            "selected_source_current": selected_source_current,
            "delivery_owner": str(delivery_owner) if delivery_owner else None,
            "source": query["source"], "figures": figures, "documents": documents,
            "primary_figure_id": query["primary_figure_id"],
            "identity_sha256": canonical_json_sha256(identity, allow_nan=False),
            "authority": "saved_vsz", "continuation_available": state == "saved_project",
            **({"next_step": {"action": "recover_visible_edits", "target": str(delivery_root),
                               "message": "Recover the separately saved visible edits before continuing the canonical project."}}
               if visible_conflict else {}),
            "ready_to_use": None, "readiness_evaluated": False}


def managed_evidence(root: Path, source: Path, source_sha256: str | None) -> dict[str, Any] | None:
    evidence = document_evidence(root)
    if evidence["plot_type"] != "ManagedPlot":
        return None  # Legacy shadows are reached through their canonical project.
    relations = []
    for item in evidence["data_sources"]:
        recorded = record_path(item["path"])
        # Managed source hashes seal file bytes, unlike the source-tree hash.
        expected = item["sha256"]
        actual = existing_file_sha256(source)
        if recorded == source:
            relations.append("recorded_path")
        elif source_sha256 and expected == actual:
            relations.append("same_content_other_path")
    if not relations:
        return None
    state = "managed_plot" if evidence["current"] else "document_conflict"
    return {"target": str(root), "kind": "managed_plot", "state": state,
            "source_relation": "recorded_path" if "recorded_path" in relations else "same_content_other_path",
            "authority": "sciplot_document", "document": evidence,
            "identity_sha256": canonical_json_sha256(evidence, allow_nan=False),
            "continuation_available": evidence["current"], "ready_to_use": None,
            "readiness_evaluated": False}
