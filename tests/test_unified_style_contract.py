from __future__ import annotations

import pytest

from sciplot_core.contract import load_plot_contract
from sciplot_core.one_step import _ISSUE_QUALITY_ACTIONS
from sciplot_core.policy import (
    UNIFIED_AXIS_LINEWIDTH_PT,
    UNIFIED_FONT_FAMILY,
    UNIFIED_FONT_SIZE_PT,
    UNIFIED_LEGEND_FONT_SIZE_PT,
    UNIFIED_LINE_WIDTH_PT,
    UNIFIED_MARKER_SIZE_PT,
    UNIFIED_MINOR_TICK_WIDTH_PT,
    UNIFIED_PANEL_LABEL_SIZE_PT,
    UNIFIED_TICK_WIDTH_PT,
)
from sciplot_core.studio import StudioSeries, _apply_series_options, _veusz_style_contract
from sciplot_core.workbench_contract import normalize_render_options


def test_all_public_styles_share_the_unified_typography_and_strokes() -> None:
    contract = load_plot_contract()
    expected = {
        "font_family": (UNIFIED_FONT_FAMILY,),
        "font_size_pt": UNIFIED_FONT_SIZE_PT,
        "legend_font_size_pt": UNIFIED_LEGEND_FONT_SIZE_PT,
        "panel_label_size_pt": UNIFIED_PANEL_LABEL_SIZE_PT,
        "axis_linewidth_pt": UNIFIED_AXIS_LINEWIDTH_PT,
        "tick_width_pt": UNIFIED_TICK_WIDTH_PT,
        "minor_tick_width_pt": UNIFIED_MINOR_TICK_WIDTH_PT,
        "line_width_pt": UNIFIED_LINE_WIDTH_PT,
        "marker_size_pt": UNIFIED_MARKER_SIZE_PT,
    }

    for style in contract.styles.values():
        assert style.typography.font_family == expected["font_family"]
        assert style.typography.font_size_pt == expected["font_size_pt"]
        assert style.typography.legend_font_size_pt == expected["legend_font_size_pt"]
        assert style.typography.panel_label_size_pt == expected["panel_label_size_pt"]
        assert style.stroke.axis_linewidth_pt == expected["axis_linewidth_pt"]
        assert style.stroke.tick_width_pt == expected["tick_width_pt"]
        assert style.stroke.minor_tick_width_pt == expected["minor_tick_width_pt"]
        assert style.stroke.line_width_pt == expected["line_width_pt"]
        assert style.stroke.marker_size_pt == expected["marker_size_pt"]


def test_style_preset_and_request_overrides_cannot_change_hard_values() -> None:
    style = _veusz_style_contract(
        {
            "style_preset": "wiley",
            "font_size_pt": 11.0,
            "legend_font_size_pt": 10.0,
            "axis_linewidth_pt": 2.0,
            "tick_width_pt": 2.0,
            "minor_tick_width_pt": 0.2,
            "line_width_pt": 3.0,
            "marker_size": 9.0,
        }
    )

    assert style.font_family == UNIFIED_FONT_FAMILY
    assert style.font_size_pt == UNIFIED_FONT_SIZE_PT
    assert style.legend_font_size_pt == UNIFIED_LEGEND_FONT_SIZE_PT
    assert style.axis_linewidth_pt == UNIFIED_AXIS_LINEWIDTH_PT
    assert style.tick_width_pt == UNIFIED_TICK_WIDTH_PT
    assert style.minor_tick_width_pt == UNIFIED_MINOR_TICK_WIDTH_PT
    assert style.line_width_pt == UNIFIED_LINE_WIDTH_PT
    assert style.marker_size_pt == UNIFIED_MARKER_SIZE_PT


def test_series_specific_line_and_marker_sizes_are_hard_standardized() -> None:
    series = [
        StudioSeries(
            label="sample",
            x_name="x",
            y_name="y",
            x_values=(0.0, 1.0),
            y_values=(1.0, 2.0),
            color="#000000",
        )
    ]

    styled = _apply_series_options(
        series,
        render_options={
            "series_styles": [{"label": "sample", "line_width": 4.0, "marker_size": 8.0}],
            "marker_sequence": ["circle"],
        },
        request={"template": "point_line"},
    )

    assert styled[0].line_width == UNIFIED_LINE_WIDTH_PT
    assert styled[0].marker_size == UNIFIED_MARKER_SIZE_PT


def test_legacy_hard_style_options_are_accepted_but_removed_from_requests() -> None:
    normalized = normalize_render_options(
        {
            "font_size_pt": 12.0,
            "line_width_pt": 4.0,
            "marker_size": 9.0,
            "size": "60x55",
        },
        template="point_line",
    )

    assert normalized == {"size": "60x55"}


def test_invalid_legacy_hard_style_options_fail_before_they_are_removed() -> None:
    for key in ("font_size_pt", "line_width_pt", "marker_size"):
        with pytest.raises(ValueError, match=key):
            normalize_render_options(
                {key: 0, "size": "60x55"},
                template="point_line",
            )


def test_renderer_owned_axis_minor_tick_options_survive_workbench_validation() -> None:
    normalized = normalize_render_options(
        {
            "x_minor_tick_count": 5,
            "y_minor_tick_count": 5,
            "x_minor_ticks": [-0.8, -0.6, -0.4, -0.2],
            "y_minor_ticks": [2.0, 4.0, 6.0, 8.0],
        },
        template="point_line",
    )

    assert normalized == {
        "x_minor_tick_count": 5,
        "y_minor_tick_count": 5,
        "x_minor_ticks": [-0.8, -0.6, -0.4, -0.2],
        "y_minor_ticks": [2.0, 4.0, 6.0, 8.0],
    }


def test_quality_repairs_reuse_the_global_line_width() -> None:
    line_widths = {
        action["series_style_patch"]["line_width"]
        for action in _ISSUE_QUALITY_ACTIONS.values()
        if action.get("id") == "normalize_line_width"
    }

    assert line_widths == {UNIFIED_LINE_WIDTH_PT}
