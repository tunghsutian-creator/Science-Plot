"""Coordinate the complete ready-rule acceptance suite."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any
from sciplot_core._paths import (
    REPO_ROOT,
)
from sciplot_core.foundation.iso_timestamps import utc_now_iso
from sciplot_core.foundation.json_values import json_safe
from sciplot_core.foundation.path_names import slug
from sciplot_core.evidence import write_evidence_status_dashboard
from sciplot_core.materials_rules import get_rule, iter_public_rules
from sciplot_core.visual_review import write_final_size_visual_review

from sciplot_core.acceptance.fixtures import (
    RULE_ACCEPTANCE_VERSION,
)

from sciplot_core.acceptance.rule_matrix import (
    build_rule_acceptance_matrix,
)

from sciplot_core.acceptance.rule_lifecycle import (
    _run_rule_lifecycle_acceptance,
)

from sciplot_core.acceptance.rule_reports import (
    _write_rule_acceptance_csv,
    _write_rule_acceptance_markdown,
)


def run_rule_acceptance_suite(
    *,
    output_root: Path,
    project_name: str = "ready_rule_acceptance",
    rule_ids: list[str] | tuple[str, ...] | None = None,
    repo_root: Path = REPO_ROOT,
) -> dict[str, Any]:
    ready_rules = list(iter_public_rules())
    ready_by_id = {rule.rule_id: rule for rule in ready_rules}
    selected_ids = list(
        dict.fromkeys(rule_ids or [rule.rule_id for rule in ready_rules])
    )
    unknown = [rule_id for rule_id in selected_ids if rule_id not in ready_by_id]
    if unknown:
        for rule_id in unknown:
            try:
                rule = get_rule(rule_id)
            except ValueError:
                continue
            if rule.fixture_status != "ready":
                raise ValueError(
                    f"Acceptance suite only runs ready rules; `{rule_id}` is {rule.fixture_status}."
                )
        raise ValueError(f"Unknown or non-ready rule ids: {', '.join(unknown)}")

    project_dir = output_root.expanduser().resolve() / slug(project_name)
    projects_root = project_dir / "projects"
    project_dir.mkdir(parents=True, exist_ok=True)
    rows_by_id = {
        row["rule_id"]: row for row in build_rule_acceptance_matrix(repo_root=repo_root)
    }
    for rule_id in selected_ids:
        rows_by_id[rule_id] = _run_rule_lifecycle_acceptance(
            ready_by_id[rule_id],
            projects_root=projects_root,
            repo_root=repo_root,
        )
    rows = [rows_by_id[rule.rule_id] for rule in ready_rules]
    selected_rows = [rows_by_id[rule_id] for rule_id in selected_ids]
    generated_at = utc_now_iso()
    visual_review = write_final_size_visual_review(
        output_dir=project_dir,
        rows=rows,
        generated_at=generated_at,
    )
    for row in rows:
        row["artifact_review"] = visual_review["records_by_rule"][row["rule_id"]]
    selected_lifecycle_failed = [
        row["rule_id"] for row in selected_rows if row["lifecycle_status"] != "passed"
    ]
    selected_size_failed = [
        row["rule_id"]
        for row in selected_rows
        if row.get("artifact_review", {}).get("status") == "failed"
    ]
    selected_failed = list(
        dict.fromkeys([*selected_lifecycle_failed, *selected_size_failed])
    )
    passed_count = sum(row["lifecycle_status"] == "passed" for row in rows)
    physical_size_passed_count = sum(
        row.get("artifact_review", {}).get("status") == "passed" for row in rows
    )
    real_data_passed_count = sum(
        row["lifecycle_status"] == "passed" and row["evidence"]["real_data_evidence"]
        for row in rows
    )
    coverage_complete = passed_count == len(ready_rules)
    physical_size_complete = physical_size_passed_count == len(ready_rules)
    selected_state = "ready" if not selected_failed else "needs_rule_repair"
    state = (
        "needs_rule_repair"
        if selected_failed
        else (
            "ready" if coverage_complete and physical_size_complete else "in_progress"
        )
    )
    payload = {
        "kind": "sciplot_ready_rule_acceptance",
        "version": RULE_ACCEPTANCE_VERSION,
        "generated_at": generated_at,
        "state": state,
        "selected_state": selected_state,
        "project_dir": str(project_dir),
        "selected_rule_ids": selected_ids,
        "failed_rule_ids": selected_failed,
        "coverage": {
            "ready_rule_count": len(ready_rules),
            "lifecycle_passed_count": passed_count,
            "lifecycle_complete": coverage_complete,
            "physical_size_passed_count": physical_size_passed_count,
            "physical_size_complete": physical_size_complete,
            "real_data_lifecycle_passed_count": real_data_passed_count,
            "instrument_shaped_gap_count": sum(
                not row["evidence"]["real_data_evidence"] for row in rows
            ),
        },
        "visual_review": visual_review["summary"],
        "matrix": rows,
        "limitations": [
            "A passed instrument-shaped fixture is not promoted to real-data acceptance.",
            "Exact-current publication QA is implemented separately; this matrix measures rule lifecycle and "
            "real-data breadth rather than journal compliance.",
            "Final PDF/TIFF dimensions are machine-checked. Contact sheets are uncalibrated overview previews "
            "whose explicit manual or agent decision does not prove final-physical-size readability.",
            "Explicit publication composition uses deterministic 183 mm figure-level layout metadata. "
            "This rule matrix does not infer composition from independent figures, and SciPlot has no "
            "standalone composition UI.",
        ],
    }
    summary_path = project_dir / "acceptance_summary.json"
    matrix_path = project_dir / "acceptance_matrix.json"
    csv_path = project_dir / "acceptance_matrix.csv"
    markdown_path = project_dir / "acceptance_matrix.md"
    summary_path.write_text(
        json.dumps(json_safe(payload), indent=2, ensure_ascii=False), encoding="utf-8"
    )
    matrix_path.write_text(
        json.dumps(json_safe(rows), indent=2, ensure_ascii=False), encoding="utf-8"
    )
    _write_rule_acceptance_csv(csv_path, rows)
    _write_rule_acceptance_markdown(markdown_path, payload)
    evidence_dashboard = write_evidence_status_dashboard(
        output_dir=project_dir,
        rows=rows,
        repo_root=repo_root,
        generated_at=generated_at,
    )
    payload["evidence_status"] = evidence_dashboard["summary"]
    payload["artifacts"] = {
        "summary": str(summary_path),
        "matrix_json": str(matrix_path),
        "matrix_csv": str(csv_path),
        "matrix_markdown": str(markdown_path),
        **visual_review["artifacts"],
        **evidence_dashboard["artifacts"],
    }
    summary_path.write_text(
        json.dumps(json_safe(payload), indent=2, ensure_ascii=False), encoding="utf-8"
    )
    return payload
