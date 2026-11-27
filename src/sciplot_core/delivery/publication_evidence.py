"""Collect QA hashes and publication artifact status."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from sciplot_core.delivery.contracts import (
    PUBLICATION_ARTIFACT_FILENAMES,
    PUBLICATION_ARTIFACT_KINDS,
)
from sciplot_core.figure_plan.artifact_locations import artifact_path_key


def qa_artifact_observations(manifest: dict[str, Any]) -> dict[str, dict[str, Any]]:
    """Index the run's format-specific QA observations without reopening artifacts."""
    qa_value = manifest.get("qa")
    qa = qa_value if isinstance(qa_value, dict) else {}
    observations: dict[str, dict[str, Any]] = {}
    for key, fmt in (("pdfs", "pdf"), ("tiffs", "tiff_300"), ("pngs", None), ("svgs", "svg")):
        reports = qa.get(key)
        if isinstance(reports, list):
            for report in reports:
                if isinstance(report, dict) and report.get("path") and report.get("sha256"):
                    path = artifact_path_key(str(report["path"]))
                    observations[path] = {} if path in observations else {
                        **report, "export_format": fmt or report.get("export_format"),
                    }
    return observations


def _qa_hash_evidence(
    manifest: dict[str, Any], figure_records: list[dict[str, Any]]
) -> list[dict[str, Any]]:
    observations = qa_artifact_observations(manifest)
    return [
        {
            "source": record["source"],
            "qa_sha256": observations.get(artifact_path_key(record["source"]), {}).get("sha256"),
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
