"""Evaluate one semantic and render request against validated envelopes."""

from __future__ import annotations

from typing import Any
from sciplot_core.materials_rules import (
    SemanticRule,
    get_rule,
)

from sciplot_core.readiness.constants import (
    VALIDATED_ENVELOPE_EVALUATION_KIND,
    VALIDATED_ENVELOPE_EVALUATION_VERSION,
    VALIDATED_RENDER_REQUEST_POLICY_VERSION,
    INSIDE_VALIDATED_ENVELOPE,
    NEEDS_HUMAN_CONFIRMATION,
    NEEDS_RULE_REPAIR,
    HIGH_CONFIDENCE_THRESHOLD,
    MEDIUM_CONFIDENCE_THRESHOLD,
    MAPPING_STATES,
)

from sciplot_core.readiness.validation import (
    _canonical_sha256,
)

from sciplot_core.readiness.render_request_contract import (
    _render_request_policy_evaluation,
)

from sciplot_core.readiness.rule_contract import (
    semantic_contract_sha256,
    rule_contract_sha256,
    rule_semantic_contract_sha256,
)

from sciplot_core.readiness.envelope_model import (
    ValidatedRuleEnvelope,
)

from sciplot_core.readiness.registry_model import (
    ValidatedEnvelopeRegistry,
)

from sciplot_core.readiness.registry_io import (
    load_validated_envelope_registry,
)

from sciplot_core.readiness.evaluation_readiness import (
    _confidence,
)


