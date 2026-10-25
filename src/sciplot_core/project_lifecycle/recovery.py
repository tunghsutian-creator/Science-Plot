"""Compact access to the existing semantic journal; no independent retry state."""

from collections.abc import Callable
from pathlib import Path
from .context import exists
from typing import Any

from sciplot_core.project_lifecycle.paths import canonical_path
from sciplot_core.project_lifecycle.context import external_project_session

from sciplot_core.plot_engine.backend import PlotBackend
from sciplot_core.plot_engine.contracts import validate_resume
from sciplot_core.plot_engine.current import require_current
from sciplot_core.project_lifecycle.errors import EngineError
from sciplot_core.project_lifecycle.receipts import receipt
from sciplot_core.project_lifecycle.context import command_scope, digest, load_head, read, transaction_path
from .contracts import NormalizedCommand, RevisionToken, AuthorityMode


def pending_edit_error(root: Path, pending: dict[str, Any], message: str) -> EngineError:
    """Point a competing edit at a read, never replay another request."""
    return EngineError(
        "document_transaction_pending", message,
        action="plot.describe", plot=str(root), description={"scope": "summary"},
        pending={"idempotency_key": pending["request"]["idempotency_key"], "phase": pending["phase"]},
    )


def project_recovery(result: dict[str, Any], root: Path, transaction: dict[str, Any] | None) -> None:
    """Read a frozen receipt without rendering, applying, or accepting a preview."""
    if transaction is None:
        return
    from sciplot_core.project_lifecycle.publication_repair import superseded_receipt

    saved = superseded_receipt(root, transaction) if transaction.get("superseded_by") else receipt(root, transaction)
    request = transaction["request"]
    resume = {"action": "plot.resume", "plot": str(root), "request": {
        "plot_id": transaction["document"]["plot_id"], "base_revision": request["base_revision"],
        "idempotency_key": request["idempotency_key"]}}
    phase = transaction["phase"]
    step = {**saved["next_step"], "plot": str(root)}
    if phase in {"committed", "exporting", "export_pending"} and not transaction.get("error"):
        step = {"action": "plot.export", "plot": str(root)}
    elif step["action"] == "retry_same_request" or phase == "complete":
        step = resume
    recovery: dict[str, Any] = {"idempotency_key": request["idempotency_key"], "base_revision": request["base_revision"],
                "transaction_revision": transaction["document"]["revision"], "current_revision": result["revision"],
                "phase": phase, "commit_status": saved["commit_status"], "export_status": saved["export_status"],
                "evidence": saved["evidence"], "next_step": step,
                **{key: saved[key] for key in ("preview", "scientific_audit", "decision_id", "error") if key in saved}}
    if result["status"] != "current":
        recovery["continuation_blocked"] = True
        recovery["next_step"] = {"action": "resolve_changed_inputs", "plot": str(root),
                                 "changed_inputs": result["changed_inputs"]}
        if (result["status"] == "stale" and phase == "applying"
                and transaction["document"].get("plot_type", "LegacyPlot") == "LegacyPlot"
                and "changes" in request and transaction.get("mode") != "reimport"):
            recovery["guarded_resume"] = {**resume, "automatic_retry": False, "owner_validation_required": True,
                "message": "Optional original-key recovery: the native apply owner must verify its saved receipt and source/native/revision guards, and may refuse. This summary remains stale."}
    else:
        recovery["resume"] = resume
    result["recovery"] = recovery
    if result["pending"] is not None and result["status"] == "current":
        result["next_step"] = step


def resume_transaction(plot: Path, request: dict[str, Any], backend: PlotBackend,
                       patch: Callable[..., dict[str, Any]]) -> dict[str, Any]:
    """Explicitly replay exactly one saved request under its original guards."""
    request = validate_resume(request)
    root = canonical_path(plot)
    with external_project_session(root):
        head = load_head(root)
        if head["document"]["plot_id"] != request["plot_id"]:
            raise EngineError("document_identity_conflict", "The recovery belongs to a different plot.", action="plot.describe")
        path = transaction_path(root, request["idempotency_key"])
        if not exists(path):
            raise EngineError("document_transaction_unknown", "This key has no saved semantic transaction; no mutation was sent.",
                              action="use_original_request")
        transaction = read(path)
        original = transaction["request"]
        if (original.get("idempotency_key") != request["idempotency_key"]
                or transaction.get("id") != digest(request["idempotency_key"])
                or transaction.get("request_hash") != digest(original)):
            raise EngineError("document_state_invalid", "The saved transaction identity does not match this key; preserve its evidence.")
        if (original["base_revision"] != request["base_revision"]
                or transaction["document"]["plot_id"] != request["plot_id"]):
            raise EngineError("document_revision_conflict", "Use the original plot and base revision for this key.", action="plot.describe")
        if transaction.get("superseded_by"):
            from sciplot_core.project_lifecycle.publication_repair import superseded_receipt

            return superseded_receipt(root, transaction)
        if "changes" not in original or transaction.get("mode") == "reimport":
            raise EngineError("document_resume_unsupported", "Continue this lifecycle through its original decision entry.",
                              action="plot.decide")
        if transaction["phase"] == "needs_review":
            require_current(backend, transaction["binding"])
        # Existing _patch/replay owns revision conflicts, native apply recovery,
        # source guards, historical results, and export-only continuation.
        normalized = transaction.get("normalized_command")
        if normalized is None:
            return patch(root, original)
        expected = normalized["expected_revision"]
        token = RevisionToken(**{**expected, "authority": AuthorityMode(expected["authority"])}) if expected else None
        command = NormalizedCommand.create(normalized["kind"], normalized["original_request"],
                                           expected_revision=token, authority=AuthorityMode(normalized["authority"]),
                                           business_request=normalized["business_request"])
        with command_scope(command):
            return patch(root, original)
