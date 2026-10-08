"""Bounded public summaries; native reviews and diagnostics stay in the journal."""

from pathlib import Path
from typing import Any
import json


def receipt(root: Path, transaction: dict[str, Any], *, replay: bool = False) -> dict[str, Any]:
    doc = transaction["document"]
    phase = transaction["phase"]
    status = {"complete": "complete", "needs_review": "needs_review", "rejected": "rejected"}.get(phase, "pending")
    result: dict[str, Any] = {
        "kind": "sciplot_plot_result", "version": 1, "status": status,
        "plot": str(root), "plot_id": doc["plot_id"], "revision": doc["revision"],
        "plot_type": doc.get("plot_type", "LegacyPlot"),
        "scientific_hash": doc["scientific_hash"], "presentation_hash": doc["presentation_hash"],
        "commit_status": "committed" if phase in {"committed", "exporting", "export_pending", "complete"} else "pending",
        "export_status": "complete" if phase == "complete" else "pending",
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
        result["next_step"] = {"action": "retry_same_request"}
        if transaction.get("error"):
            result["error"] = transaction["error"]
            result["status"] = "blocked"
            result["next_step"] = {"action": transaction["error"].get("action", "inspect_diagnostic")}
            if ((phase == "planned" and transaction["error"]["stage"] == "preview"
                 or phase == "resolving" and transaction["error"]["stage"] == "resolving") and "native_result" not in transaction):
                result["discard_request"] = {"decision_id": transaction["id"],
                    "base_revision": transaction["request"]["base_revision"], "accept": False}
    return result
