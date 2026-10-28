"""Read existing project authorities for bounded saved-work discovery."""

from pathlib import Path
from typing import Any

from sciplot_core.foundation.file_hashing import existing_file_sha256
from sciplot_core.foundation.json_hashing import canonical_json_sha256
from sciplot_core.plot_engine.backend_router import BackendRouter
from sciplot_core.plot_engine.current import changed_inputs
from sciplot_core.plot_engine.managed_state import read_canonical
from sciplot_core.plot_engine.storage import active, document_root, load_head
from sciplot_core.project_lifecycle.context import content_sha256, repository_scope
from sciplot_core.project_lifecycle.attachment_index import Attachment, read_index, require_local_owner
from sciplot_core.project_lifecycle.attachment_projection import derived_relative, metadata_view
from sciplot_core.project_lifecycle.frozen_namespace import FrozenNamespaceRepository
from sciplot_core.project_lifecycle.file_content import read_snapshot
from sciplot_core.project_store.runtime import project_runtime
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


def document_evidence(root: Path, *, attachment: Attachment | None = None,
                      snapshot: dict[str, Any] | None = None) -> dict[str, Any]:
    if attachment is None:
        if root.parent.name != '.sciplot_semantic':
            require_local_owner(root)
            return _document_evidence(root)
        from sciplot_core.project_lifecycle.store_composition import existing_store

        store = existing_store(root.parent.parent)
        snapshot = store.snapshot()
        index = read_index(store, snapshot)
        entry = index['attachments'].get(root.name)
        if entry is None or Attachment(store, entry).root != root:
            raise ValueError("The selected semantic namespace lacks its exact current project attachment.")
        attachment = Attachment(store, entry)
    assert snapshot is not None
    prefix = attachment.entry["namespace"] + "/"
    members = {name.removeprefix(prefix): attachment.store.read_bytes(name, generation=snapshot["generation"])
               for name in snapshot["files"] if name.startswith(prefix)}
    for relative, logical in attachment.entry.get("archived_derivatives", {}).items():
        if (not logical.startswith(prefix + "archive/") or str(Path(relative)) != relative
                or Path(relative).is_absolute() or ".." in Path(relative).parts or not derived_relative(Path(relative))):
            raise ValueError("The attached document has an invalid immutable history resource.")
        members[relative] = attachment.store.read_bytes(logical, generation=snapshot["generation"])
    captured = FrozenNamespaceRepository(attachment.origin, attachment.root, members)
    with repository_scope(captured):
        # Validate the original sealed envelope before projecting runtime paths.
        head = metadata_view(captured.load_head(attachment.origin), attachment)
        if (head["document"]["plot_id"] != attachment.entry["plot_id"]
                or head["binding"].get("project", str(attachment.store.root)) != str(attachment.store.root)
                or head["binding"].get("figure_id", attachment.entry["figure_id"]) != attachment.entry["figure_id"]):
            raise ValueError("The current semantic attachment does not identify this project figure.")
        pending = captured.active(attachment.origin)
        if pending is not None:
            from sciplot_core.project_lifecycle.journal_identity import saved_command

            saved_command(pending)
        pending = metadata_view(pending, attachment) if pending else None
    artifacts: dict[Path, dict[str, Any] | None] = {}
    artifact_roots: tuple[Path, ...] = ()
    if head['document'].get('plot_type') == 'ManagedPlot':
        native = Path(head['binding']['document'])
        output = attachment.output
        if output is None or not native.is_relative_to(output) or head['binding']['output'] != str(output):
            raise ValueError("The managed cache does not belong to its exact selected output role.")
        artifact_roots = (native.parent,)
        for path in (native, native.parent / 'build.json', native.parent / 'compile-intent.json'):
            artifacts[path] = read_snapshot(path) if path.exists() or path.is_symlink() else None
        captured = FrozenNamespaceRepository(attachment.origin, attachment.root, members,
            artifacts={path: fact['bytes'] for path, fact in artifacts.items() if fact is not None},
            artifact_roots=artifact_roots)
    with repository_scope(captured), project_runtime(attachment.store, generation=snapshot['generation']):
        result = _document_evidence(root, head=head, pending=pending, attached=True)
    for path, before in artifacts.items():
        after = read_snapshot(path) if path.exists() or path.is_symlink() else None
        if before != after:
            raise ValueError("The selected disposable managed artifact changed during discovery.")
    if attachment.store.snapshot()["generation"] != snapshot["generation"]:
        raise ValueError("The project generation changed during saved-work discovery.")
    return result


