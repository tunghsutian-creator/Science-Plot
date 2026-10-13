from __future__ import annotations

from pathlib import Path

import pytest

from sciplot_core.evidence.evidence_status import _fixture_hash_status
from sciplot_core.evidence.html_report import _write_html
from sciplot_core.evidence.markdown_report import _write_markdown
from sciplot_core.evidence.provenance import _expected_fixture_hashes
from sciplot_core.verification.changed import build_changed_verification_plan


def _evidence_payload(*, rule_count: int) -> dict[str, object]:
    return {
        "generated_at": "2026-07-29T00:00:00+00:00",
        "summary": {
            "rule_count": rule_count,
            "real_data_evidence_count": rule_count,
            "authorization_ready_count": rule_count,
            "source_hash_registered_count": rule_count,
            "fixture_hash_verified_count": rule_count,
            "lifecycle_passed_count": rule_count,
            "physical_size_passed_count": rule_count,
        },
        "matrix": [],
        "candidate_rejections": [],
    }


def test_evidence_report_titles_follow_the_current_rule_count(
    tmp_path: Path,
) -> None:
    payload = _evidence_payload(rule_count=24)
    markdown_path = tmp_path / "evidence.md"
    html_path = tmp_path / "evidence.html"

    _write_markdown(markdown_path, payload)
    _write_html(html_path, payload)

    assert markdown_path.read_text(encoding="utf-8").startswith(
        "# SciPlot 24-rule evidence status"
    )
    html = html_path.read_text(encoding="utf-8")
    assert "<title>SciPlot 24-rule evidence status</title>" in html
    assert "<h1>SciPlot 24-rule evidence status</h1>" in html


@pytest.mark.parametrize("provenance", [
    {"kind": "sciplot_digitized_fixture_provenance", "version": 1,
     "output_csv": "trace.csv", "output_csv_sha256": "a" * 64},
    {"kind": "sciplot_user_authorized_real_fixture_provenance", "version": 1,
     "source_data_status": "exact_unmodified_user_authorized_instrument_exports",
     "source_files": [{"source_file": "trace.csv", "source_sha256": "a" * 64}]},
])
def test_registered_legacy_fixture_hashes_verify_and_detect_drift(
    tmp_path: Path, provenance: dict[str, object],
) -> None:
    fixture = tmp_path / "trace.csv"
    fixture.write_text("placeholder for a hash-status unit test")
    inventory = [{"path": fixture.name, "sha256": "a" * 64}]

    assert _fixture_hash_status(fixture, inventory, {}, provenance)[0] == "verified"
    inventory[0]["sha256"] = "b" * 64
    status, checks = _fixture_hash_status(fixture, inventory, {}, provenance)
    assert status == "mismatch"
    assert checks[0]["expected_sha256"] == "a" * 64


@pytest.mark.parametrize("change", [
    {"source_data_status": "derived_excerpt"},
    {"kind": "unrecognized_provenance"},
    {"version": 2},
])
def test_registered_source_hash_is_not_implicitly_a_fixture_hash(
    change: dict[str, object],
) -> None:
    provenance = {
        "kind": "sciplot_user_authorized_real_fixture_provenance", "version": 1,
        "source_data_status": "exact_unmodified_user_authorized_instrument_exports",
        "source_files": [{"source_file": "trace.csv", "source_sha256": "a" * 64}],
        **change,
    }
    assert _expected_fixture_hashes(provenance) == {}


def test_digitized_output_hash_does_not_verify_an_unrelated_fixture(tmp_path: Path) -> None:
    fixture = tmp_path / "other.csv"
    fixture.write_text("different output")
    provenance = {
        "kind": "sciplot_digitized_fixture_provenance", "version": 1,
        "output_csv": "trace.csv", "output_csv_sha256": "a" * 64,
    }
    status, _ = _fixture_hash_status(
        fixture, [{"path": fixture.name, "sha256": "a" * 64}], {}, provenance,
    )
    assert status == "computed_unregistered"


def test_fixture_hash_evidence_has_a_focused_changed_owner() -> None:
    root = Path(__file__).resolve().parents[1]
    plan = build_changed_verification_plan([
        "src/sciplot_core/evidence/provenance.py", "tests/test_evidence_reports.py",
    ], repo_root=root)
    assert plan["unowned_paths"] == []
    assert "fixture_provenance_evidence" in {owner["owner_id"] for owner in plan["owners"]}
    assert any("tests/test_evidence_reports.py" in check["command"]
               for check in plan["checks"])