def evaluate_validated_envelope(
    *,
    semantic: dict[str, Any],
    source_package: dict[str, Any],
    mapping_package: dict[str, Any],
    render_request: dict[str, Any],
    registry: ValidatedEnvelopeRegistry | None = None,
) -> dict[str, Any]:
    """Evaluate a new input without trusting user- or provider-authored ready flags."""

    resolved = registry or load_validated_envelope_registry()
    rule_id = str(semantic.get("rule_id") or "").strip()
    mapping_rule_id = str(mapping_package.get("rule_id") or "").strip()
    source_rule_id = str(source_package.get("rule_id") or "").strip()
    repair_reasons: list[str] = []
    confirmation_reasons: list[str] = []

    rule: SemanticRule | None = None
    entry: ValidatedRuleEnvelope | None = None
    current_contract: str | None = None
    current_semantic_contract: str | None = None
    presented_semantic_contract: str | None = None
    presented_render_request: str | None = None
    request_contract_current = False
    if not rule_id:
        repair_reasons.append("semantic_rule_missing")
    else:
        try:
            rule = get_rule(rule_id)
        except ValueError:
            repair_reasons.append("semantic_rule_unknown")
        if rule is not None:
            current_contract = rule_contract_sha256(rule)
            current_semantic_contract = rule_semantic_contract_sha256(rule)
            entry = resolved.entry(rule.rule_id)
            if entry is None:
                repair_reasons.append("validated_envelope_missing")
            elif entry.contract_sha256 != current_contract:
                repair_reasons.append("validated_envelope_stale")
            if rule.fixture_status != "ready":
                repair_reasons.append("semantic_rule_not_ready")
            if semantic.get("semantic_family") != rule.semantic_family:
                repair_reasons.append("semantic_family_mismatch")
            if entry is not None and entry.semantic_family != rule.semantic_family:
                repair_reasons.append("certified_semantic_family_mismatch")
            if (
                entry is not None
                and entry.semantic_contract_sha256 != current_semantic_contract
            ):
                repair_reasons.append("validated_semantic_contract_stale")
            try:
                presented_semantic_contract = semantic_contract_sha256(semantic)
            except ValueError:
                repair_reasons.append("semantic_contract_invalid")
            else:
                if presented_semantic_contract != current_semantic_contract:
                    repair_reasons.append("semantic_contract_mismatch")

            request_contract, request_repairs, request_confirmations = (
                _render_request_policy_evaluation(rule, render_request)
            )
            repair_reasons.extend(request_repairs)
            confirmation_reasons.extend(request_confirmations)
            if request_contract is not None:
                presented_render_request = _canonical_sha256(request_contract)
                request_contract_current = not (
                    request_repairs or request_confirmations
                )

    if not mapping_rule_id or mapping_rule_id != rule_id:
        repair_reasons.append("mapping_rule_mismatch")
    if not source_rule_id or source_rule_id != rule_id:
        repair_reasons.append("source_rule_mismatch")
    if (
        source_package.get("kind") != "sciplot_source_package"
        or isinstance(source_package.get("version"), bool)
        or not isinstance(source_package.get("version"), int)
        or source_package.get("version") != 1
    ):
        repair_reasons.append("source_package_contract_invalid")
    if (
        mapping_package.get("kind") != "sciplot_mapping_package"
        or isinstance(mapping_package.get("version"), bool)
        or not isinstance(mapping_package.get("version"), int)
        or mapping_package.get("version") != 1
    ):
        repair_reasons.append("mapping_package_contract_invalid")
    semantic_family = str(semantic.get("semantic_family") or "").strip()
    if str(mapping_package.get("semantic_family") or "").strip() != semantic_family:
        repair_reasons.append("mapping_semantic_family_mismatch")
    if str(source_package.get("instrument_family") or "").strip() != semantic_family:
        repair_reasons.append("source_semantic_family_mismatch")
    if str(mapping_package.get("experiment_type") or "").strip() != rule_id:
        repair_reasons.append("mapping_experiment_type_mismatch")
    if semantic.get("needs_ai_intervention") is True:
        repair_reasons.append("semantic_requires_intervention")
    if semantic.get("production_status") != "ready":
        repair_reasons.append("semantic_production_not_ready")
    if semantic.get("rule_readiness") != "ready":
        repair_reasons.append("semantic_readiness_not_ready")

    mapping_state = str(mapping_package.get("status") or "")
    if mapping_state not in MAPPING_STATES:
        repair_reasons.append("mapping_state_invalid")
    elif mapping_state == NEEDS_RULE_REPAIR:
        repair_reasons.append("mapping_requires_rule_repair")
    elif mapping_state == NEEDS_HUMAN_CONFIRMATION:
        confirmation_reasons.append("mapping_requires_confirmation")

    semantic_confidence = _confidence(semantic)
    mapping_confidence = _confidence(mapping_package)
    source_confidence = _confidence(source_package)
    if (
        max(
            abs(semantic_confidence - mapping_confidence),
            abs(semantic_confidence - source_confidence),
        )
        > 1e-9
    ):
        repair_reasons.append("confidence_binding_mismatch")
    if semantic_confidence < MEDIUM_CONFIDENCE_THRESHOLD:
        repair_reasons.append("semantic_confidence_below_supported_floor")
    elif (
        semantic_confidence < HIGH_CONFIDENCE_THRESHOLD and mapping_state != "confirmed"
    ):
        confirmation_reasons.append("semantic_match_requires_confirmation")

    file_count = source_package.get("file_count")
    if (
        isinstance(file_count, bool)
        or not isinstance(file_count, int)
        or file_count < 1
    ):
        repair_reasons.append("source_package_empty")
    if source_package.get("source_kind") not in {"file", "directory"}:
        repair_reasons.append("source_kind_invalid")

    if repair_reasons:
        state = NEEDS_RULE_REPAIR
    elif confirmation_reasons:
        state = NEEDS_HUMAN_CONFIRMATION
    else:
        state = INSIDE_VALIDATED_ENVELOPE
    return {
        "kind": VALIDATED_ENVELOPE_EVALUATION_KIND,
        "version": VALIDATED_ENVELOPE_EVALUATION_VERSION,
        "state": state,
        "ready_without_ai": state == INSIDE_VALIDATED_ENVELOPE,
        "rule_id": rule_id or None,
        "semantic_family": semantic.get("semantic_family"),
        "current_contract_sha256": current_contract,
        "certified_contract_sha256": (
            entry.contract_sha256 if entry is not None else None
        ),
        "presented_semantic_contract_sha256": presented_semantic_contract,
        "current_semantic_contract_sha256": current_semantic_contract,
        "certified_semantic_contract_sha256": (
            entry.semantic_contract_sha256 if entry is not None else None
        ),
        "presented_render_request_sha256": presented_render_request,
        "request_policy_version": VALIDATED_RENDER_REQUEST_POLICY_VERSION,
        "request_contract_current": request_contract_current,
        "contract_current": bool(
            current_contract
            and entry is not None
            and current_contract == entry.contract_sha256
            and current_semantic_contract == entry.semantic_contract_sha256
            and presented_semantic_contract == current_semantic_contract
            and request_contract_current
        ),
        "mapping_state": mapping_state or None,
        "confidence": semantic_confidence,
        "repair_reasons": list(dict.fromkeys(repair_reasons)),
        "confirmation_reasons": list(dict.fromkeys(confirmation_reasons)),
        "accepted_evidence": (
            {
                "tier": entry.evidence_tier,
                "strength": entry.evidence_strength,
                "authorization_status": entry.authorization_status,
                "fixture_hash_status": entry.fixture_hash_status,
                "source_hash_status": entry.source_hash_status,
                "unit_status": entry.unit_status,
                "acceptance_generated_at": entry.acceptance_generated_at,
                "accepted_manifest_sha256": entry.accepted_manifest_sha256,
                "limitations": list(entry.limitations),
            }
            if entry is not None
            else None
        ),
        "authority": {
            "provider_ready_flags_are_ignored": True,
            "current_rule_contract_must_match_acceptance": True,
            "render_request_must_match_versioned_policy": True,
            "new_input_mapping_and_qa_still_required": True,
        },
    }
