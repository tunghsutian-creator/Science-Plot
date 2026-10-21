"""Generated original-table controls for ordinary categorical coordinates."""

from copy import deepcopy

import pytest
from jsonschema import Draft202012Validator

from sciplot_core.categorical_plan import build_categorical_preview
from sciplot_core.foundation.file_hashing import file_sha256
from sciplot_core.mapping_contract.categorical import categorical_binding_schema
from sciplot_core.studio_render.categorical_bindings import read_categorical_frame
from sciplot_core.studio_render.frame_series import _series_from_frame_records
from sciplot_core.studio_render.models import StudioPreparationBlocked
from sciplot_core.studio_render.replicate_distribution_contract import _replicate_distribution_contract
from sciplot_core.task_categorical_contract import categorical_request_schema


def _binding(source, mode="given_values", **extra):
    return {"source_sha256": file_sha256(source), "mode": mode,
        "table_selection": {"sheet": None, "header_rows": [0], "data_start_row": 1,
                            "data_end_row": len(source.read_text().splitlines())},
        "sample_column": 0, "condition_column": 1,
        "value_columns": [{"column_index": 2}], **extra}


def _derive(source, binding, **extra):
    options = {key: binding[key] for key in ("series_styles", "yscale") if key in binding}
    request = {"template": "point_line" if binding["mode"] == "given_values" else "bar",
               "categorical_binding": binding, "render_options": options, **extra}
    return _series_from_frame_records(request, frames=[read_categorical_frame(source, binding)])


def test_binding_closed_schema_and_existing_task_variant_separate(tmp_path):
    assert Draft202012Validator(categorical_request_schema()).is_valid(
        {"version": 1, "action": "create", "source": "original.xlsx", "categorical": {}})
    assert not Draft202012Validator(categorical_binding_schema()).is_valid({"values": [1, 2]})
    assert not Draft202012Validator(categorical_request_schema()).is_valid(
        {"version": 1, "action": "create", "source": "original.xlsx", "categorical": {}, "rule_id": "impact_metric"})


def test_given_values_selects_original_columns_orders_aliases_and_exact_decimal(tmp_path):
    source = tmp_path / "measurements.csv"
    source.write_text("样品,工况,Size (µm),Replicate\nB,wet,0.12345678901234567,9\nA,dry,1.0000000000000002,8\nB,dry,2.3400000000000003,7\nA,wet,3.1,6\nC,dry,99,5\n")
    original = source.read_bytes()
    binding = _binding(source, include_categories=["A", "B"], category_order=["B", "A"],
        condition_order=["dry", "wet"], category_aliases={"B": "Control", "A": "Treated"},
        series_styles=[{"label": "dry", "color": "#215977", "marker": "circle"},
                       {"label": "wet", "marker": "square", "marker_fill_mode": "open"}])
    series, axis = _derive(source, binding)
    assert [item.label for item in series] == ["dry", "wet"]
    assert [value.hex() for value in series[0].y_values] == [float("2.3400000000000003").hex(), float("1.0000000000000002").hex()]
    assert series[1].y_values == (float("0.12345678901234567"), 3.1)
    assert all(item.error_values == () for item in series)
    assert series[1].marker_fill_color == "white" and series[0].marker_fill_color == "#215977"
    assert axis["source_category_ids"] == ["B", "A"] and axis["category_labels"] == ["Control", "Treated"]
    assert source.read_bytes() == original
    assert binding["sample_column"] == 0 and binding["category_order"] == ["B", "A"]


def test_long_replicates_reuse_existing_sample_sd_with_unequal_n_and_missing_confirmation(tmp_path):
    source = tmp_path / "repeats.csv"
    source.write_text("Sample,Condition,Strength (MPa),Run\nB,low,2,1\nA,high,10,2\nB,high,8,3\nA,low,4,4\nB,low,2,5\nA,high,14,6\nB,high,12,7\nA,low,,8\nA,low,8,9\nB,low,5,10\n")
    binding = _binding(source, "mean_sample_sd", category_order=["A", "B"], condition_order=["low", "high"], category_aliases={"A": "Control"})
    with pytest.raises(StudioPreparationBlocked, match="missing_values") as error:
        _derive(source, binding)
    assert error.value.reason_code == "categorical_missing_values_confirmation_required"
    series, axis = _derive(source, binding, missing_values="exclude")
    assert [item.label for item in series] == ["A || low", "A || high", "B || low", "B || high"]
    assert [item.y_values for item in series] == [(4., 8.), (10., 14.), (2., 2., 5.), (8., 12.)]
    contract = _replicate_distribution_contract(series, template_id="bar", render_options={})
    assert [group["replicate_count"] for group in contract["groups"]] == [2, 2, 3, 2]
    assert contract["groups"][0]["bar_mean"] == 6.
    assert contract["groups"][0]["bar_error"] == pytest.approx(2 ** .5 * 2)
    assert axis["category_labels"] == ["Control", "B"]
    assert len(axis["categorical_missing_cells"]) == 1


