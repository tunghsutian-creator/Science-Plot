"""Recognize only a complete original native receipt; never replay its callback."""
from copy import deepcopy
from pathlib import Path
from typing import Any

from .attachment_index import Attachment
from .attachment_projection import metadata_view
from .journal_identity import saved_command
from .repository import digest


def applied_binding(backend: Any, namespace: Any, envelope: dict[str, Any], attachment: Attachment,
                    binding: dict[str, Any]) -> dict[str, Any] | None:
    if envelope["document"].get("plot_type") == "ManagedPlot":
        return None
    transaction = namespace.active(namespace.origin)
    if (not transaction or transaction.get("phase") not in {"applying", "native_applied"}
            or transaction.get("mode") == "reimport" or "before" not in transaction or "document" not in transaction
            or digest(transaction["before"]) != digest(envelope["document"])
            or transaction["document"].get("scientific_hash") != envelope["document"]["scientific_hash"]):
        return None
    saved_command(transaction)
    request = transaction.get("request", {})
    key = request.get("idempotency_key")
    if (not isinstance(key, str) or transaction.get("id") != digest(key)
            or transaction.get("request_hash") != digest(request)
            or request.get("base_revision") != envelope["document"]["revision"]
            or request.get("plot_id") != envelope["document"]["plot_id"]):
        return None
    review = transaction.get("review", {})
    if (review.get("kind") != "sciplot_document_edit_preview" or review.get("version") != 3
            or review.get("scientific_audit", {}).get("status") != "passed"):
        return None
    from sciplot_core.studio_core.document_edit_commands import verify_document_edit_receipt

    runtime = metadata_view(deepcopy(review), attachment)
    native = {key: value for key, value in runtime.items() if not key.startswith("_backend_")}
    receipt = verify_document_edit_receipt(Path(binding["project"]), native)
    if receipt is None or receipt.get("readonly_native_receipt") is not True:
        return None
    result = {**receipt, "_backend_updates": deepcopy(runtime.get("_backend_updates", {})),
              "_backend_expected_spec_sha256": (runtime.get("candidate_spec") or {}).get("sha256", binding["fingerprint"]["files"][binding["spec"]])}
    current: dict[str, Any] = backend.refresh_binding(binding, result)
    return current
