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
from sciplot_core.source_coverage.file_snapshots import _assert_snapshot_current, stable_file_snapshot
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
    specification = spec.read_bytes()
    native_bytes = document.read_bytes()
    native_digest = hashlib.sha256(native_bytes).hexdigest()
    records = source_records(json.loads(specification))

    def verify_sources() -> None:
        if spec.read_bytes() != specification or any(
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
    if file_sha256(document) != native_digest:
        raise ValueError("The observed native document changed during its exact scientific audit")
    return {**audit, "document_sha256": native_digest,
            "spec_sha256": hashlib.sha256(specification).hexdigest()}
