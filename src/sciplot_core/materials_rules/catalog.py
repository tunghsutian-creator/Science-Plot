"""Query, match, and serialize entries from the semantic rule catalog."""

from __future__ import annotations

from collections.abc import Callable
import re
from typing import Any
from sciplot_core.study_model import experiment_recommendation_payload

from sciplot_core.materials_rules.tokens import (
    normalize_token,
)

from sciplot_core.materials_rules.models import (
    SemanticRule,
)

from sciplot_core.materials_rules.catalog_data import (
    RULES,
    _RULE_BY_ID,
)


RuleInvocationProjector = Callable[[SemanticRule], dict[str, Any]]


def iter_rules() -> tuple[SemanticRule, ...]:
    return tuple(sorted(RULES, key=lambda rule: (rule.priority, rule.rule_id)))


def get_rule(rule_id: str) -> SemanticRule:
    try:
        return _RULE_BY_ID[rule_id]
    except KeyError as exc:
        known = ", ".join(sorted(_RULE_BY_ID))
        raise ValueError(
            f"Unknown material rule `{rule_id}`. Available rules: {known}."
        ) from exc


def resolve_rule_template(
    rule: SemanticRule | str,
    requested_template: str | None = None,
) -> str:
    """Resolve presentation independently from the rule's scientific semantics."""

    resolved = get_rule(rule) if isinstance(rule, str) else rule
    selected = (
        str(requested_template).strip()
        if requested_template is not None and str(requested_template).strip()
        else resolved.template
    )
    if selected not in resolved.presentation_templates:
        supported = ", ".join(resolved.presentation_templates)
        raise ValueError(
            f"Template `{selected}` is not supported by material rule "
            f"`{resolved.rule_id}`. Supported presentation templates: {supported}."
        )
    return selected


def _is_ready_rule(rule: SemanticRule) -> bool:
    return rule.fixture_status == "ready"


def iter_public_rules(*, include_pending: bool = False) -> tuple[SemanticRule, ...]:
    rules = iter_rules()
    if include_pending:
        return rules
    return tuple(rule for rule in rules if _is_ready_rule(rule))


def list_rules_payload(
    *,
    include_pending: bool = False,
    invocation_projector: RuleInvocationProjector | None = None,
) -> dict[str, Any]:
    rules = iter_public_rules(include_pending=include_pending)
    all_rules = iter_rules()
    return {
        "kind": "sciplot_material_rules",
        "visibility": "all" if include_pending else "ready",
        "ready_count": sum(1 for rule in all_rules if _is_ready_rule(rule)),
        "pending_count": sum(1 for rule in all_rules if not _is_ready_rule(rule)),
        "rules": [
            _rule_list_item(rule, invocation_projector=invocation_projector)
            for rule in rules
        ],
    }


def _rule_list_item(
    rule: SemanticRule,
    *,
    invocation_projector: RuleInvocationProjector | None,
) -> dict[str, Any]:
    payload = _public_rule_payload(
        rule,
        invocation_projector=invocation_projector,
    )
    return {
        "rule_id": rule.rule_id,
        "semantic_family": rule.semantic_family,
        "recipe": rule.recipe,
        "template": rule.template,
        "supported_templates": list(rule.presentation_templates),
        "presentation_data_shape": rule.presentation_data_shape,
        "x": rule.x_axis.display_label,
        "y": rule.y_axis.display_label,
        "fixture_status": rule.fixture_status,
        "priority": rule.priority,
        "invocation": payload["invocation"],
    }


def show_rule_payload(
    rule_id: str,
    *,
    invocation_projector: RuleInvocationProjector | None = None,
) -> dict[str, Any]:
    return _public_rule_payload(
        get_rule(rule_id),
        invocation_projector=invocation_projector,
    )


def _public_rule_payload(
    rule: SemanticRule,
    *,
    invocation_projector: RuleInvocationProjector | None,
) -> dict[str, Any]:
    payload = rule.to_payload()
    if invocation_projector is not None:
        payload["invocation"] = invocation_projector(rule)
    return payload