def _document_evidence(root: Path, *, head: dict[str, Any] | None = None,
                       pending: dict[str, Any] | None = None, attached: bool = False) -> dict[str, Any]:
    """Use the document owner, including content seals and native mutation guards."""
    head_sha = content_sha256(root / "head.json")
    head = head if head is not None else load_head(root)
    doc, binding = head["document"], head["binding"]
    # A copied authority must not silently operate on the original absolute binding.
    if doc.get("plot_type") == "ManagedPlot" and record_path(binding["root"]) != root:
        raise ValueError("The copied or moved document still binds another authority root.")
    for group in ("files", "source_trees", "scientific_content_files"):
        for name in binding.get(group, {}):
            record_path(name)
    for kind, group in binding["fingerprint"].items():
        if kind == "projections":
            from sciplot_core.project_commands.resources import ProjectionRead

            reads = [ProjectionRead(**item) for item in binding.get('projected_reads', [])]
            expected = {item.resource + ':' + item.kind + ':' + item.key: item.sha256 for item in reads}
            if len(expected) != len(reads) or group != expected:
                raise ValueError("The native fingerprint projections differ from their exact typed read witnesses.")
        else:
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
    pending = pending if attached else active(root)
    pending = pending if pending and pending["phase"] not in {"complete", "rejected"} else None
    native_continuation: dict[str, Any] | None = None
    if doc.get("plot_type", "LegacyPlot") == "LegacyPlot" and changed and pending is None:
        project = record_path(binding["project"])
        document, spec = record_path(binding["document"]), record_path(binding["spec"])
        if (attached or document_root(project, binding["figure_id"]) == root) and set(changed) <= {str(document), str(spec)}:
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
    if content_sha256(root / "head.json") != head_sha:
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
    store = None
    if (project / ".sciplot_store/head.json").is_file():
        from sciplot_core.project_host_factory import project_store

        store = project_store(project)
    snapshot = store.snapshot() if store is not None else None
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
    index = read_index(store, snapshot) if store is not None else None
    for figure in query["figures"]:
        entries = [entry for entry in index["attachments"].values()
                   if entry["figure_id"] == figure["figure_id"]] if index is not None else []
        if len(entries) > 1:
            raise ValueError("One figure has competing current semantic attachments.")
        if entries:
            assert store is not None and snapshot is not None
            attachment = Attachment(store, entries[0])
            documents.append(document_evidence(attachment.root, attachment=attachment, snapshot=snapshot))
        else:
            root = document_root(project, figure["figure_id"])
            require_local_owner(root)
            if snapshot is not None and index is not None:
                prefixes = tuple(item['namespace'] + '/' for item in index['attachments'].values())
                if any(name.startswith('.sciplot_semantic/') and name != '.sciplot_semantic/index.json'
                       and not name.startswith(prefixes) for name in snapshot['files']):
                    raise ValueError("Semantic attachment resources cannot fall back to an unindexed historical writer.")
            if (root / "head.json").exists():
                historical = document_evidence(root)
                if historical['project'] != str(project) or historical['figure_id'] != figure['figure_id']:
                    raise ValueError("The unattached historical shadow belongs to another project or figure.")
                documents.append(historical)
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
    # A known foreign publication owner is an explicit copy conflict regardless
    # of that copy's source currentness. Source repair cannot transfer delivery
    # ownership and must not be offered as a way around this conflict.
    state = ("project_output_conflict" if delivery_owner is not None and delivery_owner != project else
             "source_revision_required" if source_current is False or selected_source_current is False else
             "visible_edits_require_recovery" if visible_conflict else
             "source_evidence_missing" if source_current is None else
             "document_conflict" if stale else "saved_project")
    figures = [{key: item[key] for key in ("figure_id", "title", "document", "document_sha256",
                "spec", "spec_sha256")} for item in query["figures"]]
    identity = {"request_sha256": query["request_sha256"], "figures": figures,
                "documents": documents, "source": query["source"]}
    if store is not None and snapshot is not None and store.snapshot()["generation"] != snapshot["generation"]:
        raise ValueError("The project generation changed during saved-work discovery.")
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
