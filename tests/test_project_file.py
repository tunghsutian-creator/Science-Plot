"""Card 20: only the .sciplot document is needed to continue editing."""

from contextlib import closing
import hashlib
import json
import os
from pathlib import Path
import shutil
import stat
import subprocess
import sys
from zipfile import ZipFile

import pytest

from managed_plot_helpers import patch, read_managed_head_and_ir, request_for_source
from sciplot_core.foundation.file_hashing import file_sha256
from sciplot_core.plot_engine.service import PlotService
from sciplot_core.project_lifecycle import project_file
from sciplot_core.project_lifecycle.project_file import (
    ProjectFileSaveUnconfirmed,
    create_project_file,
    open_project_file,
)
from sciplot_core.project_store.errors import ProjectConflict, ProjectStoreError
from sciplot_core.project_store.repository import FileProjectStore


def _identity(store):
    snapshot = store.snapshot()
    history = {name: hashlib.sha256(store.read_bytes(name)).hexdigest()
               for name in snapshot["files"] if "/revisions/" in name}
    commands = [(row["command_id"], row["phase"]) for row in store.commands()]
    return snapshot["project_id"], snapshot["generation"], history, commands


def _new_store(tmp_path):
    path = tmp_path / "store"
    path.mkdir()
    store = FileProjectStore(path)
    generation = store.snapshot(import_legacy=True)["generation"]
    return store, generation


@pytest.mark.comprehensive
def test_native_edit_save_and_cold_reopen_one_project_file(tmp_path):
    original = tmp_path / "original"
    original.mkdir()
    drafts = tmp_path / "workspaces"
    drafts.mkdir()
    output = tmp_path / "研究图 (测试)"
    output.mkdir()
    archive = output / "新料 1.14.sciplot"
    store, _ = _new_store(original)

    request = request_for_source(original)
    source = original / "光谱 1.csv"
    (original / "A.csv").rename(source)
    request["data_binding"]["data_sources"][0]["path"] = str(source)
    original_bytes = source.read_bytes()
    with closing(PlotService()) as service:
        created = service.create(request, project=store.root)
        assert created["ready_to_use"] and created["revision"] == 0, created
    project, first, history, _commands = _identity(store)
    receipt = create_project_file(archive, store, expected_generation=first)
    assert receipt.project_id == project and receipt.generation == first
    assert stat.S_ISREG(archive.lstat().st_mode)
    assert list(output.iterdir()) == [archive]
    shutil.rmtree(original)

    for _ in range(2):
        with open_project_file(archive, workspace_parent=drafts) as session:
            assert _identity(session.store)[:3] == (project, first, history)
            assert [kid.name for kid in session.store.root.parent.iterdir()] == ["project"]
        assert not list(drafts.iterdir())
        assert file_sha256(archive) == receipt.sha256

    with (
        open_project_file(archive, workspace_parent=drafts) as editor,
        open_project_file(archive, workspace_parent=drafts) as stale,
        closing(PlotService()) as service,
    ):
        opened = service.open(editor.store.root)
        edited = service.patch(
            Path(opened["plot"]),
            patch(opened, "visual-line-width", "style.line.width", "1.2pt", "series:A"),
        )
        assert edited["ready_to_use"] and edited["revision"] == 1, edited
        assert edited["scientific_hash"] == created["scientific_hash"]
        project_id, generation, saved_history, commands = _identity(editor.store)
        assert project_id == project and generation != first
        assert len(saved_history) == 2 and saved_history.items() >= history.items()
        with pytest.raises(ProjectConflict, match="captured Store"):
            editor.save(expected_generation=first)
        assert file_sha256(archive) == receipt.sha256
        updated = editor.save(expected_generation=generation)
        assert updated.generation == generation and updated.sha256 == file_sha256(archive)
        with pytest.raises(ProjectConflict, match="changed since open"):
            stale.save(expected_generation=first)
        assert file_sha256(archive) == updated.sha256

    assert not list(drafts.iterdir())
    assert list(output.iterdir()) == [archive]
    drafts.rmdir()
    moved_dir = tmp_path / "relocated (新)"
    moved_dir.mkdir()
    moved = archive.rename(moved_dir / archive.name)
    assert not original.exists() and not drafts.exists() and not list(output.iterdir())
    # Only the archive moves. Use a new process and a previously absent work root.
    workdir = tmp_path / "cold"
    workdir.mkdir()
    env = os.environ.copy()
    env["PYTHONPATH"] = os.pathsep.join(filter(None, [
        str(Path(__file__).parent), env.get("PYTHONPATH"),
    ]))
    expected = json.dumps({
        "identity": [project, generation, saved_history, commands],
        "plot": created["plot_id"],
        "science": created["scientific_hash"],
        "source_bytes": original_bytes.hex(),
    })
    subprocess.run(
        [sys.executable, str(Path(__file__).resolve()), str(moved), str(workdir), expected],
        check=True, env=env,
    )
    assert not list(workdir.iterdir()) and list(moved_dir.iterdir()) == [moved]
    assert file_sha256(moved) == updated.sha256


