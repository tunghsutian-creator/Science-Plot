"""Categorical adapters must coexist with the unchanged pinned Managed compiler."""
from copy import deepcopy

import pytest

from sciplot_core._paths import REPO_ROOT
from sciplot_core.rendering_contract import contract_binding
from sciplot_core.rendering_contract import legacy_algorithms
from sciplot_core.studio_render.categorical_legend import categorical_legend_placement
from sciplot_core.studio_render.legend_placement import _auto_inside_legend_placement
from test_task_ordinary_categorical import _binding, _derive


def test_categorical_adapter_retains_exact_pinned_managed_algorithm_closure():
    actual = legacy_algorithms.require_legacy_algorithms(contract_binding())
    extracted = legacy_algorithms.extract_algorithm_binding(REPO_ROOT / "src/sciplot_core")
    assert actual["content_hash"] == extracted["content_hash"]
    assert actual["checked_sources"] == 24
    assert legacy_algorithms.auto_inside_legend_placement is _auto_inside_legend_placement


def test_bound_columns_measure_the_actual_grid_and_omission_returns_exact_legacy_result(tmp_path):
    source = tmp_path / "given.csv"
    source.write_text("Sample,Condition,Strength (MPa)\nA,dry,2\nB,dry,3\nA,wet,5\nB,wet,4\n")
    binding = _binding(source)
    series, _ = _derive(source, binding)
    before = deepcopy(series)
    options = {"size": "120x55", "y_min": 0, "y_max": 8}
    legacy = _auto_inside_legend_placement(series, options, template_id="point_line")
    request = {"categorical_binding": binding, "template": "point_line"}
    unrequested = categorical_legend_placement(series, options, request=request, template_id="point_line")
    assert unrequested.pop("measurement_axes") == {"x": [0.95, 2.05], "y": [0, 8]}
    assert unrequested == legacy
    request["categorical_binding"] = {**binding, "legend_columns": 2}
    measured = categorical_legend_placement(series, options, request=request, template_id="point_line")
    assert measured["position"] == legacy["position"]
    footprint = measured["footprint"]
    assert footprint["columns"] == 2 and footprint["rows"] == 1
    assert footprint["box_width_mm"] > legacy["footprint"]["box_width_mm"]
    assert footprint["box_height_mm"] < legacy["footprint"]["box_height_mm"]
    for candidate in measured["candidates"].values():
        left, right, bottom, top = candidate["rectangle_fraction"]
        assert right - left == pytest.approx(footprint["box_width_mm"] / footprint["graph_width_mm"], abs=1e-6)
        assert top - bottom == pytest.approx(footprint["box_height_mm"] / footprint["graph_height_mm"], abs=1e-6)
    explicit = categorical_legend_placement(series, options, request=request,
        template_id="point_line", position="upper_left")
    assert explicit["position"] == "upper_left"
    assert explicit["minimum_curve_clearance_mm"] == explicit["candidates"]["upper_left"]["minimum_curve_clearance_mm"]
    assert series == before


def test_categorical_grid_adapter_refuses_registered_scientific_context(tmp_path):
    source = tmp_path / "given.csv"
    source.write_text("Sample,Condition,Strength (MPa)\nA,dry,2\nB,dry,3\n")
    binding = _binding(source, legend_columns=2)
    series, _ = _derive(source, binding)
    with pytest.raises(ValueError, match="registered"):
        categorical_legend_placement(series, {}, template_id="point_line",
            request={"categorical_binding": binding, "rule_id": "impact_metric"})


@pytest.mark.parametrize("mode", ["mean_sample_sd", "mean_sample_sd_n"])
@pytest.mark.parametrize("field,value", [("legend_columns", 1), ("legend_columns", 2),
                                         ("legend_position", "upper_left")])
def test_summary_legend_grid_and_corner_requests_reject_before_native(tmp_path, mode, field, value):
    from jsonschema import Draft202012Validator
    from sciplot_core.mapping_contract.categorical import categorical_binding_schema, validate_categorical_binding

    source = tmp_path / "repeats.csv"
    source.write_text("Sample,Condition,Strength (MPa)\nA,dry,2\nA,dry,3\n")
    binding = _binding(source, mode, **{field: value})
    assert not Draft202012Validator(categorical_binding_schema(complete=True)).is_valid(binding)
    with pytest.raises(ValueError, match="native key"):
        validate_categorical_binding(binding, complete=True)


def test_explicit_axis_bounds_block_corner_reserve_instead_of_moving_the_request(tmp_path):
    from sciplot_core.studio_render.legend_clearance import _reserve_vertical_legend_clearance

    source = tmp_path / "given.csv"
    source.write_text("Sample,Condition,Strength (MPa)\nA,dry,2\nB,dry,3\nA,wet,5\nB,wet,4\n")
    binding = _binding(source, legend_columns=2, legend_position="upper_left")
    series, _ = _derive(source, binding)
    options = {"x_min": .5, "x_max": 2.5, "y_min": 0, "y_max": 5.1}
    request = {"categorical_binding": binding, "template": "point_line", "render_options": options}
    placement = categorical_legend_placement(series, options, request=request,
        template_id="point_line", position="upper_left")
    assert placement["minimum_curve_clearance_mm"] < placement["required_curve_clearance_mm"]
    updated, measured = _reserve_vertical_legend_clearance(options, request=request,
        series=series, template_id="point_line", placement=placement)
    assert updated == options and measured == placement and "axis_reserve" not in measured


@pytest.mark.parametrize("scale", ["linear", "log"])
def test_reserve_cap_applies_to_actual_final_domain_not_unrendered_candidate_bounds(tmp_path, scale):
    import math
    from sciplot_core.policy import MAX_LINEAR_LEGEND_RESERVE_FRACTION, MAX_LOG_LEGEND_RESERVE_DECADES
    from sciplot_core.studio_render.legend_clearance import _reserve_vertical_legend_clearance

    source = tmp_path / "given.csv"
    source.write_text("Sample,Condition,Strength (MPa)\nA,dry,0.0101\nB,dry,0.0102\nA,wet,0.0103\nB,wet,0.0104\n")
    binding = _binding(source, legend_columns=2, legend_position="upper_left", yscale=scale)
    series, _ = _derive(source, binding)
    options = {"yscale": scale, "x_min": .5, "x_max": 2.5}
    request = {"categorical_binding": binding, "template": "point_line", "render_options": {"yscale": scale}}
    placement = categorical_legend_placement(series, options, request=request,
        template_id="point_line", position="upper_left")
    _, measured = _reserve_vertical_legend_clearance(options, request=request,
        series=series, template_id="point_line", placement=placement)
    initial = placement["measurement_axes"]["y"]
    final = measured["measurement_axes"]["y"]
    if "axis_reserve" in measured:
        reserve = measured["axis_reserve"]
        assert reserve["revised_bound"] == final[1]
        actual = math.log10(final[1] / initial[1]) if scale == "log" else final[1] - initial[1]
        cap = MAX_LOG_LEGEND_RESERVE_DECADES if scale == "log" else (initial[1] - initial[0]) * MAX_LINEAR_LEGEND_RESERVE_FRACTION
        assert actual <= cap + 1e-12
        if scale == "log":
            assert reserve["decades"] == pytest.approx(actual, abs=1e-6)
    else:
        assert final == initial
