"""Build and hash complete semantic rule contracts."""

from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass
from typing import Any

from sciplot_core.foundation.json_values import json_safe
from sciplot_core.materials_rules import (
    SemanticRule,
    get_rule,
    semantic_payload_from_rule,
)

from sciplot_core.readiness.constants import (
    RULE_CONTRACT_VERSION,
    _RECOGNITION_CONTRACT_FIELDS,
)

from sciplot_core.readiness.validation import (
    _canonical_sha256,
)

from sciplot_core.readiness.semantic_contract import (
    semantic_contract_payload,
)

from sciplot_core.readiness.render_request_contract import (
    validated_render_request_policy_payload,
)


@dataclass(frozen=True)
class RuleContractHashes:
    """Full and semantic hashes derived from one canonical rule payload."""

    contract_sha256: str
    semantic_contract_sha256: str


def rule_contract_payload(rule: SemanticRule) -> dict[str, Any]:
    semantic = semantic_payload_from_rule(
        rule,
        confidence=100.0,
        reason=f"Validated-envelope contract for `{rule.rule_id}`.",
    )
    recognition = {
        field: deepcopy(json_safe(getattr(rule, field)))
        for field in _RECOGNITION_CONTRACT_FIELDS
    }
    for field, value in recognition.items():
        if not isinstance(value, list):
            raise ValueError(f"rule recognition contract {field} must be a list.")
    return {
        "version": RULE_CONTRACT_VERSION,
        "semantic": semantic_contract_payload(semantic),
        "recognition": recognition,
        "matcher": {
            "algorithm": "weighted_ready_rule_token_match",
            "version": 1,
            "automatic_scope": "ready_rules_only",
        },
        "render_request_policy": validated_render_request_policy_payload(rule),
    }


def semantic_contract_sha256(semantic: dict[str, Any]) -> str:
    return _canonical_sha256(semantic_contract_payload(semantic))


def rule_contract_hashes(rule: SemanticRule | str) -> RuleContractHashes:
    """Hash one resolved rule without rebuilding its canonical payload."""

    resolved = get_rule(rule) if isinstance(rule, str) else rule
    payload = rule_contract_payload(resolved)
    return RuleContractHashes(
        contract_sha256=_canonical_sha256(payload),
        semantic_contract_sha256=_canonical_sha256(payload["semantic"]),
    )


def rule_contract_sha256(rule: SemanticRule | str) -> str:
    return rule_contract_hashes(rule).contract_sha256


def rule_semantic_contract_sha256(rule: SemanticRule | str) -> str:
    return rule_contract_hashes(rule).semantic_contract_sha256