def match_rule(
    *,
    evidence: str,
    compact_evidence: str,
    vendor_model: str | None = None,
    experiment_family: str | None = None,
    requested_rule_id: str | None = None,
) -> SemanticRule | None:
    if requested_rule_id:
        return get_rule(requested_rule_id)
    candidates: list[tuple[int, SemanticRule]] = []
    # Automatic production matching is deliberately narrower than the full
    # registry. Pending rules remain inspectable and explicitly addressable,
    # but they cannot silently enter the deterministic plotting path before a
    # fixture-backed acceptance promotes them to ``ready``.
    for rule in RULES:
        if not _is_ready_rule(rule):
            continue
        score = 0
        if vendor_model and vendor_model in rule.vendor_models:
            score += 100
        if experiment_family and experiment_family in rule.experiment_families:
            score += 40
        score += 35 * sum(
            1
            for item in rule.keywords
            if _matches_rule_token(item, evidence, compact_evidence)
        )
        # A rule-named source path or experiment folder is stronger evidence
        # than a generic vendor shape classifier (for example, every
        # strain/stress table can otherwise look like tensile data).
        score += 120 * sum(
            1 for item in rule.path_keywords if item.casefold() in evidence
        )
        score += 30 * sum(
            1
            for item in rule.column_aliases
            if _matches_rule_token(item, evidence, compact_evidence)
        )
        adjusted_score = score - rule.priority
        if adjusted_score > 0:
            candidates.append((adjusted_score, rule))
    if not candidates:
        return None
    return max(candidates, key=lambda item: item[0])[1]


def _matches_rule_token(item: str, evidence: str, compact_evidence: str) -> bool:
    normalized = normalize_token(item)
    raw = str(item).strip().casefold()
    if (
        raw.isascii()
        and normalized.isascii()
        and normalized.isalnum()
        and len(normalized) <= 3
    ):
        return (
            re.search(rf"(?<![a-z0-9]){re.escape(raw)}(?![a-z0-9])", evidence)
            is not None
        )
    return normalized in compact_evidence


def semantic_payload_from_rule(
    rule: SemanticRule,
    *,
    confidence: float,
    reason: str | None = None,
    vendor_model: str | None = None,
    vendor_error: str | None = None,
) -> dict[str, Any]:
    payload = rule.to_payload()
    rule_ready = _is_ready_rule(rule)
    render_options = dict(rule.render_options)
    if rule.x_axis.scale != "linear":
        render_options.setdefault("xscale", rule.x_axis.scale)
    if rule.y_axis.scale != "linear":
        render_options.setdefault("yscale", rule.y_axis.scale)
    if rule.x_axis.reverse:
        render_options.setdefault("reverse_x", True)
    return {
        "rule_id": rule.rule_id,
        "semantic_family": rule.semantic_family,
        "recommended_recipe": rule.recipe,
        "template": rule.template,
        "presentation_contract": payload["presentation_contract"],
        "render_options": render_options,
        "confidence": confidence if rule_ready else 0.0,
        "reason": (
            reason
            or rule.reason
            or (
                f"Material rule `{rule.rule_id}` is pending fixture-backed acceptance."
                if not rule_ready
                else f"Matched material rule `{rule.rule_id}`."
            )
        ),
        "needs_ai_intervention": not rule_ready,
        "production_status": "ready" if rule_ready else "needs_rule_repair",
        "rule_readiness": rule.fixture_status,
        "vendor_model": vendor_model,
        "vendor_error": vendor_error,
        "axis_plan": payload["axis_plan"],
        "unit_plan": payload["unit_plan"],
        "analysis_plan": payload["analysis_plan"],
        "available_metrics": payload["available_metrics"],
        "experiment_recommendation": experiment_recommendation_payload(
            rule_id=rule.rule_id,
            semantic_family=rule.semantic_family,
            experiment_type_id=rule.rule_id,
        ),
        "missing_requirements": (
            []
            if rule_ready
            else [
                "fixture_backed_rule_acceptance",
                "deterministic_semantic_rule_promotion",
            ]
        ),
        "rule_priority": rule.priority,
    }