@pytest.mark.parametrize("change,code", [
    ({"category_order": ["A"]}, "invalid_categorical_order"),
    ({"include_categories": ["missing"]}, "unknown_categorical_selection"),
    ({"value_columns": [{"column_index": 0}]}, "invalid_categorical_columns"),
    ({"source_sha256": "0" * 64}, "categorical_source_changed"),
])
def test_invalid_bindings_fail_before_native_or_source_mutation(tmp_path, change, code):
    source = tmp_path / "values.csv"
    source.write_text("Sample,Condition,Value (MPa)\nA,dry,1\nB,dry,2\n")
    original = source.read_bytes()
    with pytest.raises(StudioPreparationBlocked) as error:
        _derive(source, _binding(source, **change))
    assert error.value.reason_code == code
    assert source.read_bytes() == original


def test_given_values_never_aggregate_duplicates_or_invent_missing_point(tmp_path):
    source = tmp_path / "values.csv"
    source.write_text("Sample,Condition,Value (MPa)\nA,dry,1\nA,dry,1\nB,dry,2\n")
    with pytest.raises(StudioPreparationBlocked) as error:
        _derive(source, _binding(source))
    assert error.value.reason_code == "categorical_given_values_ambiguous"


def test_positive_log_preflight_and_nonpositive_atomic_refusal(tmp_path):
    source = tmp_path / "density.csv"
    source.write_text("Sample,Condition,Density (cells cm⁻³)\nA,dry,120000\nB,dry,250000\n")
    binding = _binding(source, yscale="log")
    binding["metadata_confirmations"] = [{"source_sha256": binding["source_sha256"], "sheet": None,
        "column_index": 2, "field": "unit", "value": "cells cm⁻³",
        "evidence": {"kind": "user_statement", "asserted_by": "source owner", "statement": "Density values are cells cm⁻³."}}]
    plan = build_categorical_preview(source, request={"categorical_binding": binding})
    assert plan["rule_id"] is None and plan["template"] == "point_line"
    source.write_text(source.read_text().replace("120000", "0"))
    binding["source_sha256"] = file_sha256(source)
    binding["metadata_confirmations"][0]["source_sha256"] = binding["source_sha256"]
    with pytest.raises(StudioPreparationBlocked) as error:
        build_categorical_preview(source, request={"categorical_binding": binding})
    assert error.value.reason_code == "log_axis_nonpositive_data"


def test_explicit_workbook_sheet_header_and_unit_evidence_preserve_cells(tmp_path):
    import pandas as pd
    source = tmp_path / "summary.xlsx"
    raw = [["unrelated note", None, None], ["Unit is °C", None, None],
           [None, None, None], ["Sample", "Tm A", "Tm B"],
           ["Z", 163.7, 259.8], ["Q", 164.1, 260.2]]
    with pd.ExcelWriter(source) as writer:
        pd.DataFrame([["wrong", "sheet"]]).to_excel(writer, sheet_name="Other", header=False, index=False)
        pd.DataFrame(raw).to_excel(writer, sheet_name="Summary", header=False, index=False)
    digest = file_sha256(source)
    confirmations = [{"source_sha256": digest, "sheet": "Summary", "column_index": col,
        "field": "unit", "value": "°C", "evidence": {"kind": "source_cell", "sheet": "Summary",
        "row_index": 1, "column_index": 0, "text": "Unit is °C"}} for col in (1, 2)]
    binding = {"source_sha256": digest, "mode": "given_values", "sample_column": 0,
        "table_selection": {"sheet": "Summary", "header_rows": [3], "data_start_row": 4, "data_end_row": 6},
        "value_columns": [{"column_index": 1}, {"column_index": 2}], "metadata_confirmations": confirmations}
    series, axis = _derive(source, binding)
    assert [item.y_values for item in series] == [(163.7, 164.1), (259.8, 260.2)]
    assert axis["source_category_ids"] == ["Z", "Q"]
    assert file_sha256(source) == digest
    tampered = deepcopy(binding)
    tampered["metadata_confirmations"][0]["evidence"]["text"] = "invented note"
    with pytest.raises(ValueError, match="original"):
        _derive(source, tampered)


