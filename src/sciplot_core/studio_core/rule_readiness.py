"""Resolve canonical Studio request identity and publication rule readiness."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from sciplot_core.json_contract import require_json_bool
from sciplot_core.materials_rules import SemanticRule, get_rule
from sciplot_core.readiness import load_validated_envelope_registry
from sciplot_core.readiness.rule_certification import (
    CurrentCertifiedRuleContractSnapshot,
    current_certified_rule_contract_snapshot,
)
from sciplot_core.studio_core.rule_contract_binding import (
    STUDIO_RULE_CONTRACT_BINDING_KEY,
    StudioRuleContractBinding,
)


@dataclass(frozen=True)
class StudioRulePublicationReadiness:
    """Immutable request/catalog/certification evidence for one publish."""

    rule_id: str | None
    current_rule: SemanticRule | None
    current_certification: CurrentCertifiedRuleContractSnapshot | None
    prepared_binding: StudioRuleContractBinding | None
    persisted_pending_rule_review: bool
    pending_rule_review: bool
    publication_blocked: bool
    blockers: tuple[str, ...]

    @property
    def failure_reason(self) -> str | None:
        if not self.publication_blocked:
            return None
        if (
            self.current_rule is not None
            and self.current_rule.fixture_status != "ready"
        ):
            suffix = (
                " This project also retains preparation-time rule-review evidence."
                if self.persisted_pending_rule_review
                else ""
            )
            return (
                f"Material rule `{self.current_rule.rule_id}` is currently "
                f"`{self.current_rule.fixture_status}` and is not ready for "
                "production publication. Repair and revalidate the central rule, "
                f"then reprepare this Studio project before handoff.{suffix}"
            )
        if "current_rule_certification_missing" in self.blockers:
            return (
                f"Material rule `{self.rule_id}` has no validated-envelope "
                "certification for its current contract. Revalidate the central "
                "rule, then reprepare this Studio project before handoff."
            )
        if "current_rule_certification_stale" in self.blockers:
            return (
                f"Material rule `{self.rule_id}` no longer matches its "
                "validated-envelope certification. Repair or recertify the central "
                "rule, then reprepare this Studio project before handoff."
            )
        if "prepared_rule_contract_binding_missing" in self.blockers:
            return (
                "This rule-bearing Studio project has no prepare-time rule-contract "
                "binding. Reprepare it with the current certified rule before "
                "handoff."
            )
        if "prepared_rule_contract_binding_stale" in self.blockers:
            return (
                "This Studio project was prepared under a different rule contract "
                f"or certification state. Reprepare it with the current certified "
                f"rule `{self.rule_id}` before handoff."
            )
        if self.rule_id is not None:
            return (
                "This Studio project retains preparation-time rule-review evidence. "
                "Reprepare it with the current ready rule before handoff."
            )
        return (
            "This Studio project retains rule-review evidence but has no canonical "
            "request rule. Reprepare it with an explicit ready rule before handoff."
        )

    def to_payload(self) -> dict[str, Any]:
        if self.rule_id is None:
            contract_status = "not_applicable"
        elif any(
            blocker.startswith("current_rule_certification_")
            or blocker.startswith("prepared_rule_contract_")
            for blocker in self.blockers
        ):
            contract_status = "blocked"
        else:
            contract_status = "current"
        return {
            "kind": "sciplot_studio_rule_publication_readiness",
            "version": 2,
            "rule_id": self.rule_id,
            "persisted_pending_rule_review": (self.persisted_pending_rule_review),
            "current_rule_readiness": (
                self.current_rule.fixture_status
                if self.current_rule is not None
                else None
            ),
            "pending_rule_review": self.pending_rule_review,
            "publication_blocked": self.publication_blocked,
            "rule_contract_evidence": {
                "status": contract_status,
                "prepared": (
                    self.prepared_binding.to_payload()
                    if self.prepared_binding is not None
                    else None
                ),
                "current": (
                    self.current_certification.to_payload()
                    if self.current_certification is not None
                    else None
                ),
            },
            "blockers": list(self.blockers),
        }


def resolve_studio_rule_publication_readiness(
    request: dict[str, Any],
) -> StudioRulePublicationReadiness:
    """Compare persisted preparation evidence with current rule certification."""

    rule_id_value = request.get("rule_id")
    if rule_id_value is None:
        rule_id = None
    elif not isinstance(rule_id_value, str):
        raise ValueError("Studio request `rule_id` must be a string, null, or omitted.")
    else:
        rule_id = rule_id_value.strip() or None

    has_binding = STUDIO_RULE_CONTRACT_BINDING_KEY in request
    if rule_id is None and has_binding:
        raise ValueError(
            "A ruleless Studio request cannot carry a Studio rule-contract binding."
        )
    persisted_pending = (
        require_json_bool(
            request["pending_rule_review"],
            label="Studio request `pending_rule_review`",
        )
        if "pending_rule_review" in request
        else False
    )
    if rule_id is None:
        blockers: tuple[str, ...] = (
            ("persisted_pending_rule_review",) if persisted_pending else ()
        )
        return StudioRulePublicationReadiness(
            rule_id=None,
            current_rule=None,
            current_certification=None,
            prepared_binding=None,
            persisted_pending_rule_review=persisted_pending,
            pending_rule_review=persisted_pending,
            publication_blocked=bool(blockers),
            blockers=blockers,
        )

    current_rule = get_rule(rule_id)
    current_certification = current_certified_rule_contract_snapshot(
        rule=current_rule,
        registry=load_validated_envelope_registry(),
    )
    prepared_binding = (
        StudioRuleContractBinding.from_payload(
            request[STUDIO_RULE_CONTRACT_BINDING_KEY]
        )
        if has_binding
        else None
    )
    pending_rule_review = bool(
        persisted_pending or current_rule.fixture_status != "ready"
    )
    blocker_values: list[str] = []
    if persisted_pending:
        blocker_values.append("persisted_pending_rule_review")
    if current_rule.fixture_status != "ready":
        blocker_values.append("current_rule_not_ready")
    if current_certification.certification_status == "missing":
        blocker_values.append("current_rule_certification_missing")
    elif current_certification.certification_status == "stale":
        blocker_values.append("current_rule_certification_stale")
    if prepared_binding is None:
        blocker_values.append("prepared_rule_contract_binding_missing")
    elif not prepared_binding.matches_current_snapshot(current_certification):
        blocker_values.append("prepared_rule_contract_binding_stale")
    blockers = tuple(blocker_values)
    return StudioRulePublicationReadiness(
        rule_id=rule_id,
        current_rule=current_rule,
        current_certification=current_certification,
        prepared_binding=prepared_binding,
        persisted_pending_rule_review=persisted_pending,
        pending_rule_review=pending_rule_review,
        publication_blocked=bool(blockers),
        blockers=blockers,
    )


__all__ = [
    "StudioRulePublicationReadiness",
    "resolve_studio_rule_publication_readiness",
]
