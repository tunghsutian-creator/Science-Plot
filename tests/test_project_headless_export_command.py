"""Projects retain headless export and history without producing GUI entrypoints."""

import ast
import json
import os
from pathlib import Path
import subprocess
import sys

import pytest

from sciplot_core.launchers import inspect_project_export_command
from sciplot_core.studio_core.launchers import _write_export_edited_launcher


GUI_NAMES = ("Open_in_SciPlot_Studio.command", "Open_in_Veusz.command", "Open_SciPlot_Project.command")


def _project(tmp_path):
    project = tmp_path / "project"
    (project / "studio").mkdir(parents=True)
    (project / "source").mkdir()
    (project / "source/values.csv").write_bytes(b"x,y\n1,2\n")
    (project / "plot_request.json").write_text(json.dumps({"input": str(project / "source/values.csv")}))
    (project / "studio/document.vsz").write_bytes(b"saved native; query must not render")
    (project / "studio/spec.json").write_text('{"series":[]}')
    return project


def _files(root):
    return {p.relative_to(root).as_posix(): (p.read_bytes(), p.stat().st_mode)
            for p in root.rglob("*") if p.is_file()}


def test_new_command_has_only_readonly_check_and_exact_current_export_routes(tmp_path):
    project = _project(tmp_path)
    command = _write_export_edited_launcher(project)
    record = inspect_project_export_command(project)
    assert record["safe"] is True and record["format"] == "headless_export"
    assert record["role"] == "exact_current_export"
    text = command.read_text()
    assert 'exec "${SCIPLOT_CMD}" project inspect "${PROJECT_DIR}" --json' in text
    assert 'exec "${SCIPLOT_CMD}" studio "${PROJECT_DIR}" --export pdf,tiff_300 --json' in text
    assert "--qt-smoke" not in text
    assert all(not (project / name).exists() for name in GUI_NAMES)
    root = Path(__file__).resolve().parents[1]
    for name in ("launchers.py", "prepare_existing.py", "prepare_generated.py", "source_update_commands.py"):
        tree = ast.parse((root / "src/sciplot_core/studio_core" / name).read_text())
        assert not any(isinstance(n, ast.Name) and n.id in {"_write_studio_launcher", "_write_veusz_launcher"}
                       for n in ast.walk(tree))


def test_check_invokes_actual_headless_query_without_changing_project(tmp_path):
    project = _project(tmp_path)
    command = _write_export_edited_launcher(project)
    before = _files(project)
    root = Path(__file__).resolve().parents[1]
    environment = os.environ.copy()
    environment.update(SCIPLOT_REPO=str(root), SCIPLOT_SOURCE_ROOT=str(root / "src"),
                       SCIPLOT_PYTHON=sys.executable)
    completed = subprocess.run(["/bin/zsh", str(command), "--check"], env=environment,
                               capture_output=True, text=True, timeout=30)
    assert completed.returncode == 0, completed.stdout + completed.stderr
    payload = json.loads(completed.stdout)
    assert payload["status"] == "ok" and payload["readiness_evaluated"] is False
    assert payload["live_gui_state_evaluated"] is False
    assert _files(project) == before and not (project / ".sciplot_store").exists()


def test_legacy_export_and_opaque_gui_files_keep_exact_bytes_and_permissions(tmp_path, monkeypatch):
    project = _project(tmp_path)
    command = _write_export_edited_launcher(project)
    command.write_text(command.read_text().replace(
        '  exec "${SCIPLOT_CMD}" project inspect "${PROJECT_DIR}" --json',
        '  exec "${SCIPLOT_CMD}" studio "${DOCUMENT}" --qt-smoke',
    ))
    command.chmod(0o751)
    for name in GUI_NAMES:
        path = project / name
        path.write_bytes(b"opaque historical GUI script, not current authority")
        path.chmod(0o750)
    before = _files(project)
    read = Path.read_text

    def no_gui_read(path, *args, **kwargs):
        assert path.name not in GUI_NAMES
        return read(path, *args, **kwargs)

    monkeypatch.setattr(Path, "read_text", no_gui_read)
    assert inspect_project_export_command(project)["format"] == "legacy_export_check"
    assert _write_export_edited_launcher(project) == command
    assert _files(project) == before


@pytest.mark.parametrize("change", ["extra-command", "gui-route", "symlink", "not-executable"])
def test_unknown_export_command_is_never_accepted_or_rewritten(tmp_path, change):
    project = _project(tmp_path)
    command = _write_export_edited_launcher(project)
    if change == "extra-command":
        command.write_text(command.read_text() + "echo unregistered command\n")
    elif change == "gui-route":
        command.write_text(command.read_text().replace("--export pdf,tiff_300 --json", ""))
    elif change == "symlink":
        external = tmp_path / "external.command"
        command.rename(external)
        command.symlink_to(external)
    else:
        command.chmod(0o600)
    before = command.read_bytes(), command.stat().st_mode
    assert inspect_project_export_command(project)["safe"] is False
    with pytest.raises(ValueError, match="recognized headless"):
        _write_export_edited_launcher(project)
    assert (command.read_bytes(), command.stat().st_mode) == before
    assert command.is_symlink() is (change == "symlink")


