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
)

from sciplot_core.readiness.rule_contract import (
    rule_contract_sha256,
    rule_semantic_contract_sha256,
)

from sciplot_core.readiness.registry_model import (
    ValidatedEnvelopeRegistry,
)

from sciplot_core.readiness.registry_io import (
    load_validated_envelope_registry,
)


def validated_envelope_status(
    registry: ValidatedEnvelopeRegistry | None = None,
    *,
    registry_path: Path | None = None,
) -> dict[str, Any]:
    resolved = registry or load_validated_envelope_registry(registry_path)
    current_rules = tuple(iter_public_rules())
    current_ids = {rule.rule_id for rule in current_rules}
    registered_ids = {entry.rule_id for entry in resolved.entries}
    records: list[dict[str, Any]] = []
    stale_ids: list[str] = []
    missing_ids: list[str] = []
    for rule in current_rules:
        entry = resolved.entry(rule.rule_id)
        current_hash = rule_contract_sha256(rule)
        current_semantic_hash = rule_semantic_contract_sha256(rule)
        if entry is None:
            status = "missing"
            certified_hash = None
            certified_semantic_hash = None
            evidence_strength = None
            limitations: list[str] = []
            missing_ids.append(rule.rule_id)
        else:
            certified_hash = entry.contract_sha256
            certified_semantic_hash = entry.semantic_contract_sha256
            status = (
                "current"
                if (
                    certified_hash == current_hash
                    and certified_semantic_hash == current_semantic_hash
                    and entry.semantic_family == rule.semantic_family
                )
                else "stale"
            )
            evidence_strength = entry.evidence_strength
            limitations = list(entry.limitations)
            if status == "stale":
                stale_ids.append(rule.rule_id)
        records.append(
            {
                "rule_id": rule.rule_id,
                "semantic_family": rule.semantic_family,
                "status": status,
                "current_contract_sha256": current_hash,
                "certified_contract_sha256": certified_hash,
                "current_semantic_contract_sha256": current_semantic_hash,
                "certified_semantic_contract_sha256": certified_semantic_hash,
                "evidence_strength": evidence_strength,
                "limitations": limitations,
            }
        )
    extra_ids = sorted(registered_ids - current_ids)
    ready = not stale_ids and not missing_ids and not extra_ids
    return {
        "kind": "sciplot_validated_envelope_status",
        "version": 1,
        "status": "ready" if ready else NEEDS_RULE_REPAIR,
        "ready_without_ai_rule_count": sum(
            record["status"] == "current" for record in records
        ),
        "current_ready_rule_count": len(current_rules),
        "missing_rule_ids": missing_ids,
        "stale_rule_ids": stale_ids,
        "extra_rule_ids": extra_ids,
        "source_acceptance": deepcopy(resolved.source_acceptance),
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
            "human_daily_use_cutover_established": False,
            "human_daily_use_validation_established": False,
        },
        "limitations": list(resolved.limitations),
    }
