"""Determine whether presented inputs have enough evidence to evaluate."""

from __future__ import annotations

from typing import Any
from sciplot_core.materials_rules import (
    get_rule,
)

from sciplot_core.readiness.constants import (
    VALIDATED_ENVELOPE_EVALUATION_KIND,
    VALIDATED_ENVELOPE_EVALUATION_VERSION,
    VALIDATED_RENDER_REQUEST_POLICY_VERSION,
    INSIDE_VALIDATED_ENVELOPE,
    HIGH_CONFIDENCE_THRESHOLD,
    MEDIUM_CONFIDENCE_THRESHOLD,
    AUTHORIZATION_READY,
    FIXTURE_HASH_ACCEPTED,
    EVIDENCE_STRENGTHS,
    _EVALUATION_FIELDS,
    _EVALUATION_EVIDENCE_FIELDS,
    _EVALUATION_AUTHORITY_FIELDS,
)

from sciplot_core.readiness.validation import (
    _required_text,
    _required_int,
    _required_hash,
    _timestamp,
    _text_list,
    _canonical_sha256,
)

from sciplot_core.readiness.render_request_contract import (
    _render_request_policy_evaluation,
)

from sciplot_core.readiness.rule_contract import (
    rule_contract_sha256,
    rule_semantic_contract_sha256,
)

from sciplot_core.readiness.registry_io import (
    load_validated_envelope_registry,
)


def _confidence(payload: dict[str, Any]) -> float:
    value = payload.get("confidence")
    if isinstance(value, bool) or not isinstance(value, int | float):
        return 0.0
    result = float(value)
    return result if 0.0 <= result <= 100.0 else 0.0


