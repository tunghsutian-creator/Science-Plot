from __future__ import annotations

import json
from pathlib import Path

import pytest

from sciplot_core import task_control as control, task_execution as execution, task_planning
from sciplot_core.task_contract import TaskControlError, validate_task_request


def source(root: Path) -> Path:
    path = root / "UVvis.csv"
    path.write_text("Wavelength,Absorbance\nnm,a.u.\nE3,E3\n400,1\n450,4\n500,1\n")
    return path


def receipt(project: Path, *, ready: bool = True) -> dict:
    return {"project_dir": str(project), "status": "created" if ready else "blocked",
            "studio_run": {"ready_to_use": ready, "failure_reason": None if ready else "QA failed"}}


def test_create_locally_plans_publishes_and_same_task_never_creates_twice(tmp_path, monkeypatch):
    path = source(tmp_path)
    calls = []
    def create(*args, **kwargs):
        calls.append((args, kwargs))
        return receipt(tmp_path / "managed")
    monkeypatch.setattr(execution, "create_project", create)
    request = {"version": 1, "action": "create", "source": str(path)}
    task = tmp_path / "task"
    result = control.start_task(request, task_dir=task)
    assert result["status"] == "complete" and len(calls) == 1
    assert calls[0][1]["expected_plan"]["rule_id"] == "uvvis_spectrum"
    assert result["model_calls_by_sciplot"] == 0 and result["external_model_tokens"] is None
    assert Path(result["profile"]).is_file()
    assert control.start_task(request, task_dir=task)["status"] == "complete"
    assert control.resume_task(task, {"accept_preview": True})["status"] == "complete"
    assert len(calls) == 1


def test_unknown_experiment_pauses_and_resumes_only_with_current_source(tmp_path, monkeypatch):
    path = source(tmp_path)
    monkeypatch.setattr(task_planning, "inspect_payload", lambda _: {})
    calls = []
    monkeypatch.setattr(execution, "create_project", lambda *a, **k: calls.append(k) or receipt(tmp_path / "p"))
    task = tmp_path / "task"
    result = control.start_task({"version": 1, "action": "create", "source": str(path)}, task_dir=task)
    assert result["status"] == "needs_input" and not calls
    assert result["question"]["field"] == "rule_id"
    before = (task / "task.json").read_bytes()
    with pytest.raises(TaskControlError, match="实验规则"):
        control.resume_task(task, {"accept_preview": True})
    assert (task / "task.json").read_bytes() == before
    assert control.resume_task(task, {"rule_id": "uvvis_spectrum"})["status"] == "complete"
    assert len(calls) == 1


def test_source_change_while_question_pending_never_executes(tmp_path, monkeypatch):
    path = source(tmp_path)
    monkeypatch.setattr(task_planning, "inspect_payload", lambda _: {})
    monkeypatch.setattr(execution, "create_project", lambda *a, **k: pytest.fail("stale source executed"))
    task = tmp_path / "task"
    control.start_task({"version": 1, "action": "create", "source": str(path)}, task_dir=task)
    path.write_text(path.read_text().replace("450,4", "450,8"))
    result = control.resume_task(task, {"rule_id": "uvvis_spectrum"})
    assert result["status"] == "blocked" and result["blocker"]["reason_code"] == "source_changed"


def test_profile_reuses_selection_but_builds_plan_from_new_values(tmp_path, monkeypatch):
    path = source(tmp_path)
    calls = []
    monkeypatch.setattr(execution, "create_project", lambda *a, **k: calls.append(k) or receipt(tmp_path / "p"))
    first = control.start_task({"version": 1, "action": "create", "source": str(path)}, task_dir=tmp_path / "first")
    other = tmp_path / "new.csv"
    other.write_text(path.read_text().replace("450,4", "450,9"))
    second = control.start_task({"version": 1, "action": "create", "source": str(other),
                                 "profile": first["profile"]}, task_dir=tmp_path / "second")
    assert second["status"] == "complete"
    plans = [call["expected_plan"] for call in calls]
    assert plans[0]["preview_identity"]["source_tree_sha256"] != plans[1]["preview_identity"]["source_tree_sha256"]
    assert plans[1]["source"] == str(other)


def test_task_storage_cannot_touch_source_or_delivery(tmp_path):
    path = source(tmp_path)
    request = {"version": 1, "action": "create", "source": str(path), "out": str(tmp_path / "Visible")}
    for output in (path, tmp_path, tmp_path / "Visible" / "task"):
        with pytest.raises(TaskControlError, match="重叠"):
            control.start_task(request, task_dir=output)
    assert path.is_file()


