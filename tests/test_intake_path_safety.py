"""Retained project artifact and ZIP boundaries after browser retirement."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from sciplot_core import intake


def test_project_artifacts_ignore_manifest_supplied_external_roots(
    tmp_path: Path,
) -> None:
    project_dir = tmp_path / "output" / "project"
    project_dir.mkdir(parents=True)
    internal = project_dir / "runs" / "run_001" / "figure.pdf"
    internal.parent.mkdir(parents=True)
    internal.write_bytes(b"%PDF-safe")
    external = tmp_path / "secret.txt"
    external.write_text("secret", encoding="utf-8")
    (project_dir / "intake_manifest.json").write_text(
        json.dumps(
            {
                "project_slug": "project",
                "outputs_dir": str(tmp_path),
                "last_run": {
                    "output": str(tmp_path),
                    "figures": [str(external)],
                },
            }
        ),
        encoding="utf-8",
    )

    assert (
        intake._resolve_project_artifact(
            project_dir,
            str(internal),
        )
        == internal.resolve()
    )
    with pytest.raises(PermissionError, match="outside this SciPlot project"):
        intake._resolve_project_artifact(project_dir, str(external))

    status = intake.intake_project_status(project_dir)
    assert status["outputs_dir"] == str((project_dir / "runs" / "run_001").resolve())
    assert status["figures"] == []
    assert status["preview_figure"]["exists"] is False


def test_project_artifact_paths_reject_symlinks(
    tmp_path: Path,
) -> None:
    project_dir = tmp_path / "output" / "project"
    project_dir.mkdir(parents=True)
    target = project_dir / "artifact.txt"
    target.write_text("artifact", encoding="utf-8")
    symlink = project_dir / "artifact-link.txt"
    symlink.symlink_to(target)

    with pytest.raises(PermissionError):
        intake._resolve_project_artifact(project_dir, str(symlink))


def test_intake_zip_refuses_symlink_entries(tmp_path: Path) -> None:
    project_dir = tmp_path / "output" / "project"
    project_dir.mkdir(parents=True)
    (project_dir / "manifest.json").write_text("{}", encoding="utf-8")
    external = tmp_path / "external.txt"
    external.write_text("external", encoding="utf-8")
    (project_dir / "external-link.txt").symlink_to(external)
    zip_path = project_dir.parent / "project.zip"

    with pytest.raises(PermissionError, match="symlink-backed project entry"):
        intake._write_zip(project_dir, zip_path)

    assert not zip_path.exists()
