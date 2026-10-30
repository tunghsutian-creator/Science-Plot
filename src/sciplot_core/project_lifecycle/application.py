"""Application owner of the complete Managed and Legacy semantic aggregate lifecycle."""

from pathlib import Path
from .context import exists

from .admission import usecase, admitted
from .ports import ProjectRepository, ProjectTargets
from .targets import StoredTarget, ManagedDeliveryTarget, DecisionKind
from .contracts import RevisionToken
from .command_dispatch import CommandDispatch
from .context import load_revision, validate_saved_command
from typing import Any

from sciplot_core.plot_document import (
    apply_patch,
    seal_document,
    validate_document,
    validate_patch,
)
from sciplot_core.project_lifecycle.paths import canonical_path
from sciplot_core.project_lifecycle.context import external_project_session, project_query

from sciplot_core.plot_engine.backend import PlotBackend
from sciplot_core.plot_engine.cache_identity import build_key
from sciplot_core.plot_engine.content_store import intern_document, referenced_files, verify_document_content
from sciplot_core.plot_engine.current import changed_inputs, dependency_state, evidence_current, require_current
from sciplot_core.plot_engine.description_scope import require_selector
from sciplot_core.project_lifecycle.errors import EngineError
from sciplot_core.project_lifecycle.execution import advance, replay
from sciplot_core.plot_engine.object_operations import attach_object_operations
from sciplot_core.project_lifecycle.recovery import project_recovery, resume_transaction
from sciplot_core.project_lifecycle.recovery import pending_edit_error as _pending_edit_error
from sciplot_core.project_lifecycle.context import (
    active,
    commit,
    digest,
    load_head,
    persist,
    read,
    transaction_path,
)