def test_source_bound_question_continues_same_choice_and_refuses_stale_answer(tmp_path):
    from sciplot_core.foundation.source_tree import source_tree_sha256
    from sciplot_core.task_categorical_creation import accept_categorical_response, plan_categorical_task
    from sciplot_core.task_errors import TaskControlError
    source = tmp_path / "readings.csv"
    source.write_text("Sample,Condition,Value (MPa)\nA,dry,2\nA,dry,3\nB,dry,4\nB,dry,5\n")
    state = {"request": {"source": str(source), "categorical": {}}, "source_sha256": source_tree_sha256(source)}
    assert plan_categorical_task(state) is None
    question = state["question"]
    assert question["field"] == "categorical" and not (tmp_path / "readings_SciPlot").exists()
    with pytest.raises(TaskControlError, match="current"):
        accept_categorical_response(state, {"expected_question_id": "0" * 64, "categorical": {}})
    accept_categorical_response(state, {"expected_question_id": question["question_id"],
        "categorical": _binding(source, "mean_sample_sd")})
    assert plan_categorical_task(state) is not None
    assert state["scientific_presentation"]["rule_id"] is None
    assert len(state["categorical_answers"]) == 1


@pytest.mark.parametrize("mode", ["given_values", "mean_sample_sd"])
def test_missing_metadata_requires_source_bound_confirmation_without_guessing(tmp_path, mode):
    source = tmp_path / "values.csv"
    source.write_text("Sample,Condition,Value\nA,dry,1\nA,dry,2\nB,dry,3\nB,dry,4\n")
    with pytest.raises(StudioPreparationBlocked) as error:
        _derive(source, _binding(source, mode))
    assert error.value.reason_code == "categorical_metadata_required"


def test_sample_sd_never_claims_singleton_zero_error_and_given_missing_never_interpolates(tmp_path):
    source = tmp_path / "values.csv"
    source.write_text("Sample,Condition,Value (MPa)\nA,dry,1\nB,dry,2\nB,dry,3\n")
    with pytest.raises(StudioPreparationBlocked) as error:
        _derive(source, _binding(source, "mean_sample_sd"))
    assert error.value.reason_code == "categorical_sample_sd_requires_replicates"
    source.write_text("Sample,Condition,Value (MPa)\nA,dry,1\nB,dry,\n")
    with pytest.raises(StudioPreparationBlocked) as error:
        _derive(source, _binding(source), missing_values="exclude")
    assert error.value.reason_code == "incomplete_categorical_given_values"


def test_legacy_grouped_parser_replay_stays_distinct_from_new_decimal_precision(tmp_path):
    import pandas as pd
    from sciplot_core.studio_render.categorical_groups import _categorical_grouped_series_from_frames
    from sciplot_core.studio_render.models import StudioSourceFrame
    frame = pd.DataFrame({"Sample": ["A", "A", "A", "A"], "Condition": ["dry", "dry", "wet", "wet"],
                          "Value (MPa)": ["0.12345678901234567", "0.12345678901234567", "1.0000000000000002", "1.0000000000000002"]})
    source = tmp_path / "placeholder.csv"
    current, _ = _categorical_grouped_series_from_frames([StudioSourceFrame("input", source, "a" * 64, frame)])
    frame.attrs["sciplot_legacy_numeric_parser"] = True
    historical, _ = _categorical_grouped_series_from_frames([StudioSourceFrame("input", source, "a" * 64, frame)])
    assert current[0].y_values == (float("0.12345678901234567"),) * 2
    assert historical[0].y_values == (float(pd.to_numeric(pd.Series(["0.12345678901234567"])).iloc[0]),) * 2
    assert current[0].y_values != historical[0].y_values


