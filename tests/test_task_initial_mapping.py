"""Caller-reviewed mappings batch existing choices without bypassing evidence guards."""

from copy import deepcopy
from pathlib import Path

from jsonschema import Draft202012Validator
import pytest

from sciplot_core import task_control as control, task_execution as execution
from sciplot_core.data_mapping import load_data_mapping_execution
from sciplot_core.foundation.file_hashing import file_sha256
from sciplot_core.task_contract import TaskControlError, task_request_schema, validate_task_request
from sciplot_core.task_storage import load_task


def request_for(tmp_path):
    source = tmp_path / "original.csv"
    source.write_text("Wavelength,Absorbance,Wavelength,Absorbance\nnm,a.u.,nm,a.u.\nE0,E0,E3,E3\n400,1,405,3\n450,4,455,5\n500,2,,\n")
    selection = {"sheet": None, "header_rows": [0], "unit_row": 1, "sample_row": 2,
                 "data_start_row": 3, "data_end_row": 6}
    return {"version": 1, "action": "create", "source": str(source), "rule_id": "uvvis_spectrum",
            "mapping": {"source_sha256": file_sha256(source), "table_selection": selection,
                        "column_mapping": {"pairs": [{"x_column": 0, "y_column": 1},
                            {"x_column": 2, "y_column": 3, "table_selection": {**selection, "data_end_row": 5}}]}}}


def fake_native(monkeypatch, tmp_path):
    calls = []
    monkeypatch.setattr(execution, "create_project", lambda *a, **k: calls.append(k) or {
        "project_dir": str(tmp_path / "managed"), "studio_run": {"ready_to_use": True, "failure_reason": None}})
    monkeypatch.setattr(control, "inspect_project", lambda p: {"source": {"current": True}})
    return calls


def effective(result):
    mapped = load_data_mapping_execution(result["data_mapping"]["data_mapping_execution"])
    return Path(mapped["effective_input"]).read_text()


def test_one_call_matches_interactive_mapping_and_does_not_repeat_creation(tmp_path, monkeypatch):
    request = request_for(tmp_path)
    before = Path(request["source"]).read_bytes()
    calls = fake_native(monkeypatch, tmp_path)
    task = tmp_path / "batch"
    batched = control.start_task(request, task_dir=task)
    assert batched["status"] == "complete" and len(calls) == 1
    assert load_task(task)["initial_mapping_attempted"] is True
    assert control.start_task(request, task_dir=task)["status"] == "complete"
    assert control.resume_task(task, {"retry": True})["status"] == "complete"
    assert len(calls) == 1
    interactive = tmp_path / "interactive"
    state = control.start_task({k: v for k, v in request.items() if k != "mapping"} | {"choose_columns": True}, task_dir=interactive)
    for field in ("table_selection", "column_mapping"):
        state = control.resume_task(interactive, {"expected_question_id": state["question"]["question_id"], field: request["mapping"][field]})
    assert state["status"] == "complete" and len(calls) == 2
    assert effective(batched) == effective(state)
    assert "500,2,," in effective(batched)  # Independent point counts are retained.
    assert Path(request["source"]).read_bytes() == before


def test_source_digest_mismatch_blocks_before_native_creation(tmp_path, monkeypatch):
    request = request_for(tmp_path)
    request["mapping"]["source_sha256"] = "0" * 64
    calls = fake_native(monkeypatch, tmp_path)
    state = control.start_task(request, task_dir=tmp_path / "task")
    assert state["status"] == "blocked" and state["blocker"]["reason_code"] == "source_changed"
    assert not calls and "data_mapping" not in state


@pytest.mark.parametrize("invalid", ["cross_sample", "region", "missing_unit"])
def test_invalid_batch_stops_at_correctable_question(tmp_path, monkeypatch, invalid):
    request = request_for(tmp_path)
    good = deepcopy(request["mapping"])
    if invalid == "cross_sample":
        request["mapping"]["column_mapping"] = {"x_column": 0, "y_column": 3}
    elif invalid == "region":
        request["mapping"]["table_selection"]["data_end_row"] = 300
    else:
        path = Path(request["source"])
        path.write_text(path.read_text().replace("nm,a.u.,nm,a.u.", "nm,,nm,a.u."))
        request["mapping"]["source_sha256"] = file_sha256(path)
    calls = fake_native(monkeypatch, tmp_path)
    task = tmp_path / "task"
    state = control.start_task(request, task_dir=task)
    assert state["status"] == "needs_input" and not calls
    assert state["mapping_error"]["reason_code"] == "invalid_mapping_selection"
    assert state["question"]["question_id"]
    if invalid == "region":
        state = control.resume_task(task, {"expected_question_id": state["question"]["question_id"], "table_selection": good["table_selection"]})
    if invalid == "missing_unit":
        # Choosing the complete second pair is a correction; no guessed unit.
        good["column_mapping"] = {"pairs": [good["column_mapping"]["pairs"][1]]}
    state = control.resume_task(task, {"expected_question_id": state["question"]["question_id"], "column_mapping": good["column_mapping"]})
    assert state["status"] == "complete" and len(calls) == 1


