"""Keep the repository gate aligned with the curated documentation policy."""

from __future__ import annotations

import hashlib
import json
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
def test_distribution_policy_changes_select_policy_regressions(tmp_path, monkeypatch, capsys) -> None:
    paths = [".github/workflows/minimal-repository.yml", ".github/actions/native-runtime/action.yml",
             ".gitignore", "tests/test_repository_policy.py"]
    plan = build_changed_verification_plan(paths, repo_root=ROOT)
    assert plan["unowned_paths"] == []
    selected = next(check["command"] for check in plan["checks"] if check["check_id"] == "pytest_changed_owners")
    assert "tests/test_repository_policy.py" in selected

    workflow = (ROOT / ".github/workflows/minimal-repository.yml").read_text()
    assert "branches: [main, integration, 'integration/**', release, 'release/**']" in workflow
    assert "tags: ['**']" in workflow and "  pull_request:\n  workflow_dispatch:" in workflow
    steps = workflow.split("      - name: ")
    diagnostic = next(step for step in steps if step.startswith("Check known native CI regressions"))
    assert "github.event_name == 'workflow_dispatch' && inputs.native_regression_preflight == true" in diagnostic
    assert "inputs.native_regression_preflight" in diagnostic
    dispatch = workflow.split("  workflow_dispatch:", 1)[1].split("\njobs:", 1)[0]
    assert "native_regression_preflight:" in dispatch
    assert "type: boolean" in dispatch and "default: false" in dispatch
    for name, command in (
        ("Run focused and comprehensive second shard", "ci_public_profiles primary"),
        ("Run comprehensive first shard", "ci_public_profiles comprehensive-first"),
        ("Run scoped static type gate", "python3 -m mypy --platform darwin"),
        ("Run fixture-free lifecycle smoke", "skill/scripts/sciplot smoke --out"),
    ):
        step = next(step for step in steps if step.startswith(name))
        assert command in step
        if name != "Run comprehensive first shard":
            assert "needs.feedback-plan.outputs.mode == 'full'" in step
    bootstrap = (ROOT / ".github/actions/native-runtime/action.yml").read_text()
    for name in ("Install matching system Python and Qt toolchain", "Verify Qt build and runtime identity",
                 "Verify Chinese glyph fallback in the system Qt runtime", "Build vendored Veusz helpers",
                 "Verify vendored Veusz helpers"):
        assert name in bootstrap
    from sciplot_core.verification.ci_feedback import NATIVE_PREFIX, NATIVE_EXPECTED
    manifest = json.loads((ROOT / "src/sciplot_core/verification/input_scope_manifest.json").read_text())
    assert len(NATIVE_PREFIX) == 7 and len(NATIVE_EXPECTED) == 12
    assert hashlib.sha256(json.dumps(list(NATIVE_PREFIX)).encode()).hexdigest() == "d474f3c738239b2e6915d6c7cd4baebb85fd67bd204065274d311336a7a38bbd"
    assert hashlib.sha256(json.dumps(sorted(NATIVE_EXPECTED)).encode()).hexdigest() == "023aeb6e64fc66570b6ad3abbcd6c66fbaa414c14fc902c356a65fb3f2115232"
    assert NATIVE_EXPECTED <= set(manifest["scopes"]["public"]) & set(manifest["tiers"]["comprehensive"])
    assert "required_prefix = list(NATIVE_PREFIX)" in diagnostic
    assert "expected = set(NATIVE_EXPECTED)" in diagnostic
    assert "needs: feedback-plan" in workflow
    assert "if: ${{ always() && !cancelled() }}" in workflow
    assert "format('{0}-public-primary', needs.feedback-plan.outputs.group)" in workflow
    assert "format('{0}-public-native-first', needs.feedback-plan.outputs.group)" in workflow
    assert "cancel-in-progress: ${{ github.event_name == 'push' || github.event_name == 'pull_request' }}" in workflow
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
    plan_job = workflow.split("  feedback-plan:", 1)[1].split("  public-primary:", 1)[0]
    assert "checkout@v4" in plan_job and "pip install" not in plan_job
    assert "needs: [feedback-plan, public-primary, public-native-first]" in workflow
    ci_plan = build_changed_verification_plan(["src/sciplot_core/verification/ci_feedback.py"], repo_root=ROOT)
    ci_targets = next(check["command"] for check in ci_plan["checks"] if check["check_id"] == "pytest_changed_owners")
    assert "tests/test_repository_policy.py" in ci_targets
    from sciplot_core.verification.source_contracts import CHEAP_SOURCE_TARGETS
    check_ids = [check["check_id"] for check in ci_plan["checks"]]
    assert check_ids == ["ruff_changed_python", "pytest_shared_contracts", "mypy_owned_scope",
                         "pytest_changed_owners", "diff_whitespace"]
    shared = next(check for check in ci_plan["checks"] if check["check_id"] == "pytest_shared_contracts")
    assert shared["status"] == "planned"
    assert shared["command"] == [sys.executable, "-m", "pytest", "-q", *CHEAP_SOURCE_TARGETS]
    timestamp_node = "tests/test_iso_timestamps.py::test_first_party_contract_timestamp_implementation_has_one_owner"
    assert shared["command"].count(timestamp_node) == 1
    policy_node = "tests/test_repository_policy.py::test_distribution_policy_changes_select_policy_regressions"
    assert shared["command"].count(policy_node) == 1
    assert ci_targets[:9] == [
        sys.executable, "-m", "pytest", "-q", "-m", "focused",
        "-p", "sciplot_core.verification.public_stage_selection", "--sciplot-omit-shared-contracts",
    ]
    owner_selectors = set(ci_targets[9:])
    assert timestamp_node not in owner_selectors
    assert not set(CHEAP_SOURCE_TARGETS) & owner_selectors
    declared = {target for owner in ci_plan["owners"] for target in owner["pytest_targets"]}
    covered = {*shared["command"][4:], *owner_selectors}
    assert owner_selectors <= declared
    assert all(any(target == selector or target.startswith(selector + "::") for selector in covered)
               for target in declared)
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
    with monkeypatch.context() as context:
        context.setattr(sys, "argv", ["ci_feedback", "--base", ""])
        native_output = tmp_path / "native-output"
        context.setenv("GITHUB_OUTPUT", str(native_output))
        assert ci_feedback.main() == 0
        assert native_output.read_text() == "layer=full\n"
    from ci_public_profiles_support import exercise_profile_stage_route
    exercise_profile_stage_route(tmp_path / "profile-routes", monkeypatch, capsys)
    from ci_public_profiles_support import exercise_ci_feedback_layers
    exercise_ci_feedback_layers(ROOT, tmp_path, monkeypatch)


