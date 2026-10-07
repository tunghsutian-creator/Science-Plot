"""Fault probes for bounded local recovery and exact-intent transport replay."""

from copy import deepcopy
from hashlib import sha256
import json
import subprocess
from types import SimpleNamespace

import pytest

from sciplot_core import task_control as control, task_execution as execution
from sciplot_core import task_shortcuts as shortcuts, task_storage as storage
from sciplot_core.studio_core import annotation_operations
from sciplot_core.studio_core.annotation_schema import AnnotationOperationError
from sciplot_core.studio_core.project_session import ProjectSessionBusy
from sciplot_core.task_contract import TaskControlError


@pytest.fixture
def editing(tmp_path, monkeypatch):
    project = tmp_path / "project"
    project.mkdir()
    document = project / "document.vsz"
    document.write_bytes(b"original")
    (project / "plot_request.json").write_text(json.dumps({"delivery_output": str(tmp_path / "delivery")}))
    task = tmp_path / "task"
    contexts, previews, effects = [], [], []
    targets = [{"sample": sample, "unique": True, "object_paths": [f"/page1/graph1/{sample}"]}
               for sample in ("A", "B")]
    def context(*args, **kwargs):
        contexts.append((args, kwargs))
        return {"status": "ok", "doctor": {"status": "ready"},
                "selected_figure": {"sample_styles": deepcopy(targets)},
                "request_template": {"version": 1, "action": "edit", "project": str(project),
                                     "figure_id": "primary", "operations": [],
                                     "expected_document_sha256": sha256(document.read_bytes()).hexdigest()}}
    def preview(_project, operations, **kwargs):
        if sha256(document.read_bytes()).hexdigest() != kwargs["expected_document_sha256"]:
            raise AnnotationOperationError("stale_revision", "The original baseline changed.")
        output = kwargs["output_dir"]
        output.mkdir()
        result = {"kind": "sciplot_document_edit_preview", "version": 2, "status": "ready",
                  "project": str(project), "figure_id": "primary", "document": str(document),
                  "document_sha256": kwargs["expected_document_sha256"], "operations": operations,
                  "operation_id": sha256(str(output).encode()).hexdigest(),
                  "preview": {"path": str(output / "candidate.png")},
                  "actual_changes": [{"old_value": "1pt", "new_value": "0.7pt"}],
                  "scientific_audit": {"status": "passed"}}
        previews.append(result)
        return result
    def apply(_project, review):
        effects.append("apply")
        document.write_bytes(b"edited")
        return {"status": "applied", "document": str(document),
                "result_sha256": sha256(document.read_bytes()).hexdigest()}
    def export(_project):
        effects.append("export")
        return {"project_dir": str(project), "studio_run": {"ready_to_use": True}}
    monkeypatch.setattr(shortcuts, "edit_context", context)
    monkeypatch.setattr(control, "resolve_project_path", lambda _: project)
    monkeypatch.setattr(storage, "resolve_project_path", lambda _: project)
    monkeypatch.setattr(control, "inspect_project", lambda _: {"project": str(project), "figures": [],
                        **{key: {"current": True} for key in ("source", "qa", "delivery")}})
    monkeypatch.setattr(annotation_operations, "preview_document_operations", preview)
    monkeypatch.setattr(execution, "apply_document_edit", apply)
    monkeypatch.setattr(execution, "export_project", export)
    def start(**overrides):
        return shortcuts.style_task(project, **{"samples": ["A", "B"], "width": "0.7pt", "task_dir": task, **overrides})
    return SimpleNamespace(project=project, document=document, task=task, contexts=contexts,
                           previews=previews, effects=effects, targets=targets, preview=preview, start=start)


