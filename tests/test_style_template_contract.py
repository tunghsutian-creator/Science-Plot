from __future__ import annotations

import json
from pathlib import Path

import pandas as pd
import pytest
import sciplot_core.workflow as workflow

from sciplot_core.policy import (
    CATEGORICAL_BAR_FILL_TRANSPARENCY,
    CATEGORICAL_BAR_WIDTH_FRACTION,
    CATEGORICAL_ERROR_CAP_TO_BAR_RATIO,
    CONTROL_FIRST_BRIGHT_COLORS,
    CONTROL_FIRST_BRIGHT_PALETTE_ID,
    DEFAULT_CURVE_LINE_STYLE_SEQUENCE,
    DEFAULT_PALETTE_COLORS,
    DEFAULT_PALETTE_PRESET,
    DEFAULT_RENDER_OPTIONS,
    DEFAULT_SCALAR_FIELD_COLORS,
    TENSILE_X_AXIS_LABEL,
    TENSILE_Y_AXIS_LABEL,
    UNIFIED_HARD_OPTION_KEYS,
    UNIFIED_LEFT_MARGIN_MM,
    UNIFIED_RIGHT_MARGIN_MM,
)


def test_curve_style_contract_uses_solid_lines_for_every_series() -> None:
    assert DEFAULT_CURVE_LINE_STYLE_SEQUENCE == ("solid",)
from sciplot_core.render import render_to_dir
from sciplot_recipes.contracts import get_recipe_spec
from sciplot_core.style_contract import (
    VEUSZ_IMPLEMENTED_TEMPLATE_IDS,
    VEUSZ_TEMPLATE_COLOR_OPTIONS,
    audit_style_template_contract,
    validate_veusz_template_id,
)
from sciplot_core.studio import (
    StudioSeries,
    _VeuszAxisContract,
    _VeuszStyleContract,
    _apply_domain_render_defaults,
    _apply_readability_render_defaults,
    _expand_axis_for_visual_extents,
    _request_template,
    _resolved_domain_render_options,
    _veusz_axis_contract,
)
from sciplot_core.request_contract import (
    apply_request_patch,
    normalize_render_options,
)
from sciplot_core.terminal_request import project_terminal_render_request


def test_terminal_request_preserves_only_declared_explicit_render_keys() -> None:
    terminal = project_terminal_render_request(
        template="bar",
        render_options={"y_max": 10.0, "size": "60x55"},
        request_context={"explicit_render_option_keys": ["size"]},
    )

    assert terminal["explicit_render_option_keys"] == ["size"]


def test_default_ordinary_palette_is_control_first_then_one_through_six() -> None:
    assert CONTROL_FIRST_BRIGHT_COLORS == (
        "#222222",
        "#3568C0",
        "#C83E4D",
        "#2A9D8F",
        "#D99A24",
        "#7C9ED9",
        "#7B61A8",
    )
    assert DEFAULT_PALETTE_COLORS == CONTROL_FIRST_BRIGHT_COLORS
    assert DEFAULT_PALETTE_PRESET == CONTROL_FIRST_BRIGHT_PALETTE_ID
    assert DEFAULT_RENDER_OPTIONS["palette_preset"] == CONTROL_FIRST_BRIGHT_PALETTE_ID


def test_non_explicit_legacy_palette_follows_current_shared_default() -> None:
    series = [
        StudioSeries(
            label="control",
            x_name="x",
            y_name="y",
            x_values=(0.0, 1.0),
            y_values=(0.0, 1.0),
            color="#FFFFFF",
        )
    ]
    axis_info = {"x_label": "x", "y_label": "y"}
    inherited = _resolved_domain_render_options(
        {
            "template": "curve",
            "render_options": {"palette_preset": "jama_editorial"},
            "explicit_render_option_keys": [],
        },
        axis_info=axis_info,
        series=series,
    )
    explicit = _resolved_domain_render_options(
        {
            "template": "curve",
            "render_options": {"palette_preset": "jama_editorial"},
            "explicit_render_option_keys": ["palette_preset"],
        },
        axis_info=axis_info,
        series=series,
    )

    assert inherited["palette_preset"] == CONTROL_FIRST_BRIGHT_PALETTE_ID
    assert explicit["palette_preset"] == "jama_editorial"


