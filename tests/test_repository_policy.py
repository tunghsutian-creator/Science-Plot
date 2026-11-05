"""Keep the repository gate aligned with the curated documentation policy."""

from __future__ import annotations

import hashlib
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

from sciplot_core.verification.changed import build_changed_verification_plan

ROOT = Path(__file__).resolve().parents[1]


def _git(*args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", *args], cwd=ROOT, capture_output=True, text=True, check=False
    )


@pytest.mark.focused
def test_curated_docs_are_allowed_by_repository_policy() -> None:
    tracked = _git("ls-files", "--", "docs")
    assert tracked.returncode == 0, tracked.stderr
    paths = tracked.stdout.splitlines()
    assert "docs/INDEPENDENT_ACCEPTANCE.md" in paths
    assert "docs/TASK_CAPABILITY_MEASUREMENTS.md" in paths
    assert "docs/assets/showcase/v2/distributions/replicate-distributions.png" in paths

    ignored = _git("ls-files", "-ci", "--exclude-standard", "--", "docs")
    assert ignored.returncode == 0, ignored.stderr
    assert ignored.stdout == "", "tracked docs must all pass the .gitignore allowlist"


@pytest.mark.focused
@pytest.mark.parametrize(
    "path",
    [
        "docs/private-experiment.md",
        "docs/local-notes/output.csv",
        "docs/assets/private-notes.csv",
        "docs/assets/showcase/private-notes.csv",
        "docs/assets/showcase/v2/curves/private-source.csv",
        "docs/assets/showcase/.tmp_verify/debug.csv",
    ],
)
def test_local_only_documentation_stays_ignored(path: str) -> None:
    ignored = _git("check-ignore", "--no-index", "-q", "--", path)
    assert ignored.returncode == 0, f"local-only path is not ignored: {path}"


