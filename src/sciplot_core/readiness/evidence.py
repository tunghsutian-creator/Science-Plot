"""Normalize acceptance evidence strength and manifest paths."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from sciplot_core.readiness.validation import (
    _required_text,
)


def _evidence_strength(evidence: dict[str, Any]) -> str:
    fixture = str(evidence.get("fixture_hash_status") or "")
    source = str(evidence.get("source_hash_status") or "")
    units = str(evidence.get("unit_status") or "")
    if (
        fixture == "verified"
        and source == "registered"
        and units == "source_and_output_registered"
    ):
        return "registered_fixture_source_and_units"
    if fixture == "verified" and source == "registered":
        return "registered_fixture_and_source"
    if fixture == "verified":
        return "verified_fixture"
    return "computed_fixture_hash"


def _evidence_limitations(evidence: dict[str, Any]) -> tuple[str, ...]:
    limitations = [
        _required_text(value, "evidence limitation", maximum=4096)
        for value in evidence.get("limitations", [])
        if isinstance(value, str) and value.strip()
    ]
    if evidence.get("fixture_hash_status") == "computed_unregistered":
        limitations.append(
            "The accepted fixture hash was computed but was not registered in "
            "its provenance record."
        )
    if evidence.get("source_hash_status") != "registered":
        limitations.append(
            "The upstream source hash was not registered; the accepted fixture "
            "tree remains hash-bound."
        )
    if evidence.get("unit_status") == "canonical_contract_only":
        limitations.append(
            "Source-unit metadata was not registered; runtime parsing must still "
            "satisfy the rule's canonical axis contract."
        )
    return tuple(dict.fromkeys(limitations))


def _resolved_manifest_path(
    value: object,
    *,
    acceptance_root: Path,
) -> Path:
    text = _required_text(value, "acceptance manifest path", maximum=8192)
    path = Path(text).expanduser()
    if not path.is_absolute():
        path = acceptance_root / path
    resolved = path.resolve()
    if not resolved.is_file():
        raise FileNotFoundError(f"Acceptance manifest not found: {resolved}")
    return resolved
