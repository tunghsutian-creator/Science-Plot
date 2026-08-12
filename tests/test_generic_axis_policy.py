from __future__ import annotations

import pytest

from sciplot_core.policy import LINEAR_OUTER_PADDING_FRACTION
from sciplot_core.studio_render.axis_contract import _veusz_axis_contract
from sciplot_core.studio_render.axis_limits import compute_axis_limits
from sciplot_core.studio_render.models import StudioSeries


_OBSERVED_X = (3.5, 10.0, 41.0)


def test_generic_linear_axis_padding_uses_the_observed_span() -> None:
    limits = compute_axis_limits(
        [[1.0, 2.0, 3.0]],
        kind="line",
        x_values=[_OBSERVED_X],
    )

    assert limits.raw_xlim is not None
    observed_min, observed_max = limits.raw_xlim
    observed_span = observed_max - observed_min
    padding = observed_span * LINEAR_OUTER_PADDING_FRACTION
    assert limits.xlim == pytest.approx(
        (observed_min - padding, observed_max + padding)
    )
    assert limits.x_tick_policy is not None
    ticks = limits.x_tick_policy.major_ticks
    assert ticks
    assert limits.x_tick_policy.labeled_bounds == (ticks[0], ticks[-1])
    assert all(limits.xlim[0] < tick < limits.xlim[1] for tick in ticks)


def test_reverse_linear_axis_only_reverses_bounds_and_major_ticks() -> None:
    series = [
        StudioSeries(
            label="Observed series",
            x_name="x_observed",
            y_name="y_observed",
            x_values=_OBSERVED_X,
            y_values=(1.0, 2.0, 3.0),
            color="#374E55",
        )
    ]
    forward = _veusz_axis_contract(
        {},
        template_id="curve",
        series=series,
        explicit_render_options={},
    )
    reverse = _veusz_axis_contract(
        {"reverse_x": True},
        template_id="curve",
        series=series,
        explicit_render_options={},
    )

    assert reverse.x_min == pytest.approx(forward.x_max)
    assert reverse.x_max == pytest.approx(forward.x_min)
    assert reverse.x_ticks == tuple(reversed(forward.x_ticks))
    assert forward.x_min not in forward.x_ticks
    assert forward.x_max not in forward.x_ticks
    assert reverse.x_min not in reverse.x_ticks
    assert reverse.x_max not in reverse.x_ticks
