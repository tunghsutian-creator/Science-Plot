from __future__ import annotations

from sciplot_core.studio_core.semantic_validation import (
    _semantic_series_contract_issues,
)
from sciplot_core.studio_render.models import StudioSeries


def test_gpc_arbitrary_nonoverlapping_domains_do_not_create_a_semantic_issue() -> None:
    series = [
        StudioSeries(
            label="sample_alpha",
            x_name="Elution time",
            y_name="Detector response",
            x_values=(0.0, 1.0),
            y_values=(2.0, 3.0),
            color="#000000",
        ),
        StudioSeries(
            label="sample_beta",
            x_name="Elution time",
            y_name="Detector response",
            x_values=(10.0, 11.0),
            y_values=(4.0, 5.0),
            color="#111111",
        ),
    ]

    issues = _semantic_series_contract_issues(
        series,
        request={"rule_id": "gpc_sec_chromatogram"},
    )

    assert issues == []
