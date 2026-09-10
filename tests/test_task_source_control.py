from __future__ import annotations

import json

import pytest

from sciplot_core import task_control as control, task_execution as execution, task_source_execution as source_execution
from sciplot_core.task_contract import TaskControlError
from sciplot_core.task_storage import load_task, save_task


@pytest.fixture
def pending(tmp_path, monkeypatch):
    project, source, task = tmp_path / "project", tmp_path / "new.csv", tmp_path / "task"
    (project / "studio").mkdir(parents=True)
    (project / "studio/document.vsz").write_text("saved")
    (project / "plot_request.json").write_text(json.dumps({"delivery_output": str(tmp_path / "visible")}))
    source.write_text("x,y\n1,2\n")
    calls = []

    def preview(_project, selected, *, review_path, worksheet):
        assert _project == project and selected == source and worksheet == "Data"
        calls.append("preview")
        return {"status": "ready", "project": str(project), "revision_id": "a" * 64,
                "review_path": str(review_path), "source_update": {"changes": {}},
                "previews": [{"scope": scope, "figure_id": "f", "preview": {"path": str(task / f"{scope}.png")}}
                             for scope in ("before", "candidate")]}

    monkeypatch.setattr(source_execution, "prepare_source_update_review", preview)
    request = {"version": 1, "action": "update_source", "project": str(project),
               "source": str(source), "worksheet": "Data"}
    result = control.start_task(request, task_dir=task)
    assert result["status"] == "needs_review"
    assert {item["scope"] for item in result["previews"]} == {"before", "candidate"}
    return task, project, source, calls


@pytest.mark.parametrize("response", [
    {"accept_preview": True},
    {"accept_source_update": True},
    {"accept_source_update": 1, "expected_revision_id": "a" * 64},
    {"accept_source_update": True, "expected_revision_id": "b" * 64},
])
def test_source_review_answers_bind_exact_revision_without_mutating_receipt(pending, response, monkeypatch):
    task, _, _, _ = pending
    before = (task / "task.json").read_bytes()
    monkeypatch.setattr(source_execution, "apply_source_update_review", lambda *a, **k: pytest.fail("must not apply"))
    with pytest.raises(TaskControlError):
        control.resume_task(task, response)
    assert (task / "task.json").read_bytes() == before


def test_source_review_rejection_has_no_source_or_export_side_effect(pending, monkeypatch):
    task, project, source, calls = pending
    before = (project / "studio/document.vsz").read_bytes(), source.read_bytes()
    monkeypatch.setattr(source_execution, "apply_source_update_review", lambda *a, **k: pytest.fail("must not apply"))
    monkeypatch.setattr(execution, "export_project", lambda *a: pytest.fail("must not export"))
    response = {"accept_source_update": False, "expected_revision_id": "a" * 64}
    assert control.resume_task(task, response)["status"] == "cancelled"
    assert control.resume_task(task, response)["status"] == "cancelled"
    assert calls == ["preview"]
    assert ((project / "studio/document.vsz").read_bytes(), source.read_bytes()) == before


def test_changed_selected_source_fails_before_applying_review(pending, monkeypatch):
    task, _, source, _ = pending
    source.write_text("x,y\n1,9\n")
    monkeypatch.setattr(source_execution, "apply_source_update_review", lambda *a, **k: pytest.fail("must not apply stale source"))
    result = control.resume_task(task, {"accept_source_update": True, "expected_revision_id": "a" * 64})
    assert result["status"] == "blocked" and result["blocker"]["reason_code"] == "source_changed"


def test_source_export_retry_uses_checkpoint_without_repreparing_or_reapplying(pending, monkeypatch):
    task, project, _, calls = pending

    def apply(*args, **kwargs):
        calls.append("apply")
        return {"status": "updated", "document": str(project / "studio/document.vsz")}

    def fail_export(*args):
        state = load_task(task)
        assert state["phase"] == "exporting" and state["source_update_outcome"]["status"] == "updated"
        calls.append("export_failure")
        raise OSError("export failed")

    monkeypatch.setattr(source_execution, "apply_source_update_review", apply)
    monkeypatch.setattr(execution, "export_project", fail_export)
    result = control.resume_task(task, {"accept_source_update": True, "expected_revision_id": "a" * 64})
    assert result["status"] == "blocked" and result["phase"] == "exporting"
    monkeypatch.setattr(source_execution, "apply_source_update_review", lambda *a, **k: pytest.fail("must not apply again"))
    monkeypatch.setattr(source_execution, "prepare_source_update_review", lambda *a, **k: pytest.fail("must not prepare again"))
    monkeypatch.setattr(execution, "export_project", lambda *a: calls.append("export_success") or {
        "project_dir": str(project), "studio_run": {"ready_to_use": True, "failure_reason": None}})
    assert control.resume_task(task, {"retry": True})["status"] == "complete"
    assert control.resume_task(task, {"retry": True})["status"] == "complete"
    assert calls == ["preview", "apply", "export_failure", "export_success"]


def test_interrupted_source_preview_restarts_without_accepting_it(pending, monkeypatch):
    task, _, _, calls = pending
    state = load_task(task)
    state.update(status="running", phase="previewing")
    for key in ("preview", "previews", "revision_id"):
        state.pop(key, None)
    save_task(task, state)
    monkeypatch.setattr(source_execution, "apply_source_update_review", lambda *a, **k: pytest.fail("retry is not review acceptance"))
    resumed = control.resume_task(task, {"retry": True})
    assert resumed["status"] == "needs_review" and calls == ["preview", "preview"]
    assert load_task(task)["preview_attempt"] == 2


def test_update_source_task_directory_cannot_overlap_selected_new_data(tmp_path):
    project, source = tmp_path / "project", tmp_path / "replacement"
    (project / "studio").mkdir(parents=True)
    (project / "studio/document.vsz").write_text("saved")
    (project / "plot_request.json").write_text("{}")
    source.mkdir()
    (source / "data.csv").write_text("x,y\n1,2\n")
    with pytest.raises(TaskControlError, match="重叠"):
        control.start_task({"version": 1, "action": "update_source", "project": str(project), "source": str(source)},
                           task_dir=source / "task")
    assert not (source / "task").exists()


@pytest.mark.parametrize("field", ["data_mapping_execution", "data_mapping_proposal_id", "data_mapping_plan_binding"])
@pytest.mark.parametrize("binding", ["confirmed-binding", {}, None])
def test_mapped_source_update_requires_new_mapping_before_reading_new_source(tmp_path, monkeypatch, field, binding):
    from sciplot_core.intake import session
    from sciplot_core.studio_core.source_update_staging import prepare_candidate

    project = tmp_path / "mapped_project"
    project.mkdir()
    request = project / "plot_request.json"
    request.write_text(json.dumps({"rule_id": "uvvis_spectrum", field: binding}))
    before = request.read_bytes()
    # A missing source makes any attempted new-source read distinguishable from
    # the required early mapping rejection; no replacement files may be built.
    source, staging = tmp_path / "unread_new_source.csv", tmp_path / "candidate"
    monkeypatch.setattr(session, "prepare_intake_session",
                        lambda *a, **k: pytest.fail("must not recognize or prepare the unconfirmed new source"))
    with pytest.raises(ValueError, match="fresh explicit data mapping"):
        prepare_candidate(project, source, staging, worksheet=None)
    assert request.read_bytes() == before and not staging.exists() and not source.exists()
