"""Enrich one rule record and load candidate rejections."""

from __future__ import annotations

from pathlib import Path
from typing import Any
from sciplot_core._paths import real_world_fixture_root
from sciplot_core.materials_rules import SemanticRule

from sciplot_core.evidence.json_sources import (
    _load_json,
)

from sciplot_core.evidence.fixture_inventory import (
    _fixture_hash_inventory,
)

from sciplot_core.evidence.provenance import (
    _provenance_candidates,
    _registered_source_hashes,
)

from sciplot_core.evidence.evidence_status import (
    _fixture_hash_status,
    _authorization_status,
    _first_mapping,
)


def enrich_rule_evidence(
    rule: SemanticRule,
    evidence: dict[str, Any],
    *,
    fixture: Path,
    repo_root: Path,
) -> dict[str, Any]:
    metadata = (
        evidence.get("manifest_metadata")
        if isinstance(evidence.get("manifest_metadata"), dict)
        else {}
    )
    provenance_path = next(
        (
            candidate
            for candidate in _provenance_candidates(fixture, metadata, repo_root)
            if candidate.exists()
        ),
        None,
    )
    provenance = _load_json(provenance_path) if provenance_path is not None else {}
    inventory, tree_sha256 = _fixture_hash_inventory(fixture)
    fixture_hash_status, hash_checks = _fixture_hash_status(
        fixture, inventory, metadata, provenance
    )
    source_hashes = _registered_source_hashes(
        {"metadata": metadata, "provenance": provenance}
    )
    source_units = _first_mapping(
        metadata.get("source_units"), provenance.get("source_units")
    )
    output_units = _first_mapping(
        metadata.get("output_units"), provenance.get("output_units")
    )
    canonical_units = {
        "x": rule.x_axis.canonical_unit,
        "y": rule.y_axis.canonical_unit,
    }
    if source_units and output_units:
        unit_status = "source_and_output_registered"
    elif source_units:
        unit_status = "source_registered_canonical_output"
    else:
        unit_status = "canonical_contract_only"
    limitations = [
        str(value)
        for key in ("control_mode_limitation", "replicate_policy")
        for value in [provenance.get(key)]
        if isinstance(value, str) and value.strip()
    ]
    merged = dict(evidence)
    merged.pop("manifest_metadata", None)
    merged.update(
        {
            "source_url": evidence.get("source_url")
            or metadata.get("source_url")
            or provenance.get("source_url"),
            "doi": evidence.get("doi") or metadata.get("doi") or provenance.get("doi"),
            "license": evidence.get("license")
            or metadata.get("license")
            or provenance.get("license"),
            "authorization_status": _authorization_status(
                evidence, metadata, provenance
            ),
            "source_hash_status": "registered" if source_hashes else "unregistered",
            "registered_source_hash_count": len(source_hashes),
            "fixture_hash_status": fixture_hash_status,
            "fixture_tree_sha256": tree_sha256,
            "fixture_hashes": hash_checks,
            "source_units": source_units,
            "output_units": output_units,
            "canonical_units": canonical_units,
            "unit_status": unit_status,
            "provenance_path": str(provenance_path)
            if provenance_path is not None
            else None,
            "rejection_reason": (
                None
                if evidence.get("real_data_evidence")
                else str(
                    evidence.get("description") or "Not accepted as real-data evidence."
                )
            ),
            "limitations": limitations,
        }
    )
    return merged


def load_candidate_rejections(*, repo_root: Path) -> list[dict[str, Any]]:
    payload = _load_json(
        real_world_fixture_root(repo_root=repo_root) / "candidate_rejections.json"
    )
    entries = payload.get("entries") if isinstance(payload.get("entries"), list) else []
    return [entry for entry in entries if isinstance(entry, dict)]
