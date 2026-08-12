"""Resolve one current rule against its validated-envelope certification."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal

from sciplot_core.materials_rules.models import SemanticRule
from sciplot_core.readiness.envelope_model import ValidatedRuleEnvelope
from sciplot_core.readiness.registry_model import ValidatedEnvelopeRegistry
from sciplot_core.readiness.rule_contract import rule_contract_hashes


RuleCertificationStatus = Literal["current", "missing", "stale"]


@dataclass(frozen=True)
class CurrentCertifiedRuleContractSnapshot:
    """Current rule hashes and the selected registry entry in one pure snapshot."""

    rule_id: str
    semantic_family: str
    current_contract_sha256: str
    current_semantic_contract_sha256: str
    certified_contract_sha256: str | None
    certified_semantic_contract_sha256: str | None
    certified_semantic_family: str | None
    certification_status: RuleCertificationStatus
    certification_reasons: tuple[str, ...]
    certified_envelope: ValidatedRuleEnvelope | None = field(
        repr=False,
        compare=False,
    )

    def to_payload(self) -> dict[str, Any]:
        return {
            "rule_id": self.rule_id,
            "semantic_family": self.semantic_family,
            "current_rule_contract_sha256": self.current_contract_sha256,
            "current_rule_semantic_contract_sha256": (
                self.current_semantic_contract_sha256
            ),
            "certified_rule_contract_sha256": self.certified_contract_sha256,
            "certified_rule_semantic_contract_sha256": (
                self.certified_semantic_contract_sha256
            ),
            "certified_semantic_family": self.certified_semantic_family,
            "certification_status": self.certification_status,
            "certification_reasons": list(self.certification_reasons),
        }


def current_certified_rule_contract_snapshot(
    *,
    rule: SemanticRule,
    registry: ValidatedEnvelopeRegistry,
) -> CurrentCertifiedRuleContractSnapshot:
    """Compare one already-resolved rule with one registry lookup."""

    hashes = rule_contract_hashes(rule)
    entry = registry.entry(rule.rule_id)
    if entry is None:
        return CurrentCertifiedRuleContractSnapshot(
            rule_id=rule.rule_id,
            semantic_family=rule.semantic_family,
            current_contract_sha256=hashes.contract_sha256,
            current_semantic_contract_sha256=hashes.semantic_contract_sha256,
            certified_contract_sha256=None,
            certified_semantic_contract_sha256=None,
            certified_semantic_family=None,
            certification_status="missing",
            certification_reasons=("validated_envelope_missing",),
            certified_envelope=None,
        )

    reasons: list[str] = []
    if entry.contract_sha256 != hashes.contract_sha256:
        reasons.append("certified_rule_contract_sha256_mismatch")
    if entry.semantic_contract_sha256 != hashes.semantic_contract_sha256:
        reasons.append("certified_rule_semantic_contract_sha256_mismatch")
    if entry.semantic_family != rule.semantic_family:
        reasons.append("certified_semantic_family_mismatch")
    return CurrentCertifiedRuleContractSnapshot(
        rule_id=rule.rule_id,
        semantic_family=rule.semantic_family,
        current_contract_sha256=hashes.contract_sha256,
        current_semantic_contract_sha256=hashes.semantic_contract_sha256,
        certified_contract_sha256=entry.contract_sha256,
        certified_semantic_contract_sha256=entry.semantic_contract_sha256,
        certified_semantic_family=entry.semantic_family,
        certification_status="stale" if reasons else "current",
        certification_reasons=tuple(reasons),
        certified_envelope=entry,
    )


def current_rule_invocation_contract_payload(
    *,
    rule: SemanticRule,
    registry: ValidatedEnvelopeRegistry,
) -> dict[str, Any]:
    """Project current certification onto the existing invocation contract.

    The caller supplies an already-loaded registry.  This keeps the projection
    independent from source discovery and preserves ``SemanticRule.to_payload``
    as the static input to rule-contract hashing.
    """

    snapshot = current_certified_rule_contract_snapshot(
        rule=rule,
        registry=registry,
    )
    payload = rule.invocation_contract_payload()
    payload["availability"] = (
        "ready"
        if snapshot.certification_status == "current"
        else "needs_rule_repair"
    )
    payload["reason_codes"] = list(snapshot.certification_reasons)
    return payload


__all__ = [
    "CurrentCertifiedRuleContractSnapshot",
    "RuleCertificationStatus",
    "current_certified_rule_contract_snapshot",
    "current_rule_invocation_contract_payload",
]