def validated_envelope_evaluation_ready(
    payload: object,
    *,
    render_request: object,
) -> bool:
    """Return true only for a complete, strictly typed ready evaluation."""

    if not isinstance(payload, dict) or set(payload) != _EVALUATION_FIELDS:
        return False
    if payload.get("kind") != VALIDATED_ENVELOPE_EVALUATION_KIND:
        return False
    version = payload.get("version")
    if (
        isinstance(version, bool)
        or not isinstance(version, int)
        or version != VALIDATED_ENVELOPE_EVALUATION_VERSION
    ):
        return False
    if payload.get("state") != INSIDE_VALIDATED_ENVELOPE:
        return False
    if payload.get("ready_without_ai") is not True:
        return False
    if payload.get("contract_current") is not True:
        return False
    if payload.get("request_contract_current") is not True:
        return False
    if payload.get("repair_reasons") != []:
        return False
    if payload.get("confirmation_reasons") != []:
        return False

    try:
        evaluation_rule_id = _required_text(
            payload.get("rule_id"),
            "evaluation rule_id",
        )
        evaluation_semantic_family = _required_text(
            payload.get("semantic_family"),
            "evaluation semantic_family",
        )
        current_contract = _required_hash(
            payload.get("current_contract_sha256"),
            "evaluation current_contract_sha256",
        )
        certified_contract = _required_hash(
            payload.get("certified_contract_sha256"),
            "evaluation certified_contract_sha256",
        )
        presented_semantic = _required_hash(
            payload.get("presented_semantic_contract_sha256"),
            "evaluation presented_semantic_contract_sha256",
        )
        current_semantic = _required_hash(
            payload.get("current_semantic_contract_sha256"),
            "evaluation current_semantic_contract_sha256",
        )
        certified_semantic = _required_hash(
            payload.get("certified_semantic_contract_sha256"),
            "evaluation certified_semantic_contract_sha256",
        )
        presented_render_request = _required_hash(
            payload.get("presented_render_request_sha256"),
            "evaluation presented_render_request_sha256",
        )
        request_policy_version = _required_int(
            payload.get("request_policy_version"),
            "evaluation request_policy_version",
            minimum=1,
        )
        mapping_state = _required_text(
            payload.get("mapping_state"),
            "evaluation mapping_state",
        )
    except ValueError:
        return False
    if current_contract != certified_contract:
        return False
    if not (presented_semantic == current_semantic == certified_semantic):
        return False
    if request_policy_version != VALIDATED_RENDER_REQUEST_POLICY_VERSION:
        return False
    if mapping_state not in {"auto", "confirmed"}:
        return False
    try:
        current_rule = get_rule(evaluation_rule_id)
        registry = load_validated_envelope_registry()
    except (FileNotFoundError, ValueError):
        return False
    registry_entry = registry.entry(evaluation_rule_id)
    if (
        current_rule.fixture_status != "ready"
        or current_rule.semantic_family != evaluation_semantic_family
        or registry_entry is None
        or registry_entry.semantic_family != evaluation_semantic_family
        or current_contract != rule_contract_sha256(current_rule)
        or current_semantic != rule_semantic_contract_sha256(current_rule)
        or registry_entry.contract_sha256 != current_contract
        or registry_entry.semantic_contract_sha256 != current_semantic
    ):
        return False
    request_contract, request_repairs, request_confirmations = (
        _render_request_policy_evaluation(current_rule, render_request)
    )
    if (
        request_contract is None
        or request_repairs
        or request_confirmations
        or _canonical_sha256(request_contract) != presented_render_request
    ):
        return False

    confidence_value = payload.get("confidence")
    if isinstance(confidence_value, bool) or not isinstance(
        confidence_value,
        int | float,
    ):
        return False
    confidence = float(confidence_value)
    if not 0.0 <= confidence <= 100.0:
        return False
    if mapping_state == "auto" and confidence < HIGH_CONFIDENCE_THRESHOLD:
        return False
    if mapping_state == "confirmed" and confidence < MEDIUM_CONFIDENCE_THRESHOLD:
        return False

    evidence = payload.get("accepted_evidence")
    if not isinstance(evidence, dict) or set(evidence) != _EVALUATION_EVIDENCE_FIELDS:
        return False
    try:
        _required_text(evidence.get("tier"), "evaluation evidence tier")
        strength = _required_text(
            evidence.get("strength"),
            "evaluation evidence strength",
        )
        authorization = _required_text(
            evidence.get("authorization_status"),
            "evaluation authorization_status",
        )
        fixture_status = _required_text(
            evidence.get("fixture_hash_status"),
            "evaluation fixture_hash_status",
        )
        _required_text(
            evidence.get("source_hash_status"),
            "evaluation source_hash_status",
        )
        _required_text(evidence.get("unit_status"), "evaluation unit_status")
        _timestamp(
            evidence.get("acceptance_generated_at"),
            "evaluation acceptance_generated_at",
        )
        _required_hash(
            evidence.get("accepted_manifest_sha256"),
            "evaluation accepted_manifest_sha256",
        )
        _text_list(
            evidence.get("limitations"),
            "evaluation evidence limitations",
            maximum_items=32,
            maximum_text=4096,
        )
    except ValueError:
        return False
    if strength not in EVIDENCE_STRENGTHS:
        return False
    if authorization not in AUTHORIZATION_READY:
        return False
    if fixture_status not in FIXTURE_HASH_ACCEPTED:
        return False
    if (
        evidence["tier"] != registry_entry.evidence_tier
        or strength != registry_entry.evidence_strength
        or authorization != registry_entry.authorization_status
        or fixture_status != registry_entry.fixture_hash_status
        or evidence["source_hash_status"] != registry_entry.source_hash_status
        or evidence["unit_status"] != registry_entry.unit_status
        or evidence["acceptance_generated_at"] != registry_entry.acceptance_generated_at
        or evidence["accepted_manifest_sha256"]
        != registry_entry.accepted_manifest_sha256
        or evidence["limitations"] != list(registry_entry.limitations)
    ):
        return False

    authority = payload.get("authority")
    if (
        not isinstance(authority, dict)
        or set(authority) != _EVALUATION_AUTHORITY_FIELDS
    ):
        return False
    return all(authority[field] is True for field in _EVALUATION_AUTHORITY_FIELDS)