def test_condition_color_is_explicit_while_unspecified_existing_tone_is_preserved(tmp_path):
    from sciplot_core.policy.categorical import categorical_component_fill_color
    source = tmp_path / "repeats.csv"
    source.write_text("Sample,Condition,Strength (MPa)\nA,dry,2\nA,dry,4\nA,wet,6\nA,wet,8\nB,dry,3\nB,dry,5\nB,wet,7\nB,wet,9\n")
    plain, _ = _derive(source, _binding(source, "mean_sample_sd"))
    default = _replicate_distribution_contract(plain, template_id="bar", render_options={})
    assert default["groups"][0]["fill_color"] == categorical_component_fill_color(plain[0].color, component_index=1, component_count=2)
    binding = _binding(source, "mean_sample_sd", series_styles=[{"label": "dry", "color": "#215977"}, {"label": "wet", "color": "#B65B43"}])
    explicit, _ = _derive(source, binding)
    actual = _replicate_distribution_contract(explicit, template_id="bar", render_options={})
    assert [group["fill_color"] for group in actual["groups"]] == ["#215977", "#B65B43"] * 2
    assert [group["raw_values"] for group in actual["groups"]] == [group["raw_values"] for group in default["groups"]]


def test_composite_identity_and_duplicate_alias_collisions_never_merge_raw_members(tmp_path):
    source = tmp_path / "values.csv"
    source.write_text("Sample,Condition,Value (MPa)\nA || B,C,1\nA,B || C,2\n")
    with pytest.raises(StudioPreparationBlocked) as error:
        _derive(source, _binding(source))
    assert error.value.reason_code == "invalid_categorical_identity"
    source.write_text("Sample,Condition,Value (MPa)\nA,dry,1\nB,dry,2\n")
    with pytest.raises(StudioPreparationBlocked) as error:
        _derive(source, _binding(source, category_aliases={"A": "Shared", "B": "Shared"}))
    assert error.value.reason_code == "invalid_categorical_aliases"


def test_physical_empty_columns_and_n_disclosure_keep_original_coordinates(tmp_path):
    from sciplot_core.categorical_disclosure import categorical_replicate_evidence
    source = tmp_path / "spaced.csv"
    source.write_text(",Sample,,Condition,,Strength (MPa)\n,A,,dry,,2\n,A,,dry,,4\n,B,,dry,,6\n,B,,dry,,8\n,B,,dry,,\n")
    binding = _binding(source, "mean_sample_sd_n", sample_column=1, condition_column=3, value_columns=[{"column_index": 5}])
    evidence = categorical_replicate_evidence(source, binding)
    assert [group["source_columns"] for group in evidence["groups"]] == [[5], [5]]
    assert evidence["groups"][1]["missing_cells"] == [[5, 5]]
    assert [group["valid_n"] for group in evidence["groups"]] == [2, 2]
    assert evidence["original_source"] == str(source.resolve())


@pytest.mark.parametrize("invalid", [True, 2.0, 0, 13, "2"])
def test_legend_columns_integer_bounds_fail_closed_without_changing_defaults(invalid):
    from sciplot_core.studio_render.categorical_legend import legend_columns
    assert legend_columns(series_count=2) == 1
    assert legend_columns(series_count=2, requested=2) == 2
    with pytest.raises(StudioPreparationBlocked):
        legend_columns(series_count=2, requested=invalid)


def test_category_binding_cannot_relabel_registered_science_or_decimal_column_index(tmp_path):
    from sciplot_core.mapping_contract.categorical import validate_categorical_context, validate_categorical_binding
    source = tmp_path / "values.csv"
    source.write_text("Sample,Condition,Value (MPa)\nA,dry,1\nB,dry,2\n")
    binding = _binding(source)
    with pytest.raises(ValueError, match="registered"):
        validate_categorical_context({"categorical_binding": binding, "rule_id": "impact_metric"})
    with pytest.raises(ValueError, match="integer"):
        validate_categorical_binding({**binding, "sample_column": 0.0}, complete=True)


