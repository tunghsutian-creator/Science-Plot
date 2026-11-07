"""Bounded public summaries; native reviews and diagnostics stay in the journal."""

from pathlib import Path
from typing import Any
import json

from .contracts import Receipt


def receipt(root: Path, transaction: dict[str, Any], *, replay: bool = False) -> dict[str, Any]:
    doc = transaction["document"]
    phase = transaction["phase"]
    outcome = Receipt.of(transaction)
    result: dict[str, Any] = {
        "kind": "sciplot_plot_result", "version": 1, **outcome.to_payload(),
        "plot": str(root),
        "ready_to_use": False,
        "replayed": replay, "changed": bool(transaction["diff"]),
        "effective_risk": transaction["risk"],
        "scientific_hash_changed": doc["scientific_hash"] != transaction["before"]["scientific_hash"],
        "presentation_hash_changed": doc["presentation_hash"] != transaction["before"]["presentation_hash"],
        "evidence": str(root / "transactions" / transaction["id"] / "transaction.json"),
    }
    diff = transaction["diff"]
    if doc.get("plot_type") == "ManagedPlot":
        result["ir_hash"] = transaction["binding"].get("ir_hash")
        if "resolution" in transaction:
            result["transform_execution"] = {key: transaction["resolution"][key] for key in ("executed", "reused")}
    if transaction.get("mode") == "reimport":
        result.update({"changed": True, "native_adoption": transaction["native_adoption"]})
    if "external_mutation" in transaction:
        mutation = transaction["external_mutation"]
        result["external_mutation"] = {key: mutation[key] for key in ("mutation_id", "classification", "authority")}
    result["diff_count"] = len(diff)
    if len(json.dumps(diff, ensure_ascii=False).encode()) <= 2048:
        result["diff"] = diff
    else:
        result["diff_evidence"] = {"path": result["evidence"], "json_pointer": "/diff"}
    if phase == "needs_review":
        result.update({"decision_id": transaction["id"], "preview": transaction["review"].get("preview"),
                       "scientific_audit": {"status": transaction["review"]["scientific_audit"]["status"],
                                            "evidence": {"path": result["evidence"], "json_pointer": "/review/scientific_audit"}},
                       "next_step": {"action": "plot.decide", "request": {
                           "decision_id": transaction["id"], "base_revision": transaction["request"]["base_revision"],
                           "accept": True}}})
        if "before_preview" in transaction["review"]:
            result["before_preview"] = transaction["review"]["before_preview"]
            result["source_append_evidence"] = {"path": result["evidence"], "json_pointer": "/review/source_append"}
    elif phase == "complete":
        result.update({"ready_to_use": transaction["export"].get("ready_to_use", False),
                       "artifact_build_key": transaction.get("artifact_build_key"),
                       "exports": transaction["export"].get("exports", []), "next_step": {"action": "deliver"}})
        qa = transaction["export"].get("publication_qa")
        if qa is not None:
            result["publication_qa"] = {"status": qa["status"], "native_text_checked": qa["native_text_checked"],
                "hard_count": len(qa["hard"]), "soft_count": len(qa["soft"]),
                "evidence": {"path": result["evidence"], "json_pointer": "/export/publication_qa"}}
    elif phase == "rejected":
        result["next_step"] = {"action": "none"}
    else:
        result["next_step"] = ({"action": "plot.export", "plot": str(root)}
                               if phase in {"committed", "exporting", "export_pending"}
                               else {"action": "retry_same_request"})
        if transaction.get("error"):
            result["error"] = transaction["error"]
            result["next_step"] = {"action": transaction["error"].get("action", "inspect_diagnostic"), "plot": str(root)}
            if result["next_step"]["action"] == "retry_same_request":
                if phase in {"committed", "exporting", "export_pending"}:
                    result["next_step"] = {"action": "plot.export", "plot": str(root)}
                elif "changes" in transaction["request"] and transaction.get("mode") != "reimport":
                    result["next_step"] = {"action": "plot.resume", "plot": str(root), "request": {
                        "plot_id": doc["plot_id"], "base_revision": transaction["request"]["base_revision"],
                        "idempotency_key": transaction["request"]["idempotency_key"]}}
            if ((phase == "planned" and transaction["error"]["stage"] == "preview"
                 or phase == "resolving" and transaction["error"]["stage"] == "resolving") and "native_result" not in transaction):
                result["discard_request"] = {"decision_id": transaction["id"],
                    "base_revision": transaction["request"]["base_revision"], "accept": False}
    return result
