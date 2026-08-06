"""Build and verify output package contracts."""

from __future__ import annotations

import copy
from pathlib import Path
from typing import Any

from sciplot_core.figure_plan.manifest_gate import figure_plan_manifest_gate

from sciplot_core.study_model.run_artifacts import (
    _json_contract_matches,
)


def build_output_package_contract(
    output_dir: Path, *, manifest: dict[str, Any]
) -> dict[str, Any]:
    figures = [
        Path(path) for path in manifest.get("figures", []) if isinstance(path, str)
    ]
    required = [
        ("request_snapshot", output_dir / "request_snapshot.json"),
        ("manifest", output_dir / "manifest.json"),
        ("review_html", output_dir / "review.html"),
        ("revision_brief", output_dir / "revision_brief.md"),
    ]
    result_value = manifest.get("result")
    result = result_value if isinstance(result_value, dict) else {}
    analysis_metrics_value = result.get("analysis_metrics")
    analysis_metrics = (
        analysis_metrics_value if isinstance(analysis_metrics_value, list) else []
    )
    if analysis_metrics:
        required.append(
            ("analysis_metrics", output_dir / "tables" / "analysis_metrics.csv")
        )
    raw_archive_value = manifest.get("raw_archive")
    raw_archive = raw_archive_value if isinstance(raw_archive_value, dict) else {}
    raw_path = raw_archive.get("path")
    if isinstance(raw_path, str) and raw_path.strip():
        required.append(("raw_archive", Path(raw_path)))
    publication_intent_value = manifest.get("publication_intent")
    publication_intent = (
        publication_intent_value if isinstance(publication_intent_value, dict) else {}
    )
    if publication_intent:
        required.extend(
            [
                ("publication_intent", output_dir / "publication_intent.json"),
                ("transform_ledger", output_dir / "transform_ledger.json"),
                ("journal_profile", output_dir / "journal_profile.json"),
                ("publication_qa", output_dir / "publication_qa.json"),
            ]
        )
    artifact_status = [
        {
            "id": artifact_id,
            "path": str(path),
            "exists": path.exists(),
        }
        for artifact_id, path in required
    ]
    has_pdf = any(path.suffix.lower() == ".pdf" and path.exists() for path in figures)
    has_tiff_300 = any(
        path.name.casefold().endswith("_300dpi.tiff") and path.exists()
        for path in figures
    )
    qa_value = manifest.get("qa")
    qa = qa_value if isinstance(qa_value, dict) else {}
    artifact_status.extend(
        [
            {"id": "pdf", "path": "", "exists": has_pdf},
            {"id": "tiff_300", "path": "", "exists": has_tiff_300},
            {
                "id": "qa",
                "path": "",
                "exists": qa.get("status") == "passed",
            },
        ]
    )
    if publication_intent:
        transform_ledger_value = manifest.get("transform_ledger")
        transform_ledger = (
            transform_ledger_value if isinstance(transform_ledger_value, dict) else {}
        )
        artifact_status.append(
            {
                "id": "transform_lineage_reviewed",
                "path": str(output_dir / "transform_ledger.json"),
                "exists": transform_ledger.get("status")
                in {"runtime_recorded", "confirmed"},
            }
        )
        for filename, kind in {
            "publication_intent.json": "sciplot_publication_intent",
            "transform_ledger.json": "sciplot_transform_ledger",
            "journal_profile.json": "sciplot_publication_profile",
            "publication_qa.json": "sciplot_publication_qa",
        }.items():
            artifact_status.append(
                {
                    "id": f"{Path(filename).stem}_valid_contract",
                    "path": str(output_dir / filename),
                    "exists": _json_contract_matches(output_dir / filename, kind),
                }
            )
    if publication_intent.get("target_status") == "confirmed":
        publication_qa_value = manifest.get("publication_qa")
        publication_qa = (
            publication_qa_value if isinstance(publication_qa_value, dict) else {}
        )
        artifact_status.append(
            {
                "id": "publication_qa_passed",
                "path": str(output_dir / "publication_qa.json"),
                "exists": publication_qa.get("status") == "passed",
            }
        )
    plan_gate = figure_plan_manifest_gate(manifest)
    if plan_gate is not None:
        artifact_status.append(
            {
                "id": "resolved_figure_plan_complete",
                "path": str(output_dir / "manifest.json"),
                "exists": bool(
                    plan_gate["valid"] is True and plan_gate["complete"] is True
                ),
                "details": plan_gate,
            }
        )
    return {
        "kind": "sciplot_output_package_contract",
        "version": 1,
        "complete": all(item["exists"] for item in artifact_status),
        "artifacts": artifact_status,
    }


def verify_output_package_contract(
    package_contract: object,
    *,
    output_dir: Path,
    manifest: dict[str, Any],
) -> dict[str, Any]:
    """Rebuild the output contract from live artifacts and compare it exactly."""

    recorded = package_contract if isinstance(package_contract, dict) else {}
    expected = build_output_package_contract(
        output_dir.expanduser().resolve(),
        manifest=manifest,
    )
    checks = {
        "record_kind_current": recorded.get("kind") == "sciplot_output_package_contract"
        and recorded.get("version") == 1,
        "recorded_complete": recorded.get("complete") is True,
        "live_complete": expected.get("complete") is True,
        "artifact_records_match_live": recorded.get("artifacts")
        == expected.get("artifacts"),
    }
    return {
        "kind": "sciplot_output_package_verification",
        "version": 1,
        "passed": all(checks.values()),
        "checks": checks,
        "failed_checks": [key for key, passed in checks.items() if not passed],
        "recorded": copy.deepcopy(recorded),
        "expected": copy.deepcopy(expected),
    }
