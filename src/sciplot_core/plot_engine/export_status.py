"""Verify sealed publication bytes separately from current render-cache reuse."""
from pathlib import Path
from typing import Any

from sciplot_core.plot_engine.cache_identity import build_key
from sciplot_core.plot_engine.current import evidence_current
from sciplot_core.project_lifecycle.context import exists, read


def export_cache_record(build: str, exported: dict[str, Any], artifacts: dict[str, str],
                        inventories: dict[str, list[str]]) -> dict[str, Any]:
    """One byte-and-recipe receipt for prepared and interactive publications."""
    return {"build_key": build, "export": exported, "artifact_files": artifacts,
            "evidence_inventories": inventories}


def cached_export(root: Path, head: dict[str, Any]) -> dict[str, Any] | None:
    """Read the owner's latest cache, including its generation-owned archive, without repair."""
    path = root / "export-cache.json"
    if not exists(path):
        return None
    cache = read(path)
    key = build_key(head["document"], head["binding"])
    return cache if (cache["build_key"] == key and evidence_current(
        cache["artifact_files"], cache.get("evidence_inventories"))) else None


def _publication(cache: dict[str, Any], head: dict[str, Any]) -> dict[str, Any] | None:
    """Project only publication claims supported by the already verified receipt."""
    exported = cache["export"]
    ir_hash = head["binding"].get("ir_hash")
    if (not isinstance(exported, dict) or not ir_hash
            or exported.get("ir_hash") != ir_hash or exported.get("status") != "exported"):
        return None
    qa = exported.get("publication_qa", {})
    audit = exported.get("scientific_audit", {})
    records = exported.get("exports", [])
    files = cache["artifact_files"]
    native_sha256 = files.get(head["binding"].get("document"))
    if (not isinstance(qa, dict) or not isinstance(audit, dict) or not isinstance(records, list)
            or not native_sha256 or not records or any(not isinstance(record, dict) or record.get("sha256") is None
                or files.get(record.get("path")) != record["sha256"] for record in records)):
        return None
    return {"ir_hash": ir_hash, "document_sha256": native_sha256, "publication_qa": {"status": qa.get("status")},
            "scientific_audit": {"status": audit.get("status")},
            "ready_to_use": exported.get("ready_to_use") is True
                and qa.get("status") == audit.get("status") == "passed",
            # Earlier Managed IR has a scientific audit and a valid native
            # export, but never issued a deterministic publication QA claim.
            **({"native_export_ready": exported.get("ready_to_use") is True and audit.get("status") == "passed"}
                if qa.get("status") is None and "figure_spec" not in head["document"]["scientific"]["provenance"] else {}),
            "exports": [{key: record[key] for key in ("format", "path", "sha256")}
                        for record in records]}


def current_export(root: Path, head: dict[str, Any], *, eligible: bool) -> dict[str, Any]:
    """Read recipe and exact inventories; never create, render, export or repair."""
    try:
        cache = cached_export(root, head)
        ready = cache is not None and eligible
        publication = _publication(cache, head) if cache is not None and ready else None
    except (OSError, ValueError, RuntimeError, KeyError, TypeError) as exc:
        return {"current": False, "byte_inventory_verified": False,
                "artifact_build_key": None, "validation": "unknown",
                "reason_code": getattr(exc, "reason_code", "export_evidence_unavailable")}
    return {"current": ready, "byte_inventory_verified": cache is not None,
            "artifact_build_key": cache["build_key"] if cache is not None else None,
            "validation": "current" if ready else "stale_or_missing",
            **({"publication": publication} if publication is not None else {})}


def sealed_publication(root: Path, head: dict[str, Any]) -> dict[str, Any] | None:
    """Read exact audited bytes for copying, not the current runtime's build cache."""
    path = root / "export-cache.json"
    if not exists(path):
        return None
    cache = read(path)
    binding, exported, files = head["binding"], cache["export"], cache["artifact_files"]
    proof = exported.get("native_export_audit")
    if (not isinstance(proof, dict) or not proof.get("native_state_hash")
            or proof.get("ir_hash") != binding.get("ir_hash")
            or proof.get("canonical_sha256") != binding.get("canonical_sha256")
            or not proof.get("ir_sha256") or files.get(binding.get("ir_path")) != proof["ir_sha256"]
            or not proof.get("document_sha256") or files.get(binding.get("document")) != proof["document_sha256"]
            or not evidence_current(files, cache.get("evidence_inventories"))):
        return None
    return _publication(cache, head)