@pytest.mark.parametrize("runner_location", ["external", "source", "development"])
def test_native_preflight_places_generated_data_outside_source_before_staging(tmp_path, monkeypatch, runner_location):
    import textwrap
    from sciplot_core.foundation import research_destination

    workflow = (ROOT / ".github/workflows/minimal-repository.yml").read_text()
    step = next(part for part in workflow.split("      - name: ")
                if part.startswith("Check known native CI regressions"))
    script = textwrap.dedent(step.split("python3 - <<'PY'\n", 1)[1].split("\n          PY", 1)[0])
    prefix = script.split("from sciplot_core.verification.ci_feedback import", 1)[0]
    checkout = tmp_path / "checkout"
    (checkout / "src/sciplot_core").mkdir(parents=True)
    (checkout / "pyproject.toml").write_text('[project]\nname = "sciplot-core"\n')
    external = tmp_path / "runner"
    external.mkdir()
    marker = external / "unrelated.txt"
    marker.write_bytes(b"never remove unrelated runner files")
    runner = {"external": external, "source": checkout / ".tmp_verify/runner",
              "development": research_destination.user_cache_path("SciPlot") / "development/runner"}[runner_location]
    monkeypatch.chdir(checkout)
    monkeypatch.setenv("RUNNER_TEMP", str(runner))
    monkeypatch.delenv("PYTEST_ADDOPTS", raising=False)
    namespace = {}
    if runner_location == "external":
        exec(compile(prefix, "<ci-native-preflight-allocation>", "exec"), namespace)
        workspace = namespace["pytest_workspace"]
        assert workspace.parent == external and workspace.is_dir()
        assert namespace["pytest_tmp"] == workspace / "pytest-tmp"
        assert '"--basetemp", str(pytest_tmp)' in script
        assert '(pytest_tmp, {"native-worker.log"})' in script
        assert 'str(output / "pytest-tmp")' not in script
    else:
        with pytest.raises(ValueError, match="New research output cannot"):
            exec(compile(prefix, "<ci-native-preflight-allocation>", "exec"), namespace)
        assert not runner.exists()
    assert marker.read_bytes() == b"never remove unrelated runner files"
    assert not (checkout / ".tmp_verify/ci_known_native_regressions").exists()
