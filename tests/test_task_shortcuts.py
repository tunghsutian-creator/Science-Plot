"""Typed entries remove transport chores without bypassing task review or guards."""

from copy import deepcopy
import json
from pathlib import Path

import pytest

from sciplot_core import task_shortcuts as shortcuts
from sciplot_core.cli.dispatch import tasks as dispatch
from sciplot_core.cli.parsers import build_parser
from sciplot_core.studio_core.annotation_schema import AnnotationOperationError
from sciplot_core.task_capabilities import task_capabilities
from sciplot_core.task_contract import TaskControlError
from sciplot_core.task_next_step import task_next_step


@pytest.fixture
def ready(monkeypatch):
    calls = []
    runtime = {"kind": "sciplot_doctor", "status": "ready",
               "checks": [{"status": "passed", "detail": "large readiness evidence"}]}
    monkeypatch.setattr(shortcuts, "doctor_payload", lambda: calls.append("doctor") or runtime)
    return calls, runtime


def test_create_retains_original_input_and_existing_question_without_invented_mapping(ready, monkeypatch):
    calls, _ = ready
    question = {"field": "column_mapping", "question_id": "a" * 64, "mapping_candidates": [{"id": "real cells"}]}
    result = {"kind": "sciplot_task", "status": "needs_input", "question": question}
    def start(request, *, task_dir, entry_intent=None):
        calls.append((request, task_dir))
        return deepcopy(result)
    monkeypatch.setattr(shortcuts, "start_task", start)
    actual = shortcuts.create_task(Path("raw original.xlsx"), rule_id="uvvis_spectrum",
                                   template="curve", out=Path("/delivery"), task_dir=Path("/task"))
    assert calls == ["doctor", ({"version": 1, "action": "create", "source": "raw original.xlsx",
                                "rule_id": "uvvis_spectrum", "template": "curve", "out": "/delivery"}, Path("/task"))]
    assert actual == {**result, "doctor": {"kind": "sciplot_doctor", "status": "ready", "failed_checks": []}}


def test_create_preserves_profile_and_source_adjacent_default(ready, monkeypatch):
    requests = []
    monkeypatch.setattr(shortcuts, "start_task", lambda request, **kwargs: requests.append(request) or {"status": "complete"})
    shortcuts.create_task(Path("/original.csv"), profile=Path("/profile.json"))
    assert requests == [{"version": 1, "action": "create", "source": "/original.csv", "profile": "/profile.json"}]


def test_create_rejects_profile_conflict_before_runtime_or_task_allocation(ready, monkeypatch):
    calls, _ = ready
    monkeypatch.setattr(shortcuts, "start_task", lambda *_a, **_k: pytest.fail("allocated invalid task"))
    with pytest.raises(TaskControlError, match="复用配置"):
        shortcuts.create_task(Path("/original.csv"), rule_id="uvvis_spectrum", profile=Path("/profile.json"))
    assert calls == []


def test_runtime_failure_does_not_start_or_hide_repair(ready, monkeypatch):
    calls, runtime = ready
    runtime.update(status="blocked", next_actions=["repair exact missing runtime"],
                   checks=[{"status": "failed", "detail": "missing native runtime"}])
    monkeypatch.setattr(shortcuts, "start_task", lambda *_a, **_k: pytest.fail("allocated blocked task"))
    result = shortcuts.create_task(Path("/original.csv"))
    assert calls == ["doctor"] and result["reason_code"] == "runtime_not_ready"
    assert result["doctor"]["failed_checks"] == runtime["checks"]
    assert result["next_step"] == {"action": "repair_runtime", "next_actions": runtime["next_actions"]}


@pytest.fixture
def context(monkeypatch):
    value = {"status": "ok", "doctor": {"kind": "sciplot_doctor", "status": "ready", "failed_checks": []},
             "selected_figure": {"sample_styles": [{"sample": "Exact B", "unique": True},
                                                       {"sample": "Exact A", "unique": True}]},
             "request_template": {"version": 1, "action": "edit", "project": "/current/project",
                                  "figure_id": "secondary", "expected_document_sha256": "a" * 64, "operations": []}}
    calls = []
    monkeypatch.setattr(shortcuts, "edit_context", lambda *args, **kwargs: calls.append((args, kwargs)) or value)
    monkeypatch.setattr(shortcuts, "doctor_payload", lambda: pytest.fail("repeated context Doctor"))
    return value, calls


