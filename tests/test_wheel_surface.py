from __future__ import annotations

import subprocess
import sys
import zipfile
from pathlib import Path

import pytest


REPO_ROOT = Path(__file__).resolve().parents[1]
SOURCE_ROOT = REPO_ROOT / "src"
FIRST_PARTY_PACKAGES = ("sciplot_core", "sciplot_gui", "sciplot_recipes")
RETIRED_DISTRIBUTION_PREFIXES = (
    "sciplot_core/canvas",
    "sciplot_core/composition",
    "sciplot_core/promotion",
    "sciplot_core/session_evidence",
    "sciplot_core/codex_jobs.py",
    "sciplot_core/figure_layouts.py",
    "sciplot_core/figure_profiles.py",
    "sciplot_core/figure_workflow.py",
    "sciplot_core/scalar_strip_renderer.py",
    "sciplot_core/workbench_contract.py",
    "sciplot_gui/composition",
    "sciplot_gui/inspectors",
    "sciplot_gui/app.py",
    "sciplot_gui/main_window.py",
    "sciplot_gui/veusz_canvas.py",
)


def assert_wheel_matches_source(wheel_path: Path) -> None:
    source_modules = {
        path.relative_to(SOURCE_ROOT).as_posix()
        for package in FIRST_PARTY_PACKAGES
        for path in (SOURCE_ROOT / package).rglob("*.py")
    }
    with zipfile.ZipFile(wheel_path) as archive:
        members = set(archive.namelist())
    packaged_modules = {
        member
        for member in members
        if member.endswith(".py") and member.partition("/")[0] in FIRST_PARTY_PACKAGES
    }

    missing = sorted(source_modules - packaged_modules)
    orphaned = sorted(packaged_modules - source_modules)
    retired = sorted(
        member for member in members if member.startswith(RETIRED_DISTRIBUTION_PREFIXES)
    )

    assert missing == [], f"source modules missing from wheel: {missing}"
    assert orphaned == [], f"wheel contains modules absent from source: {orphaned}"
    assert retired == [], f"wheel contains retired distribution paths: {retired}"


@pytest.mark.comprehensive
def test_built_wheel_matches_the_current_source_tree(tmp_path: Path) -> None:
    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "pip",
            "wheel",
            ".",
            "--no-deps",
            "--no-build-isolation",
            "--wheel-dir",
            str(tmp_path),
        ],
        cwd=REPO_ROOT,
        check=False,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    wheels = list(tmp_path.glob("*.whl"))
    assert len(wheels) == 1
    assert_wheel_matches_source(wheels[0])


if __name__ == "__main__":
    if len(sys.argv) != 2:
        raise SystemExit("usage: test_wheel_surface.py PATH_TO_WHEEL")
    assert_wheel_matches_source(Path(sys.argv[1]).resolve())
