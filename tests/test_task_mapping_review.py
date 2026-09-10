from __future__ import annotations

import json
from pathlib import Path

import pytest

from sciplot_core import task_control, task_execution
from sciplot_core.data_mapping import (
    create_data_mapping_confirmation,
    execute_data_mapping_proposal,
    load_data_mapping_execution,
    resolve_data_mapping_request,
)
from sciplot_core.data_mapping.column_choice import column_choice_snapshot
from sciplot_core.data_mapping.raw_tables import _read_raw_table
from sciplot_core.foundation.file_hashing import file_sha256
from sciplot_core.mapping_contract import DataColumnMapping, DataMappingProposal, DataSourceReference
from sciplot_core.plan_preview import build_plan_preview
from sciplot_core.task_contract import TaskControlError


def _capture_creation(monkeypatch, tmp_path):
    calls = []

    def create(*args, **kwargs):
        calls.append(kwargs["expected_plan"])
        return {"project_dir": str(tmp_path / "managed"),
                "studio_run": {"ready_to_use": True, "failure_reason": None}}

    monkeypatch.setattr(task_execution, "create_project", create)
    return calls


def _answer(question, x, y):
    return {"expected_question_id": question["question"]["question_id"],
            "column_mapping": {"x_column": x, "y_column": y}}


def test_column_evidence_keeps_empty_records_at_original_positions(tmp_path):
    source = tmp_path / "UVvis.csv"
    source.write_text("Wavelength (nm),Absorbance (a.u.),Absorbance (a.u.)\n\n400,0.3,0.8\n450,0.4,0.9\n")
    reference = DataSourceReference("source", source.name, file_sha256(source), header_row=None)
    raw = _read_raw_table(reference, source, preserve_cells=True)
    assert len(raw.frame) == 4
    assert raw.frame.iloc[1].isna().all() or all(value == "" for value in raw.frame.iloc[1])
    assert list(raw.frame.iloc[2]) == ["400", "0.3", "0.8"]
    # This first slice supports finite columns, so an empty data record must
    # remain unsupported instead of being removed from the claimed evidence.
    assert column_choice_snapshot(source, "uvvis_spectrum") is None
    assert len(_read_raw_table(reference, source).frame) == 3


def test_invalid_scientific_unit_keeps_the_current_question_for_reselection(tmp_path, monkeypatch):
    source = tmp_path / "UVvis.csv"
    source.write_text("Wavelength (nm),Absorbance (nm),Absorbance (a.u.)\n400,0.3,0.8\n450,0.4,0.9\n500,0.2,0.7\n")
    calls = _capture_creation(monkeypatch, tmp_path)
    task = tmp_path / "task"
    question = task_control.start_task({"version": 1, "action": "create", "source": str(source),
                                        "rule_id": "uvvis_spectrum"}, task_dir=task)
    rejected = task_control.resume_task(task, _answer(question, 0, 1))
    assert rejected["status"] == "needs_input" and not calls
    assert rejected["question"] == question["question"]
    assert rejected["mapping_error"]["reason_code"] == "uvvis_spectrum_transform_invalid"
    accepted = task_control.resume_task(task, _answer(rejected, 0, 2))
    assert accepted["status"] == "complete" and len(calls) == 1
    assert "mapping_error" not in accepted
    assert calls[0]["scientific_transform"]["output"]["series"][0]["first_point"] == [400, 0.8]


def test_filename_unsafe_sample_stays_correctable_without_renaming(tmp_path, monkeypatch):
    source = tmp_path / "UVvis.csv"
    source.write_text("Wavelength,Absorbance,Wavelength,Absorbance\nnm,a.u.,nm,a.u.\nE/0,E/0,E3,E3\n400,0.3,400,0.8\n450,0.4,450,0.9\n")
    calls = _capture_creation(monkeypatch, tmp_path)
    task = tmp_path / "task"
    question = task_control.start_task({"version": 1, "action": "create", "source": str(source),
                                        "rule_id": "uvvis_spectrum", "choose_columns": True}, task_dir=task)
    before = (task / "task.json").read_bytes()
    with pytest.raises(TaskControlError, match="sample label cannot be preserved exactly"):
        task_control.resume_task(task, _answer(question, 0, 1))
    assert not calls and (task / "task.json").read_bytes() == before
    accepted = task_control.resume_task(task, _answer(question, 2, 3))
    assert accepted["status"] == "complete"
    assert calls[0]["scientific_transform"]["output"]["series_order"] == ["E3"]


