"""Generated controls for original replicate domains through ordinary task choices."""
from copy import deepcopy
import csv
import json
from pathlib import Path

from jsonschema import Draft202012Validator
import pandas as pd
import pytest

from sciplot_core import task_control as control, task_execution as execution
from sciplot_core.data_mapping import load_data_mapping_execution
from sciplot_core.foundation.file_hashing import file_sha256
from sciplot_core.plan_preview import verify_expected_plan
from sciplot_core.task_choice_schema import column_mapping_schema
from sciplot_core.task_contract import TaskControlError
from sciplot_core.task_storage import load_task, save_task


def original(tmp_path):
    source = tmp_path / "measurements.csv"
    source.write_text("Re,Re.1,Re.2\nkJ/m²,kJ/m²,kJ/m²\nAmber,Blue,Coral\n1,7,11\n,8,12\n1,,13\n3,,14\n,9,15\n5,,\n,,\n")
    selection = {"sheet": None, "header_rows": [0], "unit_row": 1, "sample_row": 2,
                 "data_start_row": 3, "data_end_row": 10}
    request = {"version": 1, "action": "create", "source": str(source), "rule_id": "impact_metric",
               "template": "box", "summary_statistic": "raw_only", "choose_columns": True}
    mapping = {"source_sha256": file_sha256(source), "table_selection": selection,
               "column_mapping": {"replicates": [{"column_index": 0}, {"column_index": 1}]}}
    return source, request, mapping


def native_boundary(monkeypatch, tmp_path):
    calls = []
    monkeypatch.setattr(execution, "create_project", lambda *a, **k: calls.append(k) or {
        "project_dir": str(tmp_path / "managed"), "studio_run": {"ready_to_use": True, "failure_reason": None}})
    monkeypatch.setattr(control, "inspect_project", lambda p: {"source": {"current": True}})
    return calls


def answer(task, state, mapping):
    return control.resume_task(task, {"expected_question_id": state["question"]["question_id"], "mapping": mapping})


def test_raw_subset_keeps_complete_grid_and_mask_before_finite_display(tmp_path, monkeypatch):
    source, request, mapping = original(tmp_path)
    before = source.read_bytes()
    calls = native_boundary(monkeypatch, tmp_path)
    task = tmp_path / "task"
    state = control.start_task(request, task_dir=task)
    assert state["status"] == "needs_input"
    assert state["question"]["mapping_shape"] == "replicates"
    assert not state["question"].get("mapping_candidates")
    assert "column_mapping.replicates" in state["next_step"]["message"]
    state = answer(task, state, mapping)
    assert state["status"] == "complete" and len(calls) == 1, state
    mapped = load_data_mapping_execution(state["data_mapping"]["data_mapping_execution"])
    assert [item["rows"] for item in mapped["outputs"]] == [7, 7]
    frames = [pd.read_csv(item["path"]) for item in mapped["outputs"]]
    assert frames[0].iloc[:, 0].isna().tolist() == [False, True, False, False, True, False, True]
    assert frames[1].iloc[:, 0].isna().tolist() == [False, False, True, True, False, True, True]
    assert frames[0].iloc[:, 0].dropna().tolist() == [1, 1, 3, 5]
    assert frames[1].iloc[:, 0].dropna().tolist() == [7, 8, 9]
    plan = calls[0]["expected_plan"]
    assert plan["status"] == "planned" and plan["scientific_transform"] is None
    assert plan["source_options"] == {"summary_statistic": "raw_only"}
    assert plan["data_mapping"]["mapping_shape"] == "replicates"
    assert plan["data_mapping"]["expected_sample_labels"] == ["Amber", "Blue"]
    assert "expected_series_points" not in plan["data_mapping"]
    assert verify_expected_plan(source, plan, rule_id="impact_metric", template="box") == plan
    assert source.read_bytes() == before
    assert control.resume_task(task, {"retry": True})["status"] == "complete" and len(calls) == 1


