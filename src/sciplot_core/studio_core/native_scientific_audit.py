"""Exact native and prepared-source audits without application dependencies."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
import tempfile
from typing import Any

from sciplot_core.foundation.file_hashing import file_sha256
from sciplot_core.foundation.source_locations import resolve_source_path as resolve_runtime_path
from sciplot_core.source_coverage.document_audit import _audit_exact_document_data
from sciplot_core.source_coverage.file_snapshots import (
    _assert_snapshot_current, stable_file_snapshot, _physical_file_snapshot, _require_snapshot_identity,
)
from sciplot_core.source_coverage.managed_documents import source_records, _verify_prepared_data


def audit_native_candidate(
    candidate: Path, spec_path: Path, *, native_audit: dict[str, Any] | None = None,
) -> dict[str, Any]:
    audit, spec = _audit_exact_document_data(
        document_path=candidate, spec_path=spec_path, check_presentation=False,
        native_audit=native_audit,
    )
    snapshots = [
        (stable_file_snapshot(path, label="recovery prepared source", expected_sha256=digest), digest)
        for path, digest in source_records(spec).items()
    ]
    derived = _verify_prepared_data(spec, [snapshot for snapshot, _digest in snapshots])
    for snapshot, digest in snapshots:
        _assert_snapshot_current(snapshot, label="recovery prepared source", expected_sha256=digest)
    return {
        "status": "passed",
        "unit_count": audit["unit_count"],
        "prepared_unit_count": derived["unit_count"],
    }



def audit_edited_document(
    document: Path, spec: Path, *, native_audit: dict[str, Any] | None = None,
) -> dict[str, Any]:
    specification_snapshot = stable_file_snapshot(spec, label="Observed native specification")
    specification = specification_snapshot["bytes"]
    observed = _physical_file_snapshot(document, literal=document, label="Observed native document")
    native_bytes, native_digest = observed["bytes"], observed["sha256"]
    records = source_records(json.loads(specification))

    def verify_sources() -> None:
        _assert_snapshot_current(specification_snapshot, label="Observed native specification",
                                 expected_sha256=specification_snapshot["sha256"])
        if any(
            not resolve_runtime_path(path, expected_sha256=digest).is_file()
            or file_sha256(resolve_runtime_path(path, expected_sha256=digest)) != digest
            for path, digest in records.items()
        ):
            raise ValueError(
                "Prepared scientific sources or their specification changed."
            )

    verify_sources()
    with tempfile.TemporaryDirectory(prefix="sciplot-observed-native-audit-") as temporary:
        candidate = Path(temporary).resolve() / "observed.vsz"
        candidate.write_bytes(native_bytes)
        rebound = ({**native_audit, "document": {**native_audit["document"], "path": str(candidate)}}
                   if native_audit is not None else None)
        audit = audit_native_candidate(candidate, spec, native_audit=rebound)
    verify_sources()
    current = _physical_file_snapshot(document, literal=document, label="Observed native document", expected_sha256=native_digest)
    _require_snapshot_identity(observed, current, label="Observed native document")
    return {**audit, "document_sha256": native_digest,
            "spec_sha256": hashlib.sha256(specification).hexdigest()}
