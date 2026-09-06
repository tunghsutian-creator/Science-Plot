from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

import pytest

from sciplot_core._paths import REPO_ROOT, resolve_fixture_path
from sciplot_core.foundation.file_hashing import existing_file_sha256
from sciplot_core.materials_rules import get_rule


def _studio(*arguments: str) -> tuple[dict, str]:
    completed = subprocess.run(
        [
            str(REPO_ROOT / "skill" / "scripts" / "sciplot"),
            "studio",
            *arguments,
            "--json",
        ],
        cwd=REPO_ROOT,
        text=True,
        capture_output=True,
        timeout=120,
        check=False,
    )
    assert completed.returncode == 0, completed.stdout + completed.stderr
    return json.loads(completed.stdout), completed.stderr


@pytest.mark.comprehensive
def test_dsc_public_delivery_continues_project_and_copied_package_exports_independently(
    tmp_path: Path,
) -> None:
    fixture = resolve_fixture_path(str(get_rule("dsc_curve").fixture_path))
    source = tmp_path / "dsc_source.csv"
    shutil.copy2(fixture, source)
    visible = tmp_path / "DSC_SciPlot"
    first, _ = _studio(
        str(source),
        "--out",
        str(visible),
        "--rule",
        "dsc_curve",
        "--export",
        "pdf,tiff_300",
    )
    assert first["studio_run"]["ready_to_use"] is True
    assert first["studio_run"]["delivery_package"]["path"] == str(visible)
    canonical = Path(first["document"])
    project = Path(first["project_dir"])
    original_hash = existing_file_sha256(canonical)
    launcher = visible / "Open_in_Veusz.command"

    opened, _ = _studio(str(launcher), "--prepare-only")
    assert Path(opened["document"]) == canonical
    assert Path(opened["project_dir"]) == project
    second, _ = _studio(str(launcher), "--export", "pdf,tiff_300")
    assert second["studio_run"]["ready_to_use"] is True
    assert Path(second["document"]) == canonical
    assert existing_file_sha256(canonical) == original_hash
    assert second["studio_run"]["delivery_package"]["path"] == str(visible)
    assert second["studio_run"]["delivery_verification"]["passed"] is True
    original_delivery = {
        str(path.relative_to(visible)): path.read_bytes()
        for path in visible.rglob("*")
        if path.is_file()
    }

    copied = tmp_path / "Portable copy"
    shutil.copytree(visible, copied)
    portable, stderr = _studio(str(copied / launcher.name), "--export", "pdf,tiff_300")
    assert "portable Veusz copy" in stderr
    assert portable["mode"] == "vsz"
    assert "studio_run" not in portable
    assert portable["standalone_export"]["export_ready"] is True
    assert Path(portable["document"]).is_relative_to(copied)
    assert existing_file_sha256(canonical) == original_hash
    assert {
        str(path.relative_to(visible)): path.read_bytes()
        for path in visible.rglob("*")
        if path.is_file()
    } == original_delivery
    moved = tmp_path / "Moved portable copy"
    copied.rename(moved)
    reopened, moved_stderr = _studio(str(moved / launcher.name), "--prepare-only")
    assert reopened["mode"] == "vsz"
    assert Path(reopened["document"]).is_relative_to(moved)
    assert "portable Veusz copy" in moved_stderr
