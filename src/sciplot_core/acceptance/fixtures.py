"""Resolve public and local real-world rule fixtures and evidence."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any
import pandas as pd
from sciplot_core._paths import (
    local_reference_root,
    real_world_fixture_root,
    resolve_fixture_path,
)
from sciplot_core.materials_rules import SemanticRule


DEFAULT_3DPA_FTIR_LABELS = ("PA6", "A20", "A40", "A80", "A20-2MIN", "A30-2MIN")


DEFAULT_3DPA_TORQUE_DIRS = ("转矩/260607", "转矩/Z", "torque/260607", "torque/Z")


DEFAULT_DENSE_SERIES_COUNT = 44


DEFAULT_REPRESENTATIVE_COUNT = 6


RULE_ACCEPTANCE_VERSION = 3


RULE_ACCEPTANCE_CHECK_IDS = (
    "semantic_rule_selected",
    "validated_rule_contract_current",
    "supported_templates_exercised",
    "vsz_reopen_export",
    "manual_edit_preserved",
    "canonical_pdf_tiff_pair",
    "qa_passed",
    "delivery_complete",
    "provenance_complete",
)


@dataclass(frozen=True)
class SpectrumSeries:
    label: str
    source: Path
    data: pd.DataFrame


def _public_fixture_index(repo_root: Path) -> dict[Path, dict[str, Any]]:
    corpus_root = repo_root / "tests" / "fixtures" / "polymer_corpus"
    manifest_path = corpus_root / "manifest.json"
    if not manifest_path.exists():
        corpus_root = local_reference_root(repo_root=repo_root) / "polymer_corpus"
        manifest_path = corpus_root / "manifest.json"
    if not manifest_path.exists():
        return {}
    payload = json.loads(manifest_path.read_text(encoding="utf-8"))
    entries = payload.get("entries") if isinstance(payload.get("entries"), list) else []
    indexed: dict[Path, dict[str, Any]] = {}
    for entry in entries:
        if not isinstance(entry, dict):
            continue
        fixture_value = entry.get("fixture_path")
        if not isinstance(fixture_value, str) or not fixture_value.strip():
            continue
        indexed[(corpus_root / fixture_value).resolve()] = entry
    return indexed


def _real_world_fixture_index(repo_root: Path) -> dict[Path, dict[str, Any]]:
    fixture_root = real_world_fixture_root(repo_root=repo_root)
    manifest_path = fixture_root / "evidence_manifest.json"
    if not manifest_path.exists():
        return {}
    payload = json.loads(manifest_path.read_text(encoding="utf-8"))
    entries = payload.get("entries") if isinstance(payload.get("entries"), list) else []
    indexed: dict[Path, dict[str, Any]] = {}
    for entry in entries:
        if not isinstance(entry, dict):
            continue
        fixture_value = entry.get("fixture_path")
        if not isinstance(fixture_value, str) or not fixture_value.strip():
            continue
        indexed[(fixture_root / fixture_value).resolve()] = entry
    return indexed


def _rule_fixture_evidence(rule: SemanticRule, *, repo_root: Path) -> dict[str, Any]:
    fixture = resolve_fixture_path(str(rule.fixture_path or ""), repo_root=repo_root)
    public_entry = _public_fixture_index(repo_root).get(fixture)
    if public_entry is not None:
        return {
            "tier": "public_source_excerpt",
            "real_data_evidence": True,
            "source_url": public_entry.get("source_url"),
            "doi": public_entry.get("doi"),
            "license": public_entry.get("license"),
            "description": "Reduced excerpt from a source-annotated public experimental dataset.",
            "manifest_metadata": public_entry,
        }
    real_world_entry = _real_world_fixture_index(repo_root).get(fixture)
    if real_world_entry is not None:
        return {
            "tier": str(real_world_entry.get("tier") or "user_authorized_real_excerpt"),
            "real_data_evidence": bool(real_world_entry.get("real_data_evidence")),
            "source_url": real_world_entry.get("source_url"),
            "doi": real_world_entry.get("doi"),
            "license": real_world_entry.get("license"),
            "description": str(real_world_entry.get("description") or ""),
            "source_data_status": real_world_entry.get("source_data_status"),
            "manifest_metadata": real_world_entry,
        }
    fixture_parts = set(fixture.parts)
    if "real_world" in fixture_parts:
        return {
            "tier": "user_authorized_real_excerpt",
            "real_data_evidence": True,
            "source_url": None,
            "doi": None,
            "license": None,
            "description": "User-authorized real instrument export or reduced excerpt retained as regression evidence.",
        }
    if "archived_output_raw_data" in fixture_parts:
        return {
            "tier": "archived_project_data",
            "real_data_evidence": True,
            "source_url": None,
            "doi": None,
            "license": None,
            "description": "Archived project data retained as regression evidence.",
        }
    return {
        "tier": "instrument_shaped_fixture",
        "real_data_evidence": False,
        "source_url": None,
        "doi": None,
        "license": None,
        "description": "Fixture exercises the instrument-shaped contract but is not claimed as real-data evidence.",
    }
