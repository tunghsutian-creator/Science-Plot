from __future__ import annotations

import pytest

from sciplot_core.studio_render.models import StudioSeries
from sciplot_core.studio_render.replicate_distribution_contract import (
    _replicate_distribution_contract,
)


@pytest.mark.parametrize(
    ("template_id", "expects_bar_statistics"),
    [("bar", True), ("box", False), ("box_strip", False)],
)
def test_replicate_contract_exposes_only_active_summary_fields(
    template_id: str,
    expects_bar_statistics: bool,
) -> None:
    contract = _replicate_distribution_contract(
        [
            StudioSeries(
                label="sample",
                x_name="sample",
                y_name="metric",
                x_values=(0.9, 1.0, 1.1),
                y_values=(1.0, 2.0, 3.0),
                color="#222222",
                presentation_kind="categorical_replicates",
                category_position=1.0,
            )
        ],
        template_id=template_id,
        render_options={"summary_statistic": "median_iqr"},
    )

    assert contract is not None
    bar_fields = {"bar_mean", "bar_error", "bar_error_statistic"}
    group = contract["groups"][0]
    if expects_bar_statistics:
        assert bar_fields <= group.keys()
        assert group["bar_mean"] == pytest.approx(2.0)
        assert group["bar_error"] == pytest.approx(1.0)
        assert group["bar_error_statistic"] == "sd"
        assert contract["bar_error_statistic"] == "sd"
    else:
        assert bar_fields.isdisjoint(group)
        assert "bar_error_statistic" not in contract
