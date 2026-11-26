"""Plan or resume exactly one admitted patch through the original transaction engine."""

from pathlib import Path
from typing import Any

from sciplot_core.plot_document import apply_patch, seal_document
from sciplot_core.plot_document.requests import RequestInput, admit_patch
from sciplot_core.plot_engine.backend import PlotBackend
from sciplot_core.plot_engine.current import require_current
from sciplot_core.plot_engine.export_status import cached_export

from .context import digest, exists, load_head, persist, read, transaction_path, validate_saved_command
from .contracts import RevisionToken
from .errors import EngineError
from .execution import advance, replay


def execute_patch(root: Path, request: RequestInput, backend: PlotBackend,
                  *, rollback_request: dict[str, Any] | None = None,
                  comparison: dict[str, Any] | None = None, defer_export: bool = False) -> dict[str, Any]:
    patch = admit_patch(request)
    request = patch.to_payload()
    saved = transaction_path(root, request["idempotency_key"])
    if exists(saved):
        from sciplot_core.project_lifecycle.publication_repair import prepare_saved

        transaction = read(saved)
        validate_saved_command(transaction)
        if comparison is not None and transaction.get("comparison_selection") != comparison:
            raise EngineError("comparison_selection_changed", "The saved patch belongs to another reviewed candidate.")
        return replay(root, prepare_saved(root, transaction, request, backend), backend)
    head = load_head(root)
    binding = head["binding"]
    scientific_update = False
    if head["document"].get("plot_type") == "ManagedPlot":
        from sciplot_core.plot_engine.managed_state import scientific_binding
        from sciplot_core.plot_engine.current_unit_admission import prepare_current_update

        document, diff, risk, scientific_update = prepare_current_update(root, head["document"], patch)
        if scientific_update and diff:
            binding = scientific_binding(binding, document)
    else:
        document, diff, risk = apply_patch(head["document"], patch)
    require_current(backend, binding, input_document=document)
    from sciplot_core.project_lifecycle.publication_repair import authorize_pending, reserve_repair

    repair = authorize_pending(root, head, request, document, diff, risk, scientific_update, backend)
    if diff:
        document["revision"] += 1
        document = seal_document(document)
    tx = {"id": digest(request["idempotency_key"]), "request": request, "request_hash": patch.digest,
          "before": head["document"], "document": document, "binding": binding,
          "diff": diff, "risk": "review" if repair else risk, "phase": "resolving" if scientific_update and diff else "planned"}
    if rollback_request is not None:
        tx["rollback_request"] = rollback_request
    if comparison is not None:
        if (scientific_update or repair or document["plot_type"] != "ManagedPlot"
                or RevisionToken.of(head["document"]).to_payload() != comparison["baseline"]
                or document["scientific_hash"] != comparison["baseline"]["scientific_hash"]
                or document["presentation_hash"] != comparison["presentation_hash"]
                or bool(diff) != comparison["changed"]):
            raise EngineError("comparison_selection_changed", "The current patch does not reproduce the selected presentation.")
        tx["comparison_selection"] = comparison
    if defer_export or comparison is not None and not comparison["export"]:
        tx["export_deferred"] = True
    reserve_repair(root, tx, repair, backend)
    if not diff and not tx.get("export_deferred"):
        cached = cached_export(root, head)
        if cached:
            tx.update({"phase": "complete", "export": cached["export"], "artifact_files": cached["artifact_files"],
                       "evidence_inventories": cached.get("evidence_inventories", {}),
                       "artifact_build_key": cached["build_key"]})
            persist(root, tx)
    return advance(root, tx, backend)