@pytest.mark.parametrize("status", ["needs_review", "complete", "blocked"])
def test_same_explicit_style_key_replays_without_rebinding_or_repeating_work(editing, monkeypatch, status):
    def check_checkpoint(*args, **kwargs):
        saved = storage.load_task(editing.task)
        assert saved["entry_intent"]["style"] == {"width": "0.7pt"}
        return editing.preview(*args, **kwargs)
    monkeypatch.setattr(annotation_operations, "preview_document_operations", check_checkpoint)
    first = editing.start()
    if status != "needs_review":
        if status == "blocked":
            def interrupted(_project):
                editing.effects.append("export_failed")
                raise RuntimeError("Lost export reply")
            monkeypatch.setattr(execution, "export_project", interrupted)
        first = control.resume_task(editing.task, {"accept_preview": True, "expected_operation_id": first["operation_id"]})
    before = (editing.task / "task.json").read_bytes()
    effects = list(editing.effects)
    replay = editing.start()
    assert first["status"] == replay["status"] == status
    assert (editing.task / "task.json").read_bytes() == before
    assert len(editing.contexts) == len(editing.previews) == 1 and editing.effects == effects
    if status == "blocked":
        assert replay["next_step"]["cli_argv"][-2:] == ["--retry", "--json"]


@pytest.mark.parametrize("change", [{"width": "0.8pt"}, {"color": "red"}, {"samples": ["B", "A"]},
                                     {"samples": ["A"]}, {"samples": None, "all_samples": True},
                                     {"figure_id": "secondary"}, {"figure_id": "primary"}])
def test_changed_explicit_intent_cannot_reuse_a_task_key(editing, change):
    editing.start()
    before = (editing.task / "task.json").read_bytes()
    with pytest.raises(TaskControlError) as failed:
        editing.start(**change)
    assert failed.value.reason_code == "task_intent_conflict"
    assert failed.value.repair["action"] == "resolve_task_intent_conflict"
    assert failed.value.repair["request_executed"] is False
    assert failed.value.repair["different_fields"] and "next_step" not in failed.value.repair
    assert len(editing.contexts) == len(editing.previews) == 1 and not editing.effects
    assert (editing.task / "task.json").read_bytes() == before


def test_changed_target_or_missing_entry_identity_is_not_guessed(editing):
    editing.start()
    with pytest.raises(TaskControlError, match="original style intent"):
        shortcuts.style_task(editing.project.parent / "other", samples=["A", "B"], width="0.7pt", task_dir=editing.task)
    state = storage.load_task(editing.task)
    state.pop("entry_intent")
    storage.save_task(editing.task, state)
    with pytest.raises(TaskControlError, match="original style intent"):
        editing.start()
    assert len(editing.contexts) == len(editing.previews) == 1


@pytest.mark.parametrize("width", ["0.7pt", "0.8pt"])
def test_style_task_created_after_replay_miss_keeps_original_intent_under_lease(editing, monkeypatch, width):
    original_replay = shortcuts._style_replay
    committed = {}
    def complete_after_observed_miss(task_dir, intent):
        assert not editing.task.exists()
        # Interleave the competing call after this caller saw a missing key,
        # but before it binds the current document for its proposed request.
        with monkeypatch.context() as concurrent:
            concurrent.setattr(shortcuts, "_style_replay", original_replay)
            first = editing.start()
            finished = control.resume_task(editing.task, {
                "accept_preview": True, "expected_operation_id": first["operation_id"]})
        committed.update(status=finished["status"], receipt=(editing.task / "task.json").read_bytes(),
                         request=storage.load_task(editing.task)["request"])
        assert committed["request"]["expected_document_sha256"] != sha256(editing.document.read_bytes()).hexdigest()
        return None
    monkeypatch.setattr(shortcuts, "_style_replay", complete_after_observed_miss)
    if width == "0.7pt":
        replay = editing.start(width=width)
        assert replay["status"] == committed["status"] == "complete"
    else:
        with pytest.raises(TaskControlError) as failed:
            editing.start(width=width)
        assert failed.value.reason_code == "task_intent_conflict"
    assert (editing.task / "task.json").read_bytes() == committed["receipt"]
    assert storage.load_task(editing.task)["request"] == committed["request"]
    assert len(editing.contexts) == 2 and len(editing.previews) == 1
    assert editing.effects == ["apply", "export"]