@pytest.mark.focused
def test_distribution_policy_changes_select_policy_regressions(tmp_path, monkeypatch) -> None:
    paths = [".github/workflows/minimal-repository.yml", ".gitignore", "tests/test_repository_policy.py"]
    plan = build_changed_verification_plan(paths, repo_root=ROOT)
    assert plan["unowned_paths"] == []
    selected = next(check["command"] for check in plan["checks"] if check["check_id"] == "pytest_changed_owners")
    assert "tests/test_repository_policy.py" in selected

    workflow = (ROOT / ".github/workflows/minimal-repository.yml").read_text()
    assert "  push:\n  pull_request:\n  workflow_dispatch:" in workflow
    steps = workflow.split("      - name: ")
    diagnostic = next(step for step in steps if step.startswith("Check known native CI regressions"))
    assert "steps.native-feedback.outputs.layer != 'affected'" in diagnostic
    assert "inputs.native_regression_preflight" in diagnostic
    dispatch = workflow.split("  workflow_dispatch:", 1)[1].split("\njobs:", 1)[0]
    assert "native_regression_preflight:" in dispatch
    assert "type: boolean" in dispatch and "default: false" in dispatch
    for name, command in (
        ("Run reviewed public focused behavior", "ci_public_reuse focused"),
        ("Run reviewed public comprehensive behavior", "ci_public_reuse comprehensive"),
        ("Run scoped static type gate", "python3 -m mypy --platform darwin"),
        ("Run readiness check", "skill/scripts/sciplot doctor --json"),
        ("Run fixture-free lifecycle smoke", "skill/scripts/sciplot smoke --out"),
    ):
        step = next(step for step in steps if step.startswith(name))
        assert command in step
        if name.startswith("Run reviewed public "):
            assert "&& steps.public-reference.outputs.reuse != 'true' }}" in step
        if name == "Run scoped static type gate":
            assert "        if:" not in step, "Configured static gates must run in every layer"
        else:
            assert "steps.native-feedback.outcome != 'success'" in step
            assert "steps.native-feedback.outputs.layer != 'affected'" in step
            assert "github.event_name == 'workflow_dispatch'" in step
    from sciplot_core.verification.ci_feedback import NATIVE_PREFIX, NATIVE_EXPECTED, native_preflight_plan
    manifest = json.loads((ROOT / "src/sciplot_core/verification/input_scope_manifest.json").read_text())
    assert len(NATIVE_PREFIX) == 7 and len(NATIVE_EXPECTED) == 12
    assert hashlib.sha256(json.dumps(list(NATIVE_PREFIX)).encode()).hexdigest() == "d474f3c738239b2e6915d6c7cd4baebb85fd67bd204065274d311336a7a38bbd"
    assert hashlib.sha256(json.dumps(sorted(NATIVE_EXPECTED)).encode()).hexdigest() == "023aeb6e64fc66570b6ad3abbcd6c66fbaa414c14fc902c356a65fb3f2115232"
    assert NATIVE_EXPECTED <= set(manifest["scopes"]["public"]) & set(manifest["tiers"]["comprehensive"])
    assert "required_prefix = list(NATIVE_PREFIX)" in diagnostic
    assert "expected = set(NATIVE_EXPECTED)" in diagnostic
    assert "needs: feedback-plan" in workflow
    assert "if: ${{ always() && !cancelled() }}" in workflow
    assert "needs.feedback-plan.outputs.group || format('unplanned-{0}-{1}', github.run_id, github.run_attempt)" in workflow
    assert "cancel-in-progress: ${{ github.event_name == 'push' || github.event_name == 'pull_request' }}" in workflow
    for paths, early in (
        (["README.md"], True), (["docs/DESIGN_PROJECT_LIFECYCLE.md"], False),
        (["docs/unknown-new-prose.md"], True), (["skill/SKILL.md"], True),
        (["src/sciplot_core/studio_core/annotation_operations.py"], True),
        (["src/sciplot_core/verification/public_stage.py"], True),
        (["src/sciplot_core/veusz_runtime.py"], True),
        ([".github/workflows/minimal-repository.yml"], True),
        (["src/sciplot_core/task_contract.py"], True), (["pyproject.toml"], True),
        (["tests/test_attached_edit_checkpoints_native.py"], True),
        (["src/sciplot_core/unknown.py"], True), ([], True),
        (["README.md", "src/sciplot_core/unknown.py"], True),
    ):
        decision = native_preflight_plan(paths, ROOT)
        assert decision["native_preflight"] is early, (paths, decision)
    key_step = next(step for step in steps if step.startswith("Isolate future obsolete-run scheduling"))
    source = key_step.split("          python3 - <<'PY'\n", 1)[1].split("\n          PY", 1)[0]
    compiled = compile("\n".join(line[10:] for line in source.splitlines()), "workflow-concurrency-key", "exec")
    output = tmp_path / "key-output"
    def group(**changes):
        values = dict(GITHUB_REPOSITORY="owner/repo", GITHUB_WORKFLOW_REF="owner/repo/.github/workflows/minimal.yml@refs/heads/main",
                      GITHUB_EVENT_NAME="push", GITHUB_REF="refs/heads/main", SCIPLOT_PULL_REQUEST="", GITHUB_RUN_ID="1", GITHUB_RUN_ATTEMPT="1")
        for key, value in {**values, **changes, "GITHUB_OUTPUT": str(output)}.items():
            monkeypatch.setenv(key, value)
        output.write_text("")
        exec(compiled, {})
        return output.read_text().strip()
    assert group(GITHUB_RUN_ID="1") == group(GITHUB_RUN_ID="2")
    assert group(GITHUB_REF="refs/heads/Main") != group()
    assert group(GITHUB_EVENT_NAME="pull_request", SCIPLOT_PULL_REQUEST="7", GITHUB_RUN_ID="1") == group(GITHUB_EVENT_NAME="pull_request", SCIPLOT_PULL_REQUEST="7", GITHUB_RUN_ID="2")
    for changes in ({"GITHUB_EVENT_NAME": "pull_request", "SCIPLOT_PULL_REQUEST": "7"}, {"GITHUB_WORKFLOW_REF": "other"},
                    {"GITHUB_REF": "refs/heads/other"}, {"GITHUB_REPOSITORY": "owner/other"}):
        assert group(**changes) != group()
    assert group(GITHUB_EVENT_NAME="workflow_dispatch", GITHUB_RUN_ID="1") != group(GITHUB_EVENT_NAME="workflow_dispatch", GITHUB_RUN_ID="2")
    assert group(GITHUB_EVENT_NAME="workflow_dispatch", GITHUB_RUN_ATTEMPT="1") != group(GITHUB_EVENT_NAME="workflow_dispatch", GITHUB_RUN_ATTEMPT="2")
    with pytest.raises(SystemExit):
        group(GITHUB_EVENT_NAME="pull_request", SCIPLOT_PULL_REQUEST="")
    key_job = workflow.split("  feedback-plan:", 1)[1].split("  runtime-integrity:", 1)[0]
    assert "checkout" not in key_job and "pip install" not in key_job
    validation = next(step for step in steps if step.startswith("Require a valid scheduling plan"))
    command = validation.split("        run: ", 1)[1].splitlines()[0]
    for outcome, group_value, expected_exit in (("success", "sciplot-key", 0), ("failure", "sciplot-key", 1), ("success", "", 1)):
        result = subprocess.run(["bash", "-c", command], env={**os.environ, "SCIPLOT_PLAN_RESULT": outcome, "SCIPLOT_PLAN_GROUP": group_value}, check=False)
        assert result.returncode == expected_exit
    ci_plan = build_changed_verification_plan(["src/sciplot_core/verification/ci_feedback.py"], repo_root=ROOT)
    ci_targets = next(check["command"] for check in ci_plan["checks"] if check["check_id"] == "pytest_changed_owners")
    assert "tests/test_repository_policy.py" in ci_targets
    assert "tests/test_iso_timestamps.py::test_first_party_contract_timestamp_implementation_has_one_owner" in ci_targets
    timestamp_plan = build_changed_verification_plan(["tests/test_iso_timestamps.py"], repo_root=ROOT)
    assert timestamp_plan["unowned_paths"] == []
    timestamp_targets = next(check["command"] for check in timestamp_plan["checks"] if check["check_id"] == "pytest_changed_owners")
    assert "tests/test_iso_timestamps.py" in timestamp_targets
    from sciplot_core.verification import ci_feedback
    for base in ("", "0" * 40, "--all", "HEAD~1"):
        with pytest.raises(ValueError):
            ci_feedback.changed_paths(ROOT, base)
    with monkeypatch.context() as context:
        context.setenv("GIT_DIR", str(tmp_path / "foreign-git"))
        with pytest.raises(ValueError, match="Git namespace"):
            ci_feedback.changed_paths(ROOT, "a" * 40)
    with monkeypatch.context() as context:
        calls = []
        def failed_fetch(command, **kwargs):
            calls.append(command)
            assert kwargs["timeout"] == 30
            return subprocess.CompletedProcess(command, 1, "", "unavailable")
        context.setattr(ci_feedback.subprocess, "run", failed_fetch)
        with pytest.raises(ValueError):
            ci_feedback.changed_paths(ROOT, "a" * 40)
        assert [command[1] for command in calls] == ["cat-file", "fetch"]
    with monkeypatch.context() as context:
        def diff(command, **kwargs):
            return subprocess.CompletedProcess(command, 0, "docs/DESIGN_PROJECT_LIFECYCLE.md\0src/sciplot_core/task_contract.py\0" if command[1] == "diff" else "", "")
        context.setattr(ci_feedback.subprocess, "run", diff)
        changed = ci_feedback.changed_paths(ROOT, "b" * 40)
        assert changed == ["docs/DESIGN_PROJECT_LIFECYCLE.md", "src/sciplot_core/task_contract.py"]
        assert native_preflight_plan(changed, ROOT)["native_preflight"]
    with monkeypatch.context() as context:
        context.setattr(sys, "argv", ["ci_feedback", "--base", ""])
        native_output = tmp_path / "native-output"
        context.setenv("GITHUB_OUTPUT", str(native_output))
        assert ci_feedback.main() == 0
        assert native_output.read_text() == "preflight=true\nlayer=full\n"
    from ci_public_reference_support import exercise_collector, exercise_fresh_origin, exercise_head_source, exercise_profile_stage_route, exercise_public_reference, exercise_wire
    exercise_public_reference(ROOT, tmp_path, monkeypatch)
    exercise_collector(ROOT, tmp_path, monkeypatch)
    exercise_wire(tmp_path, monkeypatch)
    exercise_head_source(tmp_path)
    exercise_fresh_origin(tmp_path, monkeypatch)
    exercise_profile_stage_route(tmp_path / "profile-routes", monkeypatch)
    from ci_public_reference_support import exercise_ci_feedback_layers
    exercise_ci_feedback_layers(ROOT, tmp_path, monkeypatch)
