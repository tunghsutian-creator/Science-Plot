from __future__ import annotations

import json
import subprocess
from types import SimpleNamespace

import pytest
from test_project_query import project as project

from sciplot_core import task_control, task_storage
from sciplot_core.foundation.file_hashing import file_sha256
from sciplot_core.project_commands import ProjectCommand, ProjectCommands, ProjectMutation
from sciplot_core.project_host_factory import project_store
from sciplot_core.studio_core import annotation_operations, document_edit
from sciplot_core.task_native_edit import native_task_request_id


def style(value="2pt"):
    return {"op": "set_style", "object_path": "/page1/graph1/series_1",
            "setting_path": "/page1/graph1/series_1/PlotLine/width",
            "expected_value": "1pt", "value": value}


@pytest.fixture
def native_task(project, tmp_path, monkeypatch):
    native, calls = project / "studio/document.vsz", []
    original = native.read_bytes()
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
    monkeypatch.setattr(subprocess, "Popen", lambda *_a, **_k: pytest.fail("Pure native lifecycle must not spawn."))
    monkeypatch.setattr(subprocess, "run", lambda *_a, **_k: pytest.fail("Pure native lifecycle must not spawn."))
    repository = project_store(project)
    before = repository.snapshot(import_legacy=True)
    request = {"version": 1, "action": "edit", "project": str(project), "figure_id": "first",
               "expected_document_sha256": file_sha256(native), "operations": [style()], "export": False}
    return SimpleNamespace(project=project, root=tmp_path / "native-task", request=request,
                           store=repository, before=before, calls=calls, native=native, original=original)


def _revise(fixture, result, value):
    return task_control.resume_task(fixture.root, {"expected_operation_id": result["operation_id"],
                                                  "revise_operations": [style(value)]})


def _cancel(fixture, result):
    return task_control.resume_task(fixture.root, {"expected_operation_id": result["operation_id"],
                                                  "accept_preview": False})


def test_native_task_revisions_two_three_two_have_distinct_owned_terminal_commands(native_task):
    f = native_task
    first = task_control.start_task(f.request, task_dir=f.root)
    second = _revise(f, first, "3pt")
    third = _revise(f, second, "2pt")
    assert len({item["operation_id"] for item in (first, second, third)}) == 3
    assert len(f.calls) == 3 and third["status"] == "needs_review"
    assert {item["command_id"]: item["phase"] for item in f.store.commands()} == {
        first["operation_id"]: "rejected", second["operation_id"]: "rejected", third["operation_id"]: "needs_review"}
    assert _cancel(f, third)["status"] == "cancelled"
    assert all(item["phase"] == "rejected" for item in f.store.commands())
    assert f.native.read_bytes() == f.original and f.store.snapshot()["generation"] == f.before["generation"]


def test_native_cancel_then_independent_task_does_not_reuse_a_rejected_change(native_task, tmp_path):
    f = native_task
    first = task_control.start_task(f.request, task_dir=f.root)
    assert _cancel(f, first)["status"] == "cancelled"
    new = task_control.start_task(f.request, task_dir=tmp_path / "another-native-task")
    assert new["status"] == "needs_review" and new["operation_id"] != first["operation_id"]
    assert len(f.calls) == 2 and ProjectCommands(f.store).query(first["operation_id"])["phase"] == "rejected"
    assert ProjectCommands(f.store).query(new["operation_id"])["phase"] == "needs_review"


@pytest.mark.parametrize("advance_head", [False, True])
def test_lost_native_preview_reply_reuses_exact_owned_revision_without_render(native_task, monkeypatch, advance_head):
    f = native_task
    producer = annotation_operations.preview_document_operations
    def lost(*args, **kwargs):
        producer(*args, **kwargs)
        raise RuntimeError("Controlled lost preview reply")
    monkeypatch.setattr(annotation_operations, "preview_document_operations", lost)
    assert task_control.start_task(f.request, task_dir=f.root)["status"] == "blocked"
    prior, = f.store.commands()
    state = task_storage.load_task(f.root)
    identity = native_task_request_id(state)
    if advance_head:
        snapshot = f.store.snapshot()
        command = ProjectCommand.create(kind="style", key="unrelated-metadata", project_id=snapshot["project_id"],
            expected_generation=snapshot["generation"], read_set={"notes.txt": None}, write_set=("notes.txt",), request={"note": "unrelated"})
        ProjectCommands(f.store).execute(command, lambda: ProjectMutation({"notes.txt": b"unrelated metadata"}, {}))
    monkeypatch.setattr(annotation_operations, "preview_document_operations", producer)
    resumed = task_control.resume_task(f.root, {"retry": True})
    assert resumed["status"] == "needs_review" and resumed["operation_id"] == prior["command_id"]
    assert native_task_request_id(task_storage.load_task(f.root)) == identity
    assert len(f.calls) == 1 and f.native.read_bytes() == f.original


def test_invalid_replacement_keeps_previous_native_core_candidate_pending(native_task, monkeypatch):
    f = native_task
    first = task_control.start_task(f.request, task_dir=f.root)
    producer = annotation_operations.preview_document_operations
    monkeypatch.setattr(annotation_operations, "preview_document_operations", lambda *_a, **_k: (_ for _ in ()).throw(ValueError("invalid native value")))
    blocked = _revise(f, first, "3pt")
    assert blocked["status"] == "blocked"
    assert ProjectCommands(f.store).query(first["operation_id"])["phase"] == "needs_review"
    monkeypatch.setattr(annotation_operations, "preview_document_operations", producer)
    retried = task_control.resume_task(f.root, {"retry": True})
    assert retried["status"] == "needs_review" and len(f.calls) == 2
    assert ProjectCommands(f.store).query(first["operation_id"])["phase"] == "rejected"


