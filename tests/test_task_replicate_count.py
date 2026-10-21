"""Generated wide replicate disclosure and genuine missing-policy decisions."""

import json
from copy import deepcopy

import pytest
from jsonschema import Draft202012Validator

from sciplot_core import task_control as control, task_execution as execution
from sciplot_core.foundation.file_hashing import file_sha256
from sciplot_core.foundation.source_tree import source_tree_sha256
from sciplot_core.task_contract import TaskControlError, task_request_schema, task_response_schema, validate_task_request
from sciplot_core.task_replicate_summary import prepare_replicate_disclosure, wide_replicate_evidence


def _source(tmp_path, *, data="1,2\n2,\n10,8\n"):
    path = tmp_path / "impact.csv"
    path.write_text("Impact strength,Impact strength\nkJ/m2,kJ/m2\nAmber,Blue\n" + data)
    return path


def _request(source, **extra):
    return {"version": 1, "action": "create", "source": str(source), "rule_id": "impact_metric",
            "template": "bar", "summary_statistic": "mean_sample_sd_n", **extra}


def test_missing_policy_is_closed_scientific_request_and_response(tmp_path):
    request = _request(_source(tmp_path), missing_values="exclude")
    assert Draft202012Validator(task_request_schema()).is_valid(request)
    assert validate_task_request(request) == request
    response = {"expected_question_id": "a" * 64, "missing_values": "exclude"}
    assert Draft202012Validator(task_response_schema()).is_valid(response)
    for bad in ("zero", "drop", "none_present", None):
        with pytest.raises(TaskControlError):
            validate_task_request({**request, "missing_values": bad})
        assert not Draft202012Validator(task_response_schema()).is_valid({**response, "missing_values": bad})
    with pytest.raises(TaskControlError):
        validate_task_request({**request, "summary_statistic": "raw_only"})
    assert not Draft202012Validator(task_request_schema()).is_valid({**request, "summary_statistic": "raw_only"})


def test_missing_values_question_resume_is_exact_and_preserves_source(tmp_path, monkeypatch):
    source = _source(tmp_path)
    original = file_sha256(source)
    task = tmp_path / "task"
    monkeypatch.setattr(execution, "create_project", lambda *_a, **_k: pytest.fail("missing exclusion was not confirmed"))
    first = control.start_task(_request(source), task_dir=task)
    assert first["status"] == "needs_input", first
    question = first["question"]
    assert question["field"] == "missing_values"
    assert [g["valid_n"] for g in question["evidence"]["groups"]] == [3, 2]
    assert [g["missing_count"] for g in question["evidence"]["groups"]] == [0, 1]
    assert question["source_sha256"] == source_tree_sha256(source)
    for answer in ({"expected_question_id": "0" * 64, "missing_values": "exclude"}, {"rule_id": "impact_metric"}):
        with pytest.raises(TaskControlError):
            control.resume_task(task, answer)
    plans = []
    def prepared(_source, **kwargs):
        plans.append(kwargs["expected_plan"])
        raise RuntimeError("Stop generated control after sealed plan")
    monkeypatch.setattr(execution, "create_project", prepared)
    result = control.resume_task(task, question["response_template"])
    assert result["status"] == "blocked" and len(plans) == 1
    options = plans[0]["source_options"]
    assert options["summary_statistic"] == "mean_sample_sd_n"
    assert options["replicate_summary_disclosure"]["missing_values"] == "exclude"
    state = json.loads((task / "task.json").read_text())
    assert state["missing_value_confirmation"]["question_id"] == question["question_id"]
    assert state["request"].get("missing_values") is None  # Answer is journaled, not invented as a request default.
    assert file_sha256(source) == original


def test_explicit_first_call_exclusion_and_no_missing_are_source_bound(tmp_path):
    source = _source(tmp_path)
    state = {"request": _request(source, missing_values="exclude"), "source_sha256": file_sha256(source)}
    disclosure = prepare_replicate_disclosure(state, source)
    assert disclosure["missing_values"] == "exclude" and "question" not in state
    source.write_text(source.read_text().replace("2,\n", "2,5\n"))
    state = {"request": _request(source), "source_sha256": file_sha256(source)}
    assert prepare_replicate_disclosure(state, source)["missing_values"] == "none_present"
    assert "question" not in state


@pytest.mark.parametrize("data", ["1,2\n,\n,8\n", "1,2\n2,typo\n10,8\n", "1,2\n2,inf\n10,8\n"])
def test_undefined_sd_and_unresolved_cells_stop_before_native(tmp_path, monkeypatch, data):
    source = _source(tmp_path, data=data)
    monkeypatch.setattr(execution, "create_project", lambda *_a, **_k: pytest.fail("undefined or unresolved summary rendered"))
    result = control.start_task(_request(source, missing_values="exclude"), task_dir=tmp_path / "task")
    assert result["status"] == "blocked", result
    assert result["blocker"]["reason_code"] == "replicate_summary_source_invalid"