def test_start_without_typed_intent_still_requires_exact_original_request(editing):
    first = editing.start()
    control.resume_task(editing.task, {"accept_preview": True, "expected_operation_id": first["operation_id"]})
    request = storage.load_task(editing.task)["request"]
    current_request = {**request, "expected_document_sha256": sha256(editing.document.read_bytes()).hexdigest()}
    before = (editing.task / "task.json").read_bytes()
    with pytest.raises(TaskControlError) as failed:
        control.start_task(current_request, task_dir=editing.task)
    assert failed.value.reason_code == "task_already_exists"
    assert (editing.task / "task.json").read_bytes() == before
    assert editing.effects == ["apply", "export"] and len(editing.previews) == 1


def test_replay_preserves_all_samples_expansion_and_equivalent_size_whitespace(editing):
    editing.start(samples=None, all_samples=True, width=" 0.7 pt ")
    editing.targets.append({"sample": "C", "unique": True})
    replay = editing.start(samples=None, all_samples=True, width="0.7pt")
    assert replay["status"] == "needs_review"
    state = storage.load_task(editing.task)
    assert state["request"]["operations"][0]["samples"] == ["A", "B"]
    assert len(editing.contexts) == len(editing.previews) == 1


def test_unknown_or_ambiguous_sample_reports_exact_choices_without_second_query(editing):
    with pytest.raises(TaskControlError) as failed:
        editing.start(samples=["a"])
    repair = failed.value.repair
    assert repair["action"] == "correct_style_target" and repair["target_count"] == 2
    assert repair["targets"] == editing.targets and repair["figure_id"] == "primary"
    assert not editing.task.exists() and len(editing.contexts) == 1
    editing.targets[0]["unique"] = False
    editing.targets[0]["object_paths"].append("/page1/graph1/also_A")
    with pytest.raises(TaskControlError) as failed:
        editing.start(samples=["A"])
    assert failed.value.repair["targets"][0]["object_paths"] == editing.targets[0]["object_paths"]
    assert not editing.task.exists()


def test_target_correction_choices_are_bounded_without_fuzzy_selection(editing):
    editing.targets[:] = [{"sample": f"Exact {index}", "unique": False,
                          "object_paths": [f"/page1/graph1/series_{path}" for path in range(20)]}
                         for index in range(20)]
    with pytest.raises(TaskControlError) as failed:
        editing.start(samples=["exact 0"])
    repair = failed.value.repair
    assert len(repair["targets"]) == 16 and repair["omitted_target_count"] == 4
    assert all(len(item["object_paths"]) == 16 and item["omitted_object_count"] == 4
               for item in repair["targets"])
    assert not editing.task.exists() and not editing.effects
    with pytest.raises(TaskControlError) as failed:
        editing.start(samples=["Exact 19"])
    assert failed.value.repair["targets"][0]["sample"] == "Exact 19"
    assert len(failed.value.repair["targets"][0]["object_paths"]) == 16


def test_one_terminated_preview_is_retried_locally_in_a_new_preserved_directory(editing, monkeypatch):
    attempts = []
    def interrupted(*args, **kwargs):
        attempts.append(kwargs["output_dir"])
        state = storage.load_task(editing.task)
        if len(attempts) == 1:
            kwargs["output_dir"].mkdir()
            (kwargs["output_dir"] / "partial").write_bytes(b"retained")
            raise subprocess.TimeoutExpired(["worker"], 120)
        assert state["preview_timeout_retries"] == 1  # Budget checkpoint precedes the retry.
        return editing.preview(*args, **kwargs)
    monkeypatch.setattr(annotation_operations, "preview_document_operations", interrupted)
    result = editing.start()
    assert result["status"] == "needs_review" and not editing.effects
    assert [path.name for path in attempts] == ["preview_001", "preview_002"]
    assert (attempts[0] / "partial").read_bytes() == b"retained"
    assert result["automatic_repairs"][0]["failed_preview_attempt"] == 1


