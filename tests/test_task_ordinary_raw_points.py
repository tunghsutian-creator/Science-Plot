"""Generated controls for ordinary original-value creation without summaries."""
import pytest


def test_single_categorical_tick_audit_keeps_exact_axis_guards_and_rejects_other_ticks():
    from copy import deepcopy
    from sciplot_core.veusz_worker.axis_matchers import _axis_record_matches_spec

    axis = {"label": "Sample", "mode": "labels", "category_labels": ["Amber"], "category_positions": [1.],
            "ticks": [1.], "scale": "linear", "min": .5, "max": 1.5, "foreground_color": "#111111",
            "label_size_pt": 7., "tick_label_size_pt": 7., "line_width_pt": .8,
            "major_tick_width_pt": .8, "major_tick_length_pt": 2.8, "minor_tick_width_pt": .8, "minor_tick_length_pt": 1.5}
    bindings = {"label": "Sample", "direction": "horizontal", "mode": "labels", "log": False, "min": .5, "max": 1.5,
                "TickLabels/format": "Auto", "MajorTicks/manualTicks": [], "MinorTicks/number": 20, "MinorTicks/manualTicks": []}
    for path in ("MajorTicks/hide", "MinorTicks/hide", "TickLabels/hide", "Label/hide", "Line/hide"):
        bindings[path] = False
    for path in ("Line/transparency", "MajorTicks/transparency", "MinorTicks/transparency"):
        bindings[path] = 0
    for path in ("Line/color", "Label/color", "TickLabels/color"):
        bindings[path] = "#111111"
    for path, value in {"Label/size": 7, "TickLabels/size": 7, "Line/width": .8, "MajorTicks/width": .8,
                        "MajorTicks/length": 2.8, "MinorTicks/width": .8, "MinorTicks/length": 1.5}.items():
        bindings[path] = f"{value}pt"
    record = {"name": "x", "bindings": bindings}
    assert _axis_record_matches_spec(record, axis, axis_name="x")
    for ticks in ([1.], [9.], [1., 2.]):
        changed = deepcopy(record)
        changed["bindings"]["MajorTicks/manualTicks"] = ticks
        assert _axis_record_matches_spec(changed, axis, axis_name="x") is (ticks == [1.])
    for field, value in (("mode", "numeric"), ("category_positions", [2.]), ("category_labels", []),
                         ("category_labels", ["Amber", "Red"]), ("ticks", [2.])):
        assert not _axis_record_matches_spec(record, {**axis, field: value}, axis_name="x")
    for field, value in (("label", "Wrong label"), ("min", .6), ("max", 1.4), ("log", True)):
        changed = deepcopy(record)
        changed["bindings"][field] = value
        assert not _axis_record_matches_spec(changed, axis, axis_name="x")


def test_raw_categorical_decimal_parsing_preserves_precision_and_unversioned_legacy_contract(tmp_path):
    import pandas as pd
    from sciplot_core.source_tables.parsing import DECIMAL_ROUND_TRIP_ENCODING, SOURCE_NUMERIC_ENCODING_KEY
    from sciplot_core.source_coverage.file_snapshots import _stable_file_snapshot
    from sciplot_core.source_coverage.managed_documents import _verify_prepared_data
    from sciplot_core.studio_render import derive_terminal_render_data_contract

    tokens = ["0.12345678901234567", "1.0000000000000002", "2.3400000000000003"]
    source = tmp_path / "replicates.csv"
    source.write_text("Impact strength\nkJ/m2\nAmber\n" + "\n".join(tokens) + "\n")
    original = source.read_bytes()
    request = {"rule_id": "impact_metric", "template": "box_strip", "render_options": {"summary_statistic": "raw_only"}}

    def source_spec(*, legacy):
        units = derive_terminal_render_data_contract(request=request, terminal_sources=[source], legacy_numeric_parser=legacy)["units"]
        return {"source_request": request, "series": units, "axes": units[0]["axes"],
                "categorical": units[0]["categorical_contract"], "reference_guides": units[0]["reference_guides"],
                "direct_labels": units[0]["direct_labels"]}

    current, historical = source_spec(legacy=False), source_spec(legacy=True)
    exact = [float(value) for value in tokens]
    legacy = pd.to_numeric(pd.Series(tokens), errors="coerce").tolist()
    assert [value.hex() for value in current["series"][0]["y_values"]] == [value.hex() for value in exact]
    assert [value.hex() for value in historical["series"][0]["y_values"]] == [value.hex() for value in legacy]
    assert legacy[0].hex() != exact[0].hex()
    snapshots = [_stable_file_snapshot(source, label="generated categorical decimals")]
    assert _verify_prepared_data(historical, snapshots)["status"] == "passed"
    assert _verify_prepared_data(current, snapshots)["status"] == "passed"
    assert _verify_prepared_data({**current, SOURCE_NUMERIC_ENCODING_KEY: DECIMAL_ROUND_TRIP_ENCODING}, snapshots)["status"] == "passed"
    with pytest.raises(ValueError, match="do not reproduce"):
        _verify_prepared_data({**historical, SOURCE_NUMERIC_ENCODING_KEY: DECIMAL_ROUND_TRIP_ENCODING}, snapshots)
    assert source.read_bytes() == original


