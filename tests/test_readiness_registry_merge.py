from __future__ import annotations

from copy import deepcopy
from dataclasses import replace
import json
from pathlib import Path

import pytest

from sciplot_core.foundation.file_hashing import file_sha256
from sciplot_core.materials_rules import SemanticRule, get_rule
from sciplot_core.readiness.constants import (
    READY_RULE_ACCEPTANCE_VERSION,
    REQUIRED_ACCEPTANCE_CHECKS,
    VALIDATED_ENVELOPE_ACCEPTANCE_LINEAGE_KIND,
    VALIDATED_ENVELOPE_ACCEPTANCE_LINEAGE_VERSION,
)
from sciplot_core.readiness.registry_build import build_validated_envelope_registry
from sciplot_core.readiness.registry_io import load_validated_envelope_registry
from sciplot_core.readiness.registry_merge import merge_validated_envelope_registry
from sciplot_core.readiness.registry_model import ValidatedEnvelopeRegistry
from sciplot_core.readiness.rule_contract import (
    rule_contract_hashes,
    rule_contract_payload,
)
from sciplot_core.readiness.status import validated_envelope_status


RULE_IDS = ("uvvis_spectrum", "xrd_pattern", "swelling_curve")
SELECTED_IDS = RULE_IDS[:2]
GENERATED_AT = "2026-08-10T10:00:00+00:00"


def _rules() -> tuple[SemanticRule, ...]:
    return tuple(get_rule(rule_id) for rule_id in RULE_IDS)


def _base_registry() -> ValidatedEnvelopeRegistry:
    source = load_validated_envelope_registry()
    entries = []
    for rule in _rules():
        entry = source.entry(rule.rule_id)
        assert entry is not None
        hashes = rule_contract_hashes(rule)
        entries.append(
            replace(
                entry,
                contract_sha256=(
                    "0" * 64 if rule.rule_id in SELECTED_IDS else hashes.contract_sha256
                ),
                semantic_contract_sha256=(
                    "1" * 64
                    if rule.rule_id in SELECTED_IDS
                    else hashes.semantic_contract_sha256
                ),
                semantic_family=rule.semantic_family,
            )
        )
    source_acceptance = deepcopy(source.source_acceptance)
    if source.version == 1:
        for key in (
            "ready_rule_count",
            "lifecycle_passed_count",
            "physical_size_passed_count",
            "real_data_lifecycle_passed_count",
        ):
            source_acceptance[key] = len(entries)
    else:
        retained_rule_ids = set(RULE_IDS)
        records = []
        for record in source_acceptance["records"]:
            retained_ids = [
                rule_id
                for rule_id in record["rule_ids"]
                if rule_id in retained_rule_ids
            ]
            if retained_ids:
                record["rule_ids"] = retained_ids
                records.append(record)
        source_acceptance["records"] = records
    return replace(
        source,
        source_acceptance=source_acceptance,
        entries=tuple(entries),
    )


def test_legacy_v1_registry_roundtrips_and_projects_composite_lineage() -> None:
    source = load_validated_envelope_registry()
    generated_at = "2026-08-09T12:35:54+00:00"
    summary_sha256 = "4" * 64
    limitation = "legacy acceptance fixture"
    legacy_payload = {
        "kind": source.kind,
        "version": 1,
        "generated_at": source.generated_at,
        "source_acceptance": {
            "kind": "sciplot_ready_rule_acceptance",
            "version": READY_RULE_ACCEPTANCE_VERSION,
            "generated_at": generated_at,
            "summary_sha256": summary_sha256,
            "ready_rule_count": len(source.entries),
            "lifecycle_passed_count": len(source.entries),
            "physical_size_passed_count": len(source.entries),
            "real_data_lifecycle_passed_count": len(source.entries),
            "limitations": [limitation],
        },
        "entries": [entry.to_dict() for entry in source.entries],
        "limitations": list(source.limitations),
    }

    legacy = ValidatedEnvelopeRegistry.from_dict(legacy_payload)
    roundtripped = ValidatedEnvelopeRegistry.from_dict(legacy.to_dict())
    status = validated_envelope_status(roundtripped)

    assert roundtripped.version == 1
    assert status["version"] == 2
    assert status["source_acceptance"] == {
        "kind": VALIDATED_ENVELOPE_ACCEPTANCE_LINEAGE_KIND,
        "version": VALIDATED_ENVELOPE_ACCEPTANCE_LINEAGE_VERSION,
        "records": [
            {
                "kind": "sciplot_ready_rule_acceptance",
                "version": READY_RULE_ACCEPTANCE_VERSION,
                "generated_at": generated_at,
                "summary_sha256": summary_sha256,
                "rule_ids": [entry.rule_id for entry in roundtripped.entries],
                "limitations": [limitation],
            }
        ],
    }


