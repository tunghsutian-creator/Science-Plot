"""Keep the repository gate aligned with the curated documentation policy."""

from __future__ import annotations

import os
import re
import subprocess
from itertools import product
from pathlib import Path
from textwrap import dedent

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

    workflow = (ROOT / paths[0]).read_text(encoding="utf-8")

    def job(name: str) -> str:
        match = re.search(rf"(?ms)^  {name}:\n(.*?)(?=^  [a-z][a-z-]*:|\Z)", workflow)
        assert match is not None, f"Missing required CI job: {name}"
        return match[1]

    jobs = workflow.split("jobs:\n", 1)[1]
    assert set(re.findall(r"(?m)^  ([a-z][a-z-]*):$", jobs)) == {
        "preflight", "public-behavior", "runtime-integrity",
    }
    preflight, profiles, final = (job(name) for name in (
        "preflight", "public-behavior", "runtime-integrity",
    ))
    assert "Check known native CI regressions before the public suites" in preflight
    assert "    needs: preflight\n" in profiles
    assert "      fail-fast: false\n" in profiles
    assert "        profile: [public-focused, public-comprehensive]\n" in profiles
    assert "include:" not in profiles and "exclude:" not in profiles
    assert "continue-on-error:" not in workflow
    assert "run: python3 -m pytest -q --input-scope public-focused\n" in profiles
    assert "public_stage --profile public-comprehensive --out" in profiles
    assert "--deselect" not in profiles and " -k " not in profiles
    assert "    env: *runtime_environment\n" in profiles
    assert all("    runs-on: ubuntu-24.04\n" in block for block in (preflight, profiles))
    assert re.findall(r"(?m)^      - \*([a-z_]+)$", profiles) == [
        "checkout", "distribution_policy", "compile_owned", "install_toolchain",
        "install_runtime", "verify_qt", "verify_glyphs", "build_helpers", "verify_helpers",
    ]
    expected_conditions = {
        "Run reviewed public focused behavior": "public-focused",
        "Run reviewed public comprehensive behavior": "public-comprehensive",
        "Verify source-checkout wrapper bootstrap": "public-focused",
        "Run readiness check": "public-focused",
        "Run fixture-free lifecycle smoke": "public-focused",
    }
    assert profiles.count("      - name:") == len(expected_conditions)
    for name, profile in expected_conditions.items():
        blocks = re.findall(
            rf"(?ms)^      - name: {re.escape(name)}\n(.*?)(?=^      - |\Z)", profiles,
        )
        assert len(blocks) == 1
        assert f"        if: matrix.profile == '{profile}'\n" in blocks[0]
    assert "run: skill/scripts/sciplot doctor --json\n" in profiles
    assert "run: skill/scripts/sciplot smoke --out .tmp_verify/ci_runtime_smoke --json\n" in profiles
    assert "    if: ${{ always() }}\n" in final
    assert "    needs: [preflight, public-behavior]\n" in final
    assert "PREFLIGHT_RESULT: ${{ needs.preflight.result }}" in final
    assert "PUBLIC_BEHAVIOR_RESULT: ${{ needs['public-behavior'].result }}" in final

    # Exercise the actual final gate, including failed, skipped and cancelled
    # prerequisites. Missing results must never become a green required check.
    assert final.count("        run: |\n") == 1
    script = dedent(final.split("        run: |\n", 1)[1])
    for first, second in product(("success", "failure", "cancelled", "skipped", ""), repeat=2):
        result = subprocess.run(
            ["bash", "-e", "-c", script], cwd=ROOT,
            env={**os.environ, "PREFLIGHT_RESULT": first, "PUBLIC_BEHAVIOR_RESULT": second},
            capture_output=True, text=True, check=False,
        )
        assert (result.returncode == 0) == (first == second == "success")
