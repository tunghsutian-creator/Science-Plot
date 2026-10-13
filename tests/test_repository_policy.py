"""Keep the repository gate aligned with the curated documentation policy."""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

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
