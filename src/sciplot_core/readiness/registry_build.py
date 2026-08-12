"""Build validated-envelope registries from acceptance evidence."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from sciplot_core.foundation.file_hashing import file_sha256
from sciplot_core.materials_rules import SemanticRule, iter_public_rules
from sciplot_core.readiness.constants import (
    AUTHORIZATION_READY,
    FIXTURE_HASH_ACCEPTED,
    READY_RULE_ACCEPTANCE_VERSION,
    REQUIRED_ACCEPTANCE_CHECKS,
    VALIDATED_ENVELOPE_ACCEPTANCE_LINEAGE_KIND,
    VALIDATED_ENVELOPE_ACCEPTANCE_LINEAGE_VERSION,
)
from sciplot_core.readiness.envelope_model import ValidatedRuleEnvelope
from sciplot_core.readiness.evidence import (
    _evidence_limitations,
    _evidence_strength,
    _resolved_manifest_path,
)
from sciplot_core.readiness.registry_model import ValidatedEnvelopeRegistry
from sciplot_core.readiness.rule_contract import (
    rule_contract_hashes,
    semantic_contract_sha256,
)
from sciplot_core.readiness.validation import (
    _now,
    _required_hash,
    _required_int,
    _required_text,
    _timestamp,
)


def _load_acceptance_summary(
    acceptance_summary_path: Path,
) -> tuple[Path, dict[str, Any], int, str]:
    summary_path = acceptance_summary_path.expanduser().resolve()
    if not summary_path.is_file():
        raise FileNotFoundError(
            f"Ready-rule acceptance summary not found: {summary_path}"
        )
    try:
        payload = json.loads(summary_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise ValueError("Ready-rule acceptance summary is not valid JSON.") from exc
    if not isinstance(payload, dict):
        raise ValueError("Ready-rule acceptance summary must contain an object.")
    if payload.get("kind") != "sciplot_ready_rule_acceptance":
        raise ValueError("Not a SciPlot ready-rule acceptance summary.")
    version = _required_int(payload.get("version"), "acceptance version", minimum=1)
    if version != READY_RULE_ACCEPTANCE_VERSION:
        raise ValueError(
            f"Unsupported acceptance version {version}; "
            f"expected {READY_RULE_ACCEPTANCE_VERSION}."
        )
    generated_at = _timestamp(payload.get("generated_at"), "acceptance generated_at")
    return summary_path, payload, version, generated_at


def _acceptance_rows(payload: dict[str, Any]) -> dict[str, dict[str, Any]]:
    matrix = payload.get("matrix")
    if not isinstance(matrix, list):
        raise ValueError("Acceptance matrix must be a list.")
    rows: dict[str, dict[str, Any]] = {}
    for row in matrix:
        if not isinstance(row, dict):
            raise ValueError("Acceptance matrix rows must be objects.")
        rule_id = _required_text(row.get("rule_id"), "acceptance rule_id")
        if rule_id in rows:
            raise ValueError(f"Duplicate acceptance row `{rule_id}`.")
        rows[rule_id] = row
    return rows


def _validate_visual_review(payload: dict[str, Any]) -> None:
    visual = payload.get("visual_review")
    if not isinstance(visual, dict):
        raise ValueError("Acceptance visual_review must be an object.")
    if visual.get("automated_status") != "passed":
        raise ValueError("Acceptance automated physical-artifact review did not pass.")
    if visual.get("manual_visual_status") != "passed":
        raise ValueError("Acceptance manual preview review was not approved.")


def _acceptance_limitations(payload: dict[str, Any]) -> tuple[str, ...]:
    return tuple(
        _required_text(value, "acceptance limitation", maximum=4096)
        for value in payload.get("limitations", [])
        if isinstance(value, str) and value.strip()
    )


def _acceptance_lineage_record(
    *,
    version: int,
    generated_at: str,
    summary_sha256: str,
    rule_ids: list[str] | tuple[str, ...],
    limitations: tuple[str, ...],
) -> dict[str, Any]:
    return {
        "kind": "sciplot_ready_rule_acceptance",
        "version": version,
        "generated_at": generated_at,
        "summary_sha256": summary_sha256,
        "rule_ids": list(rule_ids),
        "limitations": list(limitations),
    }


def _validated_entry_from_row(
    *,
    rule: SemanticRule,
    row: dict[str, Any],
    summary_path: Path,
    acceptance_generated_at: str,
) -> ValidatedRuleEnvelope:
    if row.get("semantic_family") != rule.semantic_family:
        raise ValueError(f"Acceptance semantic family drifted for `{rule.rule_id}`.")
    if row.get("template") != rule.template or row.get("recipe") != rule.recipe:
        raise ValueError(f"Acceptance render route drifted for `{rule.rule_id}`.")
    if row.get("rule_readiness") != "ready":
        raise ValueError(f"Acceptance rule `{rule.rule_id}` is not ready.")
    if row.get("lifecycle_status") != "passed":
        raise ValueError(f"Acceptance lifecycle failed for `{rule.rule_id}`.")
    checks = row.get("checks")
    if not isinstance(checks, dict):
        raise ValueError(f"Acceptance checks missing for `{rule.rule_id}`.")
    accepted_check_ids = tuple(
        sorted(str(check_id) for check_id, passed in checks.items() if passed is True)
    )
    if not REQUIRED_ACCEPTANCE_CHECKS.issubset(accepted_check_ids):
        missing = sorted(REQUIRED_ACCEPTANCE_CHECKS - set(accepted_check_ids))
        raise ValueError(
            f"Acceptance checks failed for `{rule.rule_id}`: {', '.join(missing)}"
        )
    if checks.get("validated_rule_contract_current") is not True:
        raise ValueError(
            f"Acceptance rule contract was not current for `{rule.rule_id}`."
        )
    artifact_review = row.get("artifact_review")
    if not isinstance(artifact_review, dict) or artifact_review.get("status") != "passed":
        raise ValueError(
            f"Acceptance physical-size review failed for `{rule.rule_id}`."
        )
    evidence = row.get("evidence")
    if not isinstance(evidence, dict):
        raise ValueError(f"Acceptance evidence missing for `{rule.rule_id}`.")
    if evidence.get("real_data_evidence") is not True:
        raise ValueError(f"Acceptance evidence for `{rule.rule_id}` is not real data.")
    authorization = str(evidence.get("authorization_status") or "")
    if authorization not in AUTHORIZATION_READY:
        raise ValueError(
            f"Acceptance authorization is insufficient for `{rule.rule_id}`."
        )
    fixture_hash_status = str(evidence.get("fixture_hash_status") or "")
    if fixture_hash_status not in FIXTURE_HASH_ACCEPTED:
        raise ValueError(f"Acceptance fixture hash is insufficient for `{rule.rule_id}`.")

    manifest_path = _resolved_manifest_path(
        row.get("manifest"), acceptance_root=summary_path.parent
    )
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest_semantic = manifest.get("semantic") if isinstance(manifest, dict) else None
    if not isinstance(manifest_semantic, dict):
        raise ValueError(f"Acceptance manifest semantic is missing for `{rule.rule_id}`.")
    accepted_semantic_contract = semantic_contract_sha256(manifest_semantic)
    current_hashes = rule_contract_hashes(rule)
    if accepted_semantic_contract != current_hashes.semantic_contract_sha256:
        raise ValueError(f"Accepted semantic contract drifted for `{rule.rule_id}`.")
    if row.get("rule_contract_sha256") != current_hashes.contract_sha256:
        raise ValueError(f"Acceptance rule contract drifted for `{rule.rule_id}`.")
    if row.get("accepted_rule_contract_sha256") != current_hashes.contract_sha256:
        raise ValueError(f"Accepted full rule contract drifted for `{rule.rule_id}`.")
    if row.get("semantic_contract_sha256") != current_hashes.semantic_contract_sha256:
        raise ValueError(f"Acceptance semantic contract drifted for `{rule.rule_id}`.")
    if row.get("accepted_semantic_contract_sha256") != accepted_semantic_contract:
        raise ValueError(
            f"Accepted manifest semantic hash was not preserved for `{rule.rule_id}`."
        )

    return ValidatedRuleEnvelope(
        rule_id=rule.rule_id,
        semantic_family=rule.semantic_family,
        contract_sha256=current_hashes.contract_sha256,
        semantic_contract_sha256=current_hashes.semantic_contract_sha256,
        accepted_manifest_sha256=file_sha256(manifest_path),
        acceptance_generated_at=acceptance_generated_at,
        evidence_tier=_required_text(evidence.get("tier"), f"{rule.rule_id} evidence tier"),
        evidence_strength=_evidence_strength(evidence),
        real_data_evidence=True,
        authorization_status=authorization,
        fixture_hash_status=fixture_hash_status,
        fixture_tree_sha256=_required_hash(
            evidence.get("fixture_tree_sha256"), f"{rule.rule_id} fixture tree hash"
        ),
        source_hash_status=_required_text(
            evidence.get("source_hash_status"), f"{rule.rule_id} source hash status"
        ),
        registered_source_hash_count=_required_int(
            evidence.get("registered_source_hash_count"),
            f"{rule.rule_id} registered source hash count",
        ),
        unit_status=_required_text(
            evidence.get("unit_status"), f"{rule.rule_id} unit status"
        ),
        lifecycle_status="passed",
        physical_size_status="passed",
        accepted_check_ids=accepted_check_ids,
        limitations=_evidence_limitations(evidence),
    )


def build_validated_envelope_registry(
    acceptance_summary_path: Path,
) -> ValidatedEnvelopeRegistry:
    summary_path, payload, version, generated_at = _load_acceptance_summary(
        acceptance_summary_path
    )
    if payload.get("state") != "ready":
        raise ValueError("Acceptance summary must have state=ready.")
    rules = tuple(iter_public_rules())
    rule_by_id = {rule.rule_id: rule for rule in rules}
    expected_count = len(rules)
    coverage = payload.get("coverage")
    if not isinstance(coverage, dict):
        raise ValueError("Acceptance coverage must be an object.")
    for key in (
        "ready_rule_count",
        "lifecycle_passed_count",
        "physical_size_passed_count",
        "real_data_lifecycle_passed_count",
    ):
        if coverage.get(key) != expected_count:
            raise ValueError(f"Acceptance coverage `{key}` must equal {expected_count}.")
    if coverage.get("lifecycle_complete") is not True:
        raise ValueError("Acceptance lifecycle coverage is incomplete.")
    if coverage.get("physical_size_complete") is not True:
        raise ValueError("Acceptance physical-size coverage is incomplete.")
    if coverage.get("instrument_shaped_gap_count") != 0:
        raise ValueError("Acceptance still contains instrument-shaped evidence gaps.")
    _validate_visual_review(payload)
    selected = payload.get("selected_rule_ids")
    if not isinstance(selected, list) or set(map(str, selected)) != set(rule_by_id):
        raise ValueError("Acceptance summary must select every current ready rule.")
    rows = _acceptance_rows(payload)
    if set(rows) != set(rule_by_id):
        raise ValueError("Acceptance matrix does not match current ready rules.")
    entries = tuple(
        _validated_entry_from_row(
            rule=rule,
            row=rows[rule.rule_id],
            summary_path=summary_path,
            acceptance_generated_at=generated_at,
        )
        for rule in rules
    )
    limitations = _acceptance_limitations(payload)
    record = _acceptance_lineage_record(
        version=version,
        generated_at=generated_at,
        summary_sha256=file_sha256(summary_path),
        rule_ids=[rule.rule_id for rule in rules],
        limitations=limitations,
    )
    return ValidatedEnvelopeRegistry(
        generated_at=_now(),
        source_acceptance={
            "kind": VALIDATED_ENVELOPE_ACCEPTANCE_LINEAGE_KIND,
            "version": VALIDATED_ENVELOPE_ACCEPTANCE_LINEAGE_VERSION,
            "records": [record],
        },
        entries=entries,
        limitations=(
            "A validated envelope proves the accepted deterministic rule/render contract and real-data lifecycle, not blanket journal compliance.",
            "Runtime input recognition, mapping, QA, exact-current export, and delivery must still pass for every new input.",
            "Automated acceptance and source certificates do not count as human Veusz-first daily-use validation.",
        ),
    )
