"""Manifest mirrors and complete ZIP candidates share the generation head."""

import json
from io import BytesIO
from zipfile import ZipFile

from sciplot_core.project_manifest import (
    _manifest_store,
    commit_intake_project_manifest,
    stage_intake_project_manifest,
)
from sciplot_core.project_store import FileProjectStore
from sciplot_core.project_store.adapters import publish_files


def test_staging_zip_uses_pending_whole_project_without_installing(tmp_path):
    root = tmp_path / "project"
    root.mkdir()
    (root / "source.csv").write_bytes(b"old source")
    (root / "intake_manifest.json").write_text('{"project_slug":"project"}')
    store = _manifest_store(root, {"project_slug": "project"})
    before = store.snapshot(import_legacy=True)
    payload = {"project_slug": "project", "new_run": "runs/new/result.json"}
    overlay = {"source.csv": b"new source", "runs/new/result.json": b"new result"}
    staged = stage_intake_project_manifest(root, payload, store=store, project_writes=overlay)
    assert store.snapshot()["generation"] == before["generation"]
    assert (root / "source.csv").read_bytes() == b"old source"
    assert not (root / "runs").exists()
    with ZipFile(BytesIO(staged["@snapshot/project.zip"])) as archive:
        assert archive.read("project/source.csv") == b"new source"
        assert archive.read("project/runs/new/result.json") == b"new result"
        assert json.loads(archive.read("project/intake_manifest.json")) == payload
    publish_files(store, {**overlay, **staged}, kind="publish")
    assert (root / "source.csv").read_bytes() == b"new source"
    assert (tmp_path / "project.zip").read_bytes() == staged["@snapshot/project.zip"]


def test_cold_project_adds_only_finite_local_snapshot_capability(tmp_path):
    root = tmp_path / "origin"
    root.mkdir()
    (root / "intake_manifest.json").write_text('{"project_slug":"portable"}')
    store = FileProjectStore(root)
    store.snapshot(import_legacy=True)
    store.export_bundle(tmp_path / "bundle")
    cold = FileProjectStore.import_bundle(tmp_path / "bundle", tmp_path / "cold")
    payload = {"project_slug": "portable", "cold": True}
    commit_intake_project_manifest(cold.root, payload)
    selected = _manifest_store(cold.root, payload)
    staged = stage_intake_project_manifest(cold.root, payload, store=selected)
    publish_files(selected, staged, kind="publish")
    reopened = FileProjectStore(cold.root)
    assert reopened.location_members == {"snapshot": ("portable.zip",)}
    assert reopened.locations["snapshot"] == cold.root / ".sciplot_resources/snapshot"
    assert reopened.read_bytes("@snapshot/portable.zip") == staged["@snapshot/portable.zip"]
    assert not (tmp_path / "portable.zip").exists()