def test_given_category_positions_drive_actual_axis_ticks(tmp_path):
    from sciplot_core.studio_render.series_domain import _resolved_domain_render_options
    source = tmp_path / "values.csv"
    source.write_text("Sample,Condition,Value (MPa)\nA,dry,1\nB,dry,2\n")
    binding = _binding(source)
    series, info = _derive(source, binding)
    options = _resolved_domain_render_options({"template": "point_line", "categorical_binding": binding}, axis_info=info, series=series)
    assert options["x_ticks"] == [1., 2.]
    assert options["x_min"] == .5 and options["x_max"] == 2.5


def test_full_first_call_missing_instruction_uses_same_policy_without_extra_question(tmp_path, monkeypatch):
    from sciplot_core.task_control import start_task
    import sciplot_core.task_execution as execution
    source = tmp_path / "values.csv"
    source.write_text("Sample,Condition,Value (MPa)\nA,dry,1\nA,dry,2\nA,dry,\nB,dry,3\nB,dry,4\n")
    plans = []
    def consume(_source, **options):
        plans.append(options["expected_plan"])
        raise RuntimeError("Generated stop after the complete scientific plan")
    monkeypatch.setattr(execution, "create_project", consume)
    result = start_task({"version": 1, "action": "create", "source": str(source),
        "categorical": _binding(source, "mean_sample_sd_n"), "missing_values": "exclude"}, task_dir=tmp_path / "task")
    assert result["status"] == "blocked" and len(plans) == 1
    assert plans[0]["source_options"]["replicate_summary_disclosure"]["groups"][0]["missing_count"] == 1
    assert "question" not in result


def test_existing_bounded_legend_reserve_crosses_overlap_plateau_and_respects_explicit_bound():
    from sciplot_core.studio_render.legend_clearance import _reserve_vertical_legend_clearance
    from sciplot_core.studio_render.legend_placement import _auto_inside_legend_placement
    from sciplot_core.studio_render.models import StudioSeries
    series = [StudioSeries("Alpha", "x1", "y1", (1., 2.), (163.7, 164.1), "#222222"),
              StudioSeries("Beta", "x2", "y2", (1., 2.), (259.8, 260.2), "#3568C0")]
    options = {"x_min": .5, "x_max": 2.5, "x_ticks": [1., 2.], "legend_position": "auto"}
    placement = _auto_inside_legend_placement(series, options, template_id="point_line")
    assert placement["minimum_curve_clearance_mm"] == 0.
    updated, reserved = _reserve_vertical_legend_clearance(options, request={"render_options": {}}, series=series, template_id="point_line", placement=placement)
    assert reserved["minimum_curve_clearance_mm"] >= reserved["required_curve_clearance_mm"]
    assert "axis_reserve" in reserved and updated != options
    assert [item.y_values for item in series] == [(163.7, 164.1), (259.8, 260.2)]
    same, unreserved = _reserve_vertical_legend_clearance(options, request={"render_options": {"y_max": 270.}}, series=series, template_id="point_line", placement=placement)
    assert same == options and unreserved == placement


def test_pending_category_response_cannot_adopt_changed_original_source(tmp_path):
    from sciplot_core.task_control import resume_task, start_task
    source = tmp_path / "values.csv"
    source.write_text("Sample,Condition,Value (MPa)\nA,dry,1\nB,dry,2\n")
    task = tmp_path / "task"
    first = start_task({"version": 1, "action": "create", "source": str(source), "categorical": {}}, task_dir=task)
    source.write_text(source.read_text().replace("dry,1", "dry,9"))
    changed = source.read_bytes()
    response = {"expected_question_id": first["question"]["question_id"], "categorical": _binding(source)}
    result = resume_task(task, response)
    assert result["status"] == "blocked" and result["blocker"]["reason_code"] == "source_changed"
    assert not (tmp_path / "values_SciPlot").exists() and source.read_bytes() == changed


