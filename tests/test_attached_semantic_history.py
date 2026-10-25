"""Exact namespace transfer and cold history preserve the original sealed bytes."""
from contextlib import nullcontext
import json
from pathlib import Path
import shutil

import pytest

from managed_plot_helpers import patch, request_for_source
from test_project_lifecycle import ManagedBackend
from test_attached_semantic_repository import application
from sciplot_core.foundation.file_hashing import file_sha256
from sciplot_core.project_lifecycle.application import ProjectApplication
from sciplot_core.project_lifecycle.attachment_index import INDEX, OWNER
from sciplot_core.project_lifecycle.capabilities import COMPATIBILITY_CAPABILITIES
from sciplot_core.project_lifecycle.context import repository_scope
from sciplot_core.project_lifecycle.errors import EngineError
from sciplot_core.project_lifecycle.repository import FileProjectRepository
from sciplot_core.project_lifecycle.target_adapter import FilesystemProjectTargets
from sciplot_core.project_store.repository import FileProjectStore
from sciplot_core.project_store.runtime import project_runtime


def standalone():
    repository = FileProjectRepository(lease=lambda _: nullcontext())
    return ProjectApplication(ManagedBackend(), repository, targets=FilesystemProjectTargets(repository),
                              capabilities=COMPATIBILITY_CAPABILITIES)


def old_managed(tmp_path, *, large=False):
    sources = tmp_path / "original-sources"
    sources.mkdir()
    request = request_for_source(sources)
    if large:
        source = Path(request["data_binding"]["data_sources"][0]["path"])
        source.write_text("Time,Signal\ns,V\n" + "".join(f"{number},{number + 1}\n" for number in range(4500)))
        request["data_binding"]["data_sources"][0]["sha256"] = file_sha256(source)
        request["data_binding"]["data_sources"][0]["table_selection"]["data_end_row"] = 4502
        request["template_definition"]["presentation"]["objects"]["axis:x"]["properties"]["axis.limits"] = [0, 4500]
    created = standalone().create(request)
    return sources, Path(created["plot"]), created


def bytes_in(root):
    return {path.relative_to(root).as_posix(): path.read_bytes() for path in root.rglob("*") if path.is_file()}


def test_exact_old_namespace_transfer_preserves_history_and_fences_every_old_writer(tmp_path, monkeypatch):
    sources, old, created = old_managed(tmp_path)
    before = bytes_in(old)
    sibling = old.parent / "unrelated-project"
    sibling.mkdir()
    (sibling / "head.json").write_bytes(b"do not import")
    project = tmp_path / "native-project"
    project.mkdir()
    store = FileProjectStore(project)
    store.snapshot(import_legacy=True)
    app = application()
    with project_runtime(store):
        opened = app.open(old)
    root = Path(opened["plot"])
    assert root != old and opened["plot_id"] == created["plot_id"]
    assert opened["scientific_hash"] == created["scientific_hash"]
    marker = json.loads((old / OWNER).read_bytes())
    backup = Path(marker["history_root"])
    assert {key: data for key, data in bytes_in(backup).items() if key != OWNER} == before
    assert set(bytes_in(old)) == {OWNER, "head.json"}
    assert json.loads((old / "head.json").read_bytes())["kind"] == "sciplot_attached_semantic_redirect"
    assert (old / OWNER).is_file()
    assert all(b"do not import" != store.read_bytes(name) for name in store.snapshot()["files"])
    monkeypatch.setattr(FileProjectRepository, "write", lambda *_: pytest.fail("old writer reused"))
    assert app.open(old)["plot"] == str(root)
    for operation in (lambda: FileProjectRepository().prepare_namespace(old),
                      lambda: FileProjectRepository().publish_content(old / "content/new", b"x", lambda: None)):
        with pytest.raises(EngineError) as caught:
            operation()
        assert caught.value.reason_code == "semantic_attachment_owner_required"
    with pytest.raises(EngineError) as caught:
        app.describe(backup)
    assert caught.value.reason_code == "semantic_attachment_history_read_only"
    assert sources.is_dir()


def test_managed_cold_bundle_rebuilds_after_originals_and_disposable_artifacts_disappear(tmp_path):
    sources, old, created = old_managed(tmp_path, large=True)
    old_bytes = bytes_in(old)
    assert any(name.startswith("content/") for name in old_bytes)
    project = tmp_path / "native-project"
    project.mkdir()
    store = FileProjectStore(project)
    store.snapshot(import_legacy=True)
    app = application()
    with project_runtime(store):
        opened = app.open(old)
    root = Path(opened["plot"])
    styled = app.patch(root, patch(opened, "style-before-move", "style.line.width", "1.2pt", "series:A"))
    snapshot = store.snapshot()
    history = {name: store.read_bytes(name) for name in snapshot["files"] if "/revisions/" in name or "/content/" in name}
    bundle = store.export_bundle(tmp_path / "bundle")
    sources.rename(tmp_path / "source-offline")
    project.rename(tmp_path / "project-offline")
    moved = FileProjectStore.import_bundle(bundle, tmp_path / "relocated")
    shutil.rmtree(moved.root / ".sciplot_store" / "semantic-derived", ignore_errors=True)
    newapp = application()
    with project_runtime(moved):
        cold = newapp.open(moved.root, figure_id=created["plot_id"])
        exported = newapp.export(Path(cold["plot"]))
    assert cold["plot_id"] == created["plot_id"] and cold["revision"] == styled["revision"]
    assert exported["scientific_hash"] == created["scientific_hash"]
    assert {name: moved.read_bytes(name) for name in history} == history
    assert old_bytes["revisions/00000000.json"] == next(data for name, data in history.items() if name.endswith("/revisions/00000000.json"))
    index = json.loads(moved.read_bytes(INDEX))
    attachment = next(iter(index["attachments"].values()))
    assert attachment["origin_root"] == str(old)
    with repository_scope(newapp.repository, capabilities=COMPATIBILITY_CAPABILITIES):
        loaded = newapp.repository.load_head(Path(cold["plot"]))
    assert all(Path(name).is_relative_to(moved.root) for name in loaded["binding"]["scientific_content_files"])
    assert not old.exists() and not sources.exists()
