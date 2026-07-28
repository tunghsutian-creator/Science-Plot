"""Summarize evidence rows by lifecycle and evidence tier."""

from __future__ import annotations

from typing import Any


def _status_summary(rows: list[dict[str, Any]]) -> dict[str, Any]:
    authorization_ready = {
        "license_verified",
        "license_recorded",
        "user_authorized",
        "user_authorized_archive",
    }
    return {
        "rule_count": len(rows),
        "real_data_evidence_count": sum(
            bool(row["evidence"].get("real_data_evidence")) for row in rows
        ),
        "authorization_ready_count": sum(
            row["evidence"].get("authorization_status") in authorization_ready
            for row in rows
        ),
        "source_hash_registered_count": sum(
            row["evidence"].get("source_hash_status") == "registered" for row in rows
        ),
        "fixture_hash_verified_count": sum(
            row["evidence"].get("fixture_hash_status") == "verified" for row in rows
        ),
        "fixture_hash_computed_count": sum(
            row["evidence"].get("fixture_hash_status")
            in {"verified", "computed_unregistered"}
            for row in rows
        ),
        "source_and_output_units_registered_count": sum(
            row["evidence"].get("unit_status") == "source_and_output_registered"
            for row in rows
        ),
        "lifecycle_passed_count": sum(
            row.get("lifecycle_status") == "passed" for row in rows
        ),
        "physical_size_passed_count": sum(
            row.get("artifact_review", {}).get("status") == "passed" for row in rows
        ),
        "real_data_gap_count": sum(
            not row["evidence"].get("real_data_evidence") for row in rows
        ),
    }
