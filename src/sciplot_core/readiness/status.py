"""Report registry status against current rule contracts."""

from __future__ import annotations

from copy import deepcopy
from pathlib import Path
from typing import Any
from sciplot_core.materials_rules import (
    iter_public_rules,
)

from sciplot_core.readiness.constants import (
    NEEDS_RULE_REPAIR,
    EVIDENCE_STRENGTHS,
    VALIDATED_ENVELOPE_ACCEPTANCE_LINEAGE_KIND,
    VALIDATED_ENVELOPE_ACCEPTANCE_LINEAGE_VERSION,
)

from sciplot_core.readiness.rule_certification import (
    current_certified_rule_contract_snapshot,
)
from sciplot_core.readiness.registry_model import (
    ValidatedEnvelopeRegistry,
)

from sciplot_core.readiness.registry_io import (
    load_validated_envelope_registry,
)

from sciplot_core.readiness.human_validation import (
    load_human_daily_use_validation,
)


def validated_envelope_status(
    registry: ValidatedEnvelopeRegistry | None = None,
    *,
    registry_path: Path | None = None,
) -> dict[str, Any]:
    resolved = registry or load_validated_envelope_registry(registry_path)
    human_validation = load_human_daily_use_validation()
    current_rules = tuple(iter_public_rules())
    current_ids = {rule.rule_id for rule in current_rules}
    registered_ids = {entry.rule_id for entry in resolved.entries}
    records: list[dict[str, Any]] = []
    stale_ids: list[str] = []
    missing_ids: list[str] = []
    for rule in current_rules:
        snapshot = current_certified_rule_contract_snapshot(
            rule=rule,
            registry=resolved,
        )
        entry = snapshot.certified_envelope
        current_hash = snapshot.current_contract_sha256
        current_semantic_hash = snapshot.current_semantic_contract_sha256
        if entry is None:
            evidence_strength = None
            limitations: list[str] = []
            missing_ids.append(rule.rule_id)
        else:
            evidence_strength = entry.evidence_strength
            limitations = list(entry.limitations)
            if snapshot.certification_status == "stale":
                stale_ids.append(rule.rule_id)
        records.append(
            {
                "rule_id": rule.rule_id,
                "semantic_family": rule.semantic_family,
                "status": snapshot.certification_status,
                "current_contract_sha256": current_hash,
                "certified_contract_sha256": snapshot.certified_contract_sha256,
                "current_semantic_contract_sha256": current_semantic_hash,
                "certified_semantic_contract_sha256": (
                    snapshot.certified_semantic_contract_sha256
                ),
                "evidence_strength": evidence_strength,
                "limitations": limitations,
            }
        )
    extra_ids = sorted(registered_ids - current_ids)
    ready = not stale_ids and not missing_ids and not extra_ids
    return {
        "kind": "sciplot_validated_envelope_status",
        "version": 2,
        "status": "ready" if ready else NEEDS_RULE_REPAIR,
        "ready_without_ai_rule_count": sum(
            record["status"] == "current" for record in records
        ),
        "current_ready_rule_count": len(current_rules),
        "missing_rule_ids": missing_ids,
        "stale_rule_ids": stale_ids,
        "extra_rule_ids": extra_ids,
        "source_acceptance": {
            "kind": VALIDATED_ENVELOPE_ACCEPTANCE_LINEAGE_KIND,
            "version": VALIDATED_ENVELOPE_ACCEPTANCE_LINEAGE_VERSION,
            "records": list(resolved.acceptance_lineage_records()),
        },
        "human_daily_use_validation": deepcopy(human_validation),
        "evidence_strength_counts": {
            strength: sum(record["evidence_strength"] == strength for record in records)
            for strength in sorted(EVIDENCE_STRENGTHS)
        },
        "records": records,
        "claims": {
            "current_rule_contracts_match_acceptance": ready,
            "real_data_lifecycle_certified": ready
            and len(resolved.entries) == len(current_rules)
            and all(entry.real_data_evidence for entry in resolved.entries),
            "journal_compliance_established": False,
            "human_daily_use_cutover_established": (
                human_validation["status"] == "passed"
            ),
            "human_daily_use_validation_established": (
                human_validation["status"] == "passed"
            ),
        },
        "limitations": list(resolved.limitations),
    }
