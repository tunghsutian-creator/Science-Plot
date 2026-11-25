"""Public CI profile and bounded feedback controls."""
from __future__ import annotations

import json
import os
import subprocess
from textwrap import dedent

import pytest


def exercise_profile_stage_route(tmp_path, monkeypatch, capsys):
    from sciplot_core.verification import ci_public_profiles as profiles

    calls = []
    stdout = b'{"complete": "complete worker stdout; expands in real CI"}\n'
    monkeypatch.setenv("GITHUB_SHA", "a" * 40)
    result = {"origin_head": "a" * 40, "status": "PASS", "actual_exit_code": 0}
    for path in ("ci_public_focused", "ci_public_comprehensive",
                 "ci_public_full/public-focused", "ci_public_full/public-comprehensive"):
        directory = tmp_path / ".tmp_verify" / path
        directory.mkdir(parents=True)
        (directory / "result.json").write_text(json.dumps(result))
    for lane, name, canonical in (
        ("primary/public-focused", "public-focused", True),
        ("primary/public-comprehensive-second", "public-comprehensive-second", False),
        ("comprehensive-first", "public-comprehensive-first", False),
    ):
        path = tmp_path / ".tmp_verify" / f"ci_public_{lane}" / "result.json"
        path.parent.mkdir(parents=True)
        path.write_text(json.dumps({**result, "profile": name, "canonical_profile_executed": canonical}))
    exit_code = [0]

    class Process:
        def __init__(self, command, **kwargs):
            self.timed = False
            calls.append(command)
            kwargs["stdout"].write(stdout)

        def wait(self, *, timeout):
            assert timeout == profiles.PROGRESS_INTERVAL_SECONDS
            if not self.timed:
                self.timed = True
                raise subprocess.TimeoutExpired(calls[-1], timeout)
            return exit_code[0]

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            pass

    with monkeypatch.context() as context:
        context.setattr(profiles.subprocess, "Popen", Process)
        for profile in ("focused", "comprehensive", "full"):
            assert profiles.run_profile(tmp_path, profile) == 0
            selected = "public-ci-full" if profile == "full" else "public-" + profile
            assert calls[-1][1:5] == ["-m", "sciplot_core.verification.public_stage", "--profile", selected]
            assert calls[-1][-1] == ".tmp_verify/ci_public_" + profile
            assert (tmp_path / profiles.DIRECTORY / f"{profile}.log").read_bytes() == stdout
        for profile, name in (("primary", "public-ci-primary"), ("comprehensive-first", "public-comprehensive-first")):
            assert profiles.run_profile(tmp_path, profile) == 0
            assert calls[-1][4] == name
        mismatched = tmp_path / "wrong-profile"
        wrong_profile = mismatched / ".tmp_verify/ci_public_comprehensive-first/result.json"
        wrong_profile.parent.mkdir(parents=True)
        wrong_profile.write_text(json.dumps({**result, "profile": "public-comprehensive-second",
                                             "canonical_profile_executed": False}))
        with pytest.raises(ValueError, match="profile or shard"):
            profiles.run_profile(mismatched, "comprehensive-first")
        assert "complete worker stdout" not in capsys.readouterr().out
        wrong = tmp_path / "wrong-stage-head"
        wrong_result = wrong / ".tmp_verify/ci_public_focused/result.json"
        wrong_result.parent.mkdir(parents=True)
        wrong_result.write_text(json.dumps({**result, "origin_head": "b" * 40}))
        with pytest.raises(ValueError, match="Actual public stage source"):
            profiles.run_profile(wrong, "focused")

        exit_code[0] = 7
        failed = tmp_path / "failed"
        directory = failed / ".tmp_verify/ci_public_focused"
        directory.mkdir(parents=True)
        (directory / "result.json").write_text(json.dumps({**result, "status": "BLOCKED", "actual_exit_code": 7}))
        node_a, node_b = ("tests/test_generated.py::test_failed[exact-a]", "tests/test_generated.py::test_failed[exact-b]")
        (directory / "reports.json").write_text(json.dumps({"reports": [
            {"nodeid": node_a, "when": "call", "outcome": "failed"},
            {"nodeid": node_a, "when": "teardown", "outcome": "failed"},
            {"nodeid": node_b, "when": "setup", "outcome": "failed"},
        ]}))
        (directory / "command.log").write_bytes(b"HUGE ORIGINAL PYTEST OUTPUT\n" * 10000)
        assert profiles.run_profile(failed, "focused") == 7
        console = capsys.readouterr().out
        assert f"FAILED {node_a} [call, teardown]" in console
        assert f"FAILED {node_b} [setup]" in console
        assert "HUGE ORIGINAL" not in console and len(console) < 1000
        assert (directory / "command.log").read_bytes() == b"HUGE ORIGINAL PYTEST OUTPUT\n" * 10000
        assert (failed / profiles.DIRECTORY / "focused.log").read_bytes() == stdout

        stdout = b"UNBOUNDED worker startup noise\n" * 10000 + b"ValueError: native runtime missing\n"
        no_result = tmp_path / "no-result"
        assert profiles.run_profile(no_result, "focused") == 7
        console = capsys.readouterr().out
        assert "ValueError: native runtime missing" in console and len(console) < 1000
        assert (no_result / profiles.DIRECTORY / "focused.log").read_bytes() == stdout

        half = tmp_path / "half-group"
        first = half / ".tmp_verify/ci_public_full/public-focused/result.json"
        first.parent.mkdir(parents=True)
        first.write_text(json.dumps(result))
        stdout = json.dumps({"status": "BLOCKED", "error": "stage scratch could not be prepared"}).encode()
        assert profiles.run_profile(half, "full") == 7
        console = capsys.readouterr().out
        assert "public-focused PASS" in console
        assert "no result: public-comprehensive. stage scratch could not be prepared" in console
        assert (half / profiles.DIRECTORY / "full.log").read_bytes() == stdout


