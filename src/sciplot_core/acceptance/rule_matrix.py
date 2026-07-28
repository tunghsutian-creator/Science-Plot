"""Build normalized ready-rule acceptance matrix rows."""

from __future__ import annotations

from pathlib import Path
from typing import Any
from sciplot_core._paths import (
    REPO_ROOT,
    resolve_fixture_path,
)
from sciplot_core.evidence import enrich_rule_evidence
from sciplot_core.materials_rules import SemanticRule, iter_public_rules
from sciplot_core.readiness import (
    rule_contract_sha256,
    rule_semantic_contract_sha256,
)

from sciplot_core.acceptance.fixtures import (
    RULE_ACCEPTANCE_CHECK_IDS,
    _rule_fixture_evidence,
)


def _rule_matrix_row(rule: SemanticRule, *, repo_root: Path) -> dict[str, Any]:
    fixture = resolve_fixture_path(str(rule.fixture_path or ""), repo_root=repo_root)
    evidence = enrich_rule_evidence(
        rule,
        _rule_fixture_evidence(rule, repo_root=repo_root),
        fixture=fixture,
        repo_root=repo_root,
    )
    return {
        "rule_id": rule.rule_id,
        "semantic_family": rule.semantic_family,
        "recipe": rule.recipe,
        "template": rule.template,
        "supported_templates": list(rule.presentation_templates),
        "template_acceptance": [],
        "rule_readiness": rule.fixture_status,
        "rule_contract_sha256": rule_contract_sha256(rule),
        "accepted_rule_contract_sha256": None,
        "semantic_contract_sha256": rule_semantic_contract_sha256(rule),
        "accepted_semantic_contract_sha256": None,
        "fixture_path": str(fixture),
        "fixture_exists": fixture.exists(),
        "evidence": evidence,
        "lifecycle_status": "not_run",
        "checks": {check_id: None for check_id in RULE_ACCEPTANCE_CHECK_IDS},
        "project_dir": None,
        "manifest": None,
        "artifact_review": {"status": "not_run"},
        "limitations": [],
        "error": None,
    }


def build_rule_acceptance_matrix(
    *, repo_root: Path = REPO_ROOT
) -> list[dict[str, Any]]:
    return [_rule_matrix_row(rule, repo_root=repo_root) for rule in iter_public_rules()]


def _delivery_artifact_passed(delivery: dict[str, Any], artifact_id: str) -> bool:
    artifacts = (
        delivery.get("artifacts") if isinstance(delivery.get("artifacts"), list) else []
    )
    return any(
        isinstance(item, dict)
        and item.get("id") == artifact_id
        and item.get("exists") is True
        for item in artifacts
    )


def _manual_edit_probe(document_path: Path, *, rule_id: str) -> str:
    marker = f"# SciPlot acceptance manual-edit preservation probe: {rule_id}"
    with document_path.open("a", encoding="utf-8") as handle:
        handle.write(f"\n{marker}\n")
    return marker
