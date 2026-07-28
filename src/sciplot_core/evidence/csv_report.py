"""Write the evidence status CSV report."""

from __future__ import annotations

import csv
from pathlib import Path
from typing import Any


def _write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    fields = [
        "rule_id",
        "tier",
        "real_data_evidence",
        "authorization_status",
        "source_hash_status",
        "fixture_hash_status",
        "unit_status",
        "canonical_x_unit",
        "canonical_y_unit",
        "lifecycle_status",
        "physical_size_status",
        "source_url",
        "doi",
        "license",
        "fixture_path",
        "fixture_tree_sha256",
        "provenance_path",
        "rejection_reason",
        "limitations",
    ]
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        for row in rows:
            evidence = row["evidence"]
            writer.writerow(
                {
                    "rule_id": row["rule_id"],
                    "tier": evidence.get("tier"),
                    "real_data_evidence": evidence.get("real_data_evidence"),
                    "authorization_status": evidence.get("authorization_status"),
                    "source_hash_status": evidence.get("source_hash_status"),
                    "fixture_hash_status": evidence.get("fixture_hash_status"),
                    "unit_status": evidence.get("unit_status"),
                    "canonical_x_unit": evidence.get("canonical_units", {}).get("x"),
                    "canonical_y_unit": evidence.get("canonical_units", {}).get("y"),
                    "lifecycle_status": row.get("lifecycle_status"),
                    "physical_size_status": row.get("artifact_review", {}).get(
                        "status", "not_run"
                    ),
                    "source_url": evidence.get("source_url"),
                    "doi": evidence.get("doi"),
                    "license": evidence.get("license"),
                    "fixture_path": row.get("fixture_path"),
                    "fixture_tree_sha256": evidence.get("fixture_tree_sha256"),
                    "provenance_path": evidence.get("provenance_path"),
                    "rejection_reason": evidence.get("rejection_reason"),
                    "limitations": " | ".join(evidence.get("limitations") or []),
                }
            )
