from __future__ import annotations

from sciplot_core.studio_core.semantic_validation import (
    _semantic_series_contract_issues,
)
from sciplot_core.studio_render.models import StudioSeries


def test_gpc_arbitrary_nonoverlapping_domains_do_not_create_a_semantic_issue() -> None:
    series = [
        StudioSeries(
            label="sample_alpha",
            x_name="Molar mass",
            y_name="Differential weight fraction",
            x_values=(10_000.0, 20_000.0),
            y_values=(0.2, 0.3),
            color="#000000",
        ),
        StudioSeries(
            label="sample_beta",
            x_name="Molar mass",
            y_name="Differential weight fraction",
            x_values=(100_000.0, 200_000.0),
            y_values=(0.4, 0.5),
            color="#111111",
        ),
    ]

    issues = _semantic_series_contract_issues(
        series,
        request={"rule_id": "gpc_sec_chromatogram"},
    )

    assert issues == []
