from __future__ import annotations

import json
from pathlib import Path

import pandas as pd

from sciplot_core.figure_layouts import get_figure_layout
from sciplot_core.figure_profiles import (
    figure_profile_frame_margins,
    figure_profile_render_options,
    get_figure_profile,
)
from sciplot_core.materials_rules import get_rule
from sciplot_core.policy import (
    DEFAULT_SCALAR_FIELD_COLORMAP_ID,
    DEFAULT_LOG_MINOR_TICK_COUNT,
    RHEOLOGY_TEMPERATURE_RENDER_OPTIONS,
    UNIFIED_MARKER_SIZE_PT,
)
from sciplot_core.render import render_to_dir
from sciplot_core.studio import _veusz_style_contract


def test_profiles_capture_curve_and_cloud_contract_without_scientific_defaults() -> None:
    temperature = get_figure_profile("rheology_temperature_gprime_v1")
    thickness = get_figure_profile("thickness_gprime_v1")
    cloud = get_figure_profile("relative_gradient_strip_v1")

    assert temperature.render_options["y_label_override"] == "\\italic{G}′ (Pa)"
    assert temperature.render_options["marker_fill_mode"] == "filled"
    assert temperature.render_options["marker_size"] == UNIFIED_MARKER_SIZE_PT
    assert temperature.render_options["y_minor_tick_count"] == DEFAULT_LOG_MINOR_TICK_COUNT

    assert thickness.render_options["x_label_override"] == "Thickness position (mm)"
    assert thickness.render_options["x_ticks"] == [-2.0, -1.0, 0.0, 1.0, 2.0]
    assert thickness.render_options["x_minor_ticks"][0] == -1.8
    assert thickness.render_options["x_minor_ticks"][-1] == 1.8
    assert figure_profile_frame_margins(thickness.profile_id) is None

    assert cloud.render_options["colormap_name"] == DEFAULT_SCALAR_FIELD_COLORMAP_ID
    assert len(cloud.render_options["colormap_colors"]) >= 2
    assert cloud.render_options["x_label_override"] == "Thickness position (mm)"
    assert cloud.render_options["z_label_override"] == "Γ_{G′}"
    assert cloud.render_options["z_unit_override"] == "(mm⁻¹)"
    assert "z_min" not in cloud.render_options
    assert "z_max" not in cloud.render_options
    assert "z_ticks" not in cloud.render_options
    layout = get_figure_layout(str(cloud.publication_layout_id))
    assert cloud.size_mm == layout.size_mm
    assert cloud.qa_contract["outer_frame_x_mm"] == list(
        layout.outer_frame_x_mm
    )
    assert cloud.qa_contract["colorbar_frame_mm"] == list(
        layout.colorbar_frame_mm
    )


def test_temperature_rule_uses_symbol_only_gprime_axis_and_filled_marker_profile() -> None:
    rule = get_rule("rheology_temperature_sweep")

    assert rule.y_axis.display_label == "G′ (Pa)"
    assert rule.render_options == RHEOLOGY_TEMPERATURE_RENDER_OPTIONS
    assert rule.render_options["marker_fill_mode"] == "filled"
    assert rule.render_options["y_minor_tick_count"] == DEFAULT_LOG_MINOR_TICK_COUNT


def test_named_curve_profiles_and_arbitrary_requests_use_the_global_frame() -> None:
    profiled = _veusz_style_contract({"_figure_profile_id": "thickness_gprime_v1"})
    untrusted = _veusz_style_contract(
        {
            "_figure_profile_id": "not_a_profile",
            "_frame_margins_mm": {"left": 1.0, "right": 1.0, "bottom": 1.0, "top": 1.0},
        }
    )

    assert (profiled.left_margin_mm, profiled.right_margin_mm) == (14.0, 4.5)
    assert (profiled.bottom_margin_mm, profiled.top_margin_mm) == (11.0, 5.5)
    assert (untrusted.left_margin_mm, untrusted.right_margin_mm) == (14.0, 4.5)
    assert (untrusted.bottom_margin_mm, untrusted.top_margin_mm) == (11.0, 5.5)


def test_thickness_profile_renders_explicit_minor_ticks_and_profile_frame(tmp_path: Path) -> None:
    source = tmp_path / "thickness.csv"
    x_values = [round(-2.0 + index * 0.2, 10) for index in range(21)]
    pd.DataFrame(
        {
            "Thickness position": x_values,
            "E0": [10 ** (6.0 + 0.4 * abs(x)) for x in x_values],
            "E4": [10 ** (6.2 + 0.2 * abs(x)) for x in x_values],
        }
    ).to_csv(source, index=False)

    result = render_to_dir(
        source,
        template="point_line",
        output_dir=tmp_path / "rendered",
        options=figure_profile_render_options("thickness_gprime_v1"),
        export_formats=("pdf",),
    )

    assert all(not report["issues"] for report in result["qa_reports"])
    spec = json.loads(Path(result["veusz_specs"][0]).read_text(encoding="utf-8"))
    assert spec["figure_profile_id"] == "thickness_gprime_v1"
    assert spec["style"]["margins_mm"] == {
        "left": 14.0,
        "right": 4.5,
        "bottom": 11.0,
        "top": 5.5,
    }
    assert spec["axes"]["x"]["minor_ticks"] == [
        -1.8,
        -1.6,
        -1.4,
        -1.2,
        -0.8,
        -0.6,
        -0.4,
        -0.2,
        0.2,
        0.4,
        0.6,
        0.8,
        1.2,
        1.4,
        1.6,
        1.8,
    ]
    assert spec["axes"]["y"]["minor_tick_count"] == DEFAULT_LOG_MINOR_TICK_COUNT
    assert all(series["marker"] != "none" for series in spec["series"])
