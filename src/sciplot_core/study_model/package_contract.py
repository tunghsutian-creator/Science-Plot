"""Build and verify output package contracts."""

from __future__ import annotations

import copy
from pathlib import Path
from typing import Any

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
    result = manifest.get("result") if isinstance(manifest.get("result"), dict) else {}
    analysis_metrics = (
        result.get("analysis_metrics")
        if isinstance(result.get("analysis_metrics"), list)
        else []
    )
    if analysis_metrics:
        required.append(
            ("analysis_metrics", output_dir / "tables" / "analysis_metrics.csv")
        )
    raw_archive = (
        manifest.get("raw_archive")
        if isinstance(manifest.get("raw_archive"), dict)
        else {}
    )
    raw_path = raw_archive.get("path")
    if isinstance(raw_path, str) and raw_path.strip():
        required.append(("raw_archive", Path(raw_path)))
    publication_intent = (
        manifest.get("publication_intent")
        if isinstance(manifest.get("publication_intent"), dict)
        else {}
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
    artifact_status.extend(
        [
            {"id": "pdf", "path": "", "exists": has_pdf},
            {"id": "tiff_300", "path": "", "exists": has_tiff_300},
            {
                "id": "qa",
                "path": "",
                "exists": bool(
                    isinstance(manifest.get("qa"), dict)
                    and manifest["qa"].get("status") == "passed"
                ),
            },
        ]
    )
    if publication_intent:
        transform_ledger = (
            manifest.get("transform_ledger")
            if isinstance(manifest.get("transform_ledger"), dict)
            else {}
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
        publication_qa = (
            manifest.get("publication_qa")
            if isinstance(manifest.get("publication_qa"), dict)
            else {}
        )
        artifact_status.append(
            {
                "id": "publication_qa_passed",
                "path": str(output_dir / "publication_qa.json"),
                "exists": publication_qa.get("status") == "passed",
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
