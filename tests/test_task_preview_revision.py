from __future__ import annotations

import json
import subprocess
from hashlib import sha256
from types import SimpleNamespace

import pytest
from test_project_query import project as project

from sciplot_core import task_control, task_execution, task_storage
from sciplot_core.studio_core import annotation_operations
from sciplot_core.task_contract import TaskControlError, task_response_schema
from sciplot_core.task_editing import unchanged_style_review


def style(value="2pt"):
    return {"op": "set_style", "object_path": "/page1/graph1/series_1",
            "setting_path": "/page1/graph1/series_1/PlotLine/width",
            "expected_value": "1pt", "value": value}


@pytest.fixture
def edits(tmp_path, monkeypatch):
    project = tmp_path / "project"
    project.mkdir()
    document = project / "document.vsz"
    document.write_text("original saved document")
    digest = sha256(document.read_bytes()).hexdigest()
    (project / "plot_request.json").write_text(json.dumps({"delivery_output": str(tmp_path / "Visible")}))
    monkeypatch.setattr(task_control, "resolve_project_path", lambda _: project)
    monkeypatch.setattr(task_storage, "resolve_project_path", lambda _: project)
    calls, effects = [], []

    def preview(_project, operations, **kwargs):
        output = kwargs["output_dir"]
        output.mkdir()
        review = {"kind": "sciplot_document_edit_preview", "version": 2, "status": "ready",
                  "project": str(project), "figure_id": "figure1", "document": str(document),
                  "document_sha256": digest, "operations": operations,
                  "operation_id": sha256(str(output).encode()).hexdigest(),
                  "preview": {"path": str(output / "candidate.png")},
                  "actual_changes": [{"old_value": op["expected_value"], "new_value": op["value"]}
                                     for op in operations],
                  "scientific_audit": {"status": "passed"}}
        (output / "edit-preview.json").write_text(json.dumps(review))
        calls.append(review)
        return review

    def apply(_project, review):
        effects.append(("apply", review["operation_id"]))
        return {"status": "applied", "document": str(document),
                "operation_id": review["operation_id"], "result_sha256": "f" * 64}

    def export(_project):
        effects.append(("export", None))
        return {"project_dir": str(project), "studio_run": {"ready_to_use": True}}

    monkeypatch.setattr(annotation_operations, "preview_document_operations", preview)
    monkeypatch.setattr(task_execution, "apply_document_edit", apply)
    monkeypatch.setattr(task_execution, "export_project", export)
    task = tmp_path / "task"
    request = {"version": 1, "action": "edit", "project": str(project), "figure_id": "figure1",
               "expected_document_sha256": digest, "operations": [style()], "export": False}
    return SimpleNamespace(task=task, request=request, calls=calls, effects=effects,
                           document=document, preview=preview, export=export)


def revision(edits, operation_id, value="3pt"):
    return task_control.resume_task(edits.task, {
        "expected_operation_id": operation_id, "revise_operations": [style(value)],
    })


def test_revision_preserves_original_request_and_attempts_and_is_idempotent(edits):
    first = task_control.start_task(edits.request, task_dir=edits.task)
    old_file = edits.task / "preview_001/edit-preview.json"
    old_bytes = old_file.read_bytes()
    revised = revision(edits, first["operation_id"])
    assert revised["status"] == "needs_review" and revised["preview_revision"] == 2
    assert revised["operation_id"] != first["operation_id"]
    assert old_file.read_bytes() == old_bytes
    assert not edits.effects
    record = json.loads((edits.task / "task.json").read_text())
    assert record["request"] == edits.request
    assert record["edit_revisions"][0]["revise_operations"] == [style("3pt")]
    assert edits.calls[-1]["document_sha256"] == edits.request["expected_document_sha256"]
    before = (edits.task / "task.json").read_bytes()
    assert revision(edits, first["operation_id"]) == revised
    assert task_control.start_task(edits.request, task_dir=edits.task) == revised
    assert (edits.task / "task.json").read_bytes() == before and len(edits.calls) == 2
    accepted = task_control.resume_task(edits.task, {
        "accept_preview": True, "expected_operation_id": revised["operation_id"],
    })
    assert accepted["result"]["status"] == "saved"
    assert edits.effects == [("apply", revised["operation_id"])]
    assert revision(edits, first["operation_id"]) == accepted