def test_timeout_budget_survives_resume_and_failure_does_not_request_operation_changes(editing, monkeypatch):
    attempts = []
    def timeout(*args, **kwargs):
        attempts.append(kwargs["output_dir"])
        raise subprocess.TimeoutExpired(["worker"], 120)
    monkeypatch.setattr(annotation_operations, "preview_document_operations", timeout)
    blocked = editing.start()
    assert blocked["status"] == "blocked" and len(attempts) == 2
    assert blocked["next_step"]["action"] == "retry_same_task"
    resumed = control.resume_task(editing.task, {"retry": True})
    assert resumed["status"] == "blocked" and len(attempts) == 3
    state = storage.load_task(editing.task)
    assert state["preview_timeout_retries"] == 1 and len(state["automatic_repairs"]) == 1
    assert not editing.effects


def test_document_baseline_change_during_timeout_stops_automatic_recovery(editing, monkeypatch):
    def timeout_then_changed(*args, **kwargs):
        if storage.load_task(editing.task)["preview_attempt"] == 1:
            editing.document.write_bytes(b"independent edit")
            raise subprocess.TimeoutExpired(["worker"], 120)
        return editing.preview(*args, **kwargs)
    monkeypatch.setattr(annotation_operations, "preview_document_operations", timeout_then_changed)
    blocked = editing.start()
    assert blocked["blocker"]["reason_code"] == "stale_revision"
    assert blocked["next_step"]["action"] == "refresh_edit_context"
    assert blocked["next_step"]["cli_argv"] == ["sciplot", "task", "edit-context", str(editing.project),
                                               "--operation", "set_sample_style", "--figure", "primary", "--json"]
    assert not editing.previews and not editing.effects
    assert editing.document.read_bytes() == b"independent edit"


@pytest.mark.parametrize("error,action", [
    (ValueError("timeout stale_revision invalid_operation"), "inspect_blocker_and_saved_state"),
    (RuntimeError("worker transport failed"), "inspect_blocker_and_saved_state"),
    (ProjectSessionBusy("project is busy"), "release_project_then_retry"),
    (TaskControlError("source_changed", "bound source differs"), "resolve_source_change"),
    (AnnotationOperationError("invalid_operation", "known invalid field"), "correct_preview_operations"),
])
def test_other_preview_failures_use_codes_without_retry_or_guessing(editing, monkeypatch, error, action):
    attempts = []
    def fail(*args, **kwargs):
        attempts.append(kwargs)
        raise error
    monkeypatch.setattr(annotation_operations, "preview_document_operations", fail)
    result = editing.start()
    assert result["status"] == "blocked" and result["next_step"]["action"] == action
    assert len(attempts) == 1 and "automatic_repairs" not in result and not editing.effects


@pytest.mark.parametrize("phase", ["applying", "exporting"])
def test_mutating_phases_never_auto_retry_timeout(editing, monkeypatch, phase):
    first = editing.start()
    attempts = []
    def timeout(*args):
        attempts.append(args)
        raise subprocess.TimeoutExpired(["worker"], 120)
    monkeypatch.setattr(execution, "apply_document_edit" if phase == "applying" else "export_project", timeout)
    blocked = control.resume_task(editing.task, {"accept_preview": True, "expected_operation_id": first["operation_id"]})
    assert blocked["status"] == "blocked" and blocked["phase"] == phase
    assert len(attempts) == 1 and "automatic_repairs" not in blocked
    assert editing.effects.count("apply") == (1 if phase == "exporting" else 0)


def test_creation_timeout_cannot_trigger_automatic_retry(editing, monkeypatch):
    source = editing.project.parent / "UVvis.csv"
    source.write_text("Wavelength,Absorbance\nnm,a.u.\nA,A\n400,1\n450,3\n500,2\n")
    attempts = []
    def timeout(*args, **kwargs):
        attempts.append(args)
        raise subprocess.TimeoutExpired(["worker"], 120)
    monkeypatch.setattr(execution, "create_project", timeout)
    result = control.start_task({"version": 1, "action": "create", "source": str(source)}, task_dir=editing.task)
    assert result["status"] == "blocked" and result["phase"] == "creating"
    assert len(attempts) == 1 and "automatic_repairs" not in result
    assert result["next_step"]["action"] == "inspect_blocker_and_saved_state"
