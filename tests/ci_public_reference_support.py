"""Public CI profile and bounded feedback controls."""
from __future__ import annotations

import io
import json

import pytest


def exercise_profile_stage_route(tmp_path, monkeypatch):
    from sciplot_core.verification import ci_public_profiles as profiles
    calls = []
    # The mocked stage supplies the same existing result field as a real stage;
    # keep official CI's GITHUB_SHA binding active instead of stripping it.
    monkeypatch.setenv("GITHUB_SHA", "a" * 40)
    for profile in ("focused", "comprehensive"):
        directory = tmp_path / f".tmp_verify/ci_public_{profile}"
        directory.mkdir(parents=True)
        (directory / "result.json").write_text(json.dumps({"origin_head": "a" * 40}))
    tails = []
    exit_code = [0]
    class Process:
        def __init__(self, command, **kwargs):
            self.is_tail = command[0] == "tail"
            self.stdout = io.StringIO("owner result\n") if not self.is_tail else None
            self.running = True
            calls.append(command)
            if self.is_tail:
                tails.append(self)
        def wait(self):
            self.running = False
            return 0 if self.is_tail else exit_code[0]
        def poll(self):
            return None if self.running else 0
        def terminate(self):
            self.running = False
    with monkeypatch.context() as context:
        context.setattr(profiles.subprocess, "Popen", Process)
        for profile in ("focused", "comprehensive"):
            assert profiles.run_profile(tmp_path, profile) == 0
            command = calls[-1]
            assert command[1:5] == ["-m", "sciplot_core.verification.public_stage", "--profile", "public-" + profile]
            assert command[-1] == ".tmp_verify/ci_public_" + profile
            assert str(tmp_path / (".tmp_verify/ci_public_" + profile + "/command.log")) in calls[-2]
        assert len(tails) == 2 and not any(tail.running for tail in tails)
        wrong = tmp_path / "wrong-stage-head"
        result = wrong / ".tmp_verify/ci_public_focused/result.json"
        result.parent.mkdir(parents=True)
        result.write_text(json.dumps({"origin_head": "b" * 40}))
        with pytest.raises(ValueError, match="Actual public stage source"):
            profiles.run_profile(wrong, "focused")
        assert not any(tail.running for tail in tails)
        exit_code[0] = 7
        assert profiles.run_profile(tmp_path / "failed", "focused") == 7
        assert not tails[-1].running
        assert (tmp_path / "failed" / profiles.DIRECTORY / "focused.log").read_text() == "owner result\n"


