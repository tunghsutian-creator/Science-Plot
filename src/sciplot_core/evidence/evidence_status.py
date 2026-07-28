"""Evaluate fixture and authorization evidence states."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from sciplot_core.evidence.json_sources import (
    HASH_PATTERN,
)

from sciplot_core.evidence.provenance import (
    _expected_fixture_hashes,
)


def _fixture_hash_status(
    fixture: Path,
    inventory: list[dict[str, str]],
    metadata: dict[str, Any],
    provenance: dict[str, Any],
) -> tuple[str, list[dict[str, str]]]:
    expected = _expected_fixture_hashes(provenance)
    if fixture.is_file():
        direct = (
            provenance.get("fixture_sha256")
            or metadata.get("sha256")
            or metadata.get("fixture_sha256")
        )
        if isinstance(direct, str) and HASH_PATTERN.fullmatch(direct):
            expected.setdefault(fixture.name, direct.casefold())
    checks: list[dict[str, str]] = []
    for item in inventory:
        expected_hash = expected.get(Path(item["path"]).name)
        checks.append(
            {
                **item,
                "expected_sha256": expected_hash or "",
                "status": (
                    "verified"
                    if expected_hash and expected_hash == item["sha256"]
                    else ("mismatch" if expected_hash else "computed_unregistered")
                ),
            }
        )
    if not checks:
        return "missing", checks
    if any(item["status"] == "mismatch" for item in checks):
        return "mismatch", checks
    if all(item["status"] == "verified" for item in checks):
        return "verified", checks
    return "computed_unregistered", checks


def _authorization_status(
    evidence: dict[str, Any],
    metadata: dict[str, Any],
    provenance: dict[str, Any],
) -> str:
    explicit = metadata.get("authorization_status") or provenance.get(
        "authorization_status"
    )
    if isinstance(explicit, str) and explicit.strip():
        return explicit.strip()
    if not evidence.get("real_data_evidence"):
        return "rejected_as_real_data"
    tier = str(evidence.get("tier") or "")
    license_value = str(evidence.get("license") or provenance.get("license") or "")
    if license_value and "not asserted" not in license_value.casefold():
        return "license_recorded"
    if tier.startswith("user_authorized"):
        return "user_authorized"
    if tier == "archived_project_data":
        return "user_authorized_archive"
    return "authorization_not_registered"


def _first_mapping(*values: object) -> dict[str, Any]:
    for value in values:
        if isinstance(value, dict) and value:
            return {str(key): item for key, item in value.items()}
    return {}
