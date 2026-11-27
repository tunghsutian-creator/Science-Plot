"""Application owner of the complete Managed and Legacy semantic aggregate lifecycle."""

from contextlib import AbstractContextManager
from pathlib import Path

from .admission import usecase, admitted
from .ports import ProjectRepository, ProjectTargets
from .targets import StoredTarget, ManagedDeliveryTarget, DecisionKind
from .command_dispatch import CommandDispatch
from .managed_application import ManagedPlotApplication
from typing import Any

from sciplot_core.plot_document import (
    validate_document,
)
from sciplot_core.plot_document.requests import RequestInput, admit_patch
from sciplot_core.project_lifecycle.paths import canonical_path
from sciplot_core.project_lifecycle.context import external_project_session, project_query

from sciplot_core.plot_engine.backend import PlotBackend
from sciplot_core.plot_engine.content_store import intern_document, referenced_files, verify_document_content
from sciplot_core.plot_engine.current import require_current
from sciplot_core.plot_engine.description_scope import require_selector
from sciplot_core.project_lifecycle.errors import EngineError
from sciplot_core.project_lifecycle.execution import advance, replay
from sciplot_core.project_lifecycle.legacy_rollback import rollback_legacy
from sciplot_core.project_lifecycle.managed_rollback import rollback_managed
from sciplot_core.project_lifecycle.recovery import resume_transaction
from sciplot_core.project_lifecycle.recovery import pending_edit_error as _pending_edit_error
from sciplot_core.project_lifecycle.context import (
    active,
    commit,
    load_head,
    persist,
)


class ProjectApplication(ManagedPlotApplication, CommandDispatch):
    def __init__(self, backend: PlotBackend, repository: ProjectRepository, *,
                 targets: ProjectTargets, capabilities: dict[str, Any] | None = None) -> None:
        super().__init__(backend, repository, managed_target=targets.managed_creation, capabilities=capabilities)
        self.targets = targets

    @usecase
    def resume(self, plot: Path, request: dict[str, Any]) -> dict[str, Any]:
        return resume_transaction(plot, request, self.backend, self._patch)

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
            with self.repository.query_scope(destination.root):
                head = load_head(destination.root)
                require_current(self.backend, head["binding"])
                result = self.describe(destination.root, description=description)
            if result["revision_token"] != destination.revision.to_payload():
                raise EngineError("managed_delivery_original_changed", "The exact original advanced during delivery selection; open it explicitly to review the new revision.",
                                  action="plot.describe", plot=str(destination.root))
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
    def patch(self, plot: Path, request: RequestInput) -> dict[str, Any]:
        request = admit_patch(request)
        root = canonical_path(plot)
        from .context import scientific_source_scope

        with external_project_session(root), admitted(root, "patch", request), scientific_source_scope(root, request.to_payload()):
            return self._patch(root, request)

    @usecase
    def intent(self, plot: Path, request: dict[str, Any]) -> dict[str, Any]:
        """Resolve an explicit FigureSpec edit into the existing patch owner."""
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
        return self._apply_intent(root, request)

    @usecase
    def _apply_intent(self, root: Path, request: dict[str, Any], *, defer_export: bool = False) -> dict[str, Any]:
        with external_project_session(root), admitted(root, "intent", request) as command:
            patch = admit_patch(command.business_request)
            from sciplot_core.plot_engine.typed_intent import DISPLAY_LABEL

            explicit_alias = request["property"] == DISPLAY_LABEL
            if defer_export or explicit_alias:
                from .patch_execution import execute_patch

                return execute_patch(root, patch, self.backend, defer_export=defer_export,
                                     **({"explicit_alias": True} if explicit_alias else {}))
            return self._patch(root, patch)

    def _patch(self, root: Path, request: RequestInput, *, rollback_request: dict[str, Any] | None = None) -> dict[str, Any]:
        from .patch_execution import execute_patch

        return execute_patch(root, request, self.backend, rollback_request=rollback_request)

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

            with self._managed_task_scope():
                return decide_creation(self, root, request, template_owner=self._template_creation_owner)
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
                require_current(self.backend, tx["binding"], input_document=tx["document"])
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
                return rollback_managed(root, request, self.backend)
            return rollback_legacy(root, request, self.backend, self._patch)

    @usecase
    def export(self, plot: Path, *, handoff: dict[str, Any] | None = None) -> dict[str, Any]:
        if handoff is not None:
            return self.handoff_figure(plot, handoff)
        root = canonical_path(plot)
        with external_project_session(root):
            return self._export(root)

    @usecase
    def export_created(self, plot: Path, *, plot_id: str, revision: int, series_ids: dict[str, str],
                       recipe: dict[str, Any]) -> dict[str, Any]:
        from sciplot_core.plot_engine.adoption import require_adoption

        root = canonical_path(plot)
        with external_project_session(root):
            head = load_head(root)
            document = head["document"]
            if (document["plot_id"], document["revision"]) != (plot_id, revision):
                raise EngineError("document_template_adoption_conflict",
                                  "The saved template creation no longer owns this plot revision.",
                                  action="use_original_creation_request")
            require_adoption(head["binding"], series_ids, recipe)
            return self._export(root, head=head)

    def _export(self, root: Path, *, head: dict[str, Any] | None = None) -> dict[str, Any]:
        tx = active(root)
        if tx and tx["phase"] not in {"complete", "rejected"}:
            if tx["phase"] in {"committed", "exporting", "export_pending"}:
                return replay(root, tx, self.backend)
            raise EngineError("document_transaction_pending", "The current change must finish before export.",
                              action="retry_same_request")
        if head is None:
            head = load_head(root)
        require_current(self.backend, head["binding"])
        if (tx and tx["phase"] == "complete" and not tx.get("export_deferred")
                and tx["document"]["revision"] == head["document"]["revision"]):
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
            return self._create_managed(request)

        with self._managed_task_scope():
            owner = self._template_creation_owner() if "template_definition" in request else self
            return create(owner, request, targets=self.targets,
                          allow_new_legacy_template=self._allow_new_legacy_template())

    def _allow_new_legacy_template(self) -> bool:
        return True

    def append_project_file_xy(self, path: Path, request: dict[str, Any], *, expected_generation: str) -> dict[str, Any]:
        """Append one resolved ordinary XY figure to an existing .sciplot file."""
        from .project_file_append import project_file_append_xy

        return project_file_append_xy(path, request, expected_generation=expected_generation, capabilities=self.capabilities)

    def _template_creation_owner(self) -> "ProjectApplication":
        return self

    def _managed_task_scope(self) -> AbstractContextManager[None]:
        from sciplot_core.task_semantic_owner import local_managed_actions

        return local_managed_actions(
            self.create, lambda plot: self.describe(plot, description={"scope": "summary"}),
            self.deliver, lambda request, paper_dir: self.inspect_delivery(request, paper_dir=paper_dir),
            handoff=self.handoff_figure,
        )