def exercise_ci_feedback_layers(root, tmp_path, monkeypatch):
    import re
    import sys
    from sciplot_core.verification import ci_feedback, public_stage
    from sciplot_core.verification import task_timing_feedback
    from sciplot_core.verification.type_gate_owners import ARCHITECTURE_CORE_TARGETS

    leaf = "src/sciplot_core/task_timing.py"
    with monkeypatch.context() as context:
        context.setattr(task_timing_feedback, "task_timing_feedback_eligible", lambda _root: True)
        for paths, affected in (
            (["docs/DESIGN_PROJECT_LIFECYCLE.md"], True),
            (["docs/DESIGN_PROJECT_CORE_MIGRATION.md"], True),
            ([leaf], True), ([leaf, "README.md"], False),
            ([leaf, "docs/DESIGN_PROJECT_LIFECYCLE.md"], False),
            (["README.md"], False), (["docs/unknown.md"], False),
            (["src/sciplot_core/task_contract.py"], False),
            (["src/sciplot_core/veusz_runtime.py"], False),
            (["src/sciplot_core/foundation/iso_timestamps.py"], False),
            (["src/sciplot_core/verification/public_stage.py"], False),
            (["src/sciplot_core/verification/task_timing_feedback.py"], False),
            (["src/sciplot_core/verification/ci_feedback.py"], False),
            ([".github/workflows/minimal-repository.yml"], False),
            (["tests/test_task_timing_feedback.py"], False),
            (["src/sciplot_core/unknown.py"], False), ([], False),
        ):
            plan = ci_feedback.ci_feedback_plan(paths, root)
            assert (plan["layer"] == "affected") is affected, (paths, plan)
            assert plan["native_preflight"] is not affected
            assert plan["reusable_origin"] is False
            if affected:
                assert set(ARCHITECTURE_CORE_TARGETS) <= set(plan["targets"])
                assert "tests/test_public_stage.py" in plan["targets"]
                assert plan["full_public_profiles"] == "NOT_EXECUTED"
            else:
                assert plan["targets"] == []
        assert "tests/test_task_timing_feedback.py" in ci_feedback.ci_feedback_plan([leaf], root)["targets"]
        for event in ("workflow_dispatch", "schedule", "", "workflow_run"):
            assert ci_feedback.ci_feedback_plan([leaf], root, event=event)["layer"] == "full"
        context.setattr(task_timing_feedback, "task_timing_feedback_eligible", lambda _root: False)
        assert ci_feedback.ci_feedback_plan([leaf], root)["layer"] == "full"

    workflow = (root / ".github/workflows/minimal-repository.yml").read_text()
    steps = workflow.split("      - name: ")
    conditional = {step.splitlines()[0]: re.search(r"        if: \$\{\{ (.*?) \}\}", step).group(1)
                   for step in steps if "        if: ${{ " in step}
    full_names = ("Run reviewed public focused behavior",
                  "Run reviewed public comprehensive behavior", "Run readiness check",
                  "Run fixture-free lifecycle smoke",
                  "Check known native CI regressions before the public suites")
    def enabled(expression, outcome, layer, event, admission_outcome="success", referenced="false"):
        values = {"steps.native-feedback.outcome": outcome, "steps.native-feedback.outputs.layer": layer,
                  "steps.main-admission.outcome": admission_outcome,
                  "steps.main-admission.outputs.referenced": referenced,
                  "github.event_name": event,
                  "inputs.native_regression_preflight": False}
        for key, value in values.items():
            expression = expression.replace(key, repr(value))
        return eval(expression.replace("&&", " and ").replace("||", " or ").replace("== true", "== True"),
                    {"__builtins__": {}}, {})
    for outcome, layer, event, full in (
        ("success", "affected", "push", False), ("success", "affected", "pull_request", False),
        ("success", "full", "push", True), ("failure", "affected", "push", True),
        ("", "", "push", True), ("success", "", "push", True),
        ("success", "unknown", "push", True), ("success", "affected", "workflow_dispatch", True),
    ):
        assert enabled(conditional["Run reviewed affected public feedback"], outcome, layer, event) is not full
        for name in full_names:
            assert enabled(conditional[name], outcome, layer, event) is full, name
    for name in ("Run lint gate", "Run shared source contracts", "Run scoped static type gate", "Build vendored Veusz helpers",
                 "Verify vendored Veusz helpers", "Verify minimal wheel surface", "Verify Qt build and runtime identity"):
        expression = conditional[name]
        for admission_outcome, referenced, executes in (("success", "true", False), ("success", "false", True),
                                                        ("failure", "true", True), ("", "", True)):
            assert enabled(expression, "success", "affected", "push", admission_outcome, referenced) is executes
            assert enabled(expression, "failure", "", "workflow_dispatch", admission_outcome, referenced) is executes

    with monkeypatch.context() as context:
        context.setattr(ci_feedback, "changed_paths", lambda *_args: ["src/sciplot_core/task_contract.py"])
        context.setattr(public_stage, "run_public_stage", lambda *_args, **_kw: pytest.fail("Drift must not run limited stage"))
        with pytest.raises(ValueError, match="eligibility changed"):
            ci_feedback.run_affected(root, "a" * 40, event="push")
    with monkeypatch.context() as context:
        selected = []
        context.setattr(ci_feedback, "changed_paths", lambda *_args: ["docs/DESIGN_PROJECT_LIFECYCLE.md"])
        def stage(actual_root, output, profile, *, targets=None):
            assert actual_root == tmp_path and profile == "public-affected"
            assert targets and "tests/test_repository_policy.py" in targets
            selected.extend(targets)
            output.mkdir(parents=True)
            return {"status": "PASS", "profile": profile}
        context.setattr(public_stage, "run_public_stage", stage)
        result = ci_feedback.run_affected(tmp_path, "a" * 40, event="push")
        assert selected and result["full_public_profiles"] == "NOT_EXECUTED" and result["reusable_origin"] is False
        assert (tmp_path / ".tmp_verify/ci_public_affected/feedback-result.json").is_file()
    with monkeypatch.context() as context:
        context.setattr(ci_feedback, "changed_paths", lambda *_args: (_ for _ in ()).throw(OSError("unavailable")))
        context.setattr(sys, "argv", ["ci_feedback", "--base", "a" * 40])
        destination = tmp_path / "missing-plan-output"
        context.setenv("GITHUB_OUTPUT", str(destination))
        assert ci_feedback.main() == 0
        assert destination.read_text() == "preflight=true\nlayer=full\n"
        context.setattr(sys, "argv", ["ci_feedback", "--base", "a" * 40, "--run-affected"])
        assert ci_feedback.main() == 4
        context.setattr(sys, "argv", ["ci_feedback", "--base", "a" * 40])
        context.setattr(ci_feedback, "changed_paths", lambda *_args: (_ for _ in ()).throw(RuntimeError("programming defect")))
        with pytest.raises(RuntimeError, match="programming defect"):
            ci_feedback.main()