@pytest.mark.parametrize("answer", ["old_accept", "old_reject", "unbound_accept", "unbound_reject", "old_revision"])
def test_superseded_answers_cannot_change_the_current_review(edits, answer):
    first = task_control.start_task(edits.request, task_dir=edits.task)
    revision(edits, first["operation_id"])
    response = {"accept_preview": "reject" not in answer}
    if answer.startswith("old_"):
        response["expected_operation_id"] = first["operation_id"]
    if answer == "old_revision":
        response = {"expected_operation_id": first["operation_id"], "revise_operations": [style("4pt")]}
    before = (edits.task / "task.json").read_bytes()
    with pytest.raises(TaskControlError) as failure:
        task_control.resume_task(edits.task, response)
    assert failure.value.reason_code == "stale_task_preview"
    assert (edits.task / "task.json").read_bytes() == before and not edits.effects


@pytest.mark.parametrize("changes", [{"revise_operations": []}, {"expected_operation_id": 3},
                                     {"revise_operations": "new style"}, {"export": False},
                                     {"revise_operations": [{"op": "set_style"}]},
                                     {"revise_operations": [{"op": "run_python", "code": "print(1)"}]},
                                     {"revise_operations": [{"op": "set_sample_style", "samples": ["A"], "style": {"width": 2}}]},
                                     {"revise_operations": [{"op": "add_annotation", "id": "note", "parent_path": "/page1/graph1", "text": "note",
                                                             "position": {"mode": "relative", "x": True, "y": 0.5}}]}])
def test_invalid_revision_is_read_only(edits, changes):
    first = task_control.start_task(edits.request, task_dir=edits.task)
    before = (edits.task / "task.json").read_bytes()
    with pytest.raises(TaskControlError):
        task_control.resume_task(edits.task, {"expected_operation_id": first["operation_id"],
                                              "revise_operations": [style("3pt")], **changes})
    assert (edits.task / "task.json").read_bytes() == before
    assert len(edits.calls) == 1 and not edits.effects


def test_failed_replacement_cannot_reactivate_old_preview_and_retry_keeps_new_intent(edits, monkeypatch):
    first = task_control.start_task(edits.request, task_dir=edits.task)
    def fail(*args, **kwargs):
        raise RuntimeError("Native worker interrupted")
    monkeypatch.setattr(annotation_operations, "preview_document_operations", fail)
    blocked = revision(edits, first["operation_id"])
    assert blocked["status"] == "blocked" and blocked["phase"] == "previewing"
    assert "preview" not in blocked and "operation_id" not in blocked
    assert revision(edits, first["operation_id"]) == blocked
    before = (edits.task / "task.json").read_bytes()
    with pytest.raises(TaskControlError):
        task_control.resume_task(edits.task, {"accept_preview": True, "expected_operation_id": first["operation_id"]})
    assert (edits.task / "task.json").read_bytes() == before
    monkeypatch.setattr(annotation_operations, "preview_document_operations", edits.preview)
    resumed = task_control.resume_task(edits.task, {"retry": True})
    assert resumed["preview_revision"] == 2 and resumed["status"] == "needs_review"
    assert edits.calls[-1]["operations"] == [style("3pt")]
    assert (edits.task / "preview_003/edit-preview.json").exists() and not edits.effects


