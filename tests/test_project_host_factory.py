"""Manifest and public project hosts reconstruct one exact resource capability set."""
import json

import pytest

from sciplot_core.project_host_factory import project_store
from sciplot_core.project_manifest import _manifest_store, commit_intake_project_manifest, read_intake_project_manifest
from sciplot_core.project_store import FileProjectStore, ProjectConflict, ProjectRecoveryRequired, ResourceRoot, state
from sciplot_core.project_store.adapters import publish_files
from sciplot_core.studio_core.project_command_scope import project_store as public_store


def _project(tmp_path):
    root = tmp_path / "project"
    root.mkdir()
    (root / "source.csv").write_bytes(b"x,y\n1,2\n")
    (root / "plot_request.json").write_text(json.dumps({"input": "source.csv",
        "delivery_output": str(tmp_path / "visible"), "output": str(tmp_path / "run")}))
    (root / "intake_manifest.json").write_text('{"project_slug":"sealed"}')
    return root


def _pending(store, writes, monkeypatch):
    original = state.boundary

    def stop(name):
        if name == "before_projection":
            raise OSError("controlled committed head before projection")
        original(name)

    monkeypatch.setattr(state, "boundary", stop)
    with pytest.raises(OSError, match="controlled committed head"):
        publish_files(store, writes, kind="publish")
    monkeypatch.setattr(state, "boundary", original)


def test_manifest_and_studio_entry_preserve_all_registered_delivery_run_and_snapshot_caps(tmp_path):
    from sciplot_core.studio_core.project_publication_commands import _publication_store

    root = _project(tmp_path)
    assert public_store is project_store
    selected = project_store(root, create_delivery=True, create_output=True, with_snapshot=True)
    selected = FileProjectStore(root, locations={**selected.locations,
        "snapshot": ResourceRoot(selected.locations["snapshot"], ("historic.zip", "sealed.zip"))})
    selected.snapshot(import_legacy=True)
    run_id = next(key for key in selected.locations if key.startswith("run_"))
    publish_files(selected, {"@delivery/figure.pdf": b"saved delivery", f"@{run_id}/result.json": b"saved run",
                             "@snapshot/sealed.zip": b"saved archive", "@snapshot/historic.zip": b"historic archive"}, kind="publish")
    before = selected.snapshot()
    reopened = _manifest_store(root)
    assert reopened.locations == selected.locations
    assert reopened.location_members == selected.location_members
    assert reopened.snapshot() == before
    publication = _publication_store(root)
    assert publication.locations == selected.locations
    assert publication.location_members == selected.location_members
    assert publication.snapshot() == before
    commit_intake_project_manifest(root, {"project_slug": "sealed", "native": "retained"})
    final = public_store(root, with_snapshot=True)
    assert final.locations == selected.locations and final.location_members == selected.location_members
    assert final.read_bytes("@delivery/figure.pdf") == b"saved delivery"
    assert final.read_bytes(f"@{run_id}/result.json") == b"saved run"
    assert final.read_bytes("@snapshot/sealed.zip") == b"saved archive"
    assert read_intake_project_manifest(root)["native"] == "retained"


def test_pending_snapshot_factory_uses_sealed_manifest_without_projection_or_physical_slug(tmp_path, monkeypatch):
    root = _project(tmp_path)
    store = project_store(root, create_delivery=True, create_output=True, with_snapshot=True)
    store.snapshot(import_legacy=True)
    parent_request = (root / "plot_request.json").read_bytes()
    parent_manifest = (root / "intake_manifest.json").read_bytes()
    request = {**json.loads(parent_request), "notes": "new admitted head"}
    manifest = {"project_slug": "admitted-head"}
    _pending(store, {"plot_request.json": json.dumps(request).encode(),
                     "intake_manifest.json": json.dumps(manifest).encode()}, monkeypatch)
    head = (root / ".sciplot_store/head.json").read_bytes()
    for factory in (lambda: project_store(root, with_snapshot=True), lambda: _manifest_store(root)):
        resumed = factory()
        assert resumed.location_members["snapshot"] == ("admitted-head.zip",)
        assert resumed.locations == store.locations
        assert (root / "plot_request.json").read_bytes() == parent_request
        assert (root / "intake_manifest.json").read_bytes() == parent_manifest
        assert (root / ".sciplot_store/head.json").read_bytes() == head
        with pytest.raises(ProjectRecoveryRequired):
            resumed.snapshot()
    with pytest.raises(ProjectRecoveryRequired):
        read_intake_project_manifest(root)
    resumed.recover()
    assert read_intake_project_manifest(root) == manifest


def test_cold_pending_factory_adds_only_local_finite_snapshot_without_recreating_old_roots(tmp_path, monkeypatch):
    root = _project(tmp_path)
    original = FileProjectStore(root)
    original.snapshot(import_legacy=True)
    cold = FileProjectStore.import_bundle(original.export_bundle(tmp_path / "bundle"), tmp_path / "cold")
    root.rename(tmp_path / "offline")
    _pending(cold, {"intake_manifest.json": b'{"project_slug":"cold-head"}'}, monkeypatch)
    manifest_bytes = (cold.root / "intake_manifest.json").read_bytes()
    selected = project_store(cold.root, create_delivery=True, create_output=True, with_snapshot=True)
    assert selected.locations == {"snapshot": cold.root / ".sciplot_resources/snapshot"}
    assert selected.location_members == {"snapshot": ("cold-head.zip",)}
    assert not root.exists() and not (tmp_path / "visible").exists() and not (tmp_path / "run").exists()
    assert (cold.root / "intake_manifest.json").read_bytes() == manifest_bytes


def test_intake_adapter_cannot_hide_an_unadmitted_canonical_request(tmp_path):
    root = tmp_path / "intake"
    root.mkdir()
    commit_intake_project_manifest(root, {"project_slug": "intake"})
    assert read_intake_project_manifest(root) == {"project_slug": "intake"}
    with pytest.raises(ProjectConflict, match="no canonical request"):
        project_store(root)
    (root / "plot_request.json").write_text('{"delivery_output":"unadmitted"}')
    with pytest.raises(ProjectConflict, match="no canonical request"):
        _manifest_store(root)


@pytest.mark.parametrize("member", ["plot_request.json", "delivery"])
def test_uncommitted_host_selection_rejects_aliases_before_allocating_roots(tmp_path, member):
    root = _project(tmp_path)
    if member == "plot_request.json":
        original = root / "request-original.json"
        (root / "plot_request.json").rename(original)
        (root / "plot_request.json").symlink_to(original)
    else:
        original = tmp_path / "foreign"
        original.mkdir()
        alias = tmp_path / "alias"
        alias.symlink_to(original, target_is_directory=True)
        (root / "plot_request.json").write_text(json.dumps({"delivery_output": str(alias)}))
    with pytest.raises(ValueError, match="symlink"):
        project_store(root, create_delivery=True, create_output=True)
    assert not (root / ".sciplot_store").exists()