class ProjectApplication(CommandDispatch):
    def __init__(self, backend: PlotBackend, repository: ProjectRepository, *,
                 targets: ProjectTargets, capabilities: dict[str, Any] | None = None) -> None:
        self.backend, self.repository = backend, repository
        self.targets, self.capabilities = targets, capabilities

    @usecase
    def resume(self, plot: Path, request: dict[str, Any]) -> dict[str, Any]:
        return resume_transaction(plot, request, self.backend, self._patch)

    def close(self) -> None:
        close = getattr(self.backend, "close", None)
        if close is not None:
            close()

    @usecase
    def open(self, target: Path, figure_id: str | None = None, *,
             description: dict[str, Any] | None = None) -> dict[str, Any]:
        return self._open(target, figure_id=figure_id, description=require_selector(description))

    @usecase
    def open_created(self, target: Path, *, series_ids: dict[str, str], recipe: dict[str, Any],
                     figure_id: str | None = None) -> dict[str, Any]:
        return self._open(target, figure_id=figure_id, adoption=(series_ids, recipe))

    def _open(self, target: Path, *, figure_id: str | None,
              description: dict[str, Any] | None = None,
              adoption: tuple[dict[str, str], dict[str, Any]] | None = None) -> dict[str, Any]:
        destination = self.targets.resolve_open(target, figure_id)
        if isinstance(destination, ManagedDeliveryTarget):
            head = load_head(destination.root)
            require_current(self.backend, head["binding"])
            result = self.describe(destination.root, description=description)
            result["delivery_continuation"] = {"mode": "original_local_managed", "item_id": destination.item_id,
                                               "independent_native_snapshot": destination.native_snapshot,
                                               "portable_managed_project": False}
            return result
        if isinstance(destination, StoredTarget):
            if adoption is not None:
                from sciplot_core.plot_engine.adoption import require_adoption

                require_adoption(load_head(destination.root)["binding"], *adoption)
            return self.describe(destination.root, description=description)
        root, project, selected_id = destination.root, destination.project, destination.figure_id
        self.repository.prepare_namespace(root)
        with external_project_session(root):
            if not self.repository.has_head(root):
                if self.repository.has_revision(root, 0):
                    snapshot = self.repository.load_revision(root, 0)
                    document, binding = validate_document(snapshot["document"]), snapshot["binding"]
                    if snapshot["transaction"] != "import" or document["revision"] != 0:
                        raise EngineError("document_state_invalid", "The interrupted import snapshot is invalid.")
                else:
                    document, binding = (self.backend.import_project(project, selected_id, plot_id=destination.plot_id)
                        if destination.plot_id is not None else self.backend.import_project(project, selected_id))
                    if "document" in binding:
                        from sciplot_core.plot_engine.external_mutation import capture_baseline

                        binding = capture_baseline(root, binding)
                    if adoption is not None:
                        from sciplot_core.plot_engine.adoption import adopt

                        document, binding = adopt(document, binding, series_ids=adoption[0], recipe=adoption[1])
                    document = intern_document(root, document)
                    binding["scientific_content_files"] = referenced_files(root, document)
                verify_document_content(root, document)
                if adoption is not None:
                    from sciplot_core.plot_engine.adoption import require_adoption

                    require_adoption(binding, *adoption)
                require_current(self.backend, binding)
                commit(root, document, binding, "import")
            elif adoption is not None:
                from sciplot_core.plot_engine.adoption import require_adoption

                require_adoption(load_head(root)["binding"], *adoption)
            return self._describe(root, description=description)

    @usecase
    def describe(self, plot: Path, *, description: dict[str, Any] | None = None) -> dict[str, Any]:
        description = require_selector(description)
        root = canonical_path(plot)
        with project_query(root):
            return self._describe(root, description=description)

    def _describe(self, root: Path, *, description: dict[str, Any] | None = None) -> dict[str, Any]:
        head = load_head(root)
        document, binding = head["document"], head["binding"]
        changed = changed_inputs(self.backend, binding)
        pending = active(root)
        result = {"kind": "sciplot_plot_description", "version": 1, "status": "stale" if changed else "current",
                "plot_type": document.get("plot_type", "LegacyPlot"),
                "revision_token": RevisionToken.of(document).to_payload(),
                "plot": str(root), "plot_id": document["plot_id"], "revision": document["revision"],
                "scientific_hash": document["scientific_hash"], "presentation_hash": document["presentation_hash"],
                "objects": document["presentation"]["objects"], "coverage": document["coverage"],
                "changed_inputs": changed, "dependencies": ({}
                    if description is not None and document.get("plot_type") == "ManagedPlot"
                    else dependency_state(document, binding, changed)),
                "pending": ({"idempotency_key": pending["request"]["idempotency_key"], "phase": pending["phase"]}
                            if pending and pending["phase"] not in {"complete", "rejected"} else None),
                "document": str(root / "revisions" / f'{document["revision"]:08d}.json')}
        project_recovery(result, root, pending)
        if document.get("plot_type") == "ManagedPlot":
            from sciplot_core.plot_engine.managed_description import describe_managed
            from sciplot_core.plot_engine.export_status import current_export

            result["export_current"] = current_export(root, head, eligible=not changed and result["pending"] is None, cached_export=self._cached_export)
            return attach_object_operations(describe_managed(root, head, result, self.backend, description=description), document)
        from sciplot_core.plot_engine.external_mutation import authority_status

        if description is not None and description["scope"] == "edit":
            raise EngineError("description_scope_unavailable", "Scoped edit contracts are available for ManagedPlot; use the full LegacyPlot description.",
                              action="plot.describe")
        result["authority"] = authority_status("LegacyPlot")
        if changed and not result["pending"]:
            from sciplot_core.project_lifecycle.reimport import offer

            next_step = offer(self.backend, head, changed)
            if next_step is not None:
                result["next_step"] = next_step
        return attach_object_operations(result, document)

    @usecase
    def patch(self, plot: Path, request: dict[str, Any]) -> dict[str, Any]:
        request = validate_patch(request)
        root = canonical_path(plot)
        from .context import scientific_source_scope

        with external_project_session(root), admitted(root, "patch", request), scientific_source_scope(root, request):
            return self._patch(root, request)

    @usecase
    def deliver(self, request: dict[str, Any]) -> dict[str, Any]:
        """Package exact managed revisions; each export retains its own transaction."""
        from sciplot_core.plot_engine.managed_delivery import deliver

        return deliver(self, request)

    @usecase
    def intent(self, plot: Path, request: dict[str, Any]) -> dict[str, Any]:
        """Resolve two explicit FigureSpec text edits into the existing patch owner."""
        from sciplot_core.plot_engine.typed_intent import compile_intent, validate_intent

        request = validate_intent(request)
        root = canonical_path(plot)
        if request["mode"] == "plan":
            with project_query(root):
                # No session lease, native inspection, journal reservation, preview,
                # or renderer call: a plan is a read of one current frozen revision.
                head = load_head(root)
                _, plan = compile_intent(head["document"], request)
                require_current(self.backend, head["binding"])
                pending = active(root)
                if pending and pending["phase"] not in {"complete", "rejected"}:
                    raise _pending_edit_error(root, pending, "Finish or reject the pending transaction first.")
                current = load_head(root)["document"]
                if (current["plot_id"], current["revision"], current["scientific_hash"],
                        current["presentation_hash"]) != (head["document"]["plot_id"], head["document"]["revision"],
                                                         head["document"]["scientific_hash"],
                                                         head["document"]["presentation_hash"]):
                    raise EngineError("document_revision_conflict", "The plot changed while planning this edit.",
                                      action="plot.describe", description={"scope": "summary"},
                                      current_revision=current["revision"])
                require_current(self.backend, head["binding"])
                pending = active(root)
                if pending and pending["phase"] not in {"complete", "rejected"}:
                    raise _pending_edit_error(root, pending, "An edit began while planning this request.")
                return {"plot": str(root), **plan}
        with external_project_session(root), admitted(root, "intent", request):
            saved = transaction_path(root, request["idempotency_key"])
            # Recompile a retry against the *original* snapshot. Resolving a
            # label against the new head would break replay after the first edit.
            document = read(saved)["before"] if exists(saved) else load_head(root)["document"]
            patch, _ = compile_intent(document, request)
            return self._patch(root, patch)

    def _patch(self, root: Path, request: dict[str, Any], *, rollback_request: dict[str, Any] | None = None) -> dict[str, Any]:
        saved = transaction_path(root, request["idempotency_key"])
        if exists(saved):
            from sciplot_core.project_lifecycle.publication_repair import prepare_saved

            transaction = read(saved)
            validate_saved_command(transaction)
            return replay(root, prepare_saved(root, transaction, request, self.backend), self.backend)
        head = load_head(root)
        binding = head["binding"]
        scientific_update = False
        if head["document"].get("plot_type") == "ManagedPlot":
            from sciplot_core.plot_engine.managed_state import scientific_binding
            from sciplot_core.plot_engine.current_unit_admission import prepare_current_update

            document, diff, risk, scientific_update = prepare_current_update(root, head["document"], request)
            if scientific_update and diff:
                binding = scientific_binding(binding, document)
        else:
            document, diff, risk = apply_patch(head["document"], request)
        require_current(self.backend, binding)
        from sciplot_core.project_lifecycle.publication_repair import authorize_pending, reserve_repair

        repair = authorize_pending(root, head, request, document, diff, risk, scientific_update, self.backend)
        if diff:
            document["revision"] += 1
            document = seal_document(document)
        tx = {"id": digest(request["idempotency_key"]), "request": request, "request_hash": digest(request),
              "before": head["document"], "document": document, "binding": binding,
              "diff": diff, "risk": "review" if repair else risk, "phase": "resolving" if scientific_update and diff else "planned"}
        if rollback_request is not None:
            tx["rollback_request"] = rollback_request
        reserve_repair(root, tx, repair, self.backend)
        if not diff:
            cached = self._cached_export(root, head)
            if cached:
                tx.update({"phase": "complete", "export": cached["export"], "artifact_files": cached["artifact_files"],
                           "evidence_inventories": cached.get("evidence_inventories", {}),
                           "artifact_build_key": cached["build_key"]})
                persist(root, tx)
        return advance(root, tx, self.backend)

    @usecase
    def decide(self, plot: Path, request: dict[str, Any]) -> dict[str, Any]:
        from sciplot_core.plot_engine.contracts import validate_decide

        request = validate_decide(request)
        destination = self.targets.resolve_decision(plot)
        root = destination.root
        if request.get("reimport") is True and destination.kind == DecisionKind.SEMANTIC:
            if load_head(root)["document"].get("plot_type") == "ManagedPlot":
                raise EngineError("managed_external_mutation", "Managed artifacts cannot be adopted through legacy reimport.",
                                  action="inspect_external_mutation")
            from sciplot_core.project_lifecycle.reimport import reimport_native

            with external_project_session(root):
                return reimport_native(root, request, self.backend)
        if destination.kind == DecisionKind.CREATION:
            from sciplot_core.project_lifecycle.creation import decide_creation

            return decide_creation(self, root, request)
        if set(request) != {"decision_id", "base_revision", "accept"} or type(request.get("accept")) is not bool:
            raise EngineError("document_invalid_decision", "Use decision_id, base_revision and boolean accept.")
        with external_project_session(root):
            tx = active(root)
            if tx is None or request["decision_id"] != tx["id"] or request["base_revision"] != tx["request"]["base_revision"]:
                raise EngineError("document_decision_conflict", "This decision does not identify the pending preview.")
            if "accepted" in tx:
                if tx["accepted"] != request["accept"]:
                    raise EngineError("document_decision_conflict", "This transaction already has a different decision.")
                return replay(root, tx, self.backend)
            can_discard = ((tx["phase"] == "planned" and tx.get("error", {}).get("stage") == "preview"
                            or tx["phase"] == "resolving" and tx.get("error", {}).get("stage") == "resolving")
                           and "native_result" not in tx and request["accept"] is False)
            if tx["phase"] != "needs_review" and not can_discard:
                raise EngineError("document_decision_conflict", "The transaction is not waiting for a visual decision.")
            if not can_discard and request["accept"]:
                require_current(self.backend, tx["binding"])
            tx.update({"accepted": request["accept"], "phase": "prepared" if request["accept"] else "rejected"})
            persist(root, tx)
            return advance(root, tx, self.backend)

    @usecase
    def rollback(self, plot: Path, request: dict[str, Any]) -> dict[str, Any]:
        from sciplot_core.plot_engine.contracts import validate_rollback

        request = validate_rollback(request)
        root = canonical_path(plot)
        with external_project_session(root), admitted(root, "rollback", request):
            # Freeze the inverse request, so retrying after commit does not compute a new inverse.
            if load_head(root)["document"].get("plot_type") == "ManagedPlot":
                from sciplot_core.project_lifecycle.managed_rollback import rollback_managed

                return rollback_managed(root, request, self.backend)
            saved = transaction_path(root, request["idempotency_key"])
            if exists(saved):
                tx = read(saved)
                if tx.get("rollback_request") != request:
                    raise EngineError("document_idempotency_conflict", "This key identifies another request.")
                return replay(root, tx, self.backend)
            head = load_head(root)["document"]
            target = load_revision(root, request["target_revision"])["document"]
            verify_document_content(root, target)
            if head["revision"] != request["base_revision"]:
                raise EngineError("document_revision_conflict", "Rollback requires the current revision.",
                                  current_revision=head["revision"])
            if head["scientific_hash"] != target["scientific_hash"]:
                raise EngineError("document_scientific_rollback_unsupported", "Scientific history needs its explicit executor.")
            current, previous = head["presentation"]["objects"], target["presentation"]["objects"]
            if set(current) != set(previous):
                raise EngineError("document_structural_rollback_unsupported", "Object membership differs between these revisions.")
            changes = [{"op": "set", "target": [name], "property": prop, "value": value}
                       for name, obj in previous.items() for prop, value in obj["properties"].items()
                       if current[name]["properties"].get(prop) != value]
            if not changes:
                changes = [{"op": "set", "target": [name], "property": prop, "value": value}
                           for name, obj in current.items() for prop, value in obj["properties"].items()][:1]
                if not changes:
                    raise EngineError("document_no_editable_objects", "This document has no represented property to roll back.")
            patch = {"plot_id": head["plot_id"], "base_revision": request["base_revision"],
                     "idempotency_key": request["idempotency_key"], "intent_class": "review", "changes": changes}
            return self._patch(root, patch, rollback_request=request)

    def _cached_export(self, root: Path, head: dict[str, Any]) -> dict[str, Any] | None:
        path = root / "export-cache.json"
        if not exists(path):
            return None
        cache = read(path)
        document = head["document"]
        key = build_key(document, head["binding"])
        return cache if (cache["build_key"] == key and evidence_current(
            cache["artifact_files"], cache.get("evidence_inventories"))) else None

    @usecase
    def export(self, plot: Path) -> dict[str, Any]:
        root = canonical_path(plot)
        with external_project_session(root):
            tx = active(root)
            if tx and tx["phase"] not in {"complete", "rejected"}:
                if tx["phase"] in {"committed", "exporting", "export_pending"}:
                    return replay(root, tx, self.backend)
                raise EngineError("document_transaction_pending", "The current change must finish before export.",
                                  action="retry_same_request")
            head = load_head(root)
            require_current(self.backend, head["binding"])
            if tx and tx["phase"] == "complete" and tx["document"]["revision"] == head["document"]["revision"]:
                return replay(root, tx, self.backend)
            from sciplot_core.project_lifecycle.exports import export_head

            return export_head(root, head, self.backend)

    @usecase
    def render(self, plot: Path) -> dict[str, Any]:
        from sciplot_core.project_lifecycle.exports import render_head

        root = canonical_path(plot)
        with external_project_session(root):
            head = load_head(root)
            require_current(self.backend, head["binding"])
            return render_head(root, head, self.backend)

    @usecase
    def create(self, request: dict[str, Any]) -> dict[str, Any]:
        from sciplot_core.plot_engine.contracts import validate_create
        from sciplot_core.project_lifecycle.creation import create

        request = validate_create(request)
        if "template_definition" in request and request.get("mode") != "legacy":
            from sciplot_core.project_lifecycle.managed_creation import create_managed

            return create_managed(request, self.backend, location=self.targets.managed_creation(request))

        return create(self, request, targets=self.targets)
