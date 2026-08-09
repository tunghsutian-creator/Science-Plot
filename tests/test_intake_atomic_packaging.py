from __future__ import annotations

import hashlib
import json
import subprocess
import sys
import time
import zipfile
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from threading import Event

import pytest

from sciplot_core.figure_plan import FigureTask, ResolvedFigurePlan
from sciplot_core.foundation.path_names import reserve_unique_directory
from sciplot_core.intake import IncomingFile, IntakeGroupInput
from sciplot_core.intake import packaging
from sciplot_core.intake import session
from sciplot_core.intake.project import project_builder
from sciplot_core import project_manifest
from sciplot_core.studio_core import registry_writes
from sciplot_core.workflow import project_state


def _group(content: bytes) -> list[IntakeGroupInput]:
    return [
        IntakeGroupInput(
            sample="sample",
            files=(IncomingFile(name="measurement.csv", content=content),),
        )
    ]


def _build_project(output_root: Path, content: bytes) -> dict[str, object]:
    return project_builder.create_intake_project(
        project_name="same project",
        data_type_id="mechanical",
        experiment_type_id="unknown_mechanical",
        groups=_group(content),
        output_root=output_root,
        studio_preparer=lambda _project_dir: {},
    )


def test_initial_project_plan_matches_in_canonical_mirror_and_zip(
    tmp_path: Path,
) -> None:
    task = FigureTask(
        figure_id="figure_a",
        order=1,
        title="Figure A",
        x_metric="x",
        y_metric="y",
        template="point_line",
        artifact_stem="figure_a",
        document_stem="figure_a",
    )
    plan = ResolvedFigurePlan.planned(
        rule_id="test_rule",
        selection_policy="test_selection",
        primary_figure_id=task.figure_id,
        tasks=(task,),
    )

    def prepare(project_dir: Path) -> dict[str, object]:
        request_path = project_dir / "plot_request.json"
        request = json.loads(request_path.read_text(encoding="utf-8"))
        request["resolved_figure_plan"] = plan.to_payload()
        request_path.write_text(json.dumps(request), encoding="utf-8")
        return {"studio": {"resolved_figure_plan": plan.to_payload()}}

    created = project_builder.create_intake_project(
        project_name="planned project",
        data_type_id="mechanical",
        experiment_type_id="unknown_mechanical",
        groups=_group(b"x,y\n0,1\n"),
        output_root=tmp_path / "projects",
        studio_preparer=prepare,
    )
    project_dir = Path(str(created["project_dir"]))
    canonical = json.loads(
        (project_dir / "intake_manifest.json").read_text(encoding="utf-8")
    )
    mirror = json.loads(
        next(project_dir.glob("*.sciplot.json")).read_text(encoding="utf-8")
    )
    with zipfile.ZipFile(Path(str(created["zip_path"]))) as archive:
        archived = json.loads(archive.read(f"{project_dir.name}/intake_manifest.json"))

    for payload in (canonical, mirror, archived):
        assert payload["resolved_figure_plan"] == plan.to_payload()
        assert "figure_outcomes" not in payload


