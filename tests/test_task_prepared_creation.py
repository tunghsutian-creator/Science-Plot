"""Prepared template projects are durable but never mistaken for published output."""

import pytest

from sciplot_core import task_control as control, task_execution as execution
from sciplot_core.plan_preview import build_plan_preview
from sciplot_core.studio_core import project_creation
from sciplot_core.task_contract import TaskControlError
from sciplot_core.task_storage import load_task
from test_task_control import source


def prepared_task(tmp_path, monkeypatch, *, interrupt=False):
    path = source(tmp_path)
    task = tmp_path / "task"
    project = tmp_path / "prepared"
    calls = []

    def create(_source, **kwargs):
        calls.append("prepare")
        assert kwargs["publish"] is False
        project.mkdir()
        document = project / "document.vsz"
        request_path = project / "plot_request.json"
        document.write_text("native bytes")
        request_path.write_text('{"input":"original"}')
        prepared = {"project_dir": str(project), "document": str(document), "request": str(request_path)}
        kwargs["on_prepared"](prepared)
        if interrupt:
            raise RuntimeError("Interrupted after native checkpoint")
        return {"kind": "sciplot_project_prepared_result", **prepared}

    monkeypatch.setattr(execution, "create_project", create)
    monkeypatch.setattr(execution, "export_project", lambda *_: pytest.fail("Prepared task must not publish"))
    monkeypatch.setattr(control, "inspect_project", lambda *_: pytest.fail("Prepared task has no QA/delivery to inspect"))
    request = {"version": 1, "action": "create", "source": str(path)}
    result = control.start_task(request, task_dir=task, defer_creation_export=True)
    return path, task, project, request, result, calls


def test_prepared_task_never_claims_delivery_and_same_mode_never_recreates(tmp_path, monkeypatch):
    _source, task, project, request, result, calls = prepared_task(tmp_path, monkeypatch)
    assert result["status"] == "complete" and result["phase"] == "prepared"
    assert result["ready_to_use"] is False and result["completion_scope"] == "prepared_project"
    assert result["result"]["export_performed"] is False
    assert result["next_step"]["action"] == "continue_template_creation"
    assert "current_project" not in result
    state = load_task(task)
    assert state["prepared_creation"]["files"].keys() == {"document.vsz", "plot_request.json"}
    assert state["prepared_creation"]["project"] == str(project)
    repeated = control.start_task(request, task_dir=task, defer_creation_export=True)
    assert repeated["status"] == "complete" and calls == ["prepare"]
    with pytest.raises(TaskControlError) as error:
        control.start_task(request, task_dir=task)
    assert error.value.reason_code == "task_creation_mode_conflict"


def test_checkpoint_survives_interruption_and_reuses_exact_native_bytes(tmp_path, monkeypatch):
    _source, task, project, _request, result, calls = prepared_task(tmp_path, monkeypatch, interrupt=True)
    assert result["status"] == "blocked" and result["phase"] == "prepared"
    original = (project / "document.vsz").read_bytes()
    resumed = control.resume_task(task, {"retry": True})
    assert resumed["status"] == "complete" and resumed["ready_to_use"] is False
    assert resumed["next_step"]["action"] == "continue_template_creation"
    assert calls == ["prepare"] and (project / "document.vsz").read_bytes() == original


@pytest.mark.parametrize("changed", ["source", "native", "request", "new_file"])
def test_changed_prepared_inputs_block_inspection_and_retry_without_repreparing(tmp_path, monkeypatch, changed):
    original, task, project, _request, _result, calls = prepared_task(tmp_path, monkeypatch)
    paths = {"source": original, "native": project / "document.vsz", "request": project / "plot_request.json", "new_file": project / "extra.csv"}
    paths[changed].write_text("externally changed")
    expected = "source_changed" if changed == "source" else "prepared_project_changed"
    for result in (control.inspect_task(task), control.resume_task(task, {"retry": True})):
        assert result["status"] == "blocked" and result["blocker"]["reason_code"] == expected
        assert result["ready_to_use"] is False
        assert result["next_step"]["action"] != "review_exports_and_deliver"
    assert calls == ["prepare"]


def test_project_prepare_only_uses_same_verified_plan_without_export(tmp_path, monkeypatch):
    path = source(tmp_path)
    plan = build_plan_preview(path, request={"rule_id": "uvvis_spectrum", "template": "curve"})
    payload = {"project_dir": str(tmp_path / "project"), "document": str(tmp_path / "project/document.vsz"),
               "request": str(tmp_path / "project/plot_request.json")}
    calls = []
    monkeypatch.setattr(project_creation, "prepare_studio_document", lambda *a, **k: calls.append(k) or payload)
    monkeypatch.setattr(project_creation, "_publish", lambda *_: pytest.fail("Prepare-only mode exported"))
    checkpoints = []
    result = project_creation.create_project(path, expected_plan=plan, on_prepared=checkpoints.append, publish=False)
    assert len(calls) == 1 and checkpoints == [payload]
    assert result["kind"] == "sciplot_project_prepared_result" and result["ready_to_use"] is False
    assert result["export_performed"] is False