def test_disclosure_sealed_plan_replays_original_counts_and_rejects_tampering(tmp_path):
    from sciplot_core.plan_preview import build_plan_preview, verify_expected_plan
    from sciplot_core.plan_identity import preview_identity_for

    source = _source(tmp_path)
    evidence = {**wide_replicate_evidence(source), "missing_values": "exclude"}
    plan = build_plan_preview(source, request={"rule_id": "impact_metric", "template": "bar",
        "summary_statistic": "mean_sample_sd_n", "replicate_summary_disclosure": evidence})
    assert plan["status"] == "planned", plan
    assert verify_expected_plan(source, plan, rule_id="impact_metric", template="bar") == plan
    for change in ("count", "unknown", "policy"):
        bad = deepcopy(plan)
        options = bad["source_options"]
        if change == "count":
            options["replicate_summary_disclosure"]["groups"][1]["valid_n"] = 3
        elif change == "policy":
            options["replicate_summary_disclosure"]["missing_values"] = "none_present"
        else:
            options["unknown"] = "exclude"
        bad["preview_identity"] = preview_identity_for(bad, source_sha256=source_tree_sha256(source))
        with pytest.raises(ValueError):
            verify_expected_plan(source, bad, rule_id="impact_metric", template="bar")


def test_summary_csv_projects_audited_values_and_binds_spec_without_statistics(tmp_path, monkeypatch):
    import csv
    from sciplot_core.plot_data.exports import build_plot_data_exports
    from sciplot_core.studio_render.models import StudioSeries
    from sciplot_core.studio_render import categorical_values, replicate_distribution_contract

    source = _source(tmp_path)
    disclosure = {**wide_replicate_evidence(source), "missing_values": "exclude"}
    series = [StudioSeries(label=sample, x_name=f"x{index}", y_name=f"y{index}",
        x_values=[float(index)] * len(values), y_values=values, color="#123456",
        presentation_kind="categorical_replicates", category_position=float(index))
        for index, (sample, values) in enumerate((("Amber", [1., 2., 10.]), ("Blue", [2., 8.])), 1)]
    categorical = replicate_distribution_contract._replicate_distribution_contract(series, template_id="bar", render_options={})
    spec = {"source_request": {"input": str(source), "rule_id": "impact_metric", "template": "bar", "summary_statistic": "mean_sample_sd_n", "replicate_summary_disclosure": disclosure},
            "categorical": categorical, "series": [{"x_values": [1., 1., 1.], "y_values": [1., 2., 10.], "label": "Amber"}]}
    spec_path = tmp_path / "spec.json"
    spec_path.write_text(json.dumps(spec))
    def no_statistics(*_a, **_k):
        pytest.fail("Export recalculated summary statistics")
    monkeypatch.setattr(categorical_values, "_mean_and_sample_sd", no_statistics)
    monkeypatch.setattr(replicate_distribution_contract, "_quantile", no_statistics)
    records = build_plot_data_exports({"veusz_spec": str(spec_path)}, destination=tmp_path / "data")
    summary = next(record for record in records if record.get("data_role") == "mean_sample_sd_n")
    with open(summary["path"], newline="") as handle:
        rows = list(csv.DictReader(handle))
    assert [row["sample"] for row in rows] == ["Amber", "Blue"]
    assert [row["valid_n"] for row in rows] == ["3", "2"]
    assert [row["excluded_missing_count"] for row in rows] == ["0", "1"]
    assert [float(row["mean"]) for row in rows] == [group["bar_mean"] for group in categorical["groups"]]
    assert [float(row["sample_sd"]) for row in rows] == [group["bar_error"] for group in categorical["groups"]]
    assert all(row["spec_sha256"] == file_sha256(spec_path) and row["source_sha256"] == source_tree_sha256(source) for row in rows)
    assert summary["source_sha256"] == file_sha256(spec_path)
    # Historical unmarked and raw-only specs keep their original data export.
    for request in ({}, {"summary_statistic": "raw_only"}):
        spec_path.write_text(json.dumps({**spec, "source_request": request}))
        assert not any(r.get("data_role") for r in build_plot_data_exports({"veusz_spec": str(spec_path)}, destination=tmp_path / "old"))
    bad = deepcopy(spec)
    bad["categorical"]["groups"][1]["replicate_count"] = 3
    spec_path.write_text(json.dumps(bad))
    with pytest.raises(ValueError, match="valid count"):
        build_plot_data_exports({"veusz_spec": str(spec_path)}, destination=tmp_path / "bad")