def test_metadata_batch_uses_the_same_attributed_confirmation(tmp_path, monkeypatch):
    from test_table_metadata import original, selection, confirmations

    source = original(tmp_path)
    calls = fake_native(monkeypatch, tmp_path)
    result = control.start_task({"version": 1, "action": "create", "source": str(source), "rule_id": "uvvis_spectrum",
        "mapping": {"source_sha256": file_sha256(source), "table_selection": selection(),
                    "metadata_confirmations": confirmations(source), "column_mapping": {"x_column": 0, "y_column": 1}}},
        task_dir=tmp_path / "task")
    assert result["status"] == "complete" and len(calls) == 1
    state = load_task(tmp_path / "task")
    assert state["mapping_choice"]["question"]["evidence"]["metadata_confirmations"] == confirmations(source)


@pytest.mark.parametrize("mutation", ["array", "bool_index", "extra", "sha"])
def test_batch_schema_and_runtime_reject_malformed_mapping(tmp_path, mutation):
    request = request_for(tmp_path)
    if mutation == "array":
        request["mapping"] = [[400, 1]]
    elif mutation == "bool_index":
        request["mapping"]["column_mapping"]["pairs"][0]["x_column"] = True
    elif mutation == "extra":
        request["mapping"]["values"] = [[400, 1]]
    else:
        request["mapping"]["source_sha256"] = "old"
    assert not Draft202012Validator(task_request_schema()).is_valid(request)
    with pytest.raises(TaskControlError, match="mapping"):
        validate_task_request(request)


def test_batch_requires_explicit_rule(tmp_path):
    request = request_for(tmp_path)
    request.pop("rule_id")
    assert not Draft202012Validator(task_request_schema()).is_valid(request)
    with pytest.raises(TaskControlError, match="rule_id"):
        validate_task_request(request)


@pytest.mark.parametrize("change", [{"rule_id": "typo"}, {"template": "unsupported"}])
def test_invalid_batch_rule_or_template_keeps_existing_rule_correction(tmp_path, monkeypatch, change):
    request = request_for(tmp_path) | change
    calls = fake_native(monkeypatch, tmp_path)
    task = tmp_path / "task"
    state = control.start_task(request, task_dir=task)
    assert state["status"] == "needs_input" and state["question"]["field"] == "rule_id" and not calls
    state = control.resume_task(task, {"rule_id": "uvvis_spectrum"})
    assert state["status"] == "complete" and len(calls) == 1


@pytest.mark.parametrize("after_confirmation", [False, True])
def test_interrupted_batch_retry_uses_original_intent_and_saved_confirmation(tmp_path, monkeypatch, after_confirmation):
    from sciplot_core import task_initial_mapping as batch

    request = request_for(tmp_path)
    calls = fake_native(monkeypatch, tmp_path)
    original = batch.accept_column_response

    def interrupted(*args):
        if after_confirmation:
            original(*args)
        raise RuntimeError("interrupted mapping batch")

    monkeypatch.setattr(batch, "accept_column_response", interrupted)
    task = tmp_path / "task"
    state = control.start_task(request, task_dir=task)
    assert state["status"] == "blocked" and not calls
    confirmation = next(task.glob("column_choices/*/confirmation.json"), None)
    digest = file_sha256(confirmation) if confirmation else None
    monkeypatch.setattr(batch, "accept_column_response", original)
    state = control.resume_task(task, {"retry": True})
    assert state["status"] == "complete" and len(calls) == 1
    assert not confirmation or file_sha256(confirmation) == digest


@pytest.mark.comprehensive
def test_public_cli_batch_exports_exact_independent_pairs_and_full_inspect(tmp_path):
    import json
    import subprocess
    from test_project_source_update_native import _native

    request = request_for(tmp_path)
    original = Path(request["source"]).read_bytes()
    path = tmp_path / "request.json"
    path.write_text(json.dumps(request))
    repo = Path(__file__).resolve().parents[1]

    def cli(*args):
        output = subprocess.run([str(repo / "skill/scripts/sciplot"), *map(str, args), "--json"],
                                check=True, capture_output=True, text=True)
        return json.loads(output.stdout)

    state = cli("task", "start", "--request", path, "--task-dir", tmp_path / "task")
    assert state["status"] == "complete", state
    assert all(state["current_project"][key]["current"] for key in ("source", "qa", "delivery"))
    full = cli("task", "inspect", state["task_dir"], "--full")
    assert "figures" in full["result"] and "figures" not in state["result"]
    assert full["data_mapping"] == state["data_mapping"]
    native = _native(Path(state["current_project"]["figures"][0]["document"]))["series"]
    assert native["E0"]["x"] == [400, 450, 500] and native["E0"]["y"] == [1, 4, 2]
    assert native["E3"]["x"] == [405, 455] and native["E3"]["y"] == [3, 5]
    assert all(Path(image).is_file() for image in state["next_step"]["images"])
    assert Path(request["source"]).read_bytes() == original
