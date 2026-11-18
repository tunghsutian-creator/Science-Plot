"""Restore a represented legacy presentation via the existing patch owner."""
from collections.abc import Callable
from pathlib import Path
from typing import Any

from sciplot_core.plot_engine.backend import PlotBackend
from sciplot_core.plot_engine.content_store import verify_document_content

from .context import exists, load_head, load_revision, read, transaction_path
from .errors import EngineError
from .execution import replay


def rollback_legacy(root: Path, request: dict[str, Any], backend: PlotBackend,
                    patch_plot: Callable[..., dict[str, Any]]) -> dict[str, Any]:
    """Caller holds the plot lease and has admitted the rollback command."""
    saved = transaction_path(root, request["idempotency_key"])
    if exists(saved):
        tx = read(saved)
        if tx.get("rollback_request") != request:
            raise EngineError("document_idempotency_conflict", "This key identifies another request.")
        return replay(root, tx, backend)
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
    return patch_plot(root, patch, rollback_request=request)
