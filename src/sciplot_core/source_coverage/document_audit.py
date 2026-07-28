"""Audit exact Veusz document datasets against expected units."""

from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any
from sciplot_core.veusz_runtime import veusz_worker_environment

from sciplot_core.source_coverage.file_snapshots import (
    _stable_file_snapshot,
    _assert_snapshot_current,
    _write_private_snapshot,
)


def _audit_exact_document_data(
    *,
    document_path: Path,
    spec_path: Path,
) -> tuple[dict[str, Any], dict[str, Any]]:
    document_snapshot = _stable_file_snapshot(
        document_path,
        label="Veusz document",
    )
    spec_snapshot = _stable_file_snapshot(
        spec_path,
        label="Veusz specification",
    )
    _assert_snapshot_current(document_snapshot, label="Veusz document")
    _assert_snapshot_current(spec_snapshot, label="Veusz specification")
    try:
        spec_payload = json.loads(spec_snapshot["bytes"].decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError(
            f"Mapped render Veusz specification is invalid JSON: {spec_path}"
        ) from exc
    if not isinstance(spec_payload, dict):
        raise ValueError(
            f"Mapped render Veusz specification is not an object: {spec_path}"
        )
    with tempfile.TemporaryDirectory(prefix="sciplot_vsz_audit_") as temporary:
        snapshot_root = Path(temporary)
        os.chmod(snapshot_root, 0o700)
        private_document = snapshot_root / "document.vsz"
        private_spec = snapshot_root / "spec.json"
        _write_private_snapshot(private_document, document_snapshot["bytes"])
        _write_private_snapshot(private_spec, spec_snapshot["bytes"])
        completed = subprocess.run(
            [
                sys.executable,
                "-m",
                "sciplot_core.veusz_worker",
                "audit-spec-data",
                str(private_document),
                str(private_spec),
            ],
            text=True,
            capture_output=True,
            check=False,
            timeout=120,
            env=veusz_worker_environment(),
        )
    if completed.returncode != 0:
        detail = completed.stderr.strip().splitlines()
        raise ValueError(
            "Exact-current Veusz data-consumption audit failed: "
            f"{detail[-1] if detail else completed.returncode}"
        )
    try:
        payload = json.loads(completed.stdout)
    except json.JSONDecodeError as exc:
        raise ValueError(
            "Exact-current Veusz data-consumption audit returned invalid JSON."
        ) from exc
    if (
        not isinstance(payload, dict)
        or payload.get("kind") != "sciplot_veusz_spec_data_audit"
        or payload.get("version") != 1
        or payload.get("status") != "passed"
    ):
        raise ValueError("Exact-current Veusz data-consumption audit did not pass.")
    expected_document = {
        "path": str(private_document.resolve()),
        "sha256": document_snapshot["sha256"],
    }
    expected_spec = {
        "path": str(private_spec.resolve()),
        "sha256": spec_snapshot["sha256"],
    }
    if (
        payload.get("document") != expected_document
        or payload.get("spec") != expected_spec
    ):
        raise ValueError(
            "Exact-current Veusz data-consumption audit returned stale artifacts."
        )
    units = payload.get("units")
    if (
        not isinstance(units, list)
        or not units
        or payload.get("unit_count") != len(units)
    ):
        raise ValueError(
            "Exact-current Veusz data-consumption audit has no closed unit inventory."
        )
    _assert_snapshot_current(document_snapshot, label="Veusz document")
    _assert_snapshot_current(spec_snapshot, label="Veusz specification")
    payload["document"] = {
        "path": str(document_snapshot["path"]),
        "sha256": document_snapshot["sha256"],
    }
    payload["spec"] = {
        "path": str(spec_snapshot["path"]),
        "sha256": spec_snapshot["sha256"],
    }
    return payload, spec_payload