@pytest.mark.parametrize("after_replacement", [False, True])
def test_failed_preview_can_be_corrected_with_current_revision(edits, monkeypatch, after_replacement):
    def fail(*args, **kwargs):
        raise ValueError("Native value is invalid")
    if after_replacement:
        first = task_control.start_task(edits.request, task_dir=edits.task)
    monkeypatch.setattr(annotation_operations, "preview_document_operations", fail)
    blocked = (revision(edits, first["operation_id"]) if after_replacement
               else task_control.start_task(edits.request, task_dir=edits.task))
    assert blocked["status"] == "blocked" and blocked["phase"] == "previewing"
    failed_state = json.loads((edits.task / "task.json").read_text())
    response = {"expected_preview_revision": blocked["preview_revision"], "revise_operations": [style("4pt")]}
    monkeypatch.setattr(annotation_operations, "preview_document_operations", edits.preview)
    corrected = task_control.resume_task(edits.task, response)
    assert corrected["status"] == "needs_review"
    assert corrected["preview_revision"] == blocked["preview_revision"] + 1
    state = json.loads((edits.task / "task.json").read_text())
    assert state["request"] == edits.request and state["edit_revisions"][-1] == response
    assert state["preview_failures"][-1]["blocker"] == failed_state["blocker"]
    assert state["preview_attempt"] == failed_state["preview_attempt"] + 1
    stable = (edits.task / "task.json").read_bytes()
    assert task_control.resume_task(edits.task, response) == corrected
    assert (edits.task / "task.json").read_bytes() == stable
    with pytest.raises(TaskControlError):
        task_control.resume_task(edits.task, {"accept_preview": True})
    completed = task_control.resume_task(edits.task, {"accept_preview": True,
                                                      "expected_operation_id": corrected["operation_id"]})
    assert completed["status"] == "complete" and completed["result"]["status"] == "saved"
    assert task_control.resume_task(edits.task, response) == completed


def test_uncertain_apply_cannot_be_revised(edits, monkeypatch):
    first = task_control.start_task(edits.request, task_dir=edits.task)
    def fail(*args):
        raise RuntimeError("Lost apply reply")
    monkeypatch.setattr(task_execution, "apply_document_edit", fail)
    blocked = task_control.resume_task(edits.task, {"accept_preview": True})
    assert blocked["phase"] == "applying"
    before = (edits.task / "task.json").read_bytes()
    with pytest.raises(TaskControlError) as failure:
        revision(edits, first["operation_id"])
    assert failure.value.reason_code == "task_not_revisable"
    assert (edits.task / "task.json").read_bytes() == before


@pytest.mark.parametrize("revise", [False, True])
def test_already_matching_style_needs_no_acceptance_apply_or_deferred_export(edits, revise):
    original = edits.document.read_bytes()
    if revise:
        first = task_control.start_task(edits.request, task_dir=edits.task)
        result = revision(edits, first["operation_id"], "1pt")
    else:
        result = task_control.start_task({**edits.request, "operations": [style("1pt")]}, task_dir=edits.task)
    assert result["status"] == "complete" and result["result"]["status"] == "unchanged"
    assert result["result"]["document_changed"] is False
    assert result["result"]["document_sha256"] == edits.request["expected_document_sha256"]
    assert result["result"]["export_required"] is None and result["ready_to_use"] is None
    assert "preview" not in result and not edits.effects
    assert edits.document.read_bytes() == original
    assert task_control.resume_task(edits.task, {"retry": True}) == result


def test_matching_style_still_honors_requested_export_and_recovers_without_repreview(edits, monkeypatch):
    attempts = []
    def export(project):
        attempts.append(project)
        if len(attempts) == 1:
            raise RuntimeError("Export worker interrupted")
        return edits.export(project)
    monkeypatch.setattr(task_execution, "export_project", export)
    result = task_control.start_task({**edits.request, "operations": [style("1pt")], "export": True}, task_dir=edits.task)
    assert result["status"] == "blocked" and result["phase"] == "exporting"
    result = task_control.resume_task(edits.task, {"retry": True})
    assert result["status"] == "complete" and result["edit_outcome"]["status"] == "unchanged"
    assert result["result"]["studio_run"]["ready_to_use"] is True
    assert len(edits.calls) == 1 and edits.effects == [("export", None)]


