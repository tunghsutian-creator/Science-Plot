"""Review a saved native-only change without guessing new science or identities."""

from copy import deepcopy
from pathlib import Path
from typing import Any

from sciplot_core.plot_document import seal_document

from .backend import PlotBackend
from .current import changed_inputs, require_current
from .errors import EngineError
from .execution import replay
from .external_mutation import capture_baseline, record_legacy_mutation
from .receipts import receipt
from .storage import active, digest, load_head, read, reserve, transaction_path


def offer(backend: PlotBackend, head: dict[str, Any], changed: list[str]) -> dict[str, Any] | None:
    binding = head["binding"]
    if changed != [binding.get("document")]:
        return None
    identity = digest([head["document"]["revision"], binding["fingerprint"], backend.fingerprint(binding)])
    return {"action": "plot.decide", "request": {"reimport": True,
            "base_revision": head["document"]["revision"], "decision_id": identity}}


def _align(old: dict[str, Any], imported: dict[str, Any], old_binding: dict[str, Any],
           new_binding: dict[str, Any]) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    old_objects = old["presentation"]["objects"]
    new_objects = imported["presentation"]["objects"]
    paths: dict[str, str] = {}
    for identifier, target in old_binding["targets"].items():
        path = target.get("object_path")
        if not isinstance(path, str) or path in paths:
            raise EngineError("document_reimport_identity_conflict", "Native object paths are not unique.")
        paths[path] = identifier
    aligned, targets = {}, {}
    for identifier, obj in new_objects.items():
        target = new_binding["targets"][identifier]
        stable = paths.get(target.get("object_path"))
        if stable is None or old_objects[stable]["kind"] != obj["kind"]:
            raise EngineError("document_reimport_identity_conflict", "Native object membership changed; do not infer replacement IDs.")
        if old_objects[stable].get("scientific_role") != obj.get("scientific_role"):
            raise EngineError("document_reimport_scientific_conflict", "Object scientific roles cannot be replaced by native reimport.")
        aligned[stable], targets[stable] = obj, target
    for identifier in set(old_objects) - set(aligned):
        obj = old_objects[identifier]
        if obj["properties"].get("annotation.visible", obj["properties"].get("title.visible")) is not False:
            raise EngineError("document_reimport_identity_conflict", "A represented native object disappeared.")
        aligned[identifier], targets[identifier] = deepcopy(obj), deepcopy(old_binding["targets"][identifier])
    if any(set(old_objects[name]["properties"]) != set(obj["properties"]) for name, obj in aligned.items()):
        raise EngineError("document_reimport_capability_conflict", "Represented native properties changed; explicit migration is required.")
    result = deepcopy(old)
    result["revision"] += 1
    result["presentation"]["objects"] = aligned
    new_binding["targets"] = targets
    for key in ("scientific_content_files", "template_adoption"):
        if key in old_binding:
            new_binding[key] = deepcopy(old_binding[key])
    diff = [{"target": identifier, "property": prop, "before": old_objects[identifier]["properties"][prop],
             "after": value} for identifier, obj in aligned.items() for prop, value in obj["properties"].items()
            if old_objects[identifier]["properties"][prop] != value]
    return seal_document(result), diff


def reimport_native(root: Path, request: dict[str, Any], backend: PlotBackend) -> dict[str, Any]:
    """Caller holds the document lease; acceptance still needs a frozen visual review."""
    key = "reimport:" + request["decision_id"]
    saved = transaction_path(root, key)
    if saved.exists():
        tx = read(saved)
        if tx.get("reimport_request") != request:
            raise EngineError("document_decision_conflict", "This reimport identity belongs to another request.")
        if tx["phase"] not in {"complete", "rejected"}:
            pending = active(root)
            if pending and pending["id"] != tx["id"] and pending["phase"] not in {"complete", "rejected"}:
                raise EngineError("document_transaction_pending", "A different transaction is pending.")
            head = load_head(root)
            if head["document"]["revision"] != request["base_revision"] and head["transaction"] != tx["id"]:
                raise EngineError("document_revision_conflict", "The interrupted reimport no longer starts at the current revision.")
            reserve(root, tx)
        return replay(root, tx, backend)
    head = load_head(root)
    pending = active(root)
    if pending and pending["phase"] not in {"complete", "rejected"}:
        raise EngineError("document_transaction_pending", "Finish the existing transaction before native reimport.")
    proposed = offer(backend, head, changed_inputs(backend, head["binding"]))
    if proposed is None or proposed["request"] != request:
        raise EngineError("document_reimport_conflict", "The frozen native-only change is no longer current.", action="plot.describe")
    old, old_binding = head["document"], head["binding"]
    imported, binding = backend.import_project(Path(old_binding["project"]), old_binding["figure_id"], old["plot_id"])
    # Import reads several files. Ensure its snapshot is the exact offered native change.
    if digest([old["revision"], old_binding["fingerprint"], binding["fingerprint"]]) != request["decision_id"]:
        raise EngineError("document_reimport_conflict", "Inputs changed while importing the native document.", action="plot.describe")
    audit = binding.get("native_audit_at_import", {})
    if audit.get("status") != "passed":
        raise EngineError("document_scientific_audit_failed", "Native reimport requires a passed numerical and mapping audit.")
    document, diff = _align(old, imported, old_binding, binding)
    mutation = record_legacy_mutation(root, head, binding, diff)
    binding = capture_baseline(root, binding)
    require_current(backend, binding)
    txid = digest(key)
    rendered = backend.render(binding, root / "transactions" / txid / "reimport-preview")
    require_current(backend, binding)
    tx = {"id": txid, "mode": "reimport", "request": {"idempotency_key": key, "base_revision": old["revision"]},
          "reimport_request": request, "request_hash": digest(request), "before": old, "document": document,
          "external_mutation": mutation,
          "binding": binding, "diff": diff, "risk": "review", "phase": "needs_review",
          "review": {**rendered, "scientific_audit": audit, "external_mutation": mutation}, "native_adoption": {
              "previous_sha256": old_binding["fingerprint"]["files"][old_binding["document"]],
              "current_sha256": binding["fingerprint"]["files"][binding["document"]],
              "opaque_native_content": "preserved_and_requires_visual_review"}}
    reserve(root, tx)
    return receipt(root, tx)