@pytest.mark.parametrize("all_samples,samples,expected", [
    (True, None, ["Exact B", "Exact A"]), (False, ["Exact A", "Exact B"], ["Exact A", "Exact B"]),
])
def test_style_binds_current_figure_sha_and_exact_selection_once(context, monkeypatch, all_samples, samples, expected):
    value, calls = context
    before = deepcopy(value)
    requests = []
    preview = {"kind": "sciplot_task", "status": "needs_review", "operation_id": "b" * 64,
               "preview": {"image": "/preview.png", "scientific_audit": {"status": "passed"}}}
    def start(request, *, task_dir, entry_intent=None):
        requests.append((request, task_dir))
        return deepcopy(preview)
    monkeypatch.setattr(shortcuts, "start_task", start)
    result = shortcuts.style_task(Path("/delivery with spaces"), samples=samples, all_samples=all_samples,
                                  width="0.7pt", color="#2878B5", figure_id="secondary", task_dir=Path("/task"))
    assert calls == [((Path("/delivery with spaces"),), {"operations": ["set_sample_style"], "figure_id": "secondary"})]
    assert requests == [({**value["request_template"], "operations": [{"op": "set_sample_style",
                          "samples": expected, "style": {"width": "0.7pt", "color": "#2878B5"}}]}, Path("/task"))]
    assert result == {**preview, "doctor": value["doctor"]}
    assert value == before  # No mutation of the inspected revision or implicit acceptance.


@pytest.mark.parametrize("kwargs", [{}, {"all_samples": True, "samples": ["A"]},
    {"all_samples": True}, {"all_samples": True, "width": ""},
    {"samples": []}, {"samples": ["A", "A"]}])
def test_invalid_style_intent_fails_before_context_or_task(monkeypatch, kwargs):
    monkeypatch.setattr(shortcuts, "edit_context", lambda *_a, **_k: pytest.fail("queried invalid intent"))
    monkeypatch.setattr(shortcuts, "start_task", lambda *_a, **_k: pytest.fail("allocated invalid intent"))
    options = {"width": "0.7pt", **kwargs}
    if kwargs == {"all_samples": True}:
        options.pop("width")
    with pytest.raises((TaskControlError, AnnotationOperationError)):
        shortcuts.style_task(Path("/project"), **options)


@pytest.mark.parametrize("targets,samples,code", [
    ([], None, "unknown_sample_style_target"),
    ([{"sample": "A", "unique": False}], None, "ambiguous_sample_style_target"),
    ([{"sample": "A", "unique": True}], ["a"], "unknown_sample_style_target"),
    ([{"sample": "A", "unique": False}], ["A"], "ambiguous_sample_style_target"),
])
def test_style_rejects_empty_ambiguous_or_inexact_targets_without_allocating(context, monkeypatch, targets, samples, code):
    value, _ = context
    value["selected_figure"]["sample_styles"] = targets
    monkeypatch.setattr(shortcuts, "start_task", lambda *_a, **_k: pytest.fail("allocated invalid target"))
    with pytest.raises(TaskControlError) as error:
        shortcuts.style_task(Path("/project"), samples=samples, all_samples=samples is None, width="0.7pt")
    assert error.value.reason_code == code


@pytest.mark.parametrize("reason", ["unfinished_task", "runtime_not_ready"])
def test_style_returns_existing_continuation_without_start_or_second_doctor(context, monkeypatch, reason):
    value, _ = context
    value.clear()
    value.update(status="blocked", reason_code=reason, next_step={"action": "original continuation"})
    monkeypatch.setattr(shortcuts, "start_task", lambda *_a, **_k: pytest.fail("started over existing blocker"))
    assert shortcuts.style_task(Path("/task"), all_samples=True, width="0.7pt") == value


@pytest.mark.parametrize("command,expected", [
    (["create", "/raw input.csv", "--rule", "uvvis_spectrum", "--template", "curve", "--out", "/out", "--task-dir", "/task"],
     ("create", Path("/raw input.csv"), {"rule_id": "uvvis_spectrum", "template": "curve", "profile": None, "out": Path("/out"), "task_dir": Path("/task")})),
    (["style", "/saved", "--sample", "B", "--sample", "A", "--width", "0.7pt", "--figure", "secondary"],
     ("style", Path("/saved"), {"samples": ["B", "A"], "all_samples": False, "width": "0.7pt", "color": None, "figure_id": "secondary", "task_dir": None})),
])
def test_cli_shortcuts_need_no_json_file_and_preserve_arguments(monkeypatch, capsys, command, expected):
    calls = []
    receipt = {"kind": "sciplot_task", "status": "needs_input", "doctor": {"status": "ready"}, "question": {"field": "rule_id"}}
    for name in ("create", "style"):
        monkeypatch.setattr(shortcuts, name + "_task", lambda target, _name=name, **kwargs: calls.append((_name, target, kwargs)) or deepcopy(receipt))
    monkeypatch.setattr(dispatch, "_object", lambda *_a: pytest.fail("read unnecessary JSON file"))
    args = build_parser().parse_args(["task", *command, "--json"])
    assert dispatch.dispatch_task(args) == 0
    assert calls == [expected] and json.loads(capsys.readouterr().out) == receipt


