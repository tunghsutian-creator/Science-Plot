"""Selected source-tree reads keep complete names, original identities and bytes."""

import os

import pytest

from sciplot_core.foundation.source_tree import source_tree_sha256
from sciplot_core.project_commands import ProjectCommand, ProjectCommands, ProjectMutation, SourceTreeRead
from sciplot_core.project_store import FileProjectStore, ProjectConflict, state
from sciplot_core.project_store.source_trees import observe
import sciplot_core.project_store.source_tree_io as tree_io

from test_project_store import fixture_store


def source_tree(tmp_path):
    source = tmp_path / "selected-source"
    source.mkdir()
    for name in ("a-1.csv", "a/z.csv", "a/sub/inner.csv"):
        path = source / name
        path.parent.mkdir(exist_ok=True, parents=True)
        path.write_bytes(name.encode())
    return source


def reserve_tree(store, before, source, key="tree"):
    tree = {"locator": str(source), "tree_sha256": source_tree_sha256(source)}
    return store.reserve(key, key + "-digest", expected_generation=before["generation"],
        read_set={"studio/document.vsz": before["files"]["studio/document.vsz"]["sha256"]},
        write_set=["studio/document.vsz"], metadata={"kind": "source_update", "source_trees": [tree]})


def test_fd_tree_digest_matches_existing_file_and_directory_schema_without_raw_mutation(tmp_path):
    source = source_tree(tmp_path)
    before = {str(path): (path.stat().st_ino, path.stat().st_mode, path.stat().st_mtime_ns)
              for path in (source, *source.rglob("*"))}
    for selected in (source, source / "a/z.csv"):
        assert observe(str(selected))[0] == source_tree_sha256(selected)
    assert before == {str(path): (path.stat().st_ino, path.stat().st_mode, path.stat().st_mtime_ns)
                      for path in (source, *source.rglob("*"))}


@pytest.mark.parametrize("change", ["file", "empty-directory", "root-swap", "mode", "alias", "fifo"])
def test_final_head_edge_rejects_new_tree_members_or_changed_original_identity(tmp_path, monkeypatch, change):
    store, before = fixture_store(tmp_path)
    source = source_tree(tmp_path)
    reserve_tree(store, before, source)
    def changed(name):
        if name != "before_head":
            return
        if change == "file":
            (source / "late.csv").write_bytes(b"late source")
        elif change == "empty-directory":
            (source / "late-empty").mkdir()
        elif change == "root-swap":
            source.rename(tmp_path / "original-source")
            source.mkdir()
            for original in (tmp_path / "original-source").rglob("*"):
                target = source / original.relative_to(tmp_path / "original-source")
                if original.is_dir():
                    target.mkdir(parents=True, exist_ok=True)
                else:
                    target.parent.mkdir(parents=True, exist_ok=True)
                    target.write_bytes(original.read_bytes())
        elif change == "mode":
            (source / "a/z.csv").chmod(0o600)
        elif change == "alias":
            (source / "alias.csv").symlink_to(source / "a/z.csv")
        else:
            os.mkfifo(source / "pipe")
    monkeypatch.setattr(state, "boundary", changed)
    with pytest.raises(ProjectConflict, match="source tree"):
        store.publish("tree", "tree-digest", writes={"studio/document.vsz": b"must not publish"}, result={})
    assert store.snapshot()["generation"] == before["generation"]
    assert (store.root / "studio/document.vsz").read_bytes() == b"native old"
    assert not store.locations


def test_stage_rechecks_complete_selected_tree_before_freezing_candidate(tmp_path):
    store, before = fixture_store(tmp_path)
    source = source_tree(tmp_path)
    reserve_tree(store, before, source)
    (source / "late.csv").write_bytes(b"new member before stage")
    with pytest.raises(ProjectConflict, match="source tree"):
        store.stage("tree", "tree-digest", writes={"studio/document.vsz": b"candidate"}, result={}, review={})
    assert store.query("tree")["phase"] == "reserved"
    assert not store.query("tree").get("draft")


def test_tree_alias_is_rejected_before_command_admission(tmp_path):
    store, before = fixture_store(tmp_path)
    source = source_tree(tmp_path)
    alias = tmp_path / "selected-alias"
    alias.symlink_to(source, target_is_directory=True)
    with pytest.raises(ProjectConflict, match="source tree"):
        reserve_tree(store, before, alias)
    assert store.query("tree") is None