def _accepted_row(rule: SemanticRule, *, root: Path) -> dict[str, object]:
    entry = load_validated_envelope_registry().entry(rule.rule_id)
    assert entry is not None
    hashes = rule_contract_hashes(rule)
    manifest = root / f"{rule.rule_id}.manifest.json"
    manifest.write_text(
        json.dumps({"semantic": rule_contract_payload(rule)["semantic"]}),
        encoding="utf-8",
    )
    return {
        "rule_id": rule.rule_id,
        "semantic_family": rule.semantic_family,
        "template": rule.template,
        "recipe": rule.recipe,
        "rule_readiness": "ready",
        "lifecycle_status": "passed",
        "checks": {check_id: True for check_id in REQUIRED_ACCEPTANCE_CHECKS},
        "artifact_review": {"status": "passed"},
        "evidence": {
            "tier": entry.evidence_tier,
            "real_data_evidence": True,
            "authorization_status": entry.authorization_status,
            "fixture_hash_status": entry.fixture_hash_status,
            "fixture_tree_sha256": entry.fixture_tree_sha256,
            "source_hash_status": entry.source_hash_status,
            "registered_source_hash_count": entry.registered_source_hash_count,
            "unit_status": entry.unit_status,
            "limitations": list(entry.limitations),
        },
        "manifest": str(manifest),
        "rule_contract_sha256": hashes.contract_sha256,
        "accepted_rule_contract_sha256": hashes.contract_sha256,
        "semantic_contract_sha256": hashes.semantic_contract_sha256,
        "accepted_semantic_contract_sha256": hashes.semantic_contract_sha256,
    }


def _write_summary(
    root: Path,
    *,
    selected_ids: tuple[str, ...],
    complete: bool = False,
) -> Path:
    rows = [
        _accepted_row(rule, root=root)
        if rule.rule_id in selected_ids
        else {"rule_id": rule.rule_id}
        for rule in _rules()
    ]
    selected_count = len(selected_ids)
    payload = {
        "kind": "sciplot_ready_rule_acceptance",
        "version": 3,
        "generated_at": GENERATED_AT,
        "state": "ready" if complete else "in_progress",
        "selected_state": "ready",
        "selected_rule_ids": list(selected_ids),
        "failed_rule_ids": [],
        "coverage": {
            "ready_rule_count": len(RULE_IDS),
            "lifecycle_passed_count": selected_count,
            "lifecycle_complete": complete,
            "physical_size_passed_count": selected_count,
            "physical_size_complete": complete,
            "real_data_lifecycle_passed_count": selected_count,
            "instrument_shaped_gap_count": 0,
        },
        "visual_review": {
            "automated_status": "passed",
            "manual_visual_status": "passed",
            "eligible_rule_count": selected_count,
        },
        "matrix": rows,
        "limitations": ["focused acceptance fixture"],
    }
    path = root / "acceptance_summary.json"
    path.write_text(json.dumps(payload), encoding="utf-8")
    return path


def test_scoped_merge_replaces_selected_entries_and_composes_lineage(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import sciplot_core.readiness.registry_merge as merge_module

    monkeypatch.setattr(merge_module, "iter_public_rules", _rules)
    base = _base_registry()
    summary = _write_summary(tmp_path, selected_ids=SELECTED_IDS)

    merged = merge_validated_envelope_registry(base, summary)

    assert merged.version == 2
    assert merged.entry("swelling_curve") == base.entry("swelling_curve")
    for rule_id in SELECTED_IDS:
        hashes = rule_contract_hashes(get_rule(rule_id))
        assert merged.entry(rule_id).contract_sha256 == hashes.contract_sha256
        assert (
            merged.entry(rule_id).semantic_contract_sha256
            == hashes.semantic_contract_sha256
        )
    records = merged.source_acceptance["records"]
    assert records[0]["rule_ids"] == ["swelling_curve"]
    assert records[1]["rule_ids"] == list(SELECTED_IDS)
    assert records[1]["summary_sha256"] == file_sha256(summary)
    assert ValidatedEnvelopeRegistry.from_dict(merged.to_dict()) == merged


def test_scoped_merge_rejects_stale_unselected_base_entry(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import sciplot_core.readiness.registry_merge as merge_module

    monkeypatch.setattr(merge_module, "iter_public_rules", _rules)
    base = _base_registry()
    stale = replace(base.entry("swelling_curve"), contract_sha256="2" * 64)
    base = replace(
        base,
        entries=tuple(
            stale if entry.rule_id == stale.rule_id else entry for entry in base.entries
        ),
    )
    summary = _write_summary(tmp_path, selected_ids=SELECTED_IDS)

    with pytest.raises(ValueError, match="not current for `swelling_curve`"):
        merge_validated_envelope_registry(base, summary)


def test_scoped_merge_reuses_strict_selected_row_validation(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import sciplot_core.readiness.registry_merge as merge_module

    monkeypatch.setattr(merge_module, "iter_public_rules", _rules)
    summary = _write_summary(tmp_path, selected_ids=SELECTED_IDS)
    payload = json.loads(summary.read_text(encoding="utf-8"))
    payload["matrix"][0]["accepted_semantic_contract_sha256"] = "3" * 64
    summary.write_text(json.dumps(payload), encoding="utf-8")

    with pytest.raises(ValueError, match="manifest semantic hash was not preserved"):
        merge_validated_envelope_registry(_base_registry(), summary)


def test_complete_builder_writes_one_composite_lineage_record(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import sciplot_core.readiness.registry_build as build_module

    monkeypatch.setattr(build_module, "iter_public_rules", _rules)
    summary = _write_summary(tmp_path, selected_ids=RULE_IDS, complete=True)

    registry = build_validated_envelope_registry(summary)

    assert registry.version == 2
    assert registry.source_acceptance["records"] == [
        {
            "kind": "sciplot_ready_rule_acceptance",
            "version": 3,
            "generated_at": GENERATED_AT,
            "summary_sha256": file_sha256(summary),
            "rule_ids": list(RULE_IDS),
            "limitations": ["focused acceptance fixture"],
        }
    ]