def test_source_drift_cannot_reuse_missing_question_or_disclosure(tmp_path, monkeypatch):
    from sciplot_core.plan_preview import build_plan_preview, verify_expected_plan

    source = _source(tmp_path)
    task = tmp_path / "task"
    monkeypatch.setattr(execution, "create_project", lambda *_a, **_k: pytest.fail("drifted source reached native"))
    first = control.start_task(_request(source), task_dir=task)
    disclosure = {**wide_replicate_evidence(source), "missing_values": "exclude"}
    plan = build_plan_preview(source, request={"rule_id": "impact_metric", "template": "bar",
        "summary_statistic": "mean_sample_sd_n", "replicate_summary_disclosure": disclosure})
    source.write_text(source.read_text().replace("10,8", "11,8"))
    response = control.resume_task(task, first["question"]["response_template"])
    assert response["status"] == "blocked" and response["blocker"]["reason_code"] == "source_changed"
    state = json.loads((task / "task.json").read_text())
    assert "missing_value_confirmation" not in state
    with pytest.raises(ValueError, match="Source changed"):
        verify_expected_plan(source, plan, rule_id="impact_metric", template="bar")


def test_first_call_scientific_exclude_reaches_sealed_plan_without_extra_question(tmp_path, monkeypatch):
    source = _source(tmp_path)
    plans = []
    def prepared(_source, **kwargs):
        plans.append(kwargs["expected_plan"])
        raise RuntimeError("Stop generated control after sealed plan")
    monkeypatch.setattr(execution, "create_project", prepared)
    result = control.start_task(_request(source, missing_values="exclude"), task_dir=tmp_path / "task")
    assert result["status"] == "blocked" and len(plans) == 1
    assert "question" not in result
    assert plans[0]["source_options"]["replicate_summary_disclosure"]["missing_values"] == "exclude"


def test_summary_csv_keeps_original_workbook_condition_and_processed_raw_export(tmp_path):
    import csv
    import pandas as pd
    from sciplot_core.plot_data.exports import build_plot_data_exports
    from sciplot_core.plot_data.spec_tables import replicate_summary_table

    source = tmp_path / "original.xlsx"
    with pd.ExcelWriter(source) as writer:
        pd.DataFrame([["Impact strength", "Impact strength"], ["kJ/m2", "kJ/m2"], ["Amber", "Blue"],
                      [1, 2], [2, 5], [10, 8]]).to_excel(writer, sheet_name="Cooling 7 min", header=False, index=False)
    evidence = wide_replicate_evidence(source)
    assert all(group["condition"] == "Cooling 7 min" for group in evidence["groups"])
    spec = {"source_request": {"input": str(source), "rule_id": "impact_metric", "template": "bar", "summary_statistic": "mean_sample_sd_n", "replicate_summary_disclosure": {**evidence, "missing_values": "none_present"},
                              "resolved_figure_task": {"conditions": ["Cooling 7 min"]}},
            "categorical": {"presentation_kind": "bar_error", "summary_statistic": "arithmetic_mean", "bar_error_statistic": "sd",
                            "groups": [{"sample_label": sample, "replicate_count": 3, "bar_error_statistic": "sd", "bar_mean": 4., "bar_error": 2.}
                                       for sample in ("Amber", "Blue")]}}
    spec_path = tmp_path / "spec.json"
    spec_path.write_text(json.dumps(spec))
    records = build_plot_data_exports({"processed_source": str(source), "veusz_spec": str(spec_path)}, destination=tmp_path / "data")
    assert [record["source_kind"] for record in records] == ["processed_source", "audited_categorical_contract"]
    with open(records[1]["path"], newline="") as handle:
        assert all(row["condition"] == "Cooling 7 min" and row["missing_policy"] == "none_present" for row in csv.DictReader(handle))
    bad = deepcopy(spec)
    bad["source_request"]["resolved_figure_task"]["conditions"] = ["Invented condition"]
    with pytest.raises(ValueError, match="groups"):
        replicate_summary_table(bad, spec_sha256=file_sha256(spec_path))


def test_on_demand_capability_exposes_wide_bar_n_and_missing_response_only():
    from sciplot_core.task_capabilities import task_capabilities

    create = task_capabilities(section="request", name="create")
    contract = create["scientific_presentation"]["ordinary_impact"]["mean_sample_sd_n_selection"]
    assert contract["templates"] == ["bar"] and contract["minimum_valid_n"] == 2
    assert contract["n_disclosure"] == "source_spec_bound_summary_csv"
    assert contract["missing_values"] == "explicit_exclude_when_missing"
    response = task_capabilities(section="response", name="missing_values")["schema"]
    assert Draft202012Validator(response).is_valid({"expected_question_id": "a" * 64, "missing_values": "exclude"})
    assert not Draft202012Validator(response).is_valid({"expected_question_id": "a" * 64, "missing_values": "none_present"})
