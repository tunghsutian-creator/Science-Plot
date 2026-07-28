"""Exercise all supported templates for one rule lifecycle."""

from __future__ import annotations

from pathlib import Path
from typing import Any
from sciplot_core.materials_rules import SemanticRule

from sciplot_core.acceptance.fixtures import (
    RULE_ACCEPTANCE_CHECK_IDS,
)

from sciplot_core.acceptance.rule_matrix import (
    _rule_matrix_row,
)

from sciplot_core.acceptance.rule_template import (
    _run_rule_template_acceptance,
)


def _run_rule_lifecycle_acceptance(
    rule: SemanticRule,
    *,
    projects_root: Path,
    repo_root: Path,
) -> dict[str, Any]:
    row = _rule_matrix_row(rule, repo_root=repo_root)
    fixture = Path(row["fixture_path"])
    template_results = [
        _run_rule_template_acceptance(
            rule,
            template=template,
            fixture=fixture,
            projects_root=projects_root,
        )
        for template in rule.presentation_templates
    ]
    result_by_template = {
        str(result["template"]): result for result in template_results
    }
    default_result = result_by_template[rule.template]
    supported_templates_exercised = set(result_by_template) == set(
        rule.presentation_templates
    ) and all(result.get("lifecycle_status") == "passed" for result in template_results)
    checks = {
        check_id: (
            supported_templates_exercised
            if check_id == "supported_templates_exercised"
            else all(
                result.get("checks", {}).get(check_id) is True
                for result in template_results
            )
        )
        for check_id in RULE_ACCEPTANCE_CHECK_IDS
    }
    errors = [
        {
            "template": result["template"],
            **dict(result["error"]),
        }
        for result in template_results
        if isinstance(result.get("error"), dict)
    ]
    row.update(
        {
            "lifecycle_status": "passed" if all(checks.values()) else "failed",
            "checks": checks,
            "template_acceptance": template_results,
            "rule_contract_sha256": default_result["rule_contract_sha256"],
            "accepted_rule_contract_sha256": (
                default_result["accepted_rule_contract_sha256"]
            ),
            "semantic_contract_sha256": default_result["semantic_contract_sha256"],
            "accepted_semantic_contract_sha256": default_result[
                "accepted_semantic_contract_sha256"
            ],
            "project_dir": default_result["project_dir"],
            "manifest": default_result["manifest"],
            "limitations": [
                "Every registered presentation template is exercised through "
                "native Studio prepare, reopen, PDF/TIFF export, QA, delivery, "
                "and provenance checks.",
                "The manual-edit probe appends a harmless VSZ comment and proves "
                "exact-document preservation; full visual-object inspection is "
                "exercised by the separate exact-current publication-QA suite.",
            ],
            "error": {"template_errors": errors} if errors else None,
        }
    )
    return row
