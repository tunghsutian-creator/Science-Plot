"""Persist and validate prepare-time Studio rule-contract evidence."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any, Literal, cast

from sciplot_core.materials_rules.models import SemanticRule
from sciplot_core.readiness.registry_model import ValidatedEnvelopeRegistry
from sciplot_core.readiness.rule_certification import (
    CurrentCertifiedRuleContractSnapshot,
)
from sciplot_core.readiness.validation import (
    _closed_object,
    _required_hash,
    _required_int,
    _required_text,
)


STUDIO_RULE_CONTRACT_BINDING_KEY = "studio_rule_contract_binding"
_BINDING_KIND = "sciplot_studio_rule_contract_binding"
_BINDING_VERSION = 1
_BINDING_FIELDS = frozenset(
    {
        "kind",
        "version",
        "rule_id",
        "prepared_rule_contract_sha256",
        "prepared_rule_semantic_contract_sha256",
        "certification_status",
        "certified_rule_contract_sha256",
        "certified_rule_semantic_contract_sha256",
        "certification_reasons",
    }
)
_CERTIFICATION_REASONS = frozenset(
    {
        "validated_envelope_missing",
        "certified_rule_contract_sha256_mismatch",
        "certified_rule_semantic_contract_sha256_mismatch",
        "certified_semantic_family_mismatch",
    }
)
RuleContractBindingStatus = Literal["current", "missing", "stale"]


@dataclass(frozen=True)
class StudioRuleContractBinding:
    """Strict request-level evidence captured by successful preparation."""

    rule_id: str
    prepared_rule_contract_sha256: str
    prepared_rule_semantic_contract_sha256: str
    certification_status: RuleContractBindingStatus
    certified_rule_contract_sha256: str | None
    certified_rule_semantic_contract_sha256: str | None
    certification_reasons: tuple[str, ...]

    @classmethod
    def from_payload(cls, payload: object) -> StudioRuleContractBinding:
        try:
            parsed = _closed_object(
                payload,
                label="Studio rule-contract binding",
                expected=_BINDING_FIELDS,
            )
            kind = _required_text(
                parsed["kind"],
                "Studio rule-contract binding kind",
            )
            if kind != _BINDING_KIND:
                raise ValueError("kind is not supported")
            version = _required_int(
                parsed["version"],
                "Studio rule-contract binding version",
                minimum=1,
            )
            if version != _BINDING_VERSION:
                raise ValueError(f"version {version} is not supported")
            rule_id = _required_text(
                parsed["rule_id"],
                "Studio rule-contract binding rule_id",
            )
            prepared_hash = _strict_hash(
                parsed["prepared_rule_contract_sha256"],
                "Studio rule-contract binding prepared_rule_contract_sha256",
            )
            prepared_semantic_hash = _strict_hash(
                parsed["prepared_rule_semantic_contract_sha256"],
                "Studio rule-contract binding prepared_rule_semantic_contract_sha256",
            )
            status_value = _required_text(
                parsed["certification_status"],
                "Studio rule-contract binding certification_status",
            )
            if status_value not in {"current", "missing", "stale"}:
                raise ValueError(
                    f"certification_status `{status_value}` is not supported"
                )
            status = cast(RuleContractBindingStatus, status_value)
            certified_hash = _optional_hash(
                parsed["certified_rule_contract_sha256"],
                label=("Studio rule-contract binding certified_rule_contract_sha256"),
            )
            certified_semantic_hash = _optional_hash(
                parsed["certified_rule_semantic_contract_sha256"],
                label=(
                    "Studio rule-contract binding "
                    "certified_rule_semantic_contract_sha256"
                ),
            )
            reasons_value = parsed["certification_reasons"]
            if not isinstance(reasons_value, list):
                raise ValueError("certification_reasons must be a list")
            reasons = tuple(
                _required_text(
                    reason,
                    "Studio rule-contract binding certification reason",
                )
                for reason in reasons_value
            )
            if len(set(reasons)) != len(reasons):
                raise ValueError("certification_reasons must be unique")
            unsupported = set(reasons) - _CERTIFICATION_REASONS
            if unsupported:
                raise ValueError(
                    "unsupported certification reason: "
                    + ", ".join(sorted(unsupported))
                )
            _validate_status_relationships(
                status=status,
                prepared_hash=prepared_hash,
                prepared_semantic_hash=prepared_semantic_hash,
                certified_hash=certified_hash,
                certified_semantic_hash=certified_semantic_hash,
                reasons=reasons,
            )
        except (KeyError, TypeError, ValueError) as exc:
            raise ValueError(f"Invalid Studio rule-contract binding: {exc}") from exc
        return cls(
            rule_id=rule_id,
            prepared_rule_contract_sha256=prepared_hash,
            prepared_rule_semantic_contract_sha256=prepared_semantic_hash,
            certification_status=status,
            certified_rule_contract_sha256=certified_hash,
            certified_rule_semantic_contract_sha256=certified_semantic_hash,
            certification_reasons=reasons,
        )

    @classmethod
    def from_snapshot(
        cls,
        snapshot: CurrentCertifiedRuleContractSnapshot,
    ) -> StudioRuleContractBinding:
        return cls.from_payload(
            {
                "kind": _BINDING_KIND,
                "version": _BINDING_VERSION,
                "rule_id": snapshot.rule_id,
                "prepared_rule_contract_sha256": (snapshot.current_contract_sha256),
                "prepared_rule_semantic_contract_sha256": (
                    snapshot.current_semantic_contract_sha256
                ),
                "certification_status": snapshot.certification_status,
                "certified_rule_contract_sha256": (snapshot.certified_contract_sha256),
                "certified_rule_semantic_contract_sha256": (
                    snapshot.certified_semantic_contract_sha256
                ),
                "certification_reasons": list(snapshot.certification_reasons),
            }
        )

    def matches_current_snapshot(
        self,
        snapshot: CurrentCertifiedRuleContractSnapshot,
    ) -> bool:
        return (
            self.rule_id == snapshot.rule_id
            and self.prepared_rule_contract_sha256 == snapshot.current_contract_sha256
            and self.prepared_rule_semantic_contract_sha256
            == snapshot.current_semantic_contract_sha256
            and self.certification_status == snapshot.certification_status
            and self.certified_rule_contract_sha256
            == snapshot.certified_contract_sha256
            and self.certified_rule_semantic_contract_sha256
            == snapshot.certified_semantic_contract_sha256
            and self.certification_reasons == snapshot.certification_reasons
        )

    def to_payload(self) -> dict[str, Any]:
        return {
            "kind": _BINDING_KIND,
            "version": _BINDING_VERSION,
            "rule_id": self.rule_id,
            "prepared_rule_contract_sha256": (self.prepared_rule_contract_sha256),
            "prepared_rule_semantic_contract_sha256": (
                self.prepared_rule_semantic_contract_sha256
            ),
            "certification_status": self.certification_status,
            "certified_rule_contract_sha256": (self.certified_rule_contract_sha256),
            "certified_rule_semantic_contract_sha256": (
                self.certified_rule_semantic_contract_sha256
            ),
            "certification_reasons": list(self.certification_reasons),
        }


def current_studio_rule_contract_binding(
    rule: SemanticRule | None,
    *,
    registry: ValidatedEnvelopeRegistry,
    snapshot_factory: Callable[..., CurrentCertifiedRuleContractSnapshot],
) -> StudioRuleContractBinding | None:
    """Capture current prepare-time rule evidence from the authority registry."""

    if rule is None:
        return None
    return StudioRuleContractBinding.from_snapshot(
        snapshot_factory(
            rule=rule,
            registry=registry,
        )
    )


def _optional_hash(value: object, *, label: str) -> str | None:
    return None if value is None else _strict_hash(value, label)


def _strict_hash(value: object, label: str) -> str:
    digest = _required_hash(value, label)
    if value != digest:
        raise ValueError(f"{label} must be a lowercase SHA-256 digest.")
    return digest


def _validate_status_relationships(
    *,
    status: RuleContractBindingStatus,
    prepared_hash: str,
    prepared_semantic_hash: str,
    certified_hash: str | None,
    certified_semantic_hash: str | None,
    reasons: tuple[str, ...],
) -> None:
    if status == "current":
        if certified_hash != prepared_hash:
            raise ValueError(
                "current certification must match the prepared rule contract"
            )
        if certified_semantic_hash != prepared_semantic_hash:
            raise ValueError(
                "current certification must match the prepared semantic contract"
            )
        if reasons:
            raise ValueError("current certification cannot carry mismatch reasons")
        return
    if status == "missing":
        if certified_hash is not None or certified_semantic_hash is not None:
            raise ValueError("missing certification cannot carry certified hashes")
        if reasons != ("validated_envelope_missing",):
            raise ValueError(
                "missing certification requires validated_envelope_missing"
            )
        return
    if certified_hash is None or certified_semantic_hash is None:
        raise ValueError("stale certification requires both certified hashes")
    if not reasons or "validated_envelope_missing" in reasons:
        raise ValueError("stale certification requires mismatch reasons")
    if (
        "certified_rule_contract_sha256_mismatch" in reasons
        and certified_hash == prepared_hash
    ):
        raise ValueError("full contract mismatch reason contradicts its hashes")
    if (
        "certified_rule_semantic_contract_sha256_mismatch" in reasons
        and certified_semantic_hash == prepared_semantic_hash
    ):
        raise ValueError("semantic contract mismatch reason contradicts its hashes")


__all__ = [
    "STUDIO_RULE_CONTRACT_BINDING_KEY",
    "StudioRuleContractBinding",
    "current_studio_rule_contract_binding",
]
