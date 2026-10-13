"""Auto presentation reserves native marker geometry without moving explicit bounds."""

from dataclasses import replace
import math

import pytest

from sciplot_core.policy import MIN_VISUAL_EXTENT_CLEARANCE_MM
from sciplot_core.studio_render.axis_extent import _expand_axis_for_visual_extents
from sciplot_core.studio_render.models import (
    StudioSeries,
    _VeuszAxisContract,
    _VeuszStyleContract,
)


@pytest.mark.parametrize(
    ("marker", "radius", "stroke"),
    [("diamond", 1.414, math.sqrt(2.0)), ("triangle", 1.2, 2.001),
     ("circle", 1.0, 1.0)],
)
def test_auto_axis_reserves_native_shape_and_corner_stroke(
    marker: str, radius: float, stroke: float,
) -> None:
    # Deliberately synthetic values, unrelated to any local scientific corpus.
    series = [StudioSeries("edge", "x", "y", (10.0, 30.0), (1.0, 2.0),
                           "#000000", marker=marker, marker_size=2.0)]
    style = replace(_VeuszStyleContract(), marker_line_width_pt=0.8)
    expanded, diagnostics = _expand_axis_for_visual_extents(
        _VeuszAxisContract(x_min=9.6, x_max=30.4, y_min=0.0, y_max=3.0),
        request={}, render_options={}, template_id="point_line", series=series,
        categorical_contract=None, style=style, width_mm=60.0, height_mm=55.0,
    )
    required = (2.0 * radius + 0.4 * stroke) * 25.4 / 72.0 + MIN_VISUAL_EXTENT_CLEARANCE_MM
    observed = diagnostics["axes"]["x"]
    assert observed["required_extent_mm"] == pytest.approx(required)
    assert observed["lower_clearance_mm"] >= required - 1e-6
    assert observed["upper_clearance_mm"] >= required - 1e-6
    assert diagnostics["violations"] == []
    assert series[0].x_values == (10.0, 30.0)
    assert expanded.x_ticks == ()


def test_explicit_diamond_bounds_preserve_domain_and_report_corner_clipping() -> None:
    series = [StudioSeries("edge", "x", "y", (10.0, 30.0), (1.0, 2.0),
                           "#000000", marker="diamond", marker_size=2.0)]
    original = _VeuszAxisContract(x_min=9.4, x_max=30.6, y_min=0.0, y_max=3.0)
    expanded, diagnostics = _expand_axis_for_visual_extents(
        original, request={"render_options": {"x_min": original.x_min, "x_max": original.x_max}},
        render_options={}, template_id="point_line", series=series,
        categorical_contract=None,
        style=replace(_VeuszStyleContract(), marker_line_width_pt=0.8),
        width_mm=60.0, height_mm=55.0,
    )
    assert expanded.x_min == original.x_min
    assert expanded.x_max == original.x_max
    assert diagnostics["axes"]["x"]["status"] == "unsafe_explicit_bound"
    assert {(issue["axis"], issue["side"]) for issue in diagnostics["violations"]} == {
        ("x", "lower"), ("x", "upper"),
    }
