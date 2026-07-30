from __future__ import annotations

from pathlib import Path

from sciplot_core.evidence.html_report import _write_html
from sciplot_core.evidence.markdown_report import _write_markdown


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
