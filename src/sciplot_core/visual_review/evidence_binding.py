"""Validate acceptance, evidence, and existing-decision bindings."""

from __future__ import annotations

from pathlib import Path
from typing import Any
from sciplot_core.foundation.file_hashing import file_sha256
from sciplot_core.readiness import READY_RULE_ACCEPTANCE_VERSION

from sciplot_core.visual_review.transaction import (
    FINAL_SIZE_VISUAL_DECISION_VERSION,
)


def _resolved_artifact_path(value: object, *, root: Path, label: str) -> Path:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"Acceptance artifact `{label}` is missing.")
    path = Path(value).expanduser()
    return (root / path if not path.is_absolute() else path).resolve()


def _validate_acceptance_binding(
    acceptance: dict[str, Any],
    *,
    acceptance_path: Path,
    review_path: Path,
    review_payload: dict[str, Any],
    records: list[dict[str, Any]],
    contact_sheets: list[Path],
    evidence_path: Path,
    decision_path: Path,
    source_sha256: str,
) -> None:
    if acceptance.get("kind") != "sciplot_ready_rule_acceptance":
        raise ValueError("Not a SciPlot ready-rule acceptance summary.")
    version = acceptance.get("version")
    if type(version) is not int or version != READY_RULE_ACCEPTANCE_VERSION:
        raise ValueError("Unsupported ready-rule acceptance version.")
    if acceptance.get("generated_at") != review_payload["generated_at"]:
        raise ValueError(
            "Acceptance and visual-review generation timestamps do not match."
        )
    if acceptance.get("visual_review") != review_payload["summary"]:
        raise ValueError(
            "Acceptance visual-review summary is not the supplied review source."
        )
    artifacts = acceptance.get("artifacts")
    if not isinstance(artifacts, dict):
        raise ValueError("Acceptance artifacts are missing.")
    root = acceptance_path.parent
    expected_artifacts = {
        "summary": acceptance_path,
        "visual_review_json": review_path,
        "visual_review_csv": review_path.with_suffix(".csv"),
        "visual_review_markdown": review_path.with_suffix(".md"),
        "visual_review_html": review_path.with_suffix(".html"),
        "evidence_json": evidence_path,
    }
    for key, expected in expected_artifacts.items():
        if (
            _resolved_artifact_path(artifacts.get(key), root=root, label=key)
            != expected
        ):
            raise ValueError(
                f"Acceptance artifact `{key}` is not bound to this review run."
            )
    expected_sheet_keys = {
        f"visual_contact_sheet_{index:02d}"
        for index in range(1, len(contact_sheets) + 1)
    }
    actual_sheet_keys = {
        str(key) for key in artifacts if str(key).startswith("visual_contact_sheet_")
    }
    if actual_sheet_keys != expected_sheet_keys:
        raise ValueError(
            "Acceptance contact-sheet artifact set does not match the review source."
        )
    for index, sheet in enumerate(contact_sheets, start=1):
        key = f"visual_contact_sheet_{index:02d}"
        if _resolved_artifact_path(artifacts.get(key), root=root, label=key) != sheet:
            raise ValueError(
                f"Acceptance artifact `{key}` is not bound to the reviewed PNG."
            )
    stored_review_hash = artifacts.get("visual_review_json_sha256")
    if stored_review_hash is not None and stored_review_hash != source_sha256:
        raise ValueError("Acceptance visual-review source hash no longer matches.")
    stored_decision = artifacts.get("manual_visual_review_decision")
    if stored_decision is not None and (
        _resolved_artifact_path(
            stored_decision, root=root, label="manual_visual_review_decision"
        )
        != decision_path
    ):
        raise ValueError(
            "Acceptance manual-decision artifact points outside this review run."
        )

    matrix = acceptance.get("matrix")
    if not isinstance(matrix, list) or not all(isinstance(row, dict) for row in matrix):
        raise ValueError("Acceptance matrix is invalid.")
    matrix_ids = [row.get("rule_id") for row in matrix]
    record_ids = [record["rule_id"] for record in records]
    if matrix_ids != record_ids or len(set(matrix_ids)) != len(matrix_ids):
        raise ValueError(
            "Acceptance matrix rule ids do not match the visual-review records."
        )
    for row, record in zip(matrix, records, strict=True):
        if row.get("artifact_review") != record:
            raise ValueError(
                f"Acceptance artifact review for `{record['rule_id']}` does not match the review source."
            )
    selected = acceptance.get("selected_rule_ids")
    if not isinstance(selected, list) or len(set(selected)) != len(selected):
        raise ValueError("Acceptance selected rule ids are invalid.")
    eligible_ids = {
        record["rule_id"] for record in records if record["status"] != "not_run"
    }
    if set(selected) != eligible_ids:
        raise ValueError(
            "Acceptance selected rule ids do not match eligible visual-review records."
        )


def _validate_evidence_binding(
    evidence: dict[str, Any],
    *,
    acceptance: dict[str, Any],
    generated_at: str,
    record_ids: list[str],
) -> None:
    if evidence.get("kind") != "sciplot_23_rule_evidence_status":
        raise ValueError("Not a SciPlot rule-evidence status artifact.")
    if type(evidence.get("version")) is not int or evidence["version"] != 1:
        raise ValueError("Unsupported rule-evidence status version.")
    if evidence.get("generated_at") != generated_at:
        raise ValueError(
            "Evidence and visual-review generation timestamps do not match."
        )
    if not isinstance(evidence.get("summary"), dict):
        raise ValueError("Evidence summary is invalid.")
    if acceptance.get("evidence_status") != evidence["summary"]:
        raise ValueError("Acceptance and evidence summaries are not bound.")
    matrix = evidence.get("matrix")
    if not isinstance(matrix, list) or not all(isinstance(row, dict) for row in matrix):
        raise ValueError("Evidence matrix is invalid.")
    if [row.get("rule_id") for row in matrix] != record_ids:
        raise ValueError(
            "Evidence matrix rule ids do not match the visual-review records."
        )


def _validate_existing_decision(
    decision: dict[str, Any],
    *,
    decision_path: Path,
    review_path: Path,
    acceptance: dict[str, Any],
) -> None:
    if decision.get("kind") != "sciplot_final_size_visual_decision":
        raise ValueError("Existing manual visual decision has the wrong kind.")
    if (
        type(decision.get("version")) is not int
        or decision["version"] != FINAL_SIZE_VISUAL_DECISION_VERSION
    ):
        raise ValueError("Existing manual visual decision has an unsupported version.")
    if (
        Path(str(decision.get("review_source") or "")).expanduser().resolve()
        != review_path
    ):
        raise ValueError(
            "Existing manual visual decision belongs to another review source."
        )
    artifacts = acceptance.get("artifacts")
    if not isinstance(artifacts, dict):
        raise ValueError("Acceptance artifacts are missing.")
    root = decision_path.parent.parent
    if (
        _resolved_artifact_path(
            artifacts.get("manual_visual_review_decision"),
            root=root,
            label="manual_visual_review_decision",
        )
        != decision_path
    ):
        raise ValueError("Acceptance is not bound to the existing manual decision.")
    expected_hash = artifacts.get("manual_visual_review_decision_sha256")
    if expected_hash != file_sha256(decision_path):
        raise ValueError(
            "Existing manual visual decision hash no longer matches acceptance."
        )
