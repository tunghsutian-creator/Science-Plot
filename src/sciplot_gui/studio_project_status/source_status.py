"""Verify source identity, content, and availability."""

from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Any
from sciplot_core.foundation.file_hashing import existing_file_sha256


def _source_reference(
    source_path: Path | None,
    *,
    transform_ledger: object,
) -> dict[str, Any] | None:
    if source_path is None or not isinstance(transform_ledger, dict):
        return None
    try:
        resolved_source = source_path.expanduser().resolve()
    except (OSError, RuntimeError, ValueError):
        return None
    steps = (
        transform_ledger.get("steps")
        if isinstance(transform_ledger.get("steps"), list)
        else []
    )
    records: list[dict[str, Any]] = []
    for step in steps:
        if not isinstance(step, dict):
            continue
        inputs = (
            step.get("input_artifacts")
            if isinstance(step.get("input_artifacts"), list)
            else []
        )
        records.extend(item for item in inputs if isinstance(item, dict))
    for record in records:
        value = record.get("path")
        if not isinstance(value, str):
            continue
        try:
            referenced_path = Path(value).expanduser().resolve()
        except (OSError, RuntimeError, ValueError):
            continue
        if referenced_path == resolved_source:
            return record
    return None


def _source_content_record(path: Path) -> dict[str, Any]:
    resolved = path.expanduser().resolve()
    if resolved.is_file():
        return {
            "kind": "file",
            "size_bytes": resolved.stat().st_size,
            "sha256": existing_file_sha256(resolved),
        }
    digest = hashlib.sha256()
    member_count = 0
    total_bytes = 0
    for member in sorted(
        candidate for candidate in resolved.rglob("*") if candidate.is_file()
    ):
        member_hash = existing_file_sha256(member)
        if member_hash is None:
            raise OSError(f"Could not hash source member: {member}")
        digest.update(member.relative_to(resolved).as_posix().encode("utf-8"))
        digest.update(member_hash.encode("ascii"))
        member_count += 1
        total_bytes += member.stat().st_size
    return {
        "kind": "directory",
        "size_bytes": total_bytes,
        "member_count": member_count,
        "sha256": digest.hexdigest(),
    }


def _source_status(
    source_path: Path | None,
    *,
    transform_ledger: object,
    audit_source: bool,
) -> dict[str, Any]:
    if source_path is None:
        return {
            "status": "not_established",
            "path": None,
            "exists": False,
            "audit_status": "not_available",
        }
    try:
        resolved = source_path.expanduser().resolve()
        exists = resolved.exists()
    except (OSError, RuntimeError, ValueError) as exc:
        return {
            "status": "audit_failed",
            "path": str(source_path),
            "exists": False,
            "audit_status": "audit_failed",
            "audit_error": str(exc),
        }
    base = {
        "status": "present" if exists else "missing",
        "path": str(resolved),
        "exists": exists,
        "audit_status": "not_computed",
    }
    if not audit_source or not exists:
        return base
    try:
        current = _source_content_record(resolved)
        reference = _source_reference(
            resolved,
            transform_ledger=transform_ledger,
        )
        current_hash = current.get("sha256")
        reference_hash = (
            reference.get("sha256") if isinstance(reference, dict) else None
        )
        if reference_hash and current_hash == reference_hash:
            audit_status = "matches_last_run_lineage"
        elif reference_hash:
            audit_status = "changed_since_last_run"
        else:
            audit_status = "current_hash_not_bound_to_a_run"
    except Exception as exc:
        return {
            **base,
            "audit_status": "audit_failed",
            "audit_error": f"{type(exc).__name__}: {exc}",
        }
    return {
        **base,
        "kind": current.get("kind"),
        "size_bytes": current.get("size_bytes"),
        "member_count": current.get("member_count"),
        "sha256": current_hash,
        "reference_sha256": reference_hash,
        "audit_status": audit_status,
    }