def test_tensile_contract_uses_short_labels_two_sided_padding_and_auto_legend() -> None:
    request = {"rule_id": "tensile_curve", "template": "curve", "render_options": {}}
    axis_info = {"x_label": "Tensile Strain (%)", "y_label": "Tensile Stress (MPa)"}
    series = [
        StudioSeries(
            label="A",
            x_name="x_a",
            y_name="y_a",
            x_values=(0.0, 10.0, 30.0, 52.0),
            y_values=(0.1, 30.0, 70.0, 75.0),
            color="#374E55",
        ),
        StudioSeries(
            label="B",
            x_name="x_b",
            y_name="y_b",
            x_values=(0.0, 8.0, 25.0, 45.0),
            y_values=(0.2, 25.0, 62.0, 68.0),
            color="#DF8F44",
        ),
    ]

    options = _apply_domain_render_defaults(
        {}, request=request, axis_info=axis_info
    )
    options = _apply_readability_render_defaults(
        options,
        request=request,
        axis_info=axis_info,
        series=series,
        template_id="curve",
    )

    assert options["x_label_override"] == TENSILE_X_AXIS_LABEL
    assert options["y_label_override"] == TENSILE_Y_AXIS_LABEL
    assert options["axis_mode"] == "auto"
    assert options["x_min"] < 0.0 < max(series[0].x_values) < options["x_max"]
    assert options["y_min"] < 0.1 < max(series[0].y_values) < options["y_max"]
    assert options["legend_position"] != "lower_left"


def test_tensile_summary_bar_keeps_metric_axis_labels() -> None:
    request = {"rule_id": "tensile_curve", "template": "bar", "render_options": {}}
    axis_info = {
        "x_label": "Sample",
        "y_label": "Tensile strength (MPa)",
        "category_positions": [1.0, 2.0],
        "category_labels": ["A", "B"],
    }

    options = _apply_domain_render_defaults(
        {}, request=request, axis_info=axis_info
    )

    assert options["x_label_override"] == "Sample"
    assert "y_label_override" not in options


def test_autoplot_writes_a_canonical_default_render_request(
    tmp_path, monkeypatch
) -> None:
    captured: dict[str, object] = {}

    def fake_run_request(request_path: Path) -> dict[str, object]:
        captured.update(json.loads(request_path.read_text(encoding="utf-8")))
        return {"state": "ready", "one_step": {}}

    monkeypatch.setattr(workflow, "run_request", fake_run_request)
    result = workflow.run_one_step(
        tmp_path / "input.csv",
        output_root=tmp_path / "outputs",
        project_name="canonical_request",
    )

    assert result["status"] == "ready"
    assert captured["render_options"] == normalize_render_options(
        DEFAULT_RENDER_OPTIONS
    )


def test_style_and_template_contract_audit_passes_current_registry() -> None:
    payload = audit_style_template_contract()

    assert payload["status"] == "passed"
    assert payload["issues"] == []
    assert set(payload["implemented_veusz_templates"]) == (
        VEUSZ_IMPLEMENTED_TEMPLATE_IDS
    )
    assert set(payload["template_color_options"]["heatmap"]) == (
        VEUSZ_TEMPLATE_COLOR_OPTIONS["heatmap"]
    )
    assert (
        VEUSZ_TEMPLATE_COLOR_OPTIONS["heatmap"] & UNIFIED_HARD_OPTION_KEYS
    ) == frozenset()


def test_contract_audit_reports_private_style_and_rule_template_drift() -> None:
    payload = audit_style_template_contract(
        ready_rule_templates=("curve", "violin"),
        render_defaults={"font_size_pt": 12.0},
    )

    assert payload["status"] == "failed"
    assert {issue["code"] for issue in payload["issues"]} >= {
        "render_default_style_drift",
        "ready_rule_uses_unimplemented_template",
    }


@pytest.mark.parametrize("template", sorted(VEUSZ_IMPLEMENTED_TEMPLATE_IDS))
def test_request_contract_accepts_only_implemented_veusz_templates(
    template: str,
) -> None:
    assert normalize_render_options({}, template=template) == {}


def test_request_contract_rejects_reference_only_vendor_template() -> None:
    with pytest.raises(ValueError, match="not implemented by SciPlot"):
        normalize_render_options({}, template="violin")


def test_heatmap_request_contract_accepts_the_runtime_scalar_contract() -> None:
    options = {
        "data_variables": {"x": "x", "y": "y", "z": "z"},
        "z_min": 1.0,
        "z_max": 4.0,
        "colormap_name": "sciplot_cividis",
        "colormap_colors": ["#00204C", "#FFEA46"],
        "color_invert": False,
        "contour_levels": [2.0, 3.0],
        "highlight_contour_levels": [2.5],
        "colorbar_foreground_color": "#223344",
        "colorbar_background_color": "#F7F7F7",
    }

    assert normalize_render_options(options, template="heatmap") == options


