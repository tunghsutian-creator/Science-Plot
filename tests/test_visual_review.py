from __future__ import annotations

import json
from pathlib import Path

import pytest
from PIL import Image

from sciplot_core import cli
from sciplot_core._utils import file_sha256
from sciplot_core import visual_review
from sciplot_core.visual_review import (
    FINAL_SIZE_VISUAL_DECISION_VERSION,
    FINAL_SIZE_VISUAL_REVIEW_VERSION,
    PENDING_REVIEW_STATUS,
    REQUIRED_PREVIEW_CHECKS,
    REVIEW_SURFACE,
    write_final_size_visual_review,
)


def _write_json(path: Path, payload: dict[str, object]) -> None:
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")


def _write_review_fixture(tmp_path: Path) -> tuple[Path, Path, Path]:
    project_dir = tmp_path / "acceptance_project"
    review_dir = project_dir / "final_size_visual_review"
    sheet = review_dir / "contact_sheets" / "contact_sheet_01.png"
    sheet.parent.mkdir(parents=True)
    Image.new("RGB", (32, 24), "white").save(sheet, format="PNG")

    generated_at = "2026-07-22T00:00:00+00:00"
    record = {
        "rule_id": "rule_a",
        "status": "passed",
        "expected_size_mm": [60.0, 55.0],
        "manifest": str(project_dir / "projects" / "rule_a" / "manifest.json"),
        "pdf": {
            "path": str(project_dir / "delivery" / "rule_a.pdf"),
            "physical_size_mm": [60.0, 55.0],
            "within_tolerance": True,
            "copy_hash_matches": True,
        },
        "tiff": {
            "path": str(project_dir / "delivery" / "rule_a_300dpi.tiff"),
            "physical_size_mm": [60.0, 55.0],
            "pixels": [709, 650],
            "dpi": [300.0, 300.0],
            "within_tolerance": True,
            "dpi_is_300": True,
            "copy_hash_matches": True,
        },
        "errors": [],
    }
    summary = {
        "rule_count": 1,
        "eligible_rule_count": 1,
        "physical_size_passed_count": 1,
        "physical_size_failed_count": 0,
        "not_run_count": 0,
        "contact_sheet_count": 1,
        "automated_status": "passed",
        "manual_visual_status": PENDING_REVIEW_STATUS,
        "review_surface": REVIEW_SURFACE,
        "physical_size_tolerance_mm": visual_review.PHYSICAL_SIZE_TOLERANCE_MM,
        "tiff_dpi_tolerance": visual_review.TIFF_DPI_TOLERANCE,
    }
    sheet_source = {
        "path": str(sheet.resolve()),
        "sha256": file_sha256(sheet),
        "pixels": [32, 24],
        "format": "PNG",
        "frame_count": 1,
        "review_surface": REVIEW_SURFACE,
    }
    review_path = review_dir / "final_size_visual_review.json"
    _write_json(
        review_path,
        {
            "kind": "sciplot_final_size_visual_review",
            "version": FINAL_SIZE_VISUAL_REVIEW_VERSION,
            "generated_at": generated_at,
            "summary": summary,
            "records": [record],
            "contact_sheets": [str(sheet)],
            "contact_sheet_sources": [sheet_source],
            "manual_review": {
                "status": PENDING_REVIEW_STATUS,
                "review_surface": REVIEW_SURFACE,
                "required_checks": list(REQUIRED_PREVIEW_CHECKS),
                "decision": None,
                "reviewed_at": None,
                "reviewer": None,
                "notes": [],
            },
            "limitations": [],
        },
    )

    acceptance_path = project_dir / "acceptance_summary.json"
    evidence_path = project_dir / "evidence_status.json"
    evidence_summary = {"rule_count": 1, "real_data_lifecycle_passed_count": 1}
    _write_json(
        evidence_path,
        {
            "kind": "sciplot_23_rule_evidence_status",
            "version": 1,
            "generated_at": generated_at,
            "summary": evidence_summary,
            "matrix": [{"rule_id": "rule_a"}],
        },
    )
    _write_json(
        acceptance_path,
        {
            "kind": "sciplot_ready_rule_acceptance",
            "version": 3,
            "generated_at": generated_at,
            "state": "ready",
            "selected_state": "ready",
            "selected_rule_ids": ["rule_a"],
            "visual_review": summary,
            "evidence_status": evidence_summary,
            "matrix": [{"rule_id": "rule_a", "artifact_review": record}],
            "artifacts": {
                "summary": str(acceptance_path),
                "visual_review_json": str(review_path),
                "visual_review_csv": str(review_path.with_suffix(".csv")),
                "visual_review_markdown": str(review_path.with_suffix(".md")),
                "visual_review_html": str(review_path.with_suffix(".html")),
                "visual_contact_sheet_01": str(sheet),
                "evidence_json": str(evidence_path),
            },
        },
    )
    return review_path, acceptance_path, evidence_path