def _direct_execution(tmp_path, *, sample="E0"):
    source_root = tmp_path / "raw"
    source_root.mkdir()
    source = source_root / "UVvis.csv"
    source.write_text(f"Wavelength,Absorbance\nnm,a.u.\n{sample},{sample}\n400,0.3\n450,0.4\n500,0.2\n")
    request = tmp_path / "request.json"
    request.write_text(json.dumps({"input": str(source), "rule_id": "uvvis_spectrum", "template": "curve"}))
    proposal = DataMappingProposal(
        proposal_id="direct_columns", base_request_sha256=file_sha256(request), provider="test",
        sources=(DataSourceReference("source", source.name, file_sha256(source), header_row=2),),
        columns=(DataColumnMapping("source", 0, "Wavelength (nm)", "x", expected_header=sample),
                 DataColumnMapping("source", 1, "Absorbance (a.u.)", "y", expected_header=sample)),
        sample_labels={"source": sample},
    )
    receipt = create_data_mapping_confirmation(proposal, source_root=source_root, request_path=request,
                                               output_root=tmp_path / "mappings", confirmed_by="test")
    execution = execute_data_mapping_proposal(proposal, receipt, source_root=source_root, request_path=request,
                                              output_root=tmp_path / "mappings")
    return source, execution


def test_arbitrary_mapping_plan_cannot_silently_rename_confirmed_samples(tmp_path):
    source, execution = _direct_execution(tmp_path, sample="E/0")
    plan = build_plan_preview(source, request={
        "rule_id": "uvvis_spectrum", "template": "curve",
        "data_mapping_execution": str(Path(execution["output_root"]) / "execution.json"),
        "data_mapping_proposal_id": "direct_columns",
    })
    assert plan["status"] == "blocked"
    assert plan["blocker"]["reason_code"] == "plan_mapping_invalid"
    assert "expected ['E/0'], found ['0']" in plan["blocker"]["message"]


def test_historical_v1_execution_with_directory_input_still_loads(tmp_path, monkeypatch):
    import sciplot_core.data_mapping.execution as execution_module

    original_builder = execution_module.build_transform_step

    def historical_step(**kwargs):
        # Reproduce the former writer: a v1 execution bound its one step to
        # the source directory, including for a single source file.
        return original_builder(**{**kwargs, "input_path": tmp_path / "raw"})

    monkeypatch.setattr(execution_module, "build_transform_step", historical_step)
    monkeypatch.setattr(execution_module, "DATA_MAPPING_EXECUTION_VERSION", 1)
    source, execution = _direct_execution(tmp_path)
    verified = load_data_mapping_execution(execution["output_root"])
    assert verified["version"] == 1 and verified["handoff_allowed"] is True
    assert verified["confirmation_schema_version"] == 2
    assert verified["transform_steps"][0]["input_artifacts"][0]["path"] == str(source.parent)
    _assert_mapping_gui_source_binding(verified, source.parent)


def _assert_mapping_gui_source_binding(execution, expected_source):
    from sciplot_gui.studio_project_status.mapping_status import _mapping_status
    from sciplot_gui.studio_project_status.source_status import _source_status

    request_path = Path(execution["request_seed"])
    request = json.loads(request_path.read_text())
    _effective, application = resolve_data_mapping_request(request, base_dir=request_path.parent)
    mapping, _request = _mapping_status(
        request, request_path=request_path,
        latest_run={"data_mapping_application": application, "data_mapping_coverage": {"status": "passed"}},
        request_error=None, artifact_qa_current=True, audit_mapping=True,
    )
    assert mapping["status"] == "verified"
    assert mapping["source_audit_path"] == str(expected_source)
    source = _source_status(Path(mapping["source_audit_path"]),
                            transform_ledger=application["transform_ledger"], audit_source=True)
    assert source["audit_status"] == "matches_last_run_lineage"


def test_v2_mapping_gui_audits_the_confirmed_file_not_its_parent_directory(tmp_path):
    source, execution = _direct_execution(tmp_path)
    (source.parent / "unselected.txt").write_text("This is outside the confirmed mapping input.")
    _assert_mapping_gui_source_binding(execution, source)