def test_request_template_is_validated_even_without_an_explicit_template_argument() -> None:
    with pytest.raises(ValueError, match="not implemented by SciPlot"):
        apply_request_patch({"template": "scatter"})


def test_direct_render_and_studio_generation_share_the_fail_closed_allowlist(
    tmp_path,
) -> None:
    assert validate_veusz_template_id("curve") == "curve"
    assert validate_veusz_template_id("bar") == "bar"
    with pytest.raises(ValueError, match="not implemented by SciPlot"):
        _request_template({"template": "violin"})
    with pytest.raises(ValueError, match="not implemented by SciPlot"):
        render_to_dir(
            tmp_path / "unused.csv",
            template="violin",
            output_dir=tmp_path / "out",
        )


def test_recipe_ids_resolve_to_supported_templates() -> None:
    assert _request_template({"recipe": "tensile"}) == "curve"
    assert _request_template({"recipe": "metrics_swelling"}) == "box_strip"
    assert get_recipe_spec("metrics_swelling").default_template == "box_strip"


def test_named_profiles_use_the_global_horizontal_frame() -> None:
    payload = audit_style_template_contract()
    assert payload["hard_style_values"]["global_frame"]["left_margin_mm"] == (
        UNIFIED_LEFT_MARGIN_MM
    )
    assert payload["hard_style_values"]["global_frame"]["right_margin_mm"] == (
        UNIFIED_RIGHT_MARGIN_MM
    )


@pytest.mark.parametrize(
    ("template", "expected_widget"),
    [
        ("curve", "Add('xy'"),
        ("point_line", "Add('xy'"),
        ("stacked_curve", "Add('xy'"),
        ("bar", "Add('bar', name='categorical_bar'"),
        ("box", "Add('boxplot'"),
        ("box_strip", "Add('boxplot'"),
        ("heatmap", "Add('image'"),
    ],
)
def test_each_production_template_materializes_its_declared_veusz_semantics(
    tmp_path,
    template: str,
    expected_widget: str,
) -> None:
    source = tmp_path / f"{template}.csv"
    options: dict[str, object] = {"size": "60x55"}
    if template == "heatmap":
        pd.DataFrame(
            {
                "x": [0.0, 1.0, 0.0, 1.0],
                "y": [0.0, 0.0, 1.0, 1.0],
                "z": [1.0, 2.0, 2.0, 3.0],
            }
        ).to_csv(source, index=False)
        options.update(
            {
                "data_variables": {"x": "x", "y": "y", "z": "z"},
                "z_min": 1.0,
                "z_max": 3.0,
            }
        )
    elif template in {"bar", "box", "box_strip"}:
        pd.DataFrame(
            {
                # Two-point groups deliberately put mean + sample SD above the
                # raw maximum, exercising the visual error-bar extent rather
                # than relying on raw-data padding to hide the bug.
                "Sample": ["A", "A", "B", "B"],
                "Impact strength": [10.0, 12.0, 20.0, 22.0],
            }
        ).to_csv(source, index=False)
        options["summary_statistic"] = "median_iqr"
    else:
        pd.DataFrame(
            {
                "x": [0.0, 1.0, 2.0],
                "sample_a": [1.0, 2.0, 3.0],
                "sample_b": [1.5, 2.5, 3.5],
            }
        ).to_csv(source, index=False)

    result = render_to_dir(
        source,
        template=template,
        output_dir=tmp_path / f"rendered_{template}",
        options=options,
        export_formats=("pdf",),
    )
    document = Path(result["veusz_documents"][0])
    spec = json.loads(
        Path(result["veusz_specs"][0]).read_text(encoding="utf-8")
    )

    assert spec["template"] == template
    assert expected_widget in document.read_text(encoding="utf-8")
    if template != "heatmap":
        clearance = spec["visual_extent_axis_clearance"]
        assert clearance["violations"] == []
        assert clearance["axes"]["x"]["status"] == "safe"
        assert clearance["axes"]["y"]["status"] == "safe"
        assert (
            clearance["axes"]["y"]["upper_clearance_mm"]
            >= clearance["axes"]["y"]["required_extent_mm"] - 1e-6
        )
    else:
        assert spec["scalar_field"]["colormap_colors"] == list(
            DEFAULT_SCALAR_FIELD_COLORS
        )
    if template == "bar":
        text = document.read_text(encoding="utf-8")
        assert text.count("Add('bar', name='categorical_bar'") == 1
        assert "Set('mode', 'stacked')" in text
        assert f"Set('barfill', {CATEGORICAL_BAR_WIDTH_FRACTION})" in text
        assert (
            f"('solid', '#222222', False, {CATEGORICAL_BAR_FILL_TRANSPARENCY}, "
            "'0.5pt', 'solid', '5pt', 'white', 0, True)"
        ) in text
        cap_half_width = (
            CATEGORICAL_BAR_WIDTH_FRACTION
            * CATEGORICAL_ERROR_CAP_TO_BAR_RATIO
            / 2.0
        )
        assert f"Set('xPos', [{1.0 - cap_half_width}])" in text
        assert f"Set('xPos2', [{1.0 + cap_half_width}])" in text
        error_line_count = text.count("Add('line', name='categorical_bar_error_")
        assert error_line_count >= 3
        assert error_line_count % 3 == 0
        for chunk in text.split("Add('line', name='categorical_bar_error_")[1:]:
            assert "Set('Line/color', '#111111')" in chunk.split("To('..')", 1)[0]
        highest_error = max(
            group["bar_mean"] + group["bar_error"]
            for group in spec["categorical"]["groups"]
        )
        assert spec["axes"]["y"]["max"] > highest_error
    if template == "curve":
        text = document.read_text(encoding="utf-8")
        assert "Set('keyLength', '0.40cm')" in text
        for chunk in text.split("Add('xy', name=")[1:]:
            series_chunk = chunk.split("To('..')", 1)[0]
            if "Set('marker', 'none')" in series_chunk:
                assert "Set('MarkerFill/hide', True)" in series_chunk
                assert "Set('MarkerLine/hide', True)" in series_chunk


