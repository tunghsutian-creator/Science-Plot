"""Write ready-rule acceptance CSV and Markdown reports."""

from __future__ import annotations

import csv
from pathlib import Path
from typing import Any

from sciplot_core.acceptance.fixtures import (
    RULE_ACCEPTANCE_CHECK_IDS,
)


def _write_rule_acceptance_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    fieldnames = [
        "rule_id",
        "semantic_family",
        "template",
        "rule_readiness",
        "evidence_tier",
        "real_data_evidence",
        "lifecycle_status",
        "physical_size_status",
        "rule_contract_sha256",
        "accepted_rule_contract_sha256",
        "semantic_contract_sha256",
        "accepted_semantic_contract_sha256",
        *RULE_ACCEPTANCE_CHECK_IDS,
        "fixture_path",
        "manifest",
    ]
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        for row in rows:
            writer.writerow(
                {
                    "rule_id": row["rule_id"],
                    "semantic_family": row["semantic_family"],
                    "template": row["template"],
                    "rule_readiness": row["rule_readiness"],
                    "evidence_tier": row["evidence"]["tier"],
                    "real_data_evidence": row["evidence"]["real_data_evidence"],
                    "lifecycle_status": row["lifecycle_status"],
                    "physical_size_status": row.get("artifact_review", {}).get(
                        "status", "not_run"
                    ),
                    "rule_contract_sha256": row.get("rule_contract_sha256"),
                    "accepted_rule_contract_sha256": row.get(
                        "accepted_rule_contract_sha256"
                    ),
                    "semantic_contract_sha256": row.get("semantic_contract_sha256"),
                    "accepted_semantic_contract_sha256": row.get(
                        "accepted_semantic_contract_sha256"
                    ),
                    **{
                        check_id: row["checks"].get(check_id)
                        for check_id in RULE_ACCEPTANCE_CHECK_IDS
                    },
                    "fixture_path": row["fixture_path"],
                    "manifest": row["manifest"],
                }
            )


def _write_rule_acceptance_markdown(path: Path, payload: dict[str, Any]) -> None:
    lines = [
        "# SciPlot Ready-Rule Acceptance Matrix",
        "",
        f"Generated: {payload['generated_at']}",
        "",
        "Lifecycle status and real-data evidence are deliberately separate. A fixture-backed rule is not described "
        "as real-data accepted unless its evidence metadata supports that claim.",
        "",
        "| Rule | Evidence | Real data | Lifecycle | Final size | Failed checks |",
        "|---|---|---:|---|---|---|",
    ]
    for row in payload["matrix"]:
        failed = [
            check_id for check_id, passed in row["checks"].items() if passed is False
        ]
        lines.append(
            f"| `{row['rule_id']}` | `{row['evidence']['tier']}` | "
            f"{'yes' if row['evidence']['real_data_evidence'] else 'no'} | "
            f"`{row['lifecycle_status']}` | `{row.get('artifact_review', {}).get('status', 'not_run')}` | "
            f"{', '.join(failed) or '-'} |"
        )
    lines.extend(
        [
            "",
            "## Honest coverage boundary",
            "",
            "- Rows count as real-data evidence only when their explicit `real_data_evidence` field is true; "
            "the tier records whether the source is public, user-authorized, digitized, derived, or limited.",
            "- `instrument_shaped_fixture` proves a parser/render contract only; it remains a real-data gap.",
            "- The manual-edit probe proves exact VSZ preservation. PDF/TIFF physical size is checked here, while "
            "the generated contact sheets still require an explicit visual decision.",
            "- Explicit publication composition uses deterministic 183 mm figure-level layout metadata. "
            "This rule matrix does not infer composition from independent figures, and SciPlot has no "
            "standalone composition UI.",
            "",
        ]
    )
    path.write_text("\n".join(lines), encoding="utf-8")
