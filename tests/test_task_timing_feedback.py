"""Metadata-only feedback keeps the timing consumers and rejects boundary expansion."""
from copy import deepcopy
from pathlib import Path
import sys

import pytest

from sciplot_core.verification.changed import build_changed_verification_plan, run_changed_verification
from sciplot_core.verification.task_control_owners import TASK_TIMING_FEEDBACK_TARGETS
from sciplot_core.verification.task_timing_feedback import TASK_TIMING_PATH, task_timing_feedback_eligible
from sciplot_core.verification.type_gate_owners import ARCHITECTURE_CORE_TARGETS

ROOT = Path(__file__).resolve().parents[1]


def test_current_task_timing_has_only_the_reviewed_metadata_boundary():
    assert task_timing_feedback_eligible(ROOT), "Timing gained an unreviewed boundary; update its owner before using leaf feedback."


@pytest.mark.parametrize("before,after", [
    ("import", "unused"),  # A malformed source also stays ineligible.
    ("from time import perf_counter", "from time import perf_counter\nfrom sciplot_core import task_storage"),
    ("from time import perf_counter", "from time import perf_counter\nimport os"),
    ("from time import perf_counter", "from time import perf_counter as clock"),
    ("MESSAGE_SENTINEL", "open('/tmp/feedback-unknown', 'w')"),
    ("MESSAGE_SENTINEL", "__import__('os').system('echo unknown')"),
    ("MESSAGE_SENTINEL", "Path('/tmp/feedback-unknown').write_text('unknown')"),
    ('clock = _ACTIVE.get()', 'clock = state'),
    ('state["local_timing"] = {', 'state["scientific_hash"] = {'),
    ('clock.update(root=str(root), phase=state["phase"], last=now)', 'state.update(scientific_hash="changed")'),
    ('clock.update(root=str(root), phase=state["phase"], last=now)', 'clock.update(source="changed")'),
    ('"external_model_seconds": None,', '"external_model_seconds": None, "scientific_hash": "changed",'),
    ('return function(*args, **kwargs)', 'function(*args, **kwargs)\n            return function(*args, **kwargs)'),
    ('_ACTIVE.reset(token)', '_ACTIVE.set({})'),
    ('_ACTIVE.reset(token)', 'pass'),
    ('def observe_phase(', 'def new_public_surface('),
    ('_P = ParamSpec("_P")', '_P = ParamSpec("_P")\nNEW_PUBLIC_SURFACE = True'),
])
def test_unknown_source_is_rejected_without_importing_or_executing_it(tmp_path, before, after):
    original = (ROOT / TASK_TIMING_PATH).read_text()
    if before == "MESSAGE_SENTINEL":
        changed = original + "\n" + after + "\n"
    elif before == "import":
        changed = "this is not Python ="
    else:
        assert before in original
        changed = original.replace(before, after)
    path = tmp_path / TASK_TIMING_PATH
    path.parent.mkdir(parents=True)
    path.write_text(changed)
    assert not task_timing_feedback_eligible(tmp_path)


def test_missing_or_aliased_module_is_not_a_timing_leaf(tmp_path):
    assert not task_timing_feedback_eligible(tmp_path)
    path = tmp_path / TASK_TIMING_PATH
    path.parent.mkdir(parents=True)
    path.symlink_to(ROOT / TASK_TIMING_PATH)
    assert not task_timing_feedback_eligible(tmp_path)


def test_scalar_metadata_arithmetic_edit_remains_eligible(tmp_path):
    path = tmp_path / TASK_TIMING_PATH
    path.parent.mkdir(parents=True)
    path.write_text((ROOT / TASK_TIMING_PATH).read_text().replace("round(elapsed, 6)", "round(elapsed, 5)"))
    assert task_timing_feedback_eligible(tmp_path)


def test_conditional_extra_callback_before_clock_assignment_is_ineligible(tmp_path):
    original = (ROOT / TASK_TIMING_PATH).read_text()
    before = "        started = perf_counter()\n        token = _ACTIVE.set"
    after = '''        try:
            if args and args[0].name == "rare_root":
                function(*args, **kwargs)
        finally:
            started = perf_counter()
        token = _ACTIVE.set'''
    assert original.count(before) == 1 and task_timing_feedback_eligible(ROOT)
    path = tmp_path / TASK_TIMING_PATH
    path.parent.mkdir(parents=True)
    path.write_text(original.replace(before, after))
    assert not task_timing_feedback_eligible(tmp_path)