def test_batch_and_interactive_choices_share_immutable_confirmation(tmp_path, monkeypatch):
    source, request, mapping = original(tmp_path)
    calls = native_boundary(monkeypatch, tmp_path)
    result = control.start_task({**request, "mapping": mapping}, task_dir=tmp_path / "task")
    assert result["status"] == "complete" and len(calls) == 1, result
    state = load_task(tmp_path / "task")
    proposal = json.loads(Path(state["mapping_choice"]["proposal_path"]).read_text())
    assert [item["role"] for item in proposal["columns"]] == ["value", "value"]
    assert proposal["table_confirmation"]["replicates"] == mapping["column_mapping"]["replicates"]
    assert all(item["data_start_row"] == 3 and item["data_end_row"] == 10 for item in proposal["sources"])
    assert all(item["sha256"] == file_sha256(source) and item["cell_evidence"] for item in proposal["sources"])


@pytest.mark.parametrize("bad", ["xy", "overlap", "wrong_unit", "bad_cell", "missing_sample"])
def test_invalid_raw_selection_can_be_corrected_in_same_task(tmp_path, monkeypatch, bad):
    source, request, mapping = original(tmp_path)
    if bad == "wrong_unit":
        source.write_text(source.read_text().replace("kJ/m²,kJ/m²,kJ/m²", "MPa,kJ/m²,kJ/m²"))
    elif bad == "bad_cell":
        source.write_text(source.read_text().replace("1,7,11", "broken,7,11"))
    elif bad == "missing_sample":
        source.write_text(source.read_text().replace("Amber,Blue,Coral", ",Blue,Coral"))
    mapping["source_sha256"] = file_sha256(source)
    good = deepcopy(mapping)
    if bad == "xy":
        mapping["column_mapping"] = {"x_column": 0, "y_column": 1}
    elif bad == "overlap":
        mapping["column_mapping"]["replicates"].append({"column_index": 0, "label": "duplicate"})
    else:
        good["column_mapping"] = {"replicates": [{"column_index": 1}]}
    calls = native_boundary(monkeypatch, tmp_path)
    task = tmp_path / "task"
    state = control.start_task(request, task_dir=task)
    state = answer(task, state, mapping)
    assert state["status"] == "needs_input" and not calls, state
    assert state["mapping_error"]["reason_code"] == "invalid_mapping_selection"
    state = answer(task, state, good)
    assert state["status"] == "complete" and len(calls) == 1, state


def test_replicate_choice_cannot_enter_curve_or_summary_adapter(tmp_path, monkeypatch):
    _, request, mapping = original(tmp_path)
    calls = native_boundary(monkeypatch, tmp_path)
    result = control.start_task({**request, "summary_statistic": "mean_sample_sd_n", "mapping": mapping}, task_dir=tmp_path / "summary")
    assert result["status"] == "blocked" and not calls
    result = control.start_task({**request, "rule_id": "uvvis_spectrum", "mapping": mapping}, task_dir=tmp_path / "curve")
    assert result["status"] == "needs_input" and not calls


def test_question_digest_and_source_digest_remain_required(tmp_path, monkeypatch):
    source, request, mapping = original(tmp_path)
    calls = native_boundary(monkeypatch, tmp_path)
    task = tmp_path / "task"
    state = control.start_task(request, task_dir=task)
    with pytest.raises(TaskControlError, match="旧问题"):
        control.resume_task(task, {"expected_question_id": "0" * 64, "mapping": mapping})
    mapping["source_sha256"] = "0" * 64
    state = answer(task, state, mapping)
    assert state["mapping_error"]["reason_code"] == "mapping_source_mismatch" and not calls
    mapping["source_sha256"] = file_sha256(source)
    state = answer(task, state, mapping)
    assert state["status"] == "complete" and len(calls) == 1


