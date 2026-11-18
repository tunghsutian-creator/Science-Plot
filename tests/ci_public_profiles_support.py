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
            (["README.md"], True), (["docs/unknown.md"], False),
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
            assert "native_preflight" not in plan
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

    paths = ["src/sciplot_core/source_tables/parsing.py", "src/sciplot_core/source_tables/curve_tables.py",
             "src/sciplot_core/source_tables/heatmap_tables.py"]
    regular = ci_feedback.ci_feedback_plan(paths, root, ref="refs/heads/main")
    assert regular["layer"] == "affected" and not regular["native_targets"]
    assert "tests/test_source_numeric_encodings.py" in regular["targets"]
    paths = ["src/sciplot_core/intake/table_preview.py", "tests/test_intake_review_recovery.py",
             "src/sciplot_core/panel_assembly/export.py", "src/sciplot_core/panel_assembly/preview.py",
             "tests/test_panel_assembly_export.py"]
    panel = ci_feedback.ci_feedback_plan(paths, root, event="pull_request")
    assert panel["layer"] == "affected" and len(panel["native_targets"]) == 4
    assert {"tests/test_intake_review_recovery.py", "tests/test_panel_assembly_export.py"} <= set(panel["targets"])
    for ref in ("refs/heads/integration", "refs/heads/release/next", "refs/tags/v1"):
        assert ci_feedback.ci_feedback_plan(paths, root, ref=ref)["layer"] == "full"
    for unsafe in ("src/sciplot_core/panel_assembly/unknown.py", "tests/test_private_observer.py",
                   ".github/workflows/minimal-repository.yml"):
        assert ci_feedback.ci_feedback_plan([*paths, unsafe], root)["layer"] == "full"
    assert ci_feedback.ci_feedback_plan(paths, tmp_path)["layer"] == "full"
    native_path = "src/sciplot_core/panel_assembly/native.py"
    native = ci_feedback.ci_feedback_plan([native_path], root)
    assert native["layer"] == "affected" and len(native["native_targets"]) == 4
    for path, test_file in (
        ("src/sciplot_core/panel_assembly/export.py", "tests/test_panel_assembly_export.py"),
        ("src/sciplot_core/panel_assembly/preview.py", "tests/test_panel_assembly_preview.py"),
    ):
        for changed in (path, test_file):
            targets = ci_feedback.ci_feedback_plan([changed], root)["native_targets"]
            assert len(targets) == 2 and all(target.startswith(test_file + "::") for target in targets)
    reviewed = [
        "src/sciplot_core/studio_core/managed_frequency_query.py",
        "src/sciplot_core/workflow/frequency_managed_requests.py",
        "tests/test_managed_frequency_creation.py",
        "src/sciplot_core/task_semantic_raw_analysis.py",
        "README.md",
        "src/sciplot_core/verification/input_scope_manifest.json",
        "src/sciplot_core/verification/private_corpus_inventory.json",
    ]
    assert ci_feedback.ci_feedback_plan(reviewed, root, event="pull_request")["reason"] == "scope_delta_not_proven"
    with monkeypatch.context() as context:
        context.setattr(ci_feedback, "scope_delta_is_reviewed", lambda *_args: True)
        mixed = ci_feedback.ci_feedback_plan(reviewed, root, event="pull_request", base="a" * 40)
    assert mixed["layer"] == "affected" and not mixed["unowned_paths"]
    assert "tests/test_managed_frequency_creation.py" in mixed["native_targets"]
    assert any(target.endswith("test_frequency_suite_preaccept_retry_cold_resumes_only_the_unfinished_figure")
               for target in mixed["native_targets"])
    assert "tests/test_documentation_contract.py" in mixed["targets"]
    assert "tests/test_task_shortcuts.py" in mixed["targets"]
    assert any(target.endswith("test_checked_in_inventory_is_explicitly_preliminary")
               for target in mixed["targets"])
    from sciplot_core.verification.input_scope import load_manifest
    source = {target.split("::", 1)[0] for key in ("targets", "native_targets") for target in mixed[key]}
    manifest = load_manifest()
    assert public_stage._selected_public_nodes(manifest, dict.fromkeys(source, ""), "public-affected", mixed["targets"])
    assert public_stage._selected_public_nodes(manifest, dict.fromkeys(source, ""), "public-affected-native", mixed["native_targets"])
    assert mixed["full_public_profiles"] == "NOT_EXECUTED"
    assert ci_feedback.ci_feedback_plan(reviewed, root, ref="refs/heads/release")["layer"] == "full"
    assert ci_feedback.ci_feedback_plan(
        [*reviewed, "src/sciplot_core/workflow/frequency_managed_unknown.py"], root,
    )["layer"] == "full"
    from sciplot_core.verification.ordinary_plotting_owners import (
        MANAGED_CURVE_PROJECT_NATIVE, MANAGED_CURVE_PROJECT_PATHS,
    )
    for path in MANAGED_CURVE_PROJECT_PATHS:
        leaf_plan = ci_feedback.ci_feedback_plan([path], root, event="pull_request")
        assert leaf_plan["layer"] == "affected" and not leaf_plan["unowned_paths"]
        assert "managed_curve_project" in leaf_plan["owners"]
        assert set(leaf_plan["native_targets"]) == set(MANAGED_CURVE_PROJECT_NATIVE)
        assert public_stage._selected_public_nodes(manifest, dict.fromkeys(
            (target.split("::", 1)[0] for target in leaf_plan["native_targets"]), ""),
            "public-affected-native", leaf_plan["native_targets"])
    assert ci_feedback.ci_feedback_plan(
        [*MANAGED_CURVE_PROJECT_PATHS, "src/sciplot_core/studio_core/project_creation.py"], root,
    )["layer"] == "full"

    from sciplot_core.verification.scope_feedback import SCOPE_PATHS, scope_delta_is_reviewed
    import subprocess

    scope_checkout = tmp_path / "scope-delta"
    scope_checkout.mkdir()
    def git(*args):
        return subprocess.check_output(["git", *args], cwd=scope_checkout, text=True).strip()

    git("init", "-q")
    git("config", "user.name", "Generated CI Control")
    git("config", "user.email", "generated@example.com")
    scope_path = next(path for path in SCOPE_PATHS if path.endswith("input_scope_manifest.json"))
    inventory_path = next(path for path in SCOPE_PATHS if path.endswith("private_corpus_inventory.json"))
    scope_file, inventory_file = scope_checkout / scope_path, scope_checkout / inventory_path
    scope_file.parent.mkdir(parents=True)
    test_file = "tests/test_managed_frequency_creation.py"
    fresh = test_file + "::test_generated_addition"
    old = "tests/test_dma.py::test_existing"
    scope = {"scopes": {"public": [], "private": [old]}, "tiers": {"focused": [old], "comprehensive": []}}
    inv = {"cases": [{"nodeid": old, "dependencies": ["dma"]}],
           "collection_audit": {"candidate_nodeids": [], "synthetic_candidates": [], "test_sources_sha256": "prior"}}
    scope_file.write_text(json.dumps(scope))
    inventory_file.write_text(json.dumps(inv))
    git("add", ".")
    git("commit", "-qm", "Historical science membership")
    base = git("rev-parse", "HEAD")
    scope["scopes"]["public"].append(fresh)
    scope["tiers"]["comprehensive"].append(fresh)
    inv["collection_audit"].update(candidate_nodeids=[fresh], synthetic_candidates=[{"nodeid": fresh}], test_sources_sha256="next")
    scope_file.write_text(json.dumps(scope))
    inventory_file.write_text(json.dumps(inv))
    (scope_checkout / test_file).parent.mkdir(parents=True)
    (scope_checkout / test_file).write_text("def test_generated_addition(): pass\n")
    git("add", ".")
    git("commit", "-qm", "Authorized generated addition")
    delta = {scope_path, inventory_path, test_file}
    assert scope_delta_is_reviewed(scope_checkout, base, delta, [], [test_file])
    assert not scope_delta_is_reviewed(scope_checkout, "", delta, [], [test_file])
    assert not scope_delta_is_reviewed(scope_checkout, base, delta, [], [])
    inv["cases"][0]["dependencies"] = ["tga"]
    inventory_file.write_text(json.dumps(inv))
    git("commit", "-qam", "Unauthorized private dependency")
    assert not scope_delta_is_reviewed(scope_checkout, base, delta, [], [test_file])

    from sciplot_core.verification.changed import build_changed_verification_plan

    for path in ("src/sciplot_core/source_tables/curve_tables.py", "src/sciplot_core/source_tables/heatmap_tables.py"):
        local = build_changed_verification_plan([path], repo_root=root)
        assert not local["unowned_paths"] and local["status"] == "planned"
        assert "tests/test_legacy_core_migration.py" in next(
            check["command"] for check in local["checks"] if check["check_id"] == "pytest_changed_owners"
        )

    workflow = (root / ".github/workflows/minimal-repository.yml").read_text()
    steps = workflow.split("      - name: ")
    conditional = {step.splitlines()[0]: re.search(r"        if: \$\{\{ (.*?) \}\}", step).group(1)
                   for step in steps if "        if: ${{ " in step}
    full_names = ("Run reviewed public focused behavior",
                  "Run reviewed public comprehensive behavior", "Run readiness check",
                  "Run fixture-free lifecycle smoke")
    def enabled(expression, outcome, layer, event, admission_outcome="success", referenced="false", diagnostic=False):
        values = {"steps.native-feedback.outcome": outcome, "steps.native-feedback.outputs.layer": layer,
                  "steps.main-admission.outcome": admission_outcome,
                  "steps.main-admission.outputs.referenced": referenced,
                  "github.event_name": event,
                  "inputs.native_regression_preflight": diagnostic}
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
    preflight = conditional["Check known native CI regressions before the public suites"]
    assert not enabled(preflight, "success", "full", "push", diagnostic=True)
    assert not enabled(preflight, "success", "full", "workflow_dispatch")
    assert enabled(preflight, "success", "full", "workflow_dispatch", diagnostic=True)
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
        staged = tmp_path / "native-case"
        file = staged / native_path
        file.parent.mkdir(parents=True)
        file.touch()
        context.setattr(ci_feedback, "changed_paths", lambda *_args: [native_path])
        stages = []

        def stage(_root, output, profile, *, targets=None):
            stages.append((profile, targets))
            output.mkdir(parents=True)
            return {"status": "BLOCKED" if profile == "public-affected-native" else "PASS"}

        context.setattr(public_stage, "run_public_stage", stage)
        result = ci_feedback.run_affected(staged, "a" * 40, event="push")
        assert [profile for profile, _ in stages] == ["public-affected", "public-affected-native"]
        assert stages[1][1] == native["native_targets"]
        assert result["status"] == "BLOCKED" and result["targeted_native"]["status"] == "BLOCKED"
    with monkeypatch.context() as context:
        context.setattr(ci_feedback, "changed_paths", lambda *_args: (_ for _ in ()).throw(OSError("unavailable")))
        context.setattr(sys, "argv", ["ci_feedback", "--base", "a" * 40])
        destination = tmp_path / "missing-plan-output"
        context.setenv("GITHUB_OUTPUT", str(destination))
        assert ci_feedback.main() == 0
        assert destination.read_text() == "layer=full\n"
        context.setattr(sys, "argv", ["ci_feedback", "--base", "a" * 40, "--run-affected"])
        assert ci_feedback.main() == 4
        context.setattr(sys, "argv", ["ci_feedback", "--base", "a" * 40])
        context.setattr(ci_feedback, "changed_paths", lambda *_args: (_ for _ in ()).throw(RuntimeError("programming defect")))
        with pytest.raises(RuntimeError, match="programming defect"):
            ci_feedback.main()
