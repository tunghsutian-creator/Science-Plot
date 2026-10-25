"""Finite supersession of an unchanged Managed export rejected by publication QA."""

from pathlib import Path
from typing import Any

from sciplot_core.foundation.file_hashing import file_sha256

from sciplot_core.plot_engine.backend import PlotBackend
from sciplot_core.plot_engine.current import require_current
from sciplot_core.project_lifecycle.errors import EngineError
from sciplot_core.project_lifecycle.receipts import receipt
from sciplot_core.project_lifecycle.context import active, digest, load_head, persist, read, reserve, transaction_path


def _pending_error(root: Path, pending: dict[str, Any]) -> EngineError:
    return EngineError("document_transaction_pending", "Finish or reject the pending transaction first.",
        action="plot.describe", plot=str(root), description={"scope": "summary"},
        pending={"idempotency_key": pending["request"]["idempotency_key"], "phase": pending["phase"]})


def _eligible(head: dict[str, Any], pending: dict[str, Any]) -> bool:
    error = pending.get("error", {})
    return (head["document"].get("plot_type") == "ManagedPlot"
            and head["binding"].get("kind") == "sciplot_managed_binding"
            and pending["phase"] == "export_pending" and not pending["diff"]
            and pending.get("mode") in {None, "export"} and pending["risk"] == "presentation"
            and pending["request"].get("action") == "export"
            and pending["before"] == pending["document"] == head["document"] and pending["binding"] == head["binding"]
            and pending["request"]["base_revision"] == head["document"]["revision"]
            and error.get("stage") == "export" and error.get("reason_code") == "publication_qa_failed"
            and error.get("action") == "correct_layout")


def _require_current(backend: PlotBackend, binding: dict[str, Any]) -> None:
    require_current(backend, binding)
    native = Path(binding["document"])
    if native.exists():
        marker = native.parent / "build.json"
        record = read(marker) if marker.is_file() else {}
        if record.get("ir_hash") != binding["ir_hash"] or record.get("document_sha256") != file_sha256(native):
            raise EngineError("managed_external_mutation", "The failed publication has an unsealed native artifact; inspect it before repairing layout.",
                              action="inspect_external_mutation")


def authorize_pending(root: Path, head: dict[str, Any], request: dict[str, Any], document: dict[str, Any],
                      diff: list[dict[str, Any]], risk: str, scientific_update: bool,
                      backend: PlotBackend) -> dict[str, Any] | None:
    """A new nonempty presentation request may replace only this exact failure."""
    pending = active(root)
    if pending is None or pending["phase"] in {"complete", "rejected"}:
        return None
    if (not _eligible(head, pending) or pending.get("superseded_by") or scientific_update
            or request["intent_class"] != "presentation" or not diff or risk != "presentation"
            or document["scientific"] != head["document"]["scientific"]
            or document["scientific_hash"] != head["document"]["scientific_hash"]
            or any(item.get("risk") != "presentation" for item in diff)):
        raise _pending_error(root, pending)
    _require_current(backend, head["binding"])
    return pending


def _reference(transaction: dict[str, Any]) -> dict[str, Any]:
    return {"id": transaction["id"], "idempotency_key": transaction["request"]["idempotency_key"],
            "base_revision": transaction["request"]["base_revision"]}


def reserve_repair(root: Path, transaction: dict[str, Any], previous: dict[str, Any] | None,
                   backend: PlotBackend) -> None:
    if previous is not None:
        head = load_head(root)
        if not _eligible(head, previous):
            raise _pending_error(root, previous)
        _require_current(backend, head["binding"])
        target = _reference(transaction)
        if previous.get("superseded_by") not in (None, target):
            raise _pending_error(root, previous)
        transaction["supersedes"] = _reference(previous)
        # Seal the replacement before linking it. Either interruption window is
        # recoverable by this exact request, never by executing the failed one.
        persist(root, transaction)
        previous["superseded_by"] = target
        persist(root, previous)
    reserve(root, transaction)


def prepare_saved(root: Path, transaction: dict[str, Any], request: dict[str, Any],
                  backend: PlotBackend) -> dict[str, Any]:
    """Retain ordinary replay guards and recover the finite reservation windows."""
    if transaction["request_hash"] != digest(request):
        raise EngineError("document_idempotency_conflict", "This key already belongs to a different request.",
                          action="use_original_request")
    if transaction.get("superseded_by"):
        _successor(root, transaction)
        return transaction
    if transaction["phase"] not in {"complete", "rejected"}:
        pending = active(root)
        head = load_head(root)
        if pending and pending["id"] != transaction["id"] and pending["phase"] not in {"complete", "rejected"}:
            if (transaction.get("supersedes") != _reference(pending) or not _eligible(head, pending)
                    or transaction["phase"] != "planned" or transaction["before"] != head["document"]
                    or transaction["risk"] != "review" or transaction["binding"] != head["binding"]
                    or transaction["id"] != digest(request["idempotency_key"])
                    or transaction["document"]["revision"] != head["document"]["revision"] + 1
                    or transaction["request"]["intent_class"] != "presentation" or not transaction["diff"]
                    or transaction["document"]["scientific"] != head["document"]["scientific"]
                    or transaction["document"]["scientific_hash"] != head["document"]["scientific_hash"]
                    or any(item.get("risk") != "presentation" for item in transaction["diff"])):
                raise _pending_error(root, pending)
            reserve_repair(root, transaction, pending, backend)
            return transaction
        if head["document"]["revision"] != request["base_revision"] and head["transaction"] != transaction["id"]:
            raise EngineError("document_revision_conflict", "The interrupted transaction no longer starts at the current revision.")
        reserve(root, transaction)
    return transaction


def _successor(root: Path, transaction: dict[str, Any]) -> dict[str, Any]:
    ref = transaction["superseded_by"]
    successor = read(transaction_path(root, ref["idempotency_key"]))
    if (ref != _reference(successor) or successor.get("supersedes") != _reference(transaction)
            or successor["id"] != digest(successor["request"]["idempotency_key"])
            or successor["request_hash"] != digest(successor["request"])):
        raise EngineError("document_state_invalid", "The publication repair references do not match their saved requests.")
    return successor


def superseded_receipt(root: Path, transaction: dict[str, Any]) -> dict[str, Any]:
    """Read history without reserving, rebuilding, applying or delivering it."""
    successor = _successor(root, transaction)
    request = successor["request"]
    result = receipt(root, transaction, replay=True)
    result.update({"status": "superseded", "historical": True, "ready_to_use": False, "exports": [],
        "current_revision": load_head(root)["document"]["revision"], "superseded_by": transaction["superseded_by"],
        "next_step": {"action": "plot.resume", "plot": str(root), "request": {
            "plot_id": successor["document"]["plot_id"], "base_revision": request["base_revision"],
            "idempotency_key": request["idempotency_key"]}}})
    return result