def test_timing_executes_once_preserves_science_and_restores_context_on_failure(monkeypatch, tmp_path):
    assert task_timing_feedback_eligible(ROOT)
    from sciplot_core import task_timing as timing

    now, calls = [0.0], []
    monkeypatch.setattr(timing, "perf_counter", lambda: now[0])
    state = {"task_dir": str(tmp_path), "phase": "complete", "scientific_hash": "unchanged",
             "sources": [{"sha256": "a" * 64}], "result": {"values": [1, 2, 3]}}
    original = deepcopy(state)
    outer = {"owner": "outer call"}
    token = timing._ACTIVE.set(outer)
    error = RuntimeError("the original callback failure")

    @timing.timed_task_call
    def fail():
        calls.append("fail")
        raise error

    @timing.timed_task_call
    def complete():
        calls.append("complete")
        timing.observe_phase(tmp_path, {"phase": "prepare"})
        now[0] += 2
        timing.observe_phase(tmp_path / "foreign", {"phase": "must_not_enter"})
        timing.finish_timing(state)
        return state

    try:
        with pytest.raises(RuntimeError) as caught:
            fail()
        assert caught.value is error and timing._ACTIVE.get() is outer
        result = complete()
        assert timing._ACTIVE.get() is outer and result is state
        assert calls == ["fail", "complete"]
        assert {key: value for key, value in state.items() if key != "local_timing"} == original
        assert state["local_timing"]["calls"] == 1
        assert state["local_timing"]["total_seconds"] == 2
        assert "must_not_enter" not in state["local_timing"]["last_call_phases_seconds"]
        assert state["local_timing"]["external_model_seconds"] is None
    finally:
        timing._ACTIVE.reset(token)


def test_timing_leaf_selects_consumers_guards_and_complete_type_gate():
    plan = build_changed_verification_plan([TASK_TIMING_PATH], repo_root=ROOT)
    assert plan["status"] == "planned"
    assert {owner["owner_id"] for owner in plan["owners"]} == {
        "local_task_timing_metadata", "scientific_transaction_type_gate"}
    leaf = next(owner for owner in plan["owners"] if owner["owner_id"] == "local_task_timing_metadata")
    assert tuple(leaf["pytest_targets"]) == TASK_TIMING_FEEDBACK_TARGETS
    assert set(ARCHITECTURE_CORE_TARGETS) <= set(leaf["pytest_targets"])
    checks = {check["check_id"]: check["command"] for check in plan["checks"]}
    assert checks["mypy_owned_scope"] == [sys.executable, "-m", "mypy"]
    assert "tests/test_task_control_native.py" not in checks["pytest_changed_owners"]
    assert plan["required_later"]["release"] == ["full_pytest"]


@pytest.mark.parametrize("path,owner,target", [
    ("src/sciplot_core/task_control.py", "local_task_control", "tests/test_task_control_native.py"),
    ("src/sciplot_core/task_storage.py", "local_task_control", "tests/test_task_control_native.py"),
    ("src/sciplot_core/task_future_neighbor.py", "local_task_control", "tests/test_task_control_native.py"),
    ("src/sciplot_core/project_commands/resources.py", "complete_project_command_contract", "tests/test_project_commands_store_contract.py"),
    ("src/sciplot_core/plot_transforms/identity.py", "retained_scientific_operators", "tests/test_plot_transforms.py"),
    ("src/sciplot_core/verification/public_input_guard.py", "changed_verification", "tests/test_public_stage.py"),
])
def test_shared_scientific_public_and_future_neighbors_keep_their_broader_controls(path, owner, target):
    plan = build_changed_verification_plan([TASK_TIMING_PATH, path], repo_root=ROOT)
    assert owner in {row["owner_id"] for row in plan["owners"]}
    command = next(check["command"] for check in plan["checks"] if check["check_id"] == "pytest_changed_owners")
    assert target in command


def test_unknown_scope_never_runs_a_smaller_successful_fallback():
    def forbidden(*args):
        pytest.fail("unknown ownership must fail before executing checks")

    result = run_changed_verification(repo_root=ROOT, changed_paths=[TASK_TIMING_PATH, "src/sciplot_core/unknown_feedback.py"],
                                      command_runner=forbidden)
    assert result["status"] == "failed" and result["checks_executed"] == 0
    assert result["unowned_paths"] == ["src/sciplot_core/unknown_feedback.py"]