@pytest.mark.parametrize("field,value", [
    ("valid_n", True), ("valid_n", 2.0), ("missing_count", 0.0),
    ("unit", "Pa"), ("sample", "invented"), ("condition", "wet"),
    ("source_columns", [2.0]), ("data_start_row", 2), ("extra", "not permitted"),
])
def test_fresh_categorical_disclosure_rejects_every_typed_metadata_tamper(tmp_path, field, value):
    from sciplot_core.source_coverage.replicate_disclosure import verify_replicate_summary_request
    source = tmp_path / "values.csv"
    source.write_text("Sample,Condition,Value (MPa)\nA,dry,1\nA,dry,2\nB,dry,3\nB,dry,4\n")
    binding = _binding(source, "mean_sample_sd_n")
    plan = build_categorical_preview(source, request={"categorical_binding": binding})
    request = {"input": str(source), "template": "bar", **plan["source_options"]}
    assert verify_replicate_summary_request(request)["status"] == "passed"
    changed = deepcopy(request)
    changed["replicate_summary_disclosure"]["groups"][0][field] = value
    with pytest.raises(ValueError):
        verify_replicate_summary_request(changed)


def test_categorical_publication_cannot_rebind_same_numbers_to_other_original_column(tmp_path):
    import json
    from sciplot_core.source_coverage.replicate_disclosure import verify_published_replicate_disclosures
    source = tmp_path / "values.csv"
    source.write_text("Sample,Condition,Value (MPa),Other (MPa)\nA,dry,1,1\nB,dry,2,2\n")
    binding = _binding(source)
    request = {"input": str(source), "template": "point_line", "categorical_binding": binding}
    document = tmp_path / "document.vsz"
    spec = tmp_path / "spec.json"
    spec.write_text(json.dumps({"source_request": request}))
    verify_published_replicate_disclosures(request, [document])
    changed = deepcopy(request)
    changed["categorical_binding"]["value_columns"][0]["column_index"] = 3
    with pytest.raises(ValueError, match="binding"):
        verify_published_replicate_disclosures(changed, [document])


def test_public_capabilities_disclose_categorical_scope_and_keep_compact_index():
    import json
    from sciplot_core.task_capabilities import task_capabilities
    index = task_capabilities()
    assert len(json.dumps(index)) < 2500
    create = task_capabilities(section="request", name="create")
    assert create["scientific_presentation"]["ordinary_categorical"]["rule_id"] is None
    styles = create["scientific_presentation"]["ordinary_categorical"]["series_style_fields"]
    assert styles["given_values"] == ["color", "marker", "marker_fill_mode"]
    assert styles["mean_sample_sd"] == styles["mean_sample_sd_n"] == ["color"]
    assert "arbitrary categorical pivot" in create["scientific_presentation"]["limitations"]
    assert any("categorical" in variant["properties"] for variant in create["schema"]["oneOf"])


@pytest.mark.parametrize("mode", ["mean_sample_sd", "mean_sample_sd_n"])
@pytest.mark.parametrize("field,value", [("marker", "square"), ("marker_fill_mode", "open")])
@pytest.mark.parametrize("complete", [False, True])
def test_summary_marker_requests_fail_in_partial_full_schema_and_public_preflight(tmp_path, mode, field, value, complete):
    from sciplot_core.mapping_contract.categorical import validate_categorical_binding
    from sciplot_core.task_contract import TaskControlError, validate_task_request

    source = tmp_path / "summary.csv"
    source.write_text("Sample,Condition,Strength (MPa)\nA,wet,2\nA,wet,3\nB,wet,4\nB,wet,5\n")
    choice = {"mode": mode, "series_styles": [{"label": "wet", "color": "#B65B43", field: value}]}
    binding = _binding(source, **choice) if complete else choice
    original = source.read_bytes()
    assert not Draft202012Validator(categorical_binding_schema(complete=complete)).is_valid(binding)
    with pytest.raises(ValueError, match="color only"):
        validate_categorical_binding(binding, complete=complete)
    with pytest.raises(TaskControlError, match="color only"):
        validate_task_request({"version": 1, "action": "create", "source": str(source), "categorical": binding})
    if complete:
        with pytest.raises(ValueError, match="color only"):
            build_categorical_preview(source, request={"categorical_binding": binding})
    assert source.read_bytes() == original and not (tmp_path / "summary_SciPlot").exists()