@pytest.mark.parametrize("invalid", ["annotation", "mixed", "incomplete_changes", "audit_failed", "changed_value"])
def test_only_complete_native_validated_unchanged_styles_skip_review(edits, invalid):
    task_control.start_task(edits.request, task_dir=edits.task)
    review = edits.calls[0]
    review["actual_changes"][0]["new_value"] = "1pt"
    assert unchanged_style_review(review)
    if invalid == "annotation":
        review["operations"] = [{"op": "update_annotation"}]
    elif invalid == "mixed":
        review["operations"].append({"op": "add_text"})
    elif invalid == "incomplete_changes":
        review["actual_changes"] = [{}]
    elif invalid == "audit_failed":
        review["scientific_audit"]["status"] = "failed"
    else:
        review["actual_changes"][0]["new_value"] = "2pt"
    assert not unchanged_style_review(review)


@pytest.mark.parametrize("case", ["unchanged", "changed", "native-drift", "source-drift"])
def test_current_sealed_native_producer_keeps_unchanged_and_changed_task_style_intents_distinct(project, tmp_path, monkeypatch, case):
    from sciplot_core.foundation.file_hashing import file_sha256
    from sciplot_core.project_host_factory import project_store
    from sciplot_core.studio_core import document_edit

    native = project / "studio/document.vsz"
    original = native.read_bytes()
    changed = case == "changed"
    calls = []
    def candidate(document, spec, changes, output, *, operations, **_kwargs):
        calls.append(operations)
        rendered, companion, image = output / "candidate.vsz", output / "candidate.spec.json", output / "candidate.png"
        rendered.write_bytes(document.read_bytes() + b"\ncontrolled native serialization")
        companion.write_bytes(spec.read_bytes())
        image.write_bytes(b"controlled native image")
        return {"candidate": {"path": str(rendered), "sha256": file_sha256(rendered)},
                "candidate_spec": {"path": str(companion), "sha256": file_sha256(companion)},
                "preview": {"path": str(image), "sha256": file_sha256(image)},
                "changes": [{"object_path": op["object_path"], "setting_path": op["setting_path"],
                             "old_value": op["expected_value"], "new_value": op["value"]} for op in operations],
                "scientific_audit": {"status": "passed", "document_sha256": file_sha256(rendered),
                                     "spec_sha256": file_sha256(companion)}}
    monkeypatch.setattr(document_edit, "_candidate", candidate)
    monkeypatch.setattr(document_edit, "audit_edited_document", lambda *_a: {"status": "passed"})
    monkeypatch.setattr(subprocess, "Popen", lambda *_a, **_k: pytest.fail("Pure task control must not start native processes."))
    monkeypatch.setattr(subprocess, "run", lambda *_a, **_k: pytest.fail("Pure task control must not start native processes."))
    repository = project_store(project)
    before = repository.snapshot(import_legacy=True)
    producer = annotation_operations.preview_document_operations
    drift_target = native if case == "native-drift" else project / "source/data.csv"
    drift_before = drift_target.read_bytes()
    if case in {"native-drift", "source-drift"}:
        def drift_after_freezing(*args, **kwargs):
            review = producer(*args, **kwargs)
            drift_target.write_bytes(b"controlled post-preview drift")
            return review
        monkeypatch.setattr(annotation_operations, "preview_document_operations", drift_after_freezing)
    result = task_control.start_task({"version": 1, "action": "edit", "project": str(project), "figure_id": "first",
        "expected_document_sha256": file_sha256(native), "operations": [style("2pt" if changed else "1pt")],
        "export": False}, task_dir=tmp_path / "native-task")
    if case in {"native-drift", "source-drift"}:
        assert result["status"] == "blocked" and repository.commands()[0]["phase"] == "needs_review"
        assert drift_target.read_bytes() == b"controlled post-preview drift"
        assert repository.snapshot()["generation"] == before["generation"]
        drift_target.write_bytes(drift_before)  # Explicit restoration by this controlled fixture, never a production repair.
        monkeypatch.setattr(annotation_operations, "preview_document_operations", producer)
        result = task_control.resume_task(tmp_path / "native-task", {"retry": True})
    assert result["status"] == ("needs_review" if changed else "complete")
    if not changed:
        assert result["result"]["status"] == "unchanged" and result["result"]["document_changed"] is False
        assert "preview" not in result
        reviewed = json.loads((tmp_path / "native-task/review.json").read_text())
        for fault in ("kind", "version", "decision", "candidate", "scientific-native", "scientific-spec", "actual-path", "actual-value"):
            tampered = json.loads(json.dumps(reviewed))
            if fault in {"kind", "version"}:
                tampered[fault] = "unknown"
            elif fault == "decision":
                tampered.pop("decision_id")
            elif fault == "candidate":
                tampered.pop("candidate_spec")
            elif fault in {"scientific-native", "scientific-spec"}:
                tampered["scientific_audit"]["document_sha256" if fault == "scientific-native" else "spec_sha256"] = "a" * 64
            else:
                tampered["actual_changes"][0]["setting_path" if fault == "actual-path" else "new_value"] = "different"
            assert not unchanged_style_review(tampered), fault
    record, = repository.commands()
    assert record["phase"] == ("needs_review" if changed else "rejected") and record["review"]["version"] == 3
    if not changed:
        assert record["accepted"] is False
        assert task_control.resume_task(tmp_path / "native-task", {"retry": True}) == result
    assert len(calls) == 1 and native.read_bytes() == original and repository.snapshot()["generation"] == before["generation"]


