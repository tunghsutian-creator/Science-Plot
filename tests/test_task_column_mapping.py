from __future__ import annotations

import json
from pathlib import Path

import pytest

from sciplot_core import task_control as control, task_execution as execution
from sciplot_core.data_mapping import load_data_mapping_execution
from sciplot_core.task_contract import TaskControlError
from sciplot_core.task_storage import load_task


def source(root: Path) -> Path:
    path = root / "UVvis.csv"
    path.write_text("Wavelength (nm),,Absorbance (a.u.),Absorbance (a.u.)\n500,,1,9\n450,,4,3\n400,,2,7\n")
    return path


def start(tmp_path, monkeypatch):
    raw = source(tmp_path)
    calls = []
    monkeypatch.setattr(execution, "create_project", lambda *args, **kwargs: calls.append(kwargs) or {
        "project_dir": str(tmp_path / "managed"), "studio_run": {"ready_to_use": True, "failure_reason": None},
    })
    task = tmp_path / "task"
    result = control.start_task({"version": 1, "action": "create", "source": str(raw),
                                 "rule_id": "uvvis_spectrum"}, task_dir=task)
    assert result["status"] == "needs_input" and not calls
    return raw, task, result, calls


def response(result, *, x=0, y=3):
    return {"expected_question_id": result["question"]["question_id"],
            "column_mapping": {"x_column": x, "y_column": y}}


def test_ambiguous_response_columns_pause_with_original_cells_and_preserve_chosen_values(tmp_path, monkeypatch):
    raw, task, question, calls = start(tmp_path, monkeypatch)
    original = raw.read_bytes()
    evidence = question["question"]["evidence"]
    assert [column["index"] for column in evidence["columns"]] == [0, 1, 2, 3]
    assert evidence["rows"][1] == {"row_index": 1, "cells": ["500", "", "1", "9"]}
    completed = control.resume_task(task, response(question))
    assert completed["status"] == "complete" and len(calls) == 1
    plan = calls[0]["expected_plan"]
    assert plan["source"] == str(raw)
    mapped = load_data_mapping_execution(completed["data_mapping"]["data_mapping_execution"])
    assert Path(mapped["effective_input"]).read_text().splitlines()[1:] == ["500,9", "450,3", "400,7"]
    assert mapped["transform_steps"][0]["input_artifacts"][0]["path"] == str(raw)
    assert completed["profile_unavailable"]["reason_code"] == "mapped_profile_unsupported"
    assert raw.read_bytes() == original
    assert control.resume_task(task, response(question))["status"] == "complete"
    assert len(calls) == 1


@pytest.mark.parametrize("change", [
    {"expected_question_id": "a" * 64},
    {"column_mapping": {"x_column": True, "y_column": 3}},
    {"column_mapping": {"x_column": 0, "y_column": -1}},
    {"column_mapping": {"x_column": 2, "y_column": 3}},
    {"column_mapping": {"x_column": 0, "y_column": 1}},
])
def test_invalid_answers_leave_current_question_correctable(tmp_path, monkeypatch, change):
    _raw, task, question, calls = start(tmp_path, monkeypatch)
    before = (task / "task.json").read_bytes()
    with pytest.raises(TaskControlError):
        control.resume_task(task, {**response(question), **change})
    assert (task / "task.json").read_bytes() == before and not calls
    assert control.resume_task(task, response(question))["status"] == "complete"


def test_changed_source_rejects_old_answer_without_creating_project(tmp_path, monkeypatch):
    raw, task, question, calls = start(tmp_path, monkeypatch)
    raw.write_text(raw.read_text().replace("500,,1,9", "500,,1,10"))
    result = control.resume_task(task, response(question))
    assert result["status"] == "blocked" and result["blocker"]["reason_code"] == "source_changed"
    assert not calls


def test_interrupted_creation_reuses_same_confirmed_mapping(tmp_path, monkeypatch):
    _raw, task, question, _calls = start(tmp_path, monkeypatch)
    def failed(*args, **kwargs):
        raise RuntimeError("interrupted before creating output")
    monkeypatch.setattr(execution, "create_project", failed)
    first = control.resume_task(task, response(question))
    assert first["status"] == "blocked" and first["phase"] == "creating"
    state = load_task(task)
    confirmation = Path(state["mapping_choice"]["confirmation_path"]).read_bytes()
    effective = load_data_mapping_execution(first["data_mapping"]["data_mapping_execution"])["effective_input"]
    before = Path(effective).stat().st_mtime_ns
    monkeypatch.setattr(execution, "create_project", lambda *args, **kwargs: {
        "project_dir": str(tmp_path / "managed"), "studio_run": {"ready_to_use": True, "failure_reason": None},
    })
    assert control.resume_task(task, {"retry": True})["status"] == "complete"
    assert Path(state["mapping_choice"]["confirmation_path"]).read_bytes() == confirmation
    assert Path(effective).stat().st_mtime_ns == before


def test_explicit_three_row_selection_does_not_cross_sample_pairs(tmp_path, monkeypatch):
    raw = tmp_path / "UVvis.csv"
    raw.write_text("Wavelength,Absorbance,Wavelength,Absorbance\nnm,a.u.,nm,a.u.\nE0,E0,E3,E3\n400,1,400,2\n450,4,450,8\n500,1,500,2\n")
    monkeypatch.setattr(execution, "create_project", lambda *args, **kwargs: {
        "project_dir": str(tmp_path / "managed"), "studio_run": {"ready_to_use": True, "failure_reason": None},
    })
    task = tmp_path / "task"
    result = control.start_task({"version": 1, "action": "create", "source": str(raw),
                                 "rule_id": "uvvis_spectrum", "choose_columns": True}, task_dir=task)
    assert result["status"] == "needs_input"
    with pytest.raises(TaskControlError, match="different samples"):
        control.resume_task(task, response(result))
    completed = control.resume_task(task, response(result, x=2, y=3))
    assert completed["status"] == "complete"
    mapped = load_data_mapping_execution(completed["data_mapping"]["data_mapping_execution"])
    proposal = json.loads(Path(mapped["proposal"]).read_text())
    assert proposal["sample_labels"] == {"source": "E3"}
    assert proposal["transformations"] == []