def exercise_ci_feedback_layers(root, tmp_path, monkeypatch):
    import re
    import sys
    from sciplot_core.verification import ci_feedback, public_stage
    from sciplot_core.verification.changed import build_changed_verification_plan
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
    combined = [*paths, "tests/test_source_numeric_encodings.py", "tests/test_plot_data_exports.py"]
    leaf_pair = ci_feedback.ci_feedback_plan(combined, root, event="pull_request")
    local_feedback = build_changed_verification_plan(combined, repo_root=root)["public_feedback"]
    assert leaf_pair["layer"] == "affected" and leaf_pair["targets"] == local_feedback["targets"]
    assert "tests/test_plot_data_exports.py" in leaf_pair["targets"]
    assert ci_feedback.ci_feedback_plan([*combined, "tests/test_private_corpus_preflight.py"], root)["layer"] == "full"
    assert ci_feedback.ci_feedback_plan(["README.md"], root, ref="refs/heads/main")["source_only"] is True
    assert ci_feedback.ci_feedback_plan(["README.md"], root, ref="refs/heads/integration/candidate")["source_only"] is False
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

    for path in ("src/sciplot_core/source_tables/curve_tables.py", "src/sciplot_core/source_tables/heatmap_tables.py"):
        local = build_changed_verification_plan([path], repo_root=root)
        assert not local["unowned_paths"] and local["status"] == "planned"
        assert "tests/test_legacy_core_migration.py" in next(
            check["command"] for check in local["checks"] if check["check_id"] == "pytest_changed_owners"
        )

    workflow = (root / ".github/workflows/minimal-repository.yml").read_text()
    steps = workflow.split("      - name: ")
    upload = next(step for step in steps if step.startswith("Preserve public failure evidence"))
    assert "failure()" in upload and "actions/upload-artifact@v4" in upload
    assert "/public-*/command.log" in upload and "/public-*/reports.json" in upload
    assert "include-hidden-files: true" in upload and "retention-days: 14" in upload
    assert "/source/" not in upload and "/stage-diagnostics/" not in upload
    def extract(fragment):
        body = fragment.split("        run: |\n", 1)[1]
        return dedent(re.match(r"(?: {10}[^\n]*\n)+", body).group(0)).strip()

    route = extract(next(step for step in steps if step.startswith("Seal exact feedback route")))
    join = extract(next(step for step in steps if step.startswith("Require an exact complete feedback result")))
    output = tmp_path / "route-output"
    sha = "a" * 40
    identity = f"123:2:{sha}"
    current = {**os.environ, "GITHUB_OUTPUT": str(output), "GITHUB_RUN_ID": "123",
               "GITHUB_RUN_ATTEMPT": "2", "GITHUB_SHA": sha}
    for admission, ok, source_only, layer, event, expected in (
        ("true", "false", "", "", "push", "reference"),
        ("false", "true", "true", "affected", "push", "source-only"),
        ("false", "true", "false", "affected", "push", "affected"),
        ("false", "true", "false", "affected", "pull_request", "affected"),
        ("false", "true", "false", "affected", "workflow_dispatch", "full"),
        ("false", "true", "false", "full", "push", "full"),
        ("false", "false", "true", "affected", "push", "full"),
        ("false", "true", "false", "unknown", "push", "full"),
    ):
        output.write_text("")
        env = {**current, "SCIPLOT_ADMISSION": admission, "SCIPLOT_FEEDBACK_OK": ok,
               "SCIPLOT_SOURCE_ONLY": source_only, "SCIPLOT_LAYER": layer, "GITHUB_EVENT_NAME": event}
        subprocess.run(["bash", "-e", "-c", route], env=env, check=True)
        assert output.read_text() == f"mode={expected}\nreceipt={identity}:plan\n"

    for mode in ("reference", "source-only", "affected", "full"):
        env = {**current, "SCIPLOT_PLAN_MODE": mode, "SCIPLOT_PLAN_GROUP": "group",
               "SCIPLOT_PLAN_RESULT": "success", "SCIPLOT_PLAN_RECEIPT": f"{identity}:plan",
               "SCIPLOT_PRIMARY_RESULT": "skipped" if mode == "reference" else "success",
               "SCIPLOT_PRIMARY_RECEIPT": "" if mode == "reference" else f"{identity}:public-primary",
               "SCIPLOT_FIRST_RESULT": "success" if mode == "full" else "skipped",
               "SCIPLOT_FIRST_RECEIPT": f"{identity}:public-native-first" if mode == "full" else ""}
        subprocess.run(["bash", "-c", join], env=env, check=True)
        for key, mismatch in (("SCIPLOT_PLAN_MODE", "unknown"), ("SCIPLOT_PLAN_GROUP", ""),
                              ("SCIPLOT_PLAN_RESULT", "failure"), ("SCIPLOT_PLAN_RECEIPT", "foreign"),
                              ("SCIPLOT_PRIMARY_RESULT", "cancelled"),
                              ("SCIPLOT_PRIMARY_RECEIPT", f"123:1:{sha}:public-primary"),
                              ("SCIPLOT_FIRST_RESULT", "skipped" if mode == "full" else "success"),
                              ("SCIPLOT_FIRST_RECEIPT", "foreign-sha-or-role")):
            assert subprocess.run(["bash", "-c", join], env={**env, key: mismatch}, check=False).returncode != 0

    native_job = workflow.split("  public-native-first:\n", 1)[1].split("  runtime-integrity:\n", 1)[0]
    assert "if: ${{ needs.feedback-plan.outputs.mode == 'full' }}" in native_job
    assert "Run reviewed affected public feedback" not in native_job
    primary_job = workflow.split("  public-primary:\n", 1)[1].split("  public-native-first:\n", 1)[0]
    assert "if: ${{ needs.feedback-plan.outputs.mode != 'reference' }}" in primary_job
    conditionals = {step.splitlines()[0]: re.search(r"        if: \$\{\{ (.*?) \}\}", step).group(1)
                    for step in primary_job.split("      - name: ")[1:] if "        if: ${{ " in step}
    def enabled(name, mode, event="push", diagnostic=False):
        expression = conditionals[name]
        for key, value in {"needs.feedback-plan.outputs.mode": mode, "github.event_name": event,
                           "inputs.native_regression_preflight": diagnostic}.items():
            expression = expression.replace(key, repr(value))
        return eval(expression.replace("&&", " and ").replace("||", " or ").replace("== true", "== True"),
                    {"__builtins__": {}}, {})
    for mode in ("source-only", "affected", "full"):
        assert enabled("Run reviewed affected public feedback", mode) is (mode == "affected")
        assert enabled("Run source-only documentation feedback", mode) is (mode == "source-only")
        for name in ("Run focused and comprehensive second shard", "Run shared source contracts", "Run fixture-free lifecycle smoke"):
            assert enabled(name, mode) is (mode == "full")
        for name in ("Run lint gate", "Run scoped static type gate", "Prepare native test runtime",
                     "Verify minimal wheel surface", "Verify source-checkout wrapper bootstrap"):
            assert enabled(name, mode) is (mode != "source-only")
    preflight = "Check known native CI regressions before the public suites"
    assert not enabled(preflight, "full", "push", diagnostic=True)
    assert not enabled(preflight, "full", "workflow_dispatch")
    assert enabled(preflight, "full", "workflow_dispatch", diagnostic=True)

    with monkeypatch.context() as context:
        context.setattr(ci_feedback, "changed_paths", lambda *_args: ["src/sciplot_core/task_contract.py"])
        context.setattr(public_stage, "run_public_stage", lambda *_args, **_kw: pytest.fail("Drift must not run limited stage"))
        with pytest.raises(ValueError, match="eligibility changed"):
            ci_feedback.run_affected(root, "a" * 40, event="push")
    with monkeypatch.context() as context:
        (tmp_path / "README.md").touch()
        context.setattr(ci_feedback, "changed_paths", lambda *_args: ["README.md"])
        def source_only(command, **_options):
            assert "tests/test_documentation_contract.py::test_active_documents_declare_distinct_responsibilities" in command
            assert not any("test_public_stage.py" in argument for argument in command)
            return 0
        context.setattr(ci_feedback.subprocess, "call", source_only)
        assert ci_feedback.run_source_only(tmp_path, "a" * 40, event="push", ref="refs/heads/main") == 0
        with pytest.raises(ValueError, match="eligibility changed"):
            ci_feedback.run_affected(tmp_path, "a" * 40, event="push")
    with monkeypatch.context() as context:
        selected = []
        leaf_path = "src/sciplot_core/source_tables/curve_tables.py"
        leaf = tmp_path / leaf_path
        leaf.parent.mkdir(parents=True)
        leaf.touch()
        context.setattr(ci_feedback, "changed_paths", lambda *_args: [leaf_path])
        def stage(actual_root, output, profile, *, targets=None):
            assert actual_root == tmp_path and profile == "public-affected"
            assert targets and "tests/test_plot_data_exports.py" in targets
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

        def stage(_root, output, profiles):
            stages.extend(profiles)
            output.mkdir(parents=True)
            return [{"status": "PASS"}, {"status": "BLOCKED"}]

        context.setattr(public_stage, "run_public_profiles", stage)
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
