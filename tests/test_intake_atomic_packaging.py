from __future__ import annotations

import hashlib
import zipfile
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest

from sciplot_core.foundation.path_names import reserve_unique_directory
from sciplot_core.intake import IncomingFile, IntakeGroupInput
from sciplot_core.intake import packaging
from sciplot_core.intake import session
from sciplot_core.intake.project import project_builder


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
