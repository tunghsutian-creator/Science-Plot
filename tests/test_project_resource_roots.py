"""An admitted resource inode cannot be replaced by an empty directory on retry."""

import pytest

from sciplot_core.project_commands import ProjectCommand, ProjectCommands, ProjectMutation
from sciplot_core.project_store import FileProjectStore, ProjectRecoveryRequired, state


def prepared(tmp_path):
    project = tmp_path / "project"
    delivery = tmp_path / "delivery"
    project.mkdir()
    delivery.mkdir()
    (project / "native.vsz").write_bytes(b"old")
    store = FileProjectStore(project, locations={"delivery": delivery})
    before = store.snapshot(import_legacy=True)
    command = ProjectCommand.create("native_export", "root proof", project_id=before["project_id"],
        expected_generation=before["generation"], read_set={"native.vsz": before["files"]["native.vsz"]["sha256"],
            "@delivery/export.pdf": None}, write_set=["@delivery/export.pdf"], request={})
    return store, before, delivery, command


def test_rejected_root_swap_cannot_publish_to_new_empty_root_on_resume(tmp_path, monkeypatch):
    store, _before, delivery, command = prepared(tmp_path)
    original = tmp_path / "original-owned-delivery"
    calls = []
    def swap(name):
        if name == "before_head":
            delivery.rename(original)
            delivery.mkdir()
    monkeypatch.setattr(state, "boundary", swap)
    with pytest.raises(ProjectRecoveryRequired):
        ProjectCommands(store).execute(command, lambda: (calls.append("native") or ProjectMutation(
            {"@delivery/export.pdf": b"already sealed exact export"}, {})))
    monkeypatch.setattr(state, "boundary", lambda _name: None)
    fresh = FileProjectStore(store.root, locations={"delivery": delivery})
    with pytest.raises(ProjectRecoveryRequired, match="identity"):
        ProjectCommands(fresh).resume(command)
    assert list(delivery.iterdir()) == [] and list(original.iterdir()) == []
    assert calls == ["native"]
    delivery.rename(tmp_path / "unrelated-new-empty")
    original.rename(delivery)
    assert ProjectCommands(FileProjectStore(store.root, locations={"delivery": delivery})).resume(command)["phase"] == "complete"
    assert (delivery / "export.pdf").read_bytes() == b"already sealed exact export"
    assert calls == ["native"]


def test_explicit_cold_import_rebinds_only_inventoried_roots_and_resumes_frozen_bytes(tmp_path, monkeypatch):
    store, before, _delivery, command = prepared(tmp_path)
    class Stopped(Exception):
        pass
    def stop(name):
        if name == "before_head":
            raise Stopped()
    monkeypatch.setattr(state, "boundary", stop)
    with pytest.raises(Stopped):
        ProjectCommands(store).execute(command, lambda: ProjectMutation({"@delivery/export.pdf": b"frozen exported bytes"}, {}))
    monkeypatch.setattr(state, "boundary", lambda _name: None)
    store.export_bundle(tmp_path / "bundle")
    cold = FileProjectStore.import_bundle(tmp_path / "bundle", tmp_path / "cold")
    assert cold.snapshot()["generation"] == before["generation"]
    receipt = ProjectCommands(cold).resume(command)
    assert receipt["phase"] == "complete"
    assert receipt["generation_sequence"] == before["sequence"] + 1
    assert cold.commands()[0]["generation_sequence"] == receipt["generation_sequence"]
    assert (cold.locations["delivery"] / "export.pdf").read_bytes() == b"frozen exported bytes"