def _impact(tmp_path):
    source = tmp_path / "impact.csv"
    source.write_text("Impact strength,Impact strength\nkJ/m2,kJ/m2\nB,A\n8,4\n8,\n8,7\n8,7\n8,\n")
    return source


@pytest.mark.parametrize("template", ["box", "box_strip"])
def test_raw_only_is_bound_through_verified_plan_and_skips_summary_calculators(tmp_path, monkeypatch, template):
    from sciplot_core.plan_preview import build_plan_preview, verify_expected_plan
    from sciplot_core.studio_render import categorical_layout, replicate_distribution_contract
    from sciplot_core.studio_render.models import StudioSeries
    from sciplot_core.materials_rules import analysis
    from sciplot_core.task_scientific_presentation import scientific_presentation, presentation_blocker

    source = _impact(tmp_path)
    original = source.read_bytes()
    request = {"rule_id": "impact_metric", "template": template, "summary_statistic": "raw_only"}
    plan = build_plan_preview(source, request=request)
    assert plan["status"] == "planned", plan
    assert plan["source_options"] == {"summary_statistic": "raw_only"}
    assert verify_expected_plan(source, plan, rule_id="impact_metric", template=template) == plan
    effective = scientific_presentation(request, rule_id="impact_metric", template=template)
    assert presentation_blocker(request, effective) is None
    assert effective["statistics_contract"]["summary_calculation"] == "none"
    assert effective["statistics_contract"]["center"] is None

    def no_summary(*_a, **_k):
        pytest.fail("raw-only creation computed a summary")

    monkeypatch.setattr(replicate_distribution_contract, "_quantile", no_summary)
    monkeypatch.setattr(replicate_distribution_contract, "_mean_and_sample_sd", no_summary)
    monkeypatch.setattr(categorical_layout, "_quantile", no_summary)
    monkeypatch.setattr(analysis, "_impact_metrics", no_summary)
    series = [StudioSeries(label="B", x_name="x", y_name="y", x_values=(1.,) * 5,
                           y_values=(8.,) * 5, color="#222222", presentation_kind="categorical_replicates")]
    contract = replicate_distribution_contract._replicate_distribution_contract(
        series, template_id=template, render_options={"summary_statistic": "raw_only"})
    assert contract["summary_calculation"] == "none"
    assert contract["native_veusz_boxplot"] is False
    assert contract["presentation_kind"] == "raw_points"
    assert contract["raw_replicate_count"] == 5
    assert contract["groups"][0]["raw_values"] == [8.] * 5
    assert contract["groups"][0]["boxplot_eligible"] is False
    assert contract["groups"][0]["raw_points_visible"] is True
    assert "descriptive_statistics" not in contract["groups"][0]
    # The raw-only guard precedes even axis/aspect accesses.
    assert categorical_layout._apply_categorical_box_aspect_width(
        {"summary_statistic": "raw_only"}, series, axis_contract=None, template_id=template) == {"summary_statistic": "raw_only"}
    assert analysis.compute_analysis_metrics(source_path=source, processed_source=source,
        semantic={"rule_id": "impact_metric"}, output_dir=tmp_path / "analysis", summary_statistic="raw_only") == []
    assert source.read_bytes() == original


@pytest.mark.parametrize("template,value", [("bar", "raw_only"), ("point_line", "raw_only"), ("box", "mean_sample_sd"), ("box_strip", "unknown")])
def test_raw_source_option_does_not_change_fixed_statistics_or_accept_unknown_values(tmp_path, template, value):
    from sciplot_core.plan_preview import build_plan_preview

    result = build_plan_preview(_impact(tmp_path), request={"rule_id": "impact_metric", "template": template, "summary_statistic": value})
    assert result["status"] == "blocked"
    assert result["blocker"]["reason_code"] == "plan_source_option_invalid"