def test_registration_projects_only_new_command_path_and_preserves_historical_files(tmp_path):
    from sciplot_core.project_store import FileProjectStore
    from sciplot_core.studio_core.preparation_candidate import (
        register_prepared_studio_block, studio_preparation_candidate,
    )

    project = _project(tmp_path)
    _write_export_edited_launcher(project)
    for name in GUI_NAMES:
        (project / name).write_bytes(b"historical GUI bytes")
        (project / name).chmod(0o751)
    literal = {"source": str(project / "source/values.csv"), "method": "unchanged science"}
    (project / "intake_manifest.json").write_text(json.dumps({
        "launcher": str(project / GUI_NAMES[0]), "launcher_contract": {"historical": True},
        "transform_ledger": literal,
    }))
    store = FileProjectStore(project)
    before = store.snapshot(import_legacy=True)
    original = _files(project)
    with studio_preparation_candidate(store) as candidate:
        register_prepared_studio_block(candidate.project_dir, {"document": str(candidate.project_dir / "studio/document.vsz")})
        candidate.finalize()
        writes = candidate.capture()
        assert not any(name in writes for name in GUI_NAMES)
        payload = json.loads(candidate.read_member("intake_manifest.json").data)
        assert "launcher" not in payload and "launcher_contract" not in payload
        assert payload["headless_export_command"]["path"] == str(project / "Export_Edited_Veusz.command")
        assert payload["studio"]["document"] == str(project / "studio/document.vsz")
        assert payload["transform_ledger"] == literal
    assert _files(project) == original and store.snapshot()["generation"] == before["generation"]


def test_source_update_does_not_recreate_or_delete_historical_gui_entries(tmp_path):
    from sciplot_core.studio_core.source_update_commands import source_mutation

    project = _project(tmp_path)
    for name in GUI_NAMES:
        (project / name).write_bytes(b"unchanged old GUI bytes")
    before = _files(project)
    candidate = _project(tmp_path / "candidate-parent")
    _write_export_edited_launcher(candidate)
    writes, artifacts = source_mutation(project, candidate, {}, logical_paths_bound=True)
    assert all(name not in writes and "before/" + name not in artifacts for name in GUI_NAMES)
    assert "plot_request.json" in writes and "studio/document.vsz" in writes
    assert _files(project) == before


def test_archive_and_package_status_do_not_treat_old_gui_entries_as_ready_authority(tmp_path):
    from zipfile import ZipFile
    from sciplot_core.intake.packaging import _project_package_info, _write_zip

    project = _project(tmp_path)
    _write_export_edited_launcher(project)
    (project / "project.sciplot.json").write_text('{}')
    for name in GUI_NAMES:
        (project / name).write_bytes(b"historical opaque script")
    archive = project.parent / "project.zip"
    original = _files(project)
    _write_zip(project, archive)
    with ZipFile(archive) as snapshot:
        for name in GUI_NAMES:
            assert snapshot.read("project/" + name) == original[name][0]
    status = _project_package_info(project, project_slug="project")
    assert status["complete"] and status["studio"]["complete"]
    assert "launcher" not in status and "primary_launcher" not in status and "launcher_contract" not in status
    assert "launcher" not in status["studio"] and "veusz_launcher" not in status["studio"]
    assert status["headless_export_command"]["safe"] is True
    assert all(_files(project)[name] == value for name, value in original.items())
    assert "url" not in status["zip"]
    assert "url" not in status["studio"]["documents"][0]
    (project / "studio/document.vsz").unlink()
    assert not _project_package_info(project, project_slug="project")["complete"]


def test_status_keeps_historical_manifest_bytes_without_advertising_http_endpoints(tmp_path):
    from sciplot_core.intake.status import intake_project_status

    project = _project(tmp_path)
    _write_export_edited_launcher(project)
    historical = {"project_slug": "project", "launcher": str(project / GUI_NAMES[0]),
                  "download_url": "/api/historical-only"}
    (project / "intake_manifest.json").write_text(json.dumps(historical))
    run_manifest = project / "runs/run_001/manifest.json"
    run_manifest.parent.mkdir(parents=True)
    run_manifest.write_text('{"kind":"historical_run"}')
    before = _files(project)
    result = intake_project_status(project)
    # Existing records remain historical data, not a fresh callable endpoint.
    assert result["manifest"] == historical
    assert _files(project) == before
    for value in [*result["artifacts"].values(), result["preview_figure"],
                  result["project_package"]["zip"], result["project_package"]["headless_export_command"]]:
        assert "url" not in value and "download_url" not in value
    assert result["artifacts"]["manifest"]["path"] == str(run_manifest)
    assert result["artifacts"]["manifest"]["size_bytes"] == len(before["runs/run_001/manifest.json"][0])
    assert result["preview_figure"]["display_kind"] == "none"