@pytest.mark.parametrize("mode", ["given_values", "mean_sample_sd", "mean_sample_sd_n"])
def test_mode_specific_visible_styles_keep_given_markers_and_summary_color(tmp_path, mode):
    from sciplot_core.mapping_contract.categorical import validate_categorical_binding

    source = tmp_path / "visible.csv"
    rows = "A,wet,2\nB,wet,4\n" if mode == "given_values" else "A,wet,2\nA,wet,3\nB,wet,4\nB,wet,5\n"
    source.write_text("Sample,Condition,Strength (MPa)\n" + rows)
    style = {"label": "wet", "color": "#B65B43"}
    if mode == "given_values":
        style.update(marker="square", marker_fill_mode="open")
    binding = _binding(source, mode, series_styles=[style])
    validate_categorical_binding(binding, complete=True)
    assert Draft202012Validator(categorical_binding_schema(complete=True)).is_valid(binding)
    assert Draft202012Validator(categorical_binding_schema()).is_valid({"mode": mode, "series_styles": [style]})
    preview = build_categorical_preview(source, request={"categorical_binding": binding})
    frozen = preview["source_options"]["render_options"]["series_styles"]
    assert len(frozen) == (1 if mode == "given_values" else 2)
    assert len({item["series_id"] for item in frozen}) == len(frozen)
    assert all({key: item[key] for key in style if key != "label"} ==
               {key: value for key, value in style.items() if key != "label"} for item in frozen)
    series, _ = _derive(source, binding)
    if mode == "given_values":
        assert series[0].marker == "square" and series[0].marker_fill_color == "white"
    else:
        contract = _replicate_distribution_contract(series, template_id="bar", render_options={})
        assert all(group["fill_color"] == "#B65B43" for group in contract["groups"])


@pytest.mark.parametrize("mode", [[], {"mode": "mean_sample_sd"}])
def test_style_preflight_keeps_malformed_mode_inside_public_validation_error(mode):
    from sciplot_core.task_contract import TaskControlError, validate_task_request

    with pytest.raises(TaskControlError, match="Invalid categorical binding"):
        validate_task_request({"version": 1, "action": "create", "source": "original.csv",
            "categorical": {"mode": mode, "series_styles": [{"label": "wet", "marker": "square"}]}})


@pytest.mark.parametrize("mode", ["mean_sample_sd", "mean_sample_sd_n"])
def test_summary_log_scale_fails_schema_runtime_and_public_preflight(tmp_path, mode):
    from sciplot_core.mapping_contract.categorical import validate_categorical_binding
    from sciplot_core.task_contract import TaskControlError, validate_task_request

    source = tmp_path / "summary.csv"
    source.write_text("Sample,Condition,Strength (MPa)\nA,wet,2\nA,wet,3\nB,wet,4\nB,wet,5\n")
    original = source.read_bytes()
    for complete in (False, True):
        choice = {"mode": mode, "yscale": "log"}
        binding = _binding(source, **choice) if complete else choice
        assert not Draft202012Validator(categorical_binding_schema(complete=complete)).is_valid(binding)
        with pytest.raises(ValueError, match="linear yscale and a visible y=0 baseline"):
            validate_categorical_binding(binding, complete=complete)
        with pytest.raises(TaskControlError, match="linear yscale and a visible y=0 baseline"):
            validate_task_request({"version": 1, "action": "create", "source": str(source), "categorical": binding})
        if complete:
            with pytest.raises(ValueError, match="linear yscale and a visible y=0 baseline"):
                build_categorical_preview(source, request={"categorical_binding": binding})
    assert source.read_bytes() == original and not (tmp_path / "summary_SciPlot").exists()


def test_given_value_log_scale_remains_legal_in_schema_runtime_and_preview(tmp_path):
    from sciplot_core.mapping_contract.categorical import validate_categorical_binding
    from sciplot_core.task_contract import validate_task_request

    source = tmp_path / "given.csv"
    source.write_text("Sample,Condition,Strength (MPa)\nA,wet,2\nB,wet,4\n")
    original = source.read_bytes()
    for complete in (False, True):
        choice = {"mode": "given_values", "yscale": "log"}
        binding = _binding(source, **choice) if complete else choice
        assert Draft202012Validator(categorical_binding_schema(complete=complete)).is_valid(binding)
        validate_categorical_binding(binding, complete=complete)
        validate_task_request({"version": 1, "action": "create", "source": str(source), "categorical": binding})
    preview = build_categorical_preview(source, request={"categorical_binding": binding})
    assert preview["source_options"]["render_options"]["yscale"] == "log"
    series, _ = _derive(source, binding)
    assert series[0].y_values == (2., 4.) and source.read_bytes() == original