@pytest.mark.parametrize(
    ("decision", "expected_exit", "expected_state"),
    [
        ("passed", 0, "ready"),
        ("failed", 1, "needs_rule_repair"),
    ],
)
def test_acceptance_visual_review_records_bound_preview_decision(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    decision: str,
    expected_exit: int,
    expected_state: str,
) -> None:
    review_path, acceptance_path, evidence_path = _write_review_fixture(tmp_path)

    exit_code = cli.main(
        [
            "acceptance",
            "visual-review",
            str(review_path),
            "--decision",
            decision,
            "--reviewer",
            "test-reviewer",
            "--note",
            "inspected as an uncalibrated preview",
            "--json",
        ]
    )

    assert exit_code == expected_exit
    result = json.loads(capsys.readouterr().out)
    decision_path = Path(result["decision_path"])
    assert decision_path.is_file()
    assert result["decision"]["decision"] == decision
    assert result["decision"]["version"] == FINAL_SIZE_VISUAL_DECISION_VERSION
    assert result["decision"]["review_surface"] == REVIEW_SURFACE
    assert result["decision"]["contact_sheet_sources"][0]["format"] == "PNG"
    review = json.loads(review_path.read_text(encoding="utf-8"))
    assert review["manual_review"]["decision"] == decision
    assert review["manual_review"]["reviewer"] == "test-reviewer"
    assert set(review["manual_review"]["checks"]) == set(REQUIRED_PREVIEW_CHECKS)
    acceptance = json.loads(acceptance_path.read_text(encoding="utf-8"))
    assert acceptance["state"] == expected_state
    assert acceptance["visual_review"]["manual_visual_status"] == decision
    assert acceptance["artifacts"]["visual_review_json_sha256"] == file_sha256(
        review_path
    )
    assert acceptance["artifacts"]["manual_visual_review_decision_sha256"] == file_sha256(
        decision_path
    )
    evidence = json.loads(evidence_path.read_text(encoding="utf-8"))
    assert evidence["summary"]["manual_visual_status"] == decision
    assert evidence["summary"]["review_surface"] == REVIEW_SURFACE
    assert "do not establish final-size legibility" in review_path.with_suffix(
        ".html"
    ).read_text(encoding="utf-8")


@pytest.mark.parametrize(
    "corruption",
    ["summary", "rule_ids", "check_set", "acceptance_binding"],
)
def test_visual_review_rejects_unbound_or_incoherent_sources_before_writing(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    corruption: str,
) -> None:
    review_path, acceptance_path, evidence_path = _write_review_fixture(tmp_path)
    review = json.loads(review_path.read_text(encoding="utf-8"))
    acceptance = json.loads(acceptance_path.read_text(encoding="utf-8"))
    if corruption == "summary":
        review["summary"]["physical_size_passed_count"] = 999
        _write_json(review_path, review)
    elif corruption == "rule_ids":
        review["records"][0]["rule_id"] = "forged_rule"
        _write_json(review_path, review)
    elif corruption == "check_set":
        review["manual_review"]["required_checks"].pop()
        _write_json(review_path, review)
    else:
        acceptance["artifacts"]["visual_review_json"] = str(tmp_path / "other.json")
        _write_json(acceptance_path, acceptance)
    before = {
        review_path: review_path.read_bytes(),
        acceptance_path: acceptance_path.read_bytes(),
        evidence_path: evidence_path.read_bytes(),
    }

    assert (
        cli.main(
            [
                "acceptance",
                "visual-review",
                str(review_path),
                "--decision",
                "passed",
                "--reviewer",
                "test-reviewer",
            ]
        )
        == 1
    )
    assert "Error:" in capsys.readouterr().err
    assert all(path.read_bytes() == content for path, content in before.items())
    assert not (review_path.parent / "manual_visual_review_decision.json").exists()


def test_visual_review_rejects_changed_or_undecodable_png_before_writing(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    review_path, acceptance_path, evidence_path = _write_review_fixture(tmp_path)
    sheet = review_path.parent / "contact_sheets" / "contact_sheet_01.png"
    sheet.write_bytes(b"not a PNG")
    before = {
        review_path: review_path.read_bytes(),
        acceptance_path: acceptance_path.read_bytes(),
        evidence_path: evidence_path.read_bytes(),
    }

    assert (
        cli.main(
            [
                "acceptance",
                "visual-review",
                str(review_path),
                "--decision",
                "passed",
                "--reviewer",
                "test-reviewer",
            ]
        )
        == 1
    )
    assert "decodable PNG" in capsys.readouterr().err
    assert all(path.read_bytes() == content for path, content in before.items())
    assert not (review_path.parent / "manual_visual_review_decision.json").exists()


def test_visual_review_transaction_rolls_back_every_target(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    review_path, acceptance_path, evidence_path = _write_review_fixture(tmp_path)
    before = {
        review_path: review_path.read_bytes(),
        acceptance_path: acceptance_path.read_bytes(),
        evidence_path: evidence_path.read_bytes(),
    }
    real_replace = visual_review.os.replace
    calls = 0

    def fail_third_replace(source: str | Path, target: str | Path) -> None:
        nonlocal calls
        calls += 1
        if calls == 3:
            raise OSError("injected replacement failure")
        real_replace(source, target)

    monkeypatch.setattr(visual_review.os, "replace", fail_third_replace)

    assert (
        cli.main(
            [
                "acceptance",
                "visual-review",
                str(review_path),
                "--decision",
                "passed",
                "--reviewer",
                "test-reviewer",
            ]
        )
        == 1
    )
    assert "injected replacement failure" in capsys.readouterr().err
    assert all(path.read_bytes() == content for path, content in before.items())
    assert not review_path.with_suffix(".md").exists()
    assert not review_path.with_suffix(".html").exists()
    assert not (review_path.parent / "manual_visual_review_decision.json").exists()
    assert not list(tmp_path.rglob("*.tmp"))


def test_new_visual_review_run_removes_stale_decision_artifacts(tmp_path: Path) -> None:
    review_dir = tmp_path / "final_size_visual_review"
    review_dir.mkdir()
    stale_decision = review_dir / "manual_visual_review_decision.json"
    stale_decision.write_text('{"decision": "passed"}\n', encoding="utf-8")

    write_final_size_visual_review(output_dir=tmp_path, rows=[])

    assert not stale_decision.exists()