def test_complete_replay_and_bundle_never_reopen_the_original_tree(tmp_path):
    store, before = fixture_store(tmp_path)
    source = source_tree(tmp_path)
    reserve_tree(store, before, source)
    assert store.publish("tree", "tree-digest", writes={"studio/document.vsz": b"new exact native"}, result={})["phase"] == "complete"
    source.rename(tmp_path / "offline-original")
    assert store.publish("tree", "tree-digest", writes={}, result={})["phase"] == "complete"
    store.export_bundle(tmp_path / "bundle")
    cold = FileProjectStore.import_bundle(tmp_path / "bundle", tmp_path / "cold")
    assert cold.query("tree")["phase"] == "complete"
    assert cold.read_bytes("studio/document.vsz") == b"new exact native"


def test_new_command_maps_preserved_registered_source_tree_after_complete_project_move(tmp_path):
    store, _before = fixture_store(tmp_path)
    literal = store.root / "raw"
    store.export_bundle(tmp_path / "bundle")
    cold = FileProjectStore.import_bundle(tmp_path / "bundle", tmp_path / "cold")
    original_project = store.root
    original_project.rename(tmp_path / "offline-project")
    before = cold.snapshot()
    tree = {"locator": str(literal), "tree_sha256": source_tree_sha256(cold.root / "raw")}
    cold.reserve("moved-tree", "moved-tree-digest", expected_generation=before["generation"],
        read_set={"studio/document.vsz": before["files"]["studio/document.vsz"]["sha256"]},
        write_set=["studio/document.vsz"], metadata={"kind": "source_update", "source_trees": [tree]})
    assert cold.publish("moved-tree", "moved-tree-digest", writes={"studio/document.vsz": b"cold native"}, result={})["phase"] == "complete"
    assert cold.read_bytes("studio/document.vsz") == b"cold native"
    assert cold.snapshot()["locators"][""] == str(original_project)


def test_pending_tree_cannot_resume_after_original_move_even_with_same_name_bytes(tmp_path):
    store, before = fixture_store(tmp_path)
    source = source_tree(tmp_path)
    reserve_tree(store, before, source)
    staged = store.stage("tree", "tree-digest", writes={"studio/document.vsz": b"accepted candidate"}, result={}, review={})
    store.decide("tree", "tree-digest", decision_id=staged["decision_id"], accept=True)
    source.rename(tmp_path / "offline-original")
    source.mkdir()
    with pytest.raises(ProjectConflict, match="source tree"):
        store.publish_staged("tree", "tree-digest")
    assert store.snapshot()["generation"] == before["generation"]


def test_earlier_tree_file_changed_during_later_read_is_not_admitted(tmp_path, monkeypatch):
    source = source_tree(tmp_path)
    original = tree_io.read_file
    def concurrent_write(fd, name):
        result = original(fd, name)
        if name == "a-1.csv":
            (source / "a/sub/inner.csv").write_bytes(b"changed after its prior read")
        return result
    monkeypatch.setattr(tree_io, "read_file", concurrent_write)
    with pytest.raises(ProjectConflict, match="source tree"):
        observe(str(source))


def test_real_application_preview_binds_tree_and_refuses_late_head_member_without_rerender(tmp_path, monkeypatch):
    store, before = fixture_store(tmp_path)
    source = source_tree(tmp_path)
    name = "studio/document.vsz"
    command = ProjectCommand.create("source_update", "typed source tree", project_id=before["project_id"],
        expected_generation=before["generation"], read_set={name: before["files"][name]["sha256"]},
        write_set=[name], request={}, source_trees=[SourceTreeRead(str(source), source_tree_sha256(source))])
    calls = []
    app = ProjectCommands(store)
    preview = app.preview(command, lambda: (calls.append("native candidate") or ProjectMutation({name: b"candidate"}, {})))
    assert preview["draft"]["source_tree_origins"] == preview["source_tree_origins"]
    def changed(boundary):
        if boundary == "before_head":
            (source / "late.csv").write_bytes(b"late selected source")
    monkeypatch.setattr(state, "boundary", changed)
    with pytest.raises(ProjectConflict, match="source tree"):
        app.decide(command, decision_id=preview["decision_id"], accept=True)
    assert (source / "late.csv").read_bytes() == b"late selected source"
    assert store.read_bytes(name) == b"native old"
    assert store.query(command.key)["phase"] == "accepted"
    assert calls == ["native candidate"]
