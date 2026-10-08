"""Restore the complete managed presentation through the shared transaction owner."""

from copy import deepcopy
from pathlib import Path
from typing import Any

from sciplot_core.plot_document import seal_document, validate_document

from .backend import PlotBackend
from .content_store import verify_document_content
from .current import require_current
from .errors import EngineError
from .execution import advance, replay
from .managed_state import is_managed, require_inputs, resolved_ir
from .storage import active, digest, load_head, read, reserve, transaction_path


def presentation_diff(before: dict[str, Any], after: dict[str, Any]) -> list[dict[str, Any]]:
    differences: list[dict[str, Any]] = []
    old, new = before["objects"], after["objects"]
    for target in sorted(set(old) | set(new)):
        if target not in old or target not in new:
            differences.append({"target": target, "property": "object", "before": old.get(target), "after": new.get(target)})
            continue
        for prop in sorted(set(old[target]["properties"]) | set(new[target]["properties"])):
            previous, current = old[target]["properties"].get(prop), new[target]["properties"].get(prop)
            if prop not in old[target]["properties"] or prop not in new[target]["properties"] or digest(previous) != digest(current):
                differences.append({"target": target, "property": prop, "before": previous, "after": current})
        for prop in sorted((set(old[target]) | set(new[target])) - {"properties"}):
            previous, current = old[target].get(prop), new[target].get(prop)
            if digest(previous) != digest(current):
                differences.append({"target": target, "property": "object." + prop, "before": previous, "after": current})
    for prop in sorted((set(before) | set(after)) - {"objects"}):
        if digest(before.get(prop)) != digest(after.get(prop)):
            differences.append({"target": "figure:main", "property": prop, "before": before.get(prop), "after": after.get(prop)})
    return differences


def rollback_managed(root: Path, request: dict[str, Any], backend: PlotBackend) -> dict[str, Any]:
    """Caller holds the plot lease; retries retain their original frozen target."""
    saved = transaction_path(root, request["idempotency_key"])
    if saved.exists():
        tx = read(saved)
        if tx.get("rollback_request") != request:
            raise EngineError("document_idempotency_conflict", "This rollback key identifies a different request.")
        if tx["phase"] not in {"complete", "rejected"}:
            pending = active(root)
            if pending and pending["id"] != tx["id"] and pending["phase"] not in {"complete", "rejected"}:
                raise EngineError("document_transaction_pending", "A different transaction is pending.")
            head = load_head(root)
            if head["document"]["revision"] != request["base_revision"] and head["transaction"] != tx["id"]:
                raise EngineError("document_revision_conflict", "The interrupted rollback no longer starts at the current revision.")
            reserve(root, tx)
        return replay(root, tx, backend)
    head = load_head(root)
    current = head["document"]
    if not is_managed(current):
        raise EngineError("managed_authority_required", "Complete presentation rollback requires explicit managed authority.")
    if current["revision"] != request["base_revision"]:
        raise EngineError("document_revision_conflict", "Rollback requires the current revision.", current_revision=current["revision"])
    if request["target_revision"] > current["revision"]:
        raise EngineError("document_rollback_target", "Rollback can restore only an existing committed revision.")
    pending = active(root)
    if pending and pending["phase"] not in {"complete", "rejected"}:
        raise EngineError("document_transaction_pending", "Finish the existing transaction before rollback.")
    require_inputs(current)
    require_current(backend, head["binding"])
    target = validate_document(read(root / "revisions" / f'{request["target_revision"]:08d}.json')["document"])
    verify_document_content(root, target)
    if (not is_managed(target) or target["plot_id"] != current["plot_id"]
            or target["revision"] != request["target_revision"]):
        raise EngineError("document_rollback_target", "The target revision does not identify this managed plot history.")
    if current["scientific_hash"] != target["scientific_hash"]:
        raise EngineError("document_scientific_rollback_unsupported", "Scientific history needs its explicit executor.")
    candidate = deepcopy(current)
    candidate["presentation"] = deepcopy(target["presentation"])
    differences = presentation_diff(current["presentation"], candidate["presentation"])
    if differences:
        candidate["revision"] += 1
    candidate = seal_document(candidate)
    # Compilation validates every represented domain before transaction allocation.
    # It uses frozen CAS data and never invokes scientific preparation or transforms.
    resolved_ir(root, candidate)
    require_inputs(current)
    require_current(backend, head["binding"])
    tx = {"id": digest(request["idempotency_key"]), "request": deepcopy(request),
          "request_hash": digest(request), "rollback_request": deepcopy(request),
          "before": current, "document": candidate, "binding": head["binding"],
          "diff": differences, "risk": "review", "phase": "planned"}
    reserve(root, tx)
    return advance(root, tx, backend)