def _check_relocated(moved, workdir, expected):
    with open_project_file(moved, workspace_parent=workdir) as cold, closing(PlotService()) as service:
        assert json.loads(json.dumps(_identity(cold.store))) == expected["identity"]
        opened = service.open(cold.store.root)
        assert opened["plot_id"] == expected["plot"] and opened["revision"] == 1
        assert opened["scientific_hash"] == expected["science"]
        head, ir = read_managed_head_and_ir(Path(opened["plot"]))
        row, = ir["series"]
        assert (row["id"], row["x"], row["y"]) == ("series:A", [0, 1, 2], [.25, .5, 1])
        source_metadata, = head["document"]["scientific"]["data_sources"]
        assert Path(source_metadata["path"]).name == "光谱 1.csv"
        sources = cold.store.snapshot()["sources"]
        [(source_id, versions)] = sources.items()
        [version] = versions
        restored = cold.store.resolve_source(source_id, version)
        assert restored.is_relative_to(cold.store.root) and restored.read_bytes().hex() == expected["source_bytes"]
        exported = service.export(Path(opened["plot"]))
        assert exported["ready_to_use"] and exported["scientific_hash"] == expected["science"]
        paths = [Path(item["path"]) for item in exported["exports"]]
        assert {".pdf", ".tiff"} <= {path.suffix.lower() for path in paths}
        assert all(path.is_relative_to(cold.store.root) and path.stat().st_size for path in paths)
        workspace = cold.store.root.parent
    assert not workspace.exists()


@pytest.mark.parametrize(
    ("defect", "message"),
    [
        ("duplicate", "duplicate"),
        ("truncated", "incomplete"),
        ("manifest", "member inventory"),
        ("changed_member", "manifest hash"),
    ],
)
def test_bad_archive_has_no_working_project(tmp_path, defect, message):
    store, generation = _new_store(tmp_path)
    archive = tmp_path / "sample.sciplot"
    create_project_file(archive, store, expected_generation=generation)
    original = file_sha256(archive)
    bad = tmp_path / "bad.sciplot"
    work = tmp_path / "work"
    work.mkdir()
    if defect == "truncated":
        bad.write_bytes(archive.read_bytes()[:-50])
    else:
        with ZipFile(archive) as source, ZipFile(bad, "w") as target:
            for name in source.namelist():
                data = source.read(name)
                if defect == "manifest" and name == "bundle.json":
                    metadata = json.loads(data)
                    metadata["members"]["head.json"]["size"] = -1
                    data = json.dumps(metadata).encode()
                elif defect == "changed_member" and name == "store/head.json":
                    data = bytes((data[0] ^ 1,)) + data[1:]
                target.writestr(name, data)
            if defect == "duplicate":
                with pytest.warns(UserWarning, match="Duplicate"):
                    target.writestr("bundle.json", source.read("bundle.json"))
    with pytest.raises(ProjectStoreError, match=message), open_project_file(bad, workspace_parent=work):
        pytest.fail("A malformed archive returned a working Store.")
    assert not list(work.iterdir()) and file_sha256(archive) == original


def test_publication_failure_before_and_after_replace(tmp_path, monkeypatch):
    store, generation = _new_store(tmp_path)
    output = tmp_path / "documents"
    output.mkdir()
    archive = output / "sample.sciplot"
    original = create_project_file(archive, store, expected_generation=generation)
    with pytest.raises(FileExistsError):
        create_project_file(archive, store, expected_generation=generation)
    assert file_sha256(archive) == original.sha256

    replace = project_file.os.replace
    fsync = project_file.os.fsync
    publications = []

    def fail_before(source, target, **kwargs):
        if target == archive.name:
            raise OSError("before replace")
        return replace(source, target, **kwargs)

    def observe_replace(source, target, **kwargs):
        result = replace(source, target, **kwargs)
        if target == archive.name:
            publications.append(target)
        return result

    def fail_after(fd):
        if publications and stat.S_ISDIR(project_file.os.fstat(fd).st_mode):
            raise OSError("after replace")
        return fsync(fd)

    with open_project_file(archive) as session:
        with monkeypatch.context() as local:
            local.setattr(project_file.os, "replace", fail_before)
            with pytest.raises(OSError, match="before replace"):
                session.save(expected_generation=generation)
        assert file_sha256(archive) == original.sha256
        assert list(output.iterdir()) == [archive]
        assert session.store.snapshot()["generation"] == generation
        with monkeypatch.context() as local:
            local.setattr(project_file.os, "replace", observe_replace)
            local.setattr(project_file.os, "fsync", fail_after)
            with pytest.raises(ProjectFileSaveUnconfirmed) as exc:
                session.save(expected_generation=generation)
        receipt = exc.value.receipt
        assert file_sha256(archive) == receipt.sha256
        assert list(output.iterdir()) == [archive]
        with monkeypatch.context() as local:
            local.setattr(project_file.os, "replace", observe_replace)
            assert session.save(expected_generation=generation) == receipt
        assert publications == [archive.name]
    with open_project_file(archive) as reopened:
        assert reopened.store.snapshot()["generation"] == generation


if __name__ == "__main__":
    _check_relocated(Path(sys.argv[1]), Path(sys.argv[2]), json.loads(sys.argv[3]))
