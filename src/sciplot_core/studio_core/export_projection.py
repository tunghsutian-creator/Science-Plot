"""Project known export receipt paths onto exact current resource bindings."""

from __future__ import annotations

from copy import deepcopy
from pathlib import Path
from typing import Any

from sciplot_core.project_store import FileProjectStore


def export_projection(record: dict[str, Any], store: FileProjectStore, *,
                      document: Path | None = None, spec: Path | None = None,
                      receipt_key: str = "project_command") -> dict[str, Any]:
    """Keep scientific source literals sealed; resolve only declared artifact fields."""
    payload: dict[str, Any] = deepcopy(record["result"])

    def artifact(value: str, digest: str | None = None) -> str:
        return str(store.resolve_path(value, expected_sha256=digest))

    payload["document"] = str(document) if document is not None else artifact(
        payload["document"], payload["document_sha256"])
    for item in payload["exports"]:
        item["path"] = artifact(item["path"], item["sha256"])
    payload["export_dir"] = str(Path(payload["exports"][0]["path"]).parent)
    audit = payload.get("document_audit")
    if isinstance(audit, dict):
        audit["document"]["path"] = payload["document"]
        audit["spec"]["path"] = str(spec) if spec is not None else artifact(
            audit["spec"]["path"], audit["spec"]["sha256"])
    receipt = payload.get("standalone_export")
    if isinstance(receipt, dict):
        receipt["document"] = payload["document"]
        receipt["exports"] = deepcopy(payload["exports"])
        for key in ("receipt_path", "artifact_qa_path"):
            receipt[key] = artifact(receipt[key])
        reference = receipt.get("spec_reference")
        if isinstance(reference, dict) and reference.get("exists"):
            value = str(spec) if spec is not None else artifact(reference["path"])
            reference.update(path=value, expected_path=value)
        qa = receipt.get("artifact_qa") or {}
        for category in ("pdfs", "tiffs"):
            for item in qa.get(category, []):
                if isinstance(item, dict) and isinstance(item.get("path"), str):
                    item["path"] = artifact(item["path"], item.get("sha256"))
    payload[receipt_key] = {field: record[field] for field in ("command_id", "project_id", "generation", "phase")}
    return payload