def test_no_experiment_numeric_xy_preserves_signed_ordered_missing_measurements_and_context(tmp_path):
    from sciplot_core.task_semantic_creation import build_managed_request
    from sciplot_core.task_semantic_contract import validate_intent
    from sciplot_core.task_semantic_plan import prepare_plan
    from sciplot_core.plot_engine.managed_sources import load_sources
    from sciplot_core.plot_ir import create_managed_document
    from sciplot_core.plot_transforms import resolve_transforms

    source = tmp_path / "acquisition.csv"
    source.write_text("Temperature,Heat Flow\nC,W/g\nSample Z,Sample Z\n66,-0.023\n61,0.008\n61,\n53,-0.016\n")
    original = source.read_bytes()
    intent = validate_intent({"x": {"quantity": "temperature"}, "y": {"quantity": "heat_flow"},
                              "source_context": "Original cooling acquisition; no baseline correction, normalization or integration."})
    plan = prepare_plan([source], intent)
    assert plan["decisions"] == []
    wire = build_managed_request({"request": {"intent": intent}, "semantic_plan": plan,
        "semantic_choices": {}, "task_dir": str(tmp_path / "task"), "intent_revision": 1})
    assert wire["rule_id"] == "ordinary_xy"
    assert wire["data_binding"]["provenance"]["semantic_task"]["intent"] == intent
    assert {node["kind"] for node in wire["data_binding"]["transforms"]} <= {"select", "row_slice", "rename"}
    document = create_managed_document(wire["template_definition"], wire["data_binding"], plot_id="ordinary-control")
    datasets = resolve_transforms(document, load_sources(document, wire["rule_id"]))["datasets"]
    layer = wire["template_definition"]["figure_spec"]["views"][0]["layers"][0]
    data = datasets[layer["dataset_id"]]["columns"]
    assert data["x"]["values"] == [66., 61., 61., 53.]
    assert data["y"]["values"] == [-.023, .008, None, -.016]
    assert data["x"]["unit"] == "C" and data["y"]["unit"] == "W/g"
    assert {slot["sample"] for slot in wire["data_binding"]["slots"].values()} == {"Sample Z"}
    assert source.read_bytes() == original


def test_no_experiment_time_xy_does_not_infer_stages_or_remove_missing_x_rows(tmp_path):
    from sciplot_core.task_semantic_creation import build_managed_request
    from sciplot_core.task_semantic_plan import prepare_plan
    from sciplot_core.plot_engine.managed_sources import load_sources
    from sciplot_core.plot_ir import create_managed_document
    from sciplot_core.plot_transforms import resolve_transforms

    source = tmp_path / "acquisition.csv"
    source.write_text("Time,Signal\ns,Pa\n2,-4\n1,3\n,7\n3,-1\n")
    original = source.read_bytes()
    intent = {"x": {"quantity": "time"}, "y": {"quantity": "response", "header": "Signal"}}
    plan = prepare_plan([source], intent)
    assert plan["decisions"] == []
    assert [stage["point_count"] for stage in plan["sources"][0]["candidates"][0]["stages"]] == [4]
    wire = build_managed_request({"request": {"intent": intent}, "semantic_plan": plan,
        "semantic_choices": {}, "task_dir": str(tmp_path / "task"), "intent_revision": 1})
    assert "concat_time" not in {node["kind"] for node in wire["data_binding"]["transforms"]}
    document = create_managed_document(wire["template_definition"], wire["data_binding"], plot_id="ordinary-time-control")
    datasets = resolve_transforms(document, load_sources(document, wire["rule_id"]))["datasets"]
    layer = wire["template_definition"]["figure_spec"]["views"][0]["layers"][0]
    assert datasets[layer["dataset_id"]]["columns"]["x"]["values"] == [2., 1., None, 3.]
    assert datasets[layer["dataset_id"]]["columns"]["y"]["values"] == [-4., 3., 7., -1.]
    assert source.read_bytes() == original


@pytest.mark.parametrize("source_text,intent,reason", [
    ("Temperature,Heat Flow\n66,-0.023\n61,0.008\n", {"x": {"quantity": "temperature"}, "y": {"quantity": "heat_flow"}}, "semantic_source_unit_required"),
    ("position,signal,other\ns,Pa,Pa\n1,2,3\n2,3,4\n", {"x": {"quantity": "time", "header": "position"}, "y": {"quantity": "response"}}, "coordinate_choice"),
], ids=["missing_unit", "ambiguous_source"])
def test_ordinary_xy_still_stops_for_missing_units_or_ambiguous_source(tmp_path, source_text, intent, reason):
    from sciplot_core.task_errors import TaskControlError
    from sciplot_core.task_semantic_plan import prepare_plan

    source = tmp_path / "original.csv"
    source.write_text(source_text)
    if reason == "coordinate_choice":
        plan = prepare_plan([source], intent)
        assert plan["decisions"] == [{"field": "y_header", "options": ["other", "position", "signal"],
            "message": "Select the exact observed original column header for this coordinate; units alone do not choose a response."}]
        return
    with pytest.raises(TaskControlError) as failure:
        prepare_plan([source], intent)
    assert failure.value.reason_code == reason
