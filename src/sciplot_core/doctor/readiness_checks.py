"""Check layouts, fixtures, and validated envelopes."""

from __future__ import annotations

from typing import Any
from sciplot_core._paths import resolve_fixture_path
from sciplot_core.publication import (
    get_publication_profile,
    list_composite_layouts,
)
from sciplot_core.readiness import validated_envelope_status


def _publication_layout_inventory_available() -> bool:
    """Report deterministic figure-level layout metadata without a UI claim."""

    try:
        layouts = list_composite_layouts()
        profile = get_publication_profile("sciplot_composite_183_v1")
    except Exception:
        return False
    return (
        len(layouts) == 5
        and all(
            float(layout.get("geometry_total_mm") or 0.0) == 183.0 for layout in layouts
        )
        and profile.get("integrity", {}).get("scientific_outcome_agnostic") is True
        and profile.get("integrity", {}).get("significance_required") is False
    )


def _ready_rule_fixtures_exist(rules: list[Any]) -> tuple[bool, str]:
    missing = [
        rule.rule_id
        for rule in rules
        if rule.fixture_status == "ready"
        and (
            not rule.fixture_path
            or not resolve_fixture_path(str(rule.fixture_path)).exists()
        )
    ]
    return not missing, ", ".join(
        missing
    ) if missing else "all local acceptance fixtures are available"


def _validated_envelope_summary() -> tuple[bool, str, dict[str, Any]]:
    try:
        payload = validated_envelope_status()
    except Exception as exc:
        return (
            False,
            f"{type(exc).__name__}: {exc}",
            {
                "status": "needs_rule_repair",
                "ready_without_ai_rule_count": 0,
                "current_ready_rule_count": 0,
            },
        )
    ready = payload.get("status") == "ready"
    detail = (
        f"{payload.get('ready_without_ai_rule_count', 0)}/"
        f"{payload.get('current_ready_rule_count', 0)} current rule contracts"
    )
    return ready, detail, payload