def test_explicit_axis_that_clips_marker_reports_visual_extent_violation() -> None:
    series = [
        StudioSeries(
            label="edge",
            x_name="x",
            y_name="y",
            x_values=(1.0, 10.0),
            y_values=(1.0, 100.0),
            color="#374E55",
            marker="circle",
            marker_size=2.0,
        )
    ]
    request = {"render_options": {"y_max": 100.0}}
    expanded, diagnostics = _expand_axis_for_visual_extents(
        _VeuszAxisContract(x_min=1.0, x_max=11.0, y_min=1.0, y_max=100.0),
        request=request,
        render_options={"xscale": "linear", "yscale": "linear"},
        template_id="point_line",
        series=series,
        categorical_contract=None,
        style=_VeuszStyleContract(),
        width_mm=60.0,
        height_mm=55.0,
    )

    assert expanded.y_max == 100.0
    assert diagnostics["axes"]["y"]["status"] == "unsafe_explicit_bound"
    assert any(
        item["axis"] == "y" and item["side"] == "upper"
        for item in diagnostics["violations"]
    )


def test_auto_log_axis_compacts_empty_outer_decades_before_glyph_clearance() -> None:
    series = [
        StudioSeries(
            label="log",
            x_name="x",
            y_name="y",
            x_values=(0.1, 100.0),
            y_values=(240.76, 142190.0),
            color="#374E55",
            marker="circle",
            marker_size=2.0,
        )
    ]

    axis = _veusz_axis_contract(
        {
            "xscale": "log",
            "yscale": "log",
            "y_min": 1.0,
            "y_max": 500000.0,
            "y_ticks": [1.0, 10.0, 100.0, 1000.0, 10000.0, 100000.0],
        },
        template_id="point_line",
        series=series,
        explicit_render_options={},
    )

    assert axis.y_min == 100.0
    assert axis.y_max == pytest.approx(142190.0 * 1.10)


def test_auto_log_axis_preserves_internal_legend_clearance_reserve() -> None:
    series = [
        StudioSeries(
            label="log",
            x_name="x",
            y_name="y",
            x_values=(0.0017, 3.0104),
            y_values=(0.000719357, 1.86749e14),
            color="#374E55",
        )
    ]

    axis = _veusz_axis_contract(
        {
            "xscale": "log",
            "yscale": "log",
            "y_min": 1.885997683632129e-05,
            "y_max": 2.054239e14,
            "_legend_placement_diagnostics": {
                "axis_reserve": {"side": "bottom"}
            },
        },
        template_id="curve",
        series=series,
        explicit_render_options={},
    )

    assert axis.y_min == pytest.approx(1.885997683632129e-05)
