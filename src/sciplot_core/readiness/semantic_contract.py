"""Build canonical semantic-rule contract payloads."""

from __future__ import annotations

from copy import deepcopy
from typing import Any
from sciplot_core.foundation.json_values import json_safe
from sciplot_core.materials_rules import (
    SemanticRule,
    semantic_payload_from_rule,
)

from sciplot_core.readiness.constants import (
    _SEMANTIC_CONTRACT_FIELDS,
)


def semantic_contract_payload(semantic: dict[str, Any]) -> dict[str, Any]:
    """Return the deterministic rule/render contract accepted by a lifecycle."""

    if not isinstance(semantic, dict):
        raise ValueError("semantic contract source must be an object.")
    payload: dict[str, Any] = {}
    for field in _SEMANTIC_CONTRACT_FIELDS:
        if field not in semantic:
            raise ValueError(f"semantic contract is missing `{field}`.")
        registered_field = {
            "axis_plan": "registered_axis_plan",
            "unit_plan": "registered_unit_plan",
        }.get(field)
        value = (
            semantic.get(registered_field)
            if registered_field and isinstance(semantic.get(registered_field), dict)
            else semantic[field]
        )
        payload[field] = deepcopy(json_safe(value))
    if not isinstance(payload["rule_id"], str) or not payload["rule_id"].strip():
        raise ValueError("semantic contract rule_id must be non-empty text.")
    if (
        not isinstance(payload["semantic_family"], str)
        or not payload["semantic_family"].strip()
    ):
        raise ValueError("semantic contract semantic_family must be non-empty text.")
    if not isinstance(payload["template"], str) or not payload["template"].strip():
        raise ValueError("semantic contract template must be non-empty text.")
    if not isinstance(payload["render_options"], dict):
        raise ValueError("semantic contract render_options must be an object.")
    for field in (
        "axis_plan",
        "unit_plan",
        "experiment_recommendation",
    ):
        if not isinstance(payload[field], dict):
            raise ValueError(f"semantic contract {field} must be an object.")
    for field in ("analysis_plan", "available_metrics"):
        if not isinstance(payload[field], list):
            raise ValueError(f"semantic contract {field} must be a list.")
    return payload


def _certified_render_option_baseline(rule: SemanticRule) -> dict[str, Any]:
    semantic = semantic_payload_from_rule(
        rule,
        confidence=100.0,
        reason=f"Validated render-request baseline for `{rule.rule_id}`.",
    )
    baseline = deepcopy(semantic_contract_payload(semantic)["render_options"])
    axis_plan = semantic.get("axis_plan")
    if isinstance(axis_plan, dict):
        for axis_name in ("x", "y"):
            axis = axis_plan.get(axis_name)
            display_label = (
                axis.get("display_label") if isinstance(axis, dict) else None
            )
            if isinstance(display_label, str) and display_label.strip():
                baseline.setdefault(
                    f"{axis_name}_label_override",
                    display_label.strip(),
                )
    return baseline