def test_old_precreation_blocker_retries_into_question_but_uncertain_output_stays_blocked(tmp_path, monkeypatch):
    _, request, _ = original(tmp_path)
    calls = native_boundary(monkeypatch, tmp_path)
    task = tmp_path / "task"
    control.start_task(request, task_dir=task)
    old = load_task(task)
    old.update(status="blocked", phase="planning", blocker={"reason_code": "column_mapping_unsupported", "message": "old curve-only gate"})
    old.pop("question")
    save_task(task, old)
    state = control.resume_task(task, {"retry": True})
    assert state["status"] == "needs_input" and state["question"]["mapping_shape"] == "replicates" and not calls
    old.update(phase="creating", blocker={"reason_code": "creation_outcome_uncertain", "message": "unknown outcome"})
    from sciplot_core.output_contract import resolve_user_output_layout
    from sciplot_core.task_execution import creation_output
    layout = resolve_user_output_layout(request["source"], requested_delivery_root=creation_output(old))
    layout.workspace_root.mkdir(parents=True)
    save_task(task, old)
    state = control.resume_task(task, {"retry": True})
    assert state["status"] == "blocked" and state["blocker"]["reason_code"] == "creation_outcome_uncertain" and not calls


def test_closed_schema_rejects_mixed_shapes_and_unbacked_arrays():
    valid = {"replicates": [{"column_index": 0}]}
    validator = Draft202012Validator(column_mapping_schema())
    assert validator.is_valid(valid)
    for invalid in ({**valid, "pairs": [{"x_column": 0, "y_column": 1}]},
                    {"replicates": [{"column_index": True}]}, {"replicates": [{"values": [1, 2]}]}):
        assert not validator.is_valid(invalid)


def test_unknown_creation_without_output_cannot_reopen_raw_choice(tmp_path, monkeypatch):
    _, request, _ = original(tmp_path)
    calls = native_boundary(monkeypatch, tmp_path)
    task = tmp_path / "task"
    control.start_task(request, task_dir=task)
    state = load_task(task)
    state.update(status="blocked", phase="creating", blocker={"reason_code": "creation_outcome_uncertain", "message": "native result is unknown"})
    state.pop("question")
    save_task(task, state)
    plan = (task / "plan.json").read_bytes()
    result = control.resume_task(task, {"retry": True})
    assert result["status"] == "blocked" and result["blocker"]["reason_code"] == "creation_outcome_uncertain"
    current = load_task(task)
    assert current["phase"] == "creating" and current["request"] == state["request"]
    assert not calls and "question" not in current and (task / "plan.json").read_bytes() == plan


def test_workbook_groups_have_independent_explicit_sheet_domains(tmp_path, monkeypatch):
    source = tmp_path / "workbook.xlsx"
    with pd.ExcelWriter(source) as writer:
        pd.DataFrame([["Re"], ["kJ/m²"], ["Amber"], [1], [None], [2], [None], [3]]).to_excel(writer, sheet_name="thin", header=False, index=False)
        pd.DataFrame([["Re"], ["kJ/m²"], ["Blue"], [8], [9], [10]]).to_excel(writer, sheet_name="thick", header=False, index=False)
    selection = {"sheet": "thin", "header_rows": [0], "unit_row": 1, "sample_row": 2, "data_start_row": 3, "data_end_row": 8}
    request = {"version": 1, "action": "create", "source": str(source), "rule_id": "impact_metric", "template": "box_strip", "summary_statistic": "raw_only",
               "mapping": {"source_sha256": file_sha256(source), "table_selection": selection,
                           "column_mapping": {"replicates": [{"column_index": 0}, {"column_index": 0, "table_selection": {**selection, "sheet": "thick", "data_end_row": 6}}]}}}
    calls = native_boundary(monkeypatch, tmp_path)
    state = control.start_task(request, task_dir=tmp_path / "task")
    assert state["status"] == "complete" and len(calls) == 1, state
    mapped = load_data_mapping_execution(state["data_mapping"]["data_mapping_execution"])
    assert [item["rows"] for item in mapped["outputs"]] == [5, 3]
    composite = list(csv.reader(Path(mapped["effective_input"]).open()))
    assert composite[2] == ["Amber", "Blue"] and float(composite[-1][0]) == 3 and composite[-1][1] == ""
    assert calls[0]["expected_plan"]["data_mapping"]["expected_sample_labels"] == ["Amber", "Blue"]