def test_legacy_unscoped_preview_cancellation_does_not_reject_a_shared_command(native_task):
    f = native_task
    review = annotation_operations.preview_document_operations(f.project, f.request["operations"],
        output_dir=f.root.parent / "legacy-preview", figure_id="first",
        expected_document_sha256=f.request["expected_document_sha256"])
    f.root.mkdir()
    (f.root / "review.json").write_text(json.dumps(review))
    state = {"kind": "sciplot_task", "version": 1, "task_dir": str(f.root), "created_at": "frozen legacy creation",
             "request": f.request, "project": str(f.project), "status": "needs_review", "phase": "review",
             "preview_attempt": 1, "operation_id": review["operation_id"],
             "preview": {"image": review["preview"], "review_path": str(f.root / "review.json")}}
    task_storage.save_task(f.root, state)
    assert _cancel(f, review)["status"] == "cancelled"
    assert "native_command_scope" not in task_storage.load_task(f.root)
    assert ProjectCommands(f.store).query(review["operation_id"])["phase"] == "needs_review"
    assert f.native.read_bytes() == f.original


@pytest.mark.parametrize("source_changed", [False, True])
def test_native_cancellation_is_historical_but_never_reverses_an_accepted_core_decision(native_task, source_changed):
    f = native_task
    first = task_control.start_task(f.request, task_dir=f.root)
    record = ProjectCommands(f.store).query(first["operation_id"])
    if source_changed:
        source = f.project / "source/data.csv"
        source.write_bytes(b"later source revision")
        assert _cancel(f, first)["status"] == "cancelled"
        assert source.read_bytes() == b"later source revision"
        assert ProjectCommands(f.store).query(first["operation_id"])["phase"] == "rejected"
    else:
        f.store.decide(record["command_id"], record["command_digest"], decision_id=record["decision_id"], accept=True)
        assert _cancel(f, first)["status"] == "blocked"
        assert ProjectCommands(f.store).query(first["operation_id"])["phase"] == "accepted"
    assert f.native.read_bytes() == f.original


def test_native_revision_identity_rejects_different_business_and_survives_task_relocation(native_task):
    f = native_task
    first = task_control.start_task(f.request, task_dir=f.root)
    state = task_storage.load_task(f.root)
    identity = native_task_request_id(state)
    assert native_task_request_id({**state, "task_dir": "/relocated/task"}) == identity
    with pytest.raises(ValueError, match="another business request"):
        annotation_operations.preview_document_operations(f.project, [style("3pt")],
            output_dir=f.root.parent / "conflicting-preview", figure_id="first",
            expected_document_sha256=f.request["expected_document_sha256"], request_id=identity)
    assert len(f.calls) == 1 and ProjectCommands(f.store).query(first["operation_id"])["phase"] == "needs_review"


def test_noop_reply_loss_replays_rejected_owned_candidate_without_render(native_task, monkeypatch):
    from sciplot_core import task_execution

    f = native_task
    write = task_execution.atomic_write_json
    def lost(path, payload):
        if path == f.root / 'review.json':
            raise OSError('Controlled lost task receipt after Core noop decision')
        return write(path, payload)
    monkeypatch.setattr(task_execution, 'atomic_write_json', lost)
    request = {**f.request, 'operations': [style('1pt')]}
    assert task_control.start_task(request, task_dir=f.root)['status'] == 'blocked'
    prior, = f.store.commands()
    assert prior['phase'] == 'rejected' and prior['accepted'] is False
    monkeypatch.setattr(task_execution, 'atomic_write_json', write)
    result = task_control.resume_task(f.root, {'retry': True})
    assert result['status'] == 'complete' and result['result']['status'] == 'unchanged'
    assert len(f.calls) == 1 and f.native.read_bytes() == f.original


def test_replacement_retry_closes_prior_decision_without_orphaning_new_candidate(native_task, monkeypatch):
    from sciplot_core import task_native_edit

    f = native_task
    first = task_control.start_task(f.request, task_dir=f.root)
    reject = task_native_edit._reject
    def lost(repository, records):
        reject(repository, records)
        raise OSError('Controlled lost Task reply after prior Core rejection')
    monkeypatch.setattr(task_native_edit, '_reject', lost)
    assert _revise(f, first, '3pt')['status'] == 'blocked'
    assert ProjectCommands(f.store).query(first['operation_id'])['phase'] == 'rejected'
    assert sorted(item['phase'] for item in f.store.commands()) == ['needs_review', 'rejected']
    monkeypatch.setattr(task_native_edit, '_reject', reject)
    result = task_control.resume_task(f.root, {'retry': True})
    assert result['status'] == 'needs_review' and result['operation_id'] != first['operation_id']
    assert len(f.calls) == 2 and f.native.read_bytes() == f.original



def test_native_task_cancellation_cannot_claim_another_tasks_scoped_review(native_task, tmp_path):
    f = native_task
    first = task_control.start_task(f.request, task_dir=f.root)
    other_root = tmp_path / 'other-task'
    other = task_control.start_task(f.request, task_dir=other_root)
    state = task_storage.load_task(f.root)
    state['operation_id'] = other['operation_id']
    (f.root / 'review.json').write_bytes((other_root / 'review.json').read_bytes())
    task_storage.save_task(f.root, state)
    assert _cancel(f, other)['status'] == 'blocked'
    assert all(item['phase'] == 'needs_review' for item in f.store.commands())
    assert len(f.calls) == 2 and first['operation_id'] != other['operation_id']