def test_response_schema_advertises_revision_and_bound_acceptance():
    from jsonschema import Draft202012Validator
    validator = Draft202012Validator(task_response_schema())
    validator.validate({"expected_operation_id": "a" * 64, "revise_operations": [style()]})
    validator.validate({"expected_operation_id": "a" * 64, "accept_preview": True})
    assert list(validator.iter_errors({"revise_operations": [style()]}))


@pytest.mark.parametrize("phase", ["previewing", "applying", "exporting"])
def test_worker_timeout_becomes_a_recoverable_receipt_instead_of_staying_running(edits, monkeypatch, phase):
    def timeout(*args, **kwargs):
        raise subprocess.TimeoutExpired(["native-worker"], 120)
    if phase == "previewing":
        monkeypatch.setattr(annotation_operations, "preview_document_operations", timeout)
        result = task_control.start_task(edits.request, task_dir=edits.task)
        monkeypatch.setattr(annotation_operations, "preview_document_operations", edits.preview)
    elif phase == "applying":
        task_control.start_task(edits.request, task_dir=edits.task)
        apply = task_execution.apply_document_edit
        monkeypatch.setattr(task_execution, "apply_document_edit", timeout)
        result = task_control.resume_task(edits.task, {"accept_preview": True})
        monkeypatch.setattr(task_execution, "apply_document_edit", apply)
    else:
        task_control.start_task({**edits.request, "export": True}, task_dir=edits.task)
        monkeypatch.setattr(task_execution, "export_project", timeout)
        result = task_control.resume_task(edits.task, {"accept_preview": True})
        monkeypatch.setattr(task_execution, "export_project", edits.export)
    assert result["status"] == "blocked" and result["phase"] == phase
    assert result["blocker"]["reason_code"] == "task_worker_timeout"
    assert result["blocker"]["timeout_seconds"] == 120
    resumed = task_control.resume_task(edits.task, {"retry": True})
    assert resumed["status"] == ("needs_review" if phase == "previewing" else "complete")
    assert sum(effect[0] == "apply" for effect in edits.effects) <= 1