def test_studio_run_projection_set_and_pop_reaches_canonical_mirror_and_zip(
    tmp_path: Path,
) -> None:
    project_dir = tmp_path / "project"
    project_dir.mkdir()
    mirror_path = project_dir / "project.sciplot.json"
    project_manifest.commit_intake_project_manifest(
        project_dir,
        {
            "kind": "sciplot_intake_project",
            "version": 1,
            "project_slug": "project",
            "studio": {},
        },
        mirror_path=mirror_path,
    )
    task = FigureTask(
        figure_id="figure_a",
        order=1,
        title="Figure A",
        x_metric="x",
        y_metric="y",
        template="point_line",
        artifact_stem="figure_a",
        document_stem="figure_a",
    )
    plan = ResolvedFigurePlan.planned(
        rule_id="test_rule",
        selection_policy="test_selection",
        primary_figure_id=task.figure_id,
        tasks=(task,),
    )
    outcomes = [outcome.to_payload() for outcome in plan.outcomes]
    run_manifest = {
        "created_at": "2026-07-30T00:00:00+00:00",
        "output": str(project_dir / "runs" / "studio_001"),
        "figures": [],
        "qa": {},
        "resolved_figure_plan": plan.to_payload(),
        "figure_outcomes": outcomes,
    }
    studio_run = {
        "kind": "sciplot_studio_export_run",
        "output": run_manifest["output"],
        "exports": [{"document": "runs/studio_001/studio/document.vsz"}],
        "resolved_figure_plan": plan.to_payload(),
        "figure_outcomes": outcomes,
    }

    registry_writes._register_studio_run(
        project_dir,
        run_manifest,
        studio_run=studio_run,
    )

    def persisted_payloads() -> tuple[dict[str, object], ...]:
        canonical = json.loads(
            (project_dir / "intake_manifest.json").read_text(encoding="utf-8")
        )
        mirror = json.loads(mirror_path.read_text(encoding="utf-8"))
        with zipfile.ZipFile(tmp_path / "project.zip") as archive:
            archived = json.loads(archive.read("project/intake_manifest.json"))
        return canonical, mirror, archived

    for payload in persisted_payloads():
        assert payload["resolved_figure_plan"] == plan.to_payload()
        assert "figure_outcomes" not in payload
        assert payload["last_run"]["resolved_figure_plan"] == plan.to_payload()
        assert "figure_outcomes" not in payload["last_run"]
        assert payload["studio"]["last_export_run"] == studio_run
        assert payload["studio"]["exports"] == studio_run["exports"]

    legacy_manifest = {
        "created_at": "2026-07-30T00:01:00+00:00",
        "output": str(project_dir / "runs" / "studio_002"),
        "figures": [],
        "qa": {},
    }
    legacy_run = {
        "kind": "sciplot_studio_export_run",
        "output": legacy_manifest["output"],
        "exports": [],
    }
    registry_writes._register_studio_run(
        project_dir,
        legacy_manifest,
        studio_run=legacy_run,
    )

    for payload in persisted_payloads():
        assert "resolved_figure_plan" not in payload
        assert "figure_outcomes" not in payload
        assert "resolved_figure_plan" not in payload["last_run"]
        assert "figure_outcomes" not in payload["last_run"]
        assert payload["studio"]["last_export_run"] == legacy_run


