"""One semantic entry for clients; local owners retain rendering and scientific work."""

from pathlib import Path
from typing import Any

from sciplot_core.plot_document import apply_patch, seal_document, validate_document, validate_patch
from sciplot_core.studio_core.project_query import resolve_project_figure
from sciplot_core.studio_core.project_query_paths import canonical_path
from sciplot_core.studio_core.project_session import external_project_session

from .backend import PlotBackend
from .cache_identity import build_key
from .content_store import intern_document, referenced_files, verify_document_content
from .current import changed_inputs, dependency_state, evidence_current, require_current
from .errors import EngineError
from .execution import advance, replay
from .storage import active, commit, digest, document_root, load_head, persist, read, reserve, transaction_path


class PlotService:
    def __init__(self, backend: PlotBackend | None = None) -> None:
        if backend is None:
            from sciplot_core.plot_backends.veusz import VeuszBackend
            from .backend_router import BackendRouter

            backend = BackendRouter(VeuszBackend())
        self.backend = backend

    def close(self) -> None:
        close = getattr(self.backend, "close", None)
        if close is not None:
            close()

    def open(self, target: Path, figure_id: str | None = None) -> dict[str, Any]:
        return self._open(target, figure_id=figure_id)

    def open_created(self, target: Path, *, series_ids: dict[str, str], recipe: dict[str, Any],
                     figure_id: str | None = None) -> dict[str, Any]:
        return self._open(target, figure_id=figure_id, adoption=(series_ids, recipe))

    def _open(self, target: Path, *, figure_id: str | None,
              adoption: tuple[dict[str, str], dict[str, Any]] | None = None) -> dict[str, Any]:
        target = canonical_path(target)
        if (target / "head.json").is_file():
            if adoption is not None:
                from .adoption import require_adoption

                require_adoption(load_head(target)["binding"], *adoption)
            return self.describe(target)
        selection = resolve_project_figure(target, figure_id)
        project = Path(selection["project"])
        selected_id = selection["figure_id"]
        root = document_root(project, selected_id)
        canonical_path(root)
        root.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        with external_project_session(root):
            if not (root / "head.json").exists():
                first = root / "revisions" / "00000000.json"
                if first.exists():
                    snapshot = read(first)
                    document, binding = validate_document(snapshot["document"]), snapshot["binding"]
                    if snapshot["transaction"] != "import" or document["revision"] != 0:
                        raise EngineError("document_state_invalid", "The interrupted import snapshot is invalid.")
                else:
                    document, binding = self.backend.import_project(project, selected_id)
                    if "document" in binding:
                        from .external_mutation import capture_baseline

                        binding = capture_baseline(root, binding)
                    if adoption is not None:
                        from .adoption import adopt

                        document, binding = adopt(document, binding, series_ids=adoption[0], recipe=adoption[1])
                    document = intern_document(root, document)
                    binding["scientific_content_files"] = referenced_files(root, document)
                verify_document_content(root, document)
                if adoption is not None:
                    from .adoption import require_adoption

                    require_adoption(binding, *adoption)
                require_current(self.backend, binding)
                commit(root, document, binding, "import")
            elif adoption is not None:
                from .adoption import require_adoption

                require_adoption(load_head(root)["binding"], *adoption)
            return self._describe(root)

    def describe(self, plot: Path) -> dict[str, Any]:
        root = canonical_path(plot)
        with external_project_session(root):
            return self._describe(root)

    def _describe(self, root: Path) -> dict[str, Any]:
        head = load_head(root)
        document, binding = head["document"], head["binding"]
        changed = changed_inputs(self.backend, binding)
        pending = active(root)
        result = {"kind": "sciplot_plot_description", "version": 1, "status": "stale" if changed else "current",
                "plot_type": document.get("plot_type", "LegacyPlot"),
                "plot": str(root), "plot_id": document["plot_id"], "revision": document["revision"],
                "scientific_hash": document["scientific_hash"], "presentation_hash": document["presentation_hash"],
                "objects": document["presentation"]["objects"], "coverage": document["coverage"],
                "changed_inputs": changed, "dependencies": dependency_state(document, binding, changed),
                "pending": ({"idempotency_key": pending["request"]["idempotency_key"], "phase": pending["phase"]}
                            if pending and pending["phase"] not in {"complete", "rejected"} else None),
                "document": str(root / "revisions" / f'{document["revision"]:08d}.json')}
        if document.get("plot_type") == "ManagedPlot":
            from .managed_description import describe_managed

            return describe_managed(root, head, result, self.backend)
        from .external_mutation import authority_status

        result["authority"] = authority_status("LegacyPlot")
        if changed and not result["pending"]:
            from .reimport import offer

            next_step = offer(self.backend, head, changed)
            if next_step is not None:
                result["next_step"] = next_step
        return result

    def patch(self, plot: Path, request: dict[str, Any]) -> dict[str, Any]:
        request = validate_patch(request)
        root = canonical_path(plot)
        with external_project_session(root):
            return self._patch(root, request)

    def _patch(self, root: Path, request: dict[str, Any], *, rollback_request: dict[str, Any] | None = None) -> dict[str, Any]:
        saved = transaction_path(root, request["idempotency_key"])
        if saved.exists():
            transaction = read(saved)
            if transaction["request_hash"] != digest(request):
                raise EngineError("document_idempotency_conflict", "This key already belongs to a different request.",
                                  action="use_original_request")
            if transaction["phase"] not in {"complete", "rejected"}:
                pending = active(root)
                if pending and pending["id"] != transaction["id"] and pending["phase"] not in {"complete", "rejected"}:
                    raise EngineError("document_transaction_pending", "A different transaction is pending.")
                head = load_head(root)
                if (head["document"]["revision"] != request["base_revision"]
                        and head["transaction"] != transaction["id"]):
                    raise EngineError("document_revision_conflict", "The interrupted transaction no longer starts at the current revision.")
                reserve(root, transaction)
            return replay(root, transaction, self.backend)
        head = load_head(root)
        binding = head["binding"]
        scientific_update = False
        if head["document"].get("plot_type") == "ManagedPlot":
            from .managed_updates import prepare_update
            from .managed_state import scientific_binding

            document, diff, risk, scientific_update = prepare_update(head["document"], request)
            if scientific_update:
                binding = scientific_binding(binding, document)
        else:
            document, diff, risk = apply_patch(head["document"], request)
        require_current(self.backend, binding)
        pending = active(root)
        if pending and pending["phase"] not in {"complete", "rejected"}:
            raise EngineError("document_transaction_pending", "Finish or reject the pending transaction first.",
                              action="retry_same_request", idempotency_key=pending["request"]["idempotency_key"],
                              phase=pending["phase"])
        if diff:
            document["revision"] += 1
            document = seal_document(document)
        tx = {"id": digest(request["idempotency_key"]), "request": request, "request_hash": digest(request),
              "before": head["document"], "document": document, "binding": binding,
              "diff": diff, "risk": risk, "phase": "resolving" if scientific_update and diff else "planned"}
        if rollback_request is not None:
            tx["rollback_request"] = rollback_request
        reserve(root, tx)
        if not diff:
            cached = self._cached_export(root, head)
            if cached:
                tx.update({"phase": "complete", "export": cached["export"], "artifact_files": cached["artifact_files"],
                           "evidence_inventories": cached.get("evidence_inventories", {}),
                           "artifact_build_key": cached["build_key"]})
                persist(root, tx)
        return advance(root, tx, self.backend)

    def decide(self, plot: Path, request: dict[str, Any]) -> dict[str, Any]:
        from .contracts import validate_decide

        request = validate_decide(request)
        root = canonical_path(plot)
        if request.get("reimport") is True and (root / "head.json").is_file():
            if load_head(root)["document"].get("plot_type") == "ManagedPlot":
                raise EngineError("managed_external_mutation", "Managed artifacts cannot be adopted through legacy reimport.",
                                  action="inspect_external_mutation")
            from .reimport import reimport_native

            with external_project_session(root):
                return reimport_native(root, request, self.backend)
        if (root / "creation.json").exists():
            from .creation import decide_creation

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

    def rollback(self, plot: Path, request: dict[str, Any]) -> dict[str, Any]:
        from .contracts import validate_rollback

        request = validate_rollback(request)
        root = canonical_path(plot)
        if set(request) != {"base_revision", "target_revision", "idempotency_key"} or any(
            type(request.get(key)) is not int or request[key] < 0 for key in ("base_revision", "target_revision")
        ):
            raise EngineError("document_invalid_rollback", "Use base_revision, target_revision and idempotency_key.")
        with external_project_session(root):
            # Freeze the inverse request, so retrying after commit does not compute a new inverse.
            if load_head(root)["document"].get("plot_type") == "ManagedPlot":
                from .managed_rollback import rollback_managed

                return rollback_managed(root, request, self.backend)
            saved = transaction_path(root, request["idempotency_key"])
            if saved.exists():
                tx = read(saved)
                if tx.get("rollback_request") != request:
                    raise EngineError("document_idempotency_conflict", "This key identifies another request.")
                return replay(root, tx, self.backend)
            head = load_head(root)["document"]
            target = validate_document(read(root / "revisions" / f'{request["target_revision"]:08d}.json')["document"])
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
        if not path.exists():
            return None
        cache = read(path)
        document = head["document"]
        key = build_key(document, head["binding"])
        return cache if (cache["build_key"] == key and evidence_current(
            cache["artifact_files"], cache.get("evidence_inventories"))) else None

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
            from .exports import export_head

            return export_head(root, head, self.backend)

    def render(self, plot: Path) -> dict[str, Any]:
        from .exports import render_head

        root = canonical_path(plot)
        with external_project_session(root):
            head = load_head(root)
            require_current(self.backend, head["binding"])
            return render_head(root, head, self.backend)

    def create(self, request: dict[str, Any]) -> dict[str, Any]:
        from .creation import create
        from .contracts import validate_create

        request = validate_create(request)
        if "template_definition" in request and request.get("mode") != "legacy":
            from .managed_creation import create_managed

            return create_managed(request, self.backend)

        return create(self, request)
