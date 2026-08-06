from __future__ import annotations

from copy import deepcopy
from dataclasses import replace

from sciplot_core.materials_rules import get_rule
from sciplot_core.readiness import rule_contract as rule_contract_module
from sciplot_core.readiness.registry_io import (
    load_validated_envelope_registry,
)
from sciplot_core.readiness.registry_model import ValidatedEnvelopeRegistry
from sciplot_core.readiness.envelope_model import ValidatedRuleEnvelope
from sciplot_core.readiness.rule_certification import (
    current_certified_rule_contract_snapshot,
)
from sciplot_core.readiness.rule_contract import (
    rule_contract_hashes,
)
from sciplot_core.readiness.status import validated_envelope_status
from sciplot_core.readiness.validation import _canonical_sha256


def _registry_without_rule(
    registry: ValidatedEnvelopeRegistry,
    rule_id: str,
) -> ValidatedEnvelopeRegistry:
    source_acceptance = deepcopy(registry.source_acceptance)
    for field in (
        "ready_rule_count",
        "lifecycle_passed_count",
        "physical_size_passed_count",
        "real_data_lifecycle_passed_count",
    ):
        source_acceptance[field] -= 1
    return replace(
        registry,
        source_acceptance=source_acceptance,
        entries=tuple(entry for entry in registry.entries if entry.rule_id != rule_id),
    )


def _registry_with_replaced_entry(
    registry: ValidatedEnvelopeRegistry,
    replacement: ValidatedRuleEnvelope,
) -> ValidatedEnvelopeRegistry:
    rule_id = replacement.rule_id
    return replace(
        registry,
        entries=tuple(
            replacement if entry.rule_id == rule_id else entry
            for entry in registry.entries
        ),
    )


def test_rule_contract_hashes_builds_one_canonical_payload(
    monkeypatch,
) -> None:
    rule = get_rule("swelling_curve")
    original_payload = rule_contract_module.rule_contract_payload
    expected_payload = original_payload(rule)
    calls: list[str] = []

    def counting_payload(resolved_rule):
        calls.append(resolved_rule.rule_id)
        return original_payload(resolved_rule)

    monkeypatch.setattr(
        rule_contract_module,
        "rule_contract_payload",
        counting_payload,
    )

    hashes = rule_contract_hashes(rule)

    assert calls == [rule.rule_id]
    assert hashes.contract_sha256 == _canonical_sha256(expected_payload)
    assert hashes.semantic_contract_sha256 == _canonical_sha256(
        expected_payload["semantic"]
    )


def test_current_snapshot_uses_one_registry_lookup_and_is_pure(
    monkeypatch,
) -> None:
    rule = get_rule("swelling_curve")
    registry = load_validated_envelope_registry()
    rule_before = deepcopy(rule.to_payload())
    registry_before = registry.to_dict()
    original_entry = ValidatedEnvelopeRegistry.entry
    lookups: list[str] = []

    def counting_entry(self, rule_id):
        lookups.append(rule_id)
        return original_entry(self, rule_id)

    monkeypatch.setattr(ValidatedEnvelopeRegistry, "entry", counting_entry)

    snapshot = current_certified_rule_contract_snapshot(
        rule=rule,
        registry=registry,
    )
    first_payload = snapshot.to_payload()
    first_payload["certification_reasons"].append("caller_mutation")

    assert lookups == [rule.rule_id]
    assert snapshot.certification_status == "current"
    assert snapshot.certification_reasons == ()
    assert snapshot.certified_envelope is not None
    assert snapshot.to_payload() == {
        "rule_id": rule.rule_id,
        "semantic_family": rule.semantic_family,
        "current_rule_contract_sha256": snapshot.current_contract_sha256,
        "current_rule_semantic_contract_sha256": (
            snapshot.current_semantic_contract_sha256
        ),
        "certified_rule_contract_sha256": snapshot.current_contract_sha256,
        "certified_rule_semantic_contract_sha256": (
            snapshot.current_semantic_contract_sha256
        ),
        "certified_semantic_family": rule.semantic_family,
        "certification_status": "current",
        "certification_reasons": [],
    }
    assert rule.to_payload() == rule_before
    assert registry.to_dict() == registry_before


def test_missing_certification_has_one_stable_reason() -> None:
    rule = get_rule("swelling_curve")
    registry = _registry_without_rule(
        load_validated_envelope_registry(),
        rule.rule_id,
    )

    snapshot = current_certified_rule_contract_snapshot(
        rule=rule,
        registry=registry,
    )

    assert snapshot.certification_status == "missing"
    assert snapshot.certification_reasons == ("validated_envelope_missing",)
    assert snapshot.certified_contract_sha256 is None
    assert snapshot.certified_semantic_contract_sha256 is None
    assert snapshot.certified_semantic_family is None
    assert snapshot.certified_envelope is None


def test_recognition_only_drift_reports_full_contract_reason() -> None:
    rule = get_rule("swelling_curve")
    drifted_rule = replace(
        rule,
        keywords=(*rule.keywords, "recognition-only-drift"),
    )

    snapshot = current_certified_rule_contract_snapshot(
        rule=drifted_rule,
        registry=load_validated_envelope_registry(),
    )

    assert snapshot.certification_status == "stale"
    assert snapshot.certification_reasons == (
        "certified_rule_contract_sha256_mismatch",
    )


def test_semantic_drift_reports_full_and_semantic_contract_reasons() -> None:
    rule = get_rule("swelling_curve")
    drifted_rule = replace(
        rule,
        render_options={**rule.render_options, "line_width": 9.25},
    )

    snapshot = current_certified_rule_contract_snapshot(
        rule=drifted_rule,
        registry=load_validated_envelope_registry(),
    )

    assert snapshot.certification_status == "stale"
    assert snapshot.certification_reasons == (
        "certified_rule_contract_sha256_mismatch",
        "certified_rule_semantic_contract_sha256_mismatch",
    )


def test_certified_family_drift_reports_family_reason() -> None:
    rule = get_rule("swelling_curve")
    registry = load_validated_envelope_registry()
    entry = registry.entry(rule.rule_id)
    assert entry is not None
    drifted_registry = _registry_with_replaced_entry(
        registry,
        replace(entry, semantic_family="outdated_family"),
    )

    snapshot = current_certified_rule_contract_snapshot(
        rule=rule,
        registry=drifted_registry,
    )

    assert snapshot.certification_status == "stale"
    assert snapshot.certification_reasons == ("certified_semantic_family_mismatch",)


def test_status_facade_preserves_its_version_one_public_schema() -> None:
    payload = validated_envelope_status()

    assert set(payload) == {
        "kind",
        "version",
        "status",
        "ready_without_ai_rule_count",
        "current_ready_rule_count",
        "missing_rule_ids",
        "stale_rule_ids",
        "extra_rule_ids",
        "source_acceptance",
        "human_daily_use_validation",
        "evidence_strength_counts",
        "records",
        "claims",
        "limitations",
    }
    assert payload["kind"] == "sciplot_validated_envelope_status"
    assert payload["version"] == 1
    assert all(
        set(record)
        == {
            "rule_id",
            "semantic_family",
            "status",
            "current_contract_sha256",
            "certified_contract_sha256",
            "current_semantic_contract_sha256",
            "certified_semantic_contract_sha256",
            "evidence_strength",
            "limitations",
        }
        for record in payload["records"]
    )
