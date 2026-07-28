"""Represent one validated rule envelope."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from sciplot_core.readiness.constants import (
    AUTHORIZATION_READY,
    FIXTURE_HASH_ACCEPTED,
    EVIDENCE_STRENGTHS,
    REQUIRED_ACCEPTANCE_CHECKS,
)

from sciplot_core.readiness.validation import (
    _required_text,
    _required_bool,
    _required_int,
    _required_hash,
    _timestamp,
    _closed_object,
    _text_list,
)


@dataclass(frozen=True)
class ValidatedRuleEnvelope:
    rule_id: str
    semantic_family: str
    contract_sha256: str
    semantic_contract_sha256: str
    accepted_manifest_sha256: str
    acceptance_generated_at: str
    evidence_tier: str
    evidence_strength: str
    real_data_evidence: bool
    authorization_status: str
    fixture_hash_status: str
    fixture_tree_sha256: str
    source_hash_status: str
    registered_source_hash_count: int
    unit_status: str
    lifecycle_status: str
    physical_size_status: str
    accepted_check_ids: tuple[str, ...]
    limitations: tuple[str, ...]

    def __post_init__(self) -> None:
        object.__setattr__(self, "rule_id", _required_text(self.rule_id, "rule_id"))
        object.__setattr__(
            self,
            "semantic_family",
            _required_text(self.semantic_family, "semantic_family"),
        )
        object.__setattr__(
            self,
            "contract_sha256",
            _required_hash(self.contract_sha256, "contract_sha256"),
        )
        object.__setattr__(
            self,
            "semantic_contract_sha256",
            _required_hash(
                self.semantic_contract_sha256,
                "semantic_contract_sha256",
            ),
        )
        object.__setattr__(
            self,
            "accepted_manifest_sha256",
            _required_hash(
                self.accepted_manifest_sha256,
                "accepted_manifest_sha256",
            ),
        )
        object.__setattr__(
            self,
            "acceptance_generated_at",
            _timestamp(self.acceptance_generated_at, "acceptance_generated_at"),
        )
        object.__setattr__(
            self,
            "evidence_tier",
            _required_text(self.evidence_tier, "evidence_tier"),
        )
        strength = _required_text(self.evidence_strength, "evidence_strength")
        if strength not in EVIDENCE_STRENGTHS:
            raise ValueError(f"Unsupported evidence_strength `{strength}`.")
        object.__setattr__(self, "evidence_strength", strength)
        real_data_evidence = _required_bool(
            self.real_data_evidence,
            "real_data_evidence",
        )
        if not real_data_evidence:
            raise ValueError("Validated envelopes require real_data_evidence=true.")
        object.__setattr__(self, "real_data_evidence", real_data_evidence)
        authorization = _required_text(
            self.authorization_status,
            "authorization_status",
        )
        if authorization not in AUTHORIZATION_READY:
            raise ValueError(
                f"Envelope authorization_status is not accepted: `{authorization}`."
            )
        object.__setattr__(self, "authorization_status", authorization)
        fixture_status = _required_text(
            self.fixture_hash_status,
            "fixture_hash_status",
        )
        if fixture_status not in FIXTURE_HASH_ACCEPTED:
            raise ValueError(
                f"Envelope fixture_hash_status is not accepted: `{fixture_status}`."
            )
        object.__setattr__(self, "fixture_hash_status", fixture_status)
        object.__setattr__(
            self,
            "fixture_tree_sha256",
            _required_hash(self.fixture_tree_sha256, "fixture_tree_sha256"),
        )
        object.__setattr__(
            self,
            "source_hash_status",
            _required_text(self.source_hash_status, "source_hash_status"),
        )
        object.__setattr__(
            self,
            "registered_source_hash_count",
            _required_int(
                self.registered_source_hash_count,
                "registered_source_hash_count",
            ),
        )
        object.__setattr__(
            self,
            "unit_status",
            _required_text(self.unit_status, "unit_status"),
        )
        if self.lifecycle_status != "passed":
            raise ValueError("Validated envelopes require lifecycle_status=passed.")
        if self.physical_size_status != "passed":
            raise ValueError("Validated envelopes require physical_size_status=passed.")
        accepted_checks = tuple(
            _required_text(value, "accepted_check_id")
            for value in self.accepted_check_ids
        )
        if len(set(accepted_checks)) != len(accepted_checks):
            raise ValueError("accepted_check_ids must be unique.")
        if not REQUIRED_ACCEPTANCE_CHECKS.issubset(accepted_checks):
            missing = sorted(REQUIRED_ACCEPTANCE_CHECKS - set(accepted_checks))
            raise ValueError(
                "Validated envelope is missing acceptance checks: " + ", ".join(missing)
            )
        object.__setattr__(self, "accepted_check_ids", accepted_checks)
        object.__setattr__(
            self,
            "limitations",
            tuple(
                _required_text(value, "limitation", maximum=4096)
                for value in self.limitations
            ),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "rule_id": self.rule_id,
            "semantic_family": self.semantic_family,
            "contract_sha256": self.contract_sha256,
            "semantic_contract_sha256": self.semantic_contract_sha256,
            "accepted_manifest_sha256": self.accepted_manifest_sha256,
            "acceptance_generated_at": self.acceptance_generated_at,
            "evidence_tier": self.evidence_tier,
            "evidence_strength": self.evidence_strength,
            "real_data_evidence": self.real_data_evidence,
            "authorization_status": self.authorization_status,
            "fixture_hash_status": self.fixture_hash_status,
            "fixture_tree_sha256": self.fixture_tree_sha256,
            "source_hash_status": self.source_hash_status,
            "registered_source_hash_count": self.registered_source_hash_count,
            "unit_status": self.unit_status,
            "lifecycle_status": self.lifecycle_status,
            "physical_size_status": self.physical_size_status,
            "accepted_check_ids": list(self.accepted_check_ids),
            "limitations": list(self.limitations),
        }

    @classmethod
    def from_dict(cls, payload: object) -> ValidatedRuleEnvelope:
        parsed = _closed_object(
            payload,
            label="validated rule envelope",
            expected=frozenset(
                {
                    "rule_id",
                    "semantic_family",
                    "contract_sha256",
                    "semantic_contract_sha256",
                    "accepted_manifest_sha256",
                    "acceptance_generated_at",
                    "evidence_tier",
                    "evidence_strength",
                    "real_data_evidence",
                    "authorization_status",
                    "fixture_hash_status",
                    "fixture_tree_sha256",
                    "source_hash_status",
                    "registered_source_hash_count",
                    "unit_status",
                    "lifecycle_status",
                    "physical_size_status",
                    "accepted_check_ids",
                    "limitations",
                }
            ),
        )
        return cls(
            rule_id=parsed["rule_id"],
            semantic_family=parsed["semantic_family"],
            contract_sha256=parsed["contract_sha256"],
            semantic_contract_sha256=parsed["semantic_contract_sha256"],
            accepted_manifest_sha256=parsed["accepted_manifest_sha256"],
            acceptance_generated_at=parsed["acceptance_generated_at"],
            evidence_tier=parsed["evidence_tier"],
            evidence_strength=parsed["evidence_strength"],
            real_data_evidence=parsed["real_data_evidence"],
            authorization_status=parsed["authorization_status"],
            fixture_hash_status=parsed["fixture_hash_status"],
            fixture_tree_sha256=parsed["fixture_tree_sha256"],
            source_hash_status=parsed["source_hash_status"],
            registered_source_hash_count=parsed["registered_source_hash_count"],
            unit_status=parsed["unit_status"],
            lifecycle_status=parsed["lifecycle_status"],
            physical_size_status=parsed["physical_size_status"],
            accepted_check_ids=_text_list(
                parsed["accepted_check_ids"],
                "accepted_check_ids",
            ),
            limitations=_text_list(
                parsed["limitations"],
                "limitations",
                maximum_items=32,
                maximum_text=4096,
            ),
        )