@pytest.mark.parametrize("change", [{"version": True}, {"action": "python"},
                                    {"source": ""}, {"unknown": 1}])
def test_request_is_closed_and_typed(change):
    with pytest.raises(TaskControlError):
        validate_task_request({"version": 1, "action": "create", "source": "/data.csv", **change})


def test_task_record_tampering_is_rejected(tmp_path, monkeypatch):
    path = source(tmp_path)
    monkeypatch.setattr(execution, "create_project", lambda *a, **k: receipt(tmp_path / "p"))
    task = tmp_path / "task"
    control.start_task({"version": 1, "action": "create", "source": str(path)}, task_dir=task)
    record = json.loads((task / "task.json").read_text())
    record["request"]["source"] = "/other.csv"
    (task / "task.json").write_text(json.dumps(record))
    with pytest.raises(TaskControlError, match="记录发生变化"):
        control.inspect_task(task)


def _edit_task(tmp_path, monkeypatch):
    from sciplot_core.studio_core import annotation_operations
    project = tmp_path / "project"
    project.mkdir()
    (project / "plot_request.json").write_text(json.dumps({"delivery_output": str(tmp_path / "Visible")}))
    monkeypatch.setattr(control, "resolve_project_path", lambda _: project)
    from sciplot_core import task_storage
    monkeypatch.setattr(task_storage, "resolve_project_path", lambda _: project)
    review = {"project": str(project), "operation_id": "a" * 64,
              "preview": {"path": "/candidate.png"}, "scientific_audit": {"status": "passed"}}
    monkeypatch.setattr(annotation_operations, "preview_document_operations", lambda *a, **k: review)
    task = tmp_path / "task"
    result = control.start_task({"version": 1, "action": "edit", "project": str(project),
                                "expected_document_sha256": "b" * 64,
                                "operations": [{"op": "set_style"}]}, task_dir=task)
    assert result["status"] == "needs_review"
    return task, project


def test_review_then_apply_and_export_are_one_local_continuation(tmp_path, monkeypatch):
    task, project = _edit_task(tmp_path, monkeypatch)
    calls = []
    monkeypatch.setattr(execution, "apply_document_edit", lambda *a: calls.append("apply") or {"status": "applied"})
    monkeypatch.setattr(execution, "export_project", lambda *a: calls.append("export") or receipt(project))
    result = control.resume_task(task, {"accept_preview": True})
    assert result["status"] == "complete" and calls == ["apply", "export"]
    control.resume_task(task, {"accept_preview": True})
    assert calls == ["apply", "export"]


def test_export_failure_retry_does_not_reapply_or_recreate(tmp_path, monkeypatch):
    task, project = _edit_task(tmp_path, monkeypatch)
    calls = []
    monkeypatch.setattr(execution, "apply_document_edit", lambda *a: calls.append("apply") or {"status": "applied"})
    results = iter([receipt(project, ready=False), receipt(project)])
    monkeypatch.setattr(execution, "export_project", lambda *a: next(results))
    result = control.resume_task(task, {"accept_preview": True})
    assert result["status"] == "blocked" and result["phase"] == "exporting"
    assert control.resume_task(task, {"retry": True})["status"] == "complete"
    assert calls == ["apply"]


def test_first_export_exception_keeps_prepared_project_for_retry(tmp_path, monkeypatch):
    path = source(tmp_path)
    project = tmp_path / "prepared"
    calls = []
    def create(*args, **kwargs):
        calls.append("prepare")
        kwargs["on_prepared"]({"project_dir": str(project)})
        raise RuntimeError("Export worker stopped")
    monkeypatch.setattr(execution, "create_project", create)
    monkeypatch.setattr(execution, "export_project", lambda p: calls.append("export") or receipt(p))
    task = tmp_path / "task"
    result = control.start_task({"version": 1, "action": "create", "source": str(path)}, task_dir=task)
    assert result["status"] == "blocked" and result["phase"] == "exporting"
    assert result["project"] == str(project)
    assert control.resume_task(task, {"retry": True})["status"] == "complete"
    assert calls == ["prepare", "export"]


def test_declined_review_never_mutates_document(tmp_path, monkeypatch):
    task, _ = _edit_task(tmp_path, monkeypatch)
    monkeypatch.setattr(execution, "apply_document_edit", lambda *a: pytest.fail("declined review applied"))
    assert control.resume_task(task, {"accept_preview": False})["status"] == "cancelled"
