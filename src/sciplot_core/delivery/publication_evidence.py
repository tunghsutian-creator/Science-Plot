"""Collect QA hashes and publication artifact status."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from sciplot_core.delivery.contracts import (
    PUBLICATION_ARTIFACT_FILENAMES,
    PUBLICATION_ARTIFACT_KINDS,
)
from sciplot_core.figure_plan.artifact_locations import artifact_path_key


def _qa_hash_evidence(
    manifest: dict[str, Any], figure_records: list[dict[str, Any]]
) -> list[dict[str, Any]]:
    qa_value = manifest.get("qa")
    qa_payload = qa_value if isinstance(qa_value, dict) else {}
    qa_hashes = {
        artifact_path_key(str(report.get("path"))): str(
            report.get("sha256")
        )
        for report_group in (qa_payload.get(key) for key in ("pdfs", "tiffs", "pngs", "svgs"))
        if isinstance(report_group, list)
        for report in report_group
        if isinstance(report, dict) and report.get("path") and report.get("sha256")
    }
    return [
        {
            "source": record["source"],
            "qa_sha256": qa_hashes.get(
                artifact_path_key(record["source"])
            ),
            "source_sha256": record.get("source_sha256"),
            "delivery_sha256": record.get("delivery_sha256"),
        }
        for record in figure_records
    ]


def _publication_status(output_dir: Path) -> tuple[bool, list[dict[str, Any]]]:
    present = any(
        (output_dir / filename).exists() for filename in PUBLICATION_ARTIFACT_FILENAMES
    )
    if not present:
        return False, []
    statuses: list[dict[str, Any]] = []
    for filename in PUBLICATION_ARTIFACT_FILENAMES:
        path = output_dir / filename
        valid_json = False
        valid_contract = False
        if path.exists():
            try:
                import json

                payload = json.loads(path.read_text(encoding="utf-8"))
                valid_json = isinstance(payload, dict)
                valid_contract = (
                    valid_json
                    and payload.get("kind") == PUBLICATION_ARTIFACT_KINDS[filename]
                )
            except (OSError, ValueError):
                pass
        statuses.extend(
            [
                {
                    "id": f"{Path(filename).stem}_valid_json",
                    "path": str(path),
                    "exists": valid_json,
                },
                {
                    "id": f"{Path(filename).stem}_valid_contract",
                    "path": str(path),
                    "exists": valid_contract,
                },
            ]
        )
    return True, statuses
