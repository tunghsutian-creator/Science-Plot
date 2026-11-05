"""Keep the repository gate aligned with the curated documentation policy."""

from __future__ import annotations

import ast
import json
import subprocess
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
def test_distribution_policy_changes_select_policy_regressions() -> None:
    paths = [".github/workflows/minimal-repository.yml", ".gitignore", "tests/test_repository_policy.py"]
    plan = build_changed_verification_plan(paths, repo_root=ROOT)
    assert plan["unowned_paths"] == []
    selected = next(check["command"] for check in plan["checks"] if check["check_id"] == "pytest_changed_owners")
    assert "tests/test_repository_policy.py" in selected

    workflow = (ROOT / ".github/workflows/minimal-repository.yml").read_text()
    assert "  push:\n  pull_request:\n  workflow_dispatch:" in workflow
    steps = workflow.split("      - name: ")
    diagnostic = next(step for step in steps if step.startswith("Check known native CI regressions"))
    assert "if: ${{ github.event_name == 'workflow_dispatch' && inputs.native_regression_preflight }}" in diagnostic
    dispatch = workflow.split("  workflow_dispatch:", 1)[1].split("\njobs:", 1)[0]
    assert "native_regression_preflight:" in dispatch
    assert "type: boolean" in dispatch and "default: false" in dispatch
    for name, command in (
        ("Run reviewed public focused behavior", "--input-scope public-focused"),
        ("Run reviewed public comprehensive behavior", "--profile public-comprehensive"),
        ("Run scoped static type gate", "python3 -m mypy --platform darwin"),
        ("Run readiness check", "skill/scripts/sciplot doctor --json"),
        ("Run fixture-free lifecycle smoke", "skill/scripts/sciplot smoke --out"),
    ):
        step = next(step for step in steps if step.startswith(name))
        assert command in step
        assert "        if:" not in step, f"Required gate became conditional: {name}"
    # Inspect the actual diagnostic selector, not a second copied list of nodes.
    script = diagnostic.split("          python3 - <<'PY'\n", 1)[1].split("\n          PY", 1)[0]
    tree = ast.parse("\n".join(line[10:] for line in script.splitlines()))
    assignments = {node.targets[0].id: node.value for node in tree.body
                   if isinstance(node, ast.Assign) and isinstance(node.targets[0], ast.Name)}
    prefix = ast.literal_eval(assignments["required_prefix"])
    expected_expression = assignments["expected"]
    assert isinstance(expected_expression, ast.BinOp) and isinstance(expected_expression.op, ast.BitOr)
    expected = set(prefix) | ast.literal_eval(expected_expression.right)
    manifest = json.loads((ROOT / "src/sciplot_core/verification/input_scope_manifest.json").read_text())
    assert len(prefix) == 7 and len(expected) == 12
    assert expected <= set(manifest["scopes"]["public"]) & set(manifest["tiers"]["comprehensive"])