@pytest.mark.parametrize("arguments", [
    ["style", "/saved", "--width", "0.7pt"],
    ["style", "/saved", "--all-samples", "--sample", "A", "--width", "0.7pt"],
    ["resume", "/task"], ["resume", "/task", "--retry", "--response", "/answer.json"],
    ["resume", "/task", "--accept-preview", "--retry"],
])
def test_cli_mutually_exclusive_inputs_rejected_during_parse(arguments):
    with pytest.raises(SystemExit):
        build_parser().parse_args(["task", *arguments])


@pytest.mark.parametrize("arguments", [
    ["--accept-preview"], ["--accept-preview", "--expected-operation-id", "invalid"],
    ["--retry", "--expected-operation-id", "a" * 64],
    ["--response", "/missing.json", "--expected-operation-id", "a" * 64],
])
def test_cli_preview_binding_errors_fail_before_read_or_resume(monkeypatch, arguments):
    monkeypatch.setattr(dispatch, "resume_task", lambda *_a: pytest.fail("resumed without valid explicit binding"))
    monkeypatch.setattr(dispatch, "_object", lambda *_a: pytest.fail("read file before rejecting invalid combination"))
    args = build_parser().parse_args(["task", "resume", "/task", *arguments])
    with pytest.raises(TaskControlError):
        dispatch.dispatch_task(args)


@pytest.mark.parametrize("arguments,answer", [
    (["--accept-preview", "--expected-operation-id", "b" * 64], {"accept_preview": True, "expected_operation_id": "b" * 64}),
    (["--retry"], {"retry": True}),
])
def test_cli_resume_uses_caller_binding_without_reading_latest_task(monkeypatch, capsys, arguments, answer):
    calls = []
    monkeypatch.setattr(dispatch, "_object", lambda *_a: pytest.fail("read unnecessary JSON file"))
    monkeypatch.setattr(dispatch, "resume_task", lambda target, response: calls.append((target, response)) or {"status": "complete"})
    args = build_parser().parse_args(["task", "resume", "/task with spaces", *arguments, "--json"])
    assert dispatch.dispatch_task(args) == 0
    assert calls == [(Path("/task with spaces"), answer)]
    assert json.loads(capsys.readouterr().out) == {"status": "complete"}


def test_cli_resume_response_file_remains_compatible(tmp_path, monkeypatch):
    answer = {"accept_preview": False, "expected_operation_id": "a" * 64}
    path = tmp_path / "answer.json"
    path.write_text(json.dumps(answer))
    calls = []
    monkeypatch.setattr(dispatch, "resume_task", lambda target, response: calls.append(response) or {"status": "cancelled"})
    args = build_parser().parse_args(["task", "resume", "/task", "--response", str(path)])
    assert dispatch.dispatch_task(args) == 0 and calls == [answer]


def test_guidance_carries_exact_current_arguments_without_shell_concatenation():
    state = {"status": "needs_review", "phase": "review", "request": {"action": "edit"},
             "task_dir": "/task with spaces/$(literal)", "operation_id": "b" * 64}
    result = task_next_step(state)
    assert result["cli_argv"] == ["sciplot", "task", "resume", state["task_dir"], "--accept-preview",
                                  "--expected-operation-id", "b" * 64, "--json"]
    assert result["response_template"] == {"accept_preview": True, "expected_operation_id": "b" * 64}
    state.update(status="blocked", phase="exporting")
    assert task_next_step(state)["cli_argv"] == ["sciplot", "task", "resume", state["task_dir"], "--retry", "--json"]
    state.update(status="needs_review", request={"action": "update_source"}, revision_id="c" * 64)
    assert "cli_argv" not in task_next_step(state)
    assert "typed_entries" in task_capabilities()