def test_raw_projection_preserves_decimal_bits_duplicates_and_numeric_sample(tmp_path, monkeypatch):
    source, request, mapping = original(tmp_path)
    tokens = ["0.12345678901234567", "1.0000000000000002", "0.12345678901234567"]
    source.write_text("Impact strength,Notes\nkJ/m2,\n100,\n" + tokens[0] + ',\n,\n' + tokens[1] + ',\n' + tokens[2] + ',\n')
    mapping.update(source_sha256=file_sha256(source), table_selection={**mapping["table_selection"], "data_end_row": 7},
                   column_mapping={"replicates": [{"column_index": 0}]})
    calls = native_boundary(monkeypatch, tmp_path)
    result = control.start_task({**request, "mapping": mapping}, task_dir=tmp_path / "task")
    assert result["status"] == "complete" and len(calls) == 1, result
    mapped = load_data_mapping_execution(result["data_mapping"]["data_mapping_execution"])
    from sciplot_core.semantic_sources.impact_sources import _read_impact_source
    payload = _read_impact_source(Path(mapped["effective_input"]))
    assert payload.samples == ("100",)
    assert [value.hex() for value in payload.values[0]] == [float(value).hex() for value in tokens]
    assert mapped["outputs"][0]["rows"] == 4


@pytest.mark.parametrize("structured", [False, True])
def test_xy_table_serialization_retains_original_bytes(tmp_path, structured):
    from sciplot_core.data_mapping.output_files import paired_table_text
    from sciplot_core.data_mapping.source_mapping import _prepare_mapping_frames
    from sciplot_core.data_mapping.table_choice import table_choice_snapshot, select_table, proposal_for_table_columns
    source = tmp_path / "xy.csv"
    expected = "Wavelength,Absorbance\nnm,a.u.\nAmber,Amber\n400.1234567890123,0.12345678901234567\n450.2345678901234,1.2345678901234567\n"
    source.write_text(expected)
    selected = select_table(table_choice_snapshot(source, "uvvis_spectrum"),
                            {"sheet": None, "header_rows": [0], "unit_row": 1, "sample_row": 2, "data_start_row": 3, "data_end_row": 5})
    seed = tmp_path / "seed.json"
    seed.write_text("{}")
    proposal = proposal_for_table_columns(selected, pairs=[{"x_column": 0, "y_column": 1}], request_path=seed,
                                         proposal_id="xy_unchanged", created_at="2026-10-20T00:00:00+00:00",
                                         structured_identity=structured)
    _, frames, _, _, _ = _prepare_mapping_frames(proposal, source_root=tmp_path)
    serialized = paired_table_text(proposal, frames)
    assert serialized.splitlines()[3:] == expected.splitlines()[3:]
    assert list(proposal.sample_labels.values()) == ["Amber"]
    if structured:
        assert serialized.splitlines()[2] == ",".join([proposal.sources[0].source_id] * 2)
    else:
        assert serialized.encode() == expected.encode()
    assert source.read_bytes() == expected.encode()


@pytest.mark.parametrize("after_confirmation", [False, True])
def test_interrupted_raw_choice_reuses_same_task_confirmation(tmp_path, monkeypatch, after_confirmation):
    from sciplot_core import task_initial_mapping as initial
    _, request, mapping = original(tmp_path)
    calls = native_boundary(monkeypatch, tmp_path)
    real = initial.accept_column_response

    def interrupt(*args):
        if after_confirmation:
            real(*args)
        raise RuntimeError("generated interruption")

    monkeypatch.setattr(initial, "accept_column_response", interrupt)
    task = tmp_path / "task"
    result = control.start_task({**request, "mapping": mapping}, task_dir=task)
    assert result["status"] == "blocked" and not calls
    confirmation = next(task.glob("column_choices/*/confirmation.json"), None)
    digest = file_sha256(confirmation) if confirmation else None
    monkeypatch.setattr(initial, "accept_column_response", real)
    result = control.resume_task(task, {"retry": True})
    assert result["status"] == "complete" and len(calls) == 1
    assert not confirmation or file_sha256(confirmation) == digest