def test_studio_run_registration_propagates_zip_refresh_failure(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    project_dir = tmp_path / "project"
    project_dir.mkdir()
    project_manifest.commit_intake_project_manifest(
        project_dir,
        {
            "kind": "sciplot_intake_project",
            "version": 1,
            "project_slug": "project",
            "studio": {},
        },
        mirror_path=project_dir / "project.sciplot.json",
    )
    zip_path = packaging.refresh_intake_project_zip(project_dir)
    prior_manifest = (project_dir / "intake_manifest.json").read_bytes()
    prior_mirror = (project_dir / "project.sciplot.json").read_bytes()
    prior_zip = zip_path.read_bytes()
    monkeypatch.setattr(
        packaging,
        "_refresh_intake_project_zip_unlocked",
        lambda _project, _manifest: (_ for _ in ()).throw(
            OSError("synthetic ZIP failure")
        ),
    )

    with pytest.raises(OSError, match="synthetic ZIP failure"):
        registry_writes._register_studio_run(
            project_dir,
            {
                "created_at": "2026-07-30T00:00:00+00:00",
                "output": str(project_dir / "runs" / "studio_001"),
                "figures": [],
                "qa": {},
            },
            studio_run={
                "kind": "sciplot_studio_export_run",
                "exports": [],
            },
        )

    assert (project_dir / "intake_manifest.json").read_bytes() == prior_manifest
    assert (project_dir / "project.sciplot.json").read_bytes() == prior_mirror
    assert zip_path.read_bytes() == prior_zip


def test_standalone_studio_run_without_intake_manifest_skips_registry_and_zip(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    project_dir = tmp_path / "standalone_mapping"
    project_dir.mkdir()
    snapshot_called = False

    def fail_if_called(_project: Path, _manifest: dict[str, object]) -> Path:
        nonlocal snapshot_called
        snapshot_called = True
        raise AssertionError("A standalone Studio run must not create an Intake ZIP.")

    monkeypatch.setattr(
        packaging,
        "_refresh_intake_project_zip_unlocked",
        fail_if_called,
    )

    registry_writes._register_studio_run(
        project_dir,
        {
            "created_at": "2026-07-30T00:00:00+00:00",
            "output": str(project_dir / "runs" / "studio_001"),
            "figures": [],
            "qa": {},
        },
        studio_run={
            "kind": "sciplot_studio_export_run",
            "exports": [],
        },
    )

    assert not snapshot_called
    assert not (project_dir / "intake_manifest.json").exists()
    assert not tuple(project_dir.glob("*.sciplot.json"))
    assert not (tmp_path / "standalone_mapping.zip").exists()


def test_unique_directory_reservation_is_atomic_across_threads(
    tmp_path: Path,
) -> None:
    output_root = tmp_path / "projects"

    with ThreadPoolExecutor(max_workers=8) as executor:
        paths = list(
            executor.map(
                lambda _index: reserve_unique_directory(output_root, "same"),
                range(8),
            )
        )

    assert len(set(paths)) == 8
    assert {path.name for path in paths} == {
        "same",
        "same_2",
        "same_3",
        "same_4",
        "same_5",
        "same_6",
        "same_7",
        "same_8",
    }
    assert all(path.is_dir() for path in paths)


def test_same_name_session_files_are_atomically_reserved(
    tmp_path: Path,
) -> None:
    with ThreadPoolExecutor(max_workers=8) as executor:
        paths = list(
            executor.map(
                lambda _index: session._session_path(tmp_path, "same source"),
                range(8),
            )
        )

    assert len(set(paths)) == 8
    assert {path.name for path in paths} == {
        "same_source.json",
        "same_source_2.json",
        "same_source_3.json",
        "same_source_4.json",
        "same_source_5.json",
        "same_source_6.json",
        "same_source_7.json",
        "same_source_8.json",
    }
    assert all(path.is_file() for path in paths)


def test_concurrent_same_name_intake_projects_are_isolated_and_complete(
    tmp_path: Path,
) -> None:
    output_root = tmp_path / "projects"
    contents = [b"x,y\n0,1\n", b"x,y\n0,2\n"]

    with ThreadPoolExecutor(max_workers=2) as executor:
        projects = list(
            executor.map(
                lambda content: _build_project(output_root, content),
                contents,
            )
        )

    project_dirs = [Path(str(project["project_dir"])) for project in projects]
    assert len(set(project_dirs)) == 2
    assert {path.name for path in project_dirs} == {
        "same_project",
        "same_project_2",
    }
    archived_contents = {
        next(path.glob("raw/sample/*.csv")).read_bytes() for path in project_dirs
    }
    assert archived_contents == set(contents)
    for project, project_dir in zip(projects, project_dirs, strict=True):
        zip_path = Path(str(project["zip_path"]))
        assert zip_path.name == f"{project_dir.name}.zip"
        with zipfile.ZipFile(zip_path) as archive:
            assert archive.testzip() is None
            assert all(
                member.startswith(f"{project_dir.name}/")
                for member in archive.namelist()
            )
    assert not list(output_root.glob(".*.sciplot-tmp-*"))


def test_failed_project_packaging_rolls_back_and_retry_reuses_base_name(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    output_root = tmp_path / "projects"
    original_write_zip = project_builder._write_zip

    def fail_zip(_project_dir: Path, _zip_path: Path) -> None:
        raise OSError("synthetic ZIP failure")

    monkeypatch.setattr(project_builder, "_write_zip", fail_zip)
    with pytest.raises(OSError, match="synthetic ZIP failure"):
        _build_project(output_root, b"x,y\n0,1\n")

    assert list(output_root.iterdir()) == []

    monkeypatch.setattr(project_builder, "_write_zip", original_write_zip)
    project = _build_project(output_root, b"x,y\n0,1\n")

    assert Path(str(project["project_dir"])).name == "same_project"
    assert Path(str(project["zip_path"])).is_file()


def test_zip_refresh_is_atomic_idempotent_and_recovers_after_write_failure(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    project_dir = tmp_path / "project"
    project_dir.mkdir()
    payload = project_dir / "payload.txt"
    payload.write_text("first", encoding="utf-8")
    zip_path = tmp_path / "project.zip"

    packaging._write_zip(project_dir, zip_path)
    initial_bytes = zip_path.read_bytes()
    initial_hash = hashlib.sha256(initial_bytes).hexdigest()
    packaging._write_zip(project_dir, zip_path)
    assert hashlib.sha256(zip_path.read_bytes()).hexdigest() == initial_hash

    payload.write_text("second", encoding="utf-8")
    original_write = packaging.zipfile.ZipFile.write

    def fail_write(
        self: zipfile.ZipFile,
        filename: str | Path,
        arcname: str | Path | None = None,
        compress_type: int | None = None,
        compresslevel: int | None = None,
    ) -> None:
        raise OSError("synthetic member failure")

    monkeypatch.setattr(packaging.zipfile.ZipFile, "write", fail_write)
    with pytest.raises(OSError, match="synthetic member failure"):
        packaging._write_zip(project_dir, zip_path)

    assert zip_path.read_bytes() == initial_bytes
    assert not list(tmp_path.glob(".project.zip.sciplot-tmp-*"))

    monkeypatch.setattr(packaging.zipfile.ZipFile, "write", original_write)
    packaging._write_zip(project_dir, zip_path)
    with zipfile.ZipFile(zip_path) as archive:
        assert archive.testzip() is None
        assert archive.read("project/payload.txt") == b"second"
    assert not list(tmp_path.glob(".project.zip.sciplot-tmp-*"))


def test_concurrent_zip_refreshes_publish_only_complete_archives(
    tmp_path: Path,
) -> None:
    project_dir = tmp_path / "project"
    project_dir.mkdir()
    for index in range(20):
        (project_dir / f"payload_{index:02d}.txt").write_text(
            f"value {index}\n",
            encoding="utf-8",
        )
    zip_path = tmp_path / "project.zip"

    with ThreadPoolExecutor(max_workers=8) as executor:
        list(
            executor.map(
                lambda _index: packaging._write_zip(project_dir, zip_path),
                range(16),
            )
        )

    with zipfile.ZipFile(zip_path) as archive:
        assert archive.testzip() is None
        assert len(archive.namelist()) == 20
        assert archive.read("project/payload_19.txt") == b"value 19\n"
    assert not list(tmp_path.glob(".project.zip.sciplot-tmp-*"))


def test_zip_snapshot_cannot_mix_manifest_generations(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    project_dir = tmp_path / "project"
    project_dir.mkdir()
    mirror_path = project_dir / "project.sciplot.json"
    old_manifest = {
        "kind": "sciplot_intake_project",
        "version": 1,
        "state": "old",
    }
    project_manifest.commit_intake_project_manifest(
        project_dir,
        old_manifest,
        mirror_path=mirror_path,
    )
    zip_path = tmp_path / "project.zip"
    canonical_written = Event()
    continue_archive = Event()
    edit_started = Event()
    original_write = packaging.zipfile.ZipFile.write

    def pause_after_canonical(
        self: zipfile.ZipFile,
        filename: str | Path,
        arcname: str | Path | None = None,
        compress_type: int | None = None,
        compresslevel: int | None = None,
    ) -> None:
        original_write(
            self,
            filename,
            arcname=arcname,
            compress_type=compress_type,
            compresslevel=compresslevel,
        )
        if Path(filename).name == "intake_manifest.json":
            canonical_written.set()
            assert continue_archive.wait(timeout=5)

    def edit_manifest() -> None:
        edit_started.set()
        with project_manifest.edit_intake_project_manifest(
            project_dir,
            require_existing=True,
        ) as payload:
            assert payload is not None
            payload["state"] = "new"

    monkeypatch.setattr(packaging.zipfile.ZipFile, "write", pause_after_canonical)
    with ThreadPoolExecutor(max_workers=2) as executor:
        archive_future = executor.submit(packaging._write_zip, project_dir, zip_path)
        assert canonical_written.wait(timeout=5)
        edit_future = executor.submit(edit_manifest)
        assert edit_started.wait(timeout=5)
        try:
            time.sleep(0.05)
            assert not edit_future.done()
        finally:
            continue_archive.set()
        archive_future.result(timeout=5)
        edit_future.result(timeout=5)

    with zipfile.ZipFile(zip_path) as archive:
        canonical = json.loads(
            archive.read("project/intake_manifest.json").decode("utf-8")
        )
        mirror = json.loads(
            archive.read("project/project.sciplot.json").decode("utf-8")
        )
    assert canonical == mirror == old_manifest
    assert project_manifest.read_intake_project_manifest(project_dir) == {
        **old_manifest,
        "state": "new",
    }


def test_project_manifest_commit_keeps_canonical_and_mirror_identical(
    tmp_path: Path,
) -> None:
    project_dir = tmp_path / "project"
    project_dir.mkdir()
    mirror_path = project_dir / "project.sciplot.json"

    paths = project_manifest.commit_intake_project_manifest(
        project_dir,
        {"kind": "sciplot_intake_project", "version": 1, "state": "ready"},
        mirror_path=mirror_path,
    )

    assert paths == (project_dir / "intake_manifest.json", mirror_path)
    assert project_manifest.read_intake_project_manifest(project_dir) == {
        "kind": "sciplot_intake_project",
        "version": 1,
        "state": "ready",
    }
    assert (project_dir / "intake_manifest.json").read_bytes() == (
        mirror_path.read_bytes()
    )


def test_project_manifest_accepts_a_project_local_parent_alias(
    tmp_path: Path,
) -> None:
    real_parent = tmp_path / "real"
    real_parent.mkdir()
    project_dir = real_parent / "project"
    project_dir.mkdir()
    parent_alias = tmp_path / "alias"
    parent_alias.symlink_to(real_parent, target_is_directory=True)
    mirror_alias = parent_alias / "project" / "project.sciplot.json"

    project_manifest.commit_intake_project_manifest(
        project_dir,
        {"kind": "sciplot_intake_project", "version": 1, "state": "ready"},
        mirror_path=mirror_alias,
    )

    assert (project_dir / "intake_manifest.json").is_file()
    assert (project_dir / "project.sciplot.json").is_file()


def test_project_manifest_commit_rolls_back_every_written_copy(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    project_dir = tmp_path / "project"
    project_dir.mkdir()
    mirror_path = project_dir / "project.sciplot.json"
    original = {"kind": "sciplot_intake_project", "version": 1, "state": "old"}
    project_manifest.commit_intake_project_manifest(
        project_dir,
        original,
        mirror_path=mirror_path,
    )
    real_writer = project_manifest.atomic_write_json
    write_count = 0

    def fail_second_write(path: Path, payload: dict[str, object]) -> Path:
        nonlocal write_count
        write_count += 1
        if write_count == 2:
            raise OSError("synthetic mirror write failure")
        return real_writer(path, payload)

    monkeypatch.setattr(project_manifest, "atomic_write_json", fail_second_write)
    with pytest.raises(OSError, match="synthetic mirror write failure"):
        project_manifest.commit_intake_project_manifest(
            project_dir,
            {**original, "state": "new"},
        )

    assert project_manifest.read_intake_project_manifest(project_dir) == original
    assert (project_dir / "intake_manifest.json").read_bytes() == (
        mirror_path.read_bytes()
    )


def test_project_manifest_edit_exception_does_not_commit_mutation(
    tmp_path: Path,
) -> None:
    project_dir = tmp_path / "project"
    project_dir.mkdir()
    mirror_path = project_dir / "project.sciplot.json"
    original = {"kind": "sciplot_intake_project", "version": 1, "state": "old"}
    project_manifest.commit_intake_project_manifest(
        project_dir,
        original,
        mirror_path=mirror_path,
    )

    with pytest.raises(RuntimeError, match="synthetic edit failure"):
        with project_manifest.edit_intake_project_manifest(
            project_dir,
            require_existing=True,
        ) as payload:
            assert payload is not None
            payload["state"] = "new"
            raise RuntimeError("synthetic edit failure")

    assert project_manifest.read_intake_project_manifest(project_dir) == original
    assert (project_dir / "intake_manifest.json").read_bytes() == (
        mirror_path.read_bytes()
    )


def test_concurrent_project_manifest_commits_publish_one_complete_state(
    tmp_path: Path,
) -> None:
    project_dir = tmp_path / "project"
    project_dir.mkdir()
    mirror_path = project_dir / "project.sciplot.json"
    payloads = [
        {"kind": "sciplot_intake_project", "version": 1, "state": state}
        for state in ("first", "second")
    ]

    with ThreadPoolExecutor(max_workers=2) as executor:
        list(
            executor.map(
                lambda payload: project_manifest.commit_intake_project_manifest(
                    project_dir,
                    payload,
                    mirror_path=mirror_path,
                ),
                payloads,
            )
        )

    final = project_manifest.read_intake_project_manifest(project_dir)
    assert final in payloads
    assert (project_dir / "intake_manifest.json").read_bytes() == (
        mirror_path.read_bytes()
    )


def test_project_manifest_edits_preserve_disjoint_cross_process_updates(
    tmp_path: Path,
) -> None:
    project_dir = tmp_path / "project"
    project_dir.mkdir()
    mirror_path = project_dir / "project.sciplot.json"
    project_manifest.commit_intake_project_manifest(
        project_dir,
        {"kind": "sciplot_intake_project", "version": 1},
        mirror_path=mirror_path,
    )
    started_path = tmp_path / "child_started"
    child_code = (
        "import sys\n"
        "from pathlib import Path\n"
        "from sciplot_core.project_manifest import edit_intake_project_manifest\n"
        "project = Path(sys.argv[1])\n"
        "Path(sys.argv[2]).write_text('started', encoding='utf-8')\n"
        "with edit_intake_project_manifest(project, require_existing=True) as payload:\n"
        "    payload['child_update'] = True\n"
    )
    process: subprocess.Popen[str] | None = None
    try:
        with project_manifest.edit_intake_project_manifest(
            project_dir,
            require_existing=True,
        ) as payload:
            assert payload is not None
            payload["parent_update"] = True
            process = subprocess.Popen(
                [
                    sys.executable,
                    "-c",
                    child_code,
                    str(project_dir),
                    str(started_path),
                ],
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
            )
            deadline = time.monotonic() + 5.0
            while not started_path.exists() and time.monotonic() < deadline:
                time.sleep(0.01)
            assert started_path.is_file()
            assert process.poll() is None
            assert project_manifest.read_intake_project_manifest(project_dir) == {
                "kind": "sciplot_intake_project",
                "version": 1,
            }
        _stdout, stderr = process.communicate(timeout=5)
        assert process.returncode == 0, stderr
    finally:
        if process is not None and process.poll() is None:
            process.kill()
            process.communicate()

    final = project_manifest.read_intake_project_manifest(project_dir)
    assert final == {
        "kind": "sciplot_intake_project",
        "version": 1,
        "parent_update": True,
        "child_update": True,
    }
    assert (project_dir / "intake_manifest.json").read_bytes() == (
        mirror_path.read_bytes()
    )


def test_project_manifest_commit_rejects_symlink_backed_mirror(
    tmp_path: Path,
) -> None:
    project_dir = tmp_path / "project"
    project_dir.mkdir()
    outside = tmp_path / "outside.sciplot.json"
    outside.write_text('{"state": "outside"}', encoding="utf-8")
    mirror_path = project_dir / "project.sciplot.json"
    mirror_path.symlink_to(outside)

    with pytest.raises(PermissionError, match="symlink-backed"):
        project_manifest.commit_intake_project_manifest(
            project_dir,
            {"kind": "sciplot_intake_project", "version": 1, "state": "new"},
        )

    assert outside.read_text(encoding="utf-8") == '{"state": "outside"}'
    assert not (project_dir / "intake_manifest.json").exists()


def test_zip_replace_failure_keeps_last_good_archive_and_cleans_stage(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    project_dir = tmp_path / "project"
    project_dir.mkdir()
    payload = project_dir / "payload.txt"
    payload.write_text("first", encoding="utf-8")
    zip_path = tmp_path / "project.zip"
    packaging._write_zip(project_dir, zip_path)
    initial_bytes = zip_path.read_bytes()

    payload.write_text("second", encoding="utf-8")

    def fail_replace(_source: Path, _destination: Path) -> None:
        raise OSError("synthetic replace failure")

    monkeypatch.setattr(packaging.os, "replace", fail_replace)
    with pytest.raises(OSError, match="synthetic replace failure"):
        packaging._write_zip(project_dir, zip_path)

    assert zip_path.read_bytes() == initial_bytes
    assert not list(tmp_path.glob(".project.zip.sciplot-tmp-*"))


def test_studio_package_preparation_failure_is_explicit(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    project_dir = tmp_path / "project"
    project_dir.mkdir()
    convergence_calls: list[Path] = []

    def fail_prepare(
        command: list[str],
        **_kwargs: object,
    ) -> subprocess.CompletedProcess[str]:
        raise subprocess.CalledProcessError(
            returncode=7,
            cmd=command,
            stderr="synthetic Studio preparation failure",
        )

    def record_convergence(path: str | Path, **_kwargs: object) -> dict[str, object]:
        convergence_calls.append(Path(path))
        return {}

    monkeypatch.setattr(packaging.subprocess, "run", fail_prepare)
    monkeypatch.setattr(
        packaging,
        "converge_intake_project_launchers",
        record_convergence,
    )

    with pytest.raises(
        RuntimeError,
        match="synthetic Studio preparation failure",
    ):
        packaging._prepare_studio_project_package(project_dir)

    assert convergence_calls == []


def test_failed_studio_preparation_does_not_refresh_project_zip(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    project_dir = tmp_path / "project"
    project_dir.mkdir()
    request_path = project_dir / "project.sciplot.json"
    request_path.write_text('{"state": "old"}', encoding="utf-8")
    (project_dir / "intake_manifest.json").write_text(
        '{"state": "old"}',
        encoding="utf-8",
    )
    zip_path = tmp_path / "project.zip"
    zip_path.write_bytes(b"last complete archive")
    refresh_calls: list[Path] = []

    def fail_prepare(_project_dir: Path) -> None:
        raise RuntimeError("synthetic Studio preparation failure")

    def record_refresh(path: str | Path) -> Path:
        refresh_calls.append(Path(path))
        return zip_path

    monkeypatch.setattr(packaging, "_prepare_studio_project_package", fail_prepare)
    monkeypatch.setattr(packaging, "refresh_intake_project_zip", record_refresh)

    with pytest.raises(
        RuntimeError,
        match="synthetic Studio preparation failure",
    ):
        project_state._update_intake_project_after_run(
            request_path,
            {
                "created_at": "2026-07-30T00:00:00+00:00",
                "output": str(project_dir / "runs" / "run_001"),
                "figures": [],
            },
        )

    assert refresh_calls == []
    assert zip_path.read_bytes() == b"last complete archive"
    assert (project_dir / "intake_manifest.json").read_text(
        encoding="utf-8"
    ) == '{"state": "old"}'
    assert request_path.read_text(encoding="utf-8") == '{"state": "old"}'


def test_run_state_is_committed_after_studio_preparation(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    project_dir = tmp_path / "project"
    project_dir.mkdir()
    request_path = project_dir / "plot_request.json"
    request_path.write_text("{}", encoding="utf-8")
    mirror_path = project_dir / "project.sciplot.json"
    project_manifest.commit_intake_project_manifest(
        project_dir,
        {"kind": "sciplot_intake_project", "version": 1, "state": "old"},
        mirror_path=mirror_path,
    )
    events: list[str] = []

    def prepare(path: Path) -> None:
        events.append("prepare")
        payload = project_manifest.read_intake_project_manifest(path)
        assert payload is not None
        payload["studio"] = {"status": "prepared"}
        project_manifest.commit_intake_project_manifest(path, payload)

    def refresh(path: str | Path) -> Path:
        events.append("refresh")
        return Path(path).parent / "project.zip"

    monkeypatch.setattr(packaging, "_prepare_studio_project_package", prepare)
    monkeypatch.setattr(packaging, "refresh_intake_project_zip", refresh)

    project_state._update_intake_project_after_run(
        request_path,
        {
            "created_at": "2026-07-30T00:00:00+00:00",
            "output": str(project_dir / "runs" / "run_001"),
            "figures": ["figure.pdf"],
        },
    )

    final = project_manifest.read_intake_project_manifest(project_dir)
    assert final is not None
    assert final["studio"] == {"status": "prepared"}
    assert final["last_run"]["figures"] == ["figure.pdf"]
    assert events == ["prepare", "refresh"]
    assert (project_dir / "intake_manifest.json").read_bytes() == (
        mirror_path.read_bytes()
    )
