"""Automatic export intentions never bypass an unknown or foreign output writer."""

import pytest

from sciplot_core.project_commands import ProjectCommand, ProjectCommands, ProjectMutation, ProjectCommandUnknown
from sciplot_core.project_store import FileProjectStore, ProjectConflict
from sciplot_core.project_store.adapters import publish_files
from sciplot_core.studio_core.export_replay import current_export


def exported(tmp_path):
    root = tmp_path / "output"
    root.mkdir()
    store = FileProjectStore(root)
    before = store.snapshot(import_legacy=True)
    request = {"document": "studio/document.vsz", "figure_id": "A", "formats": ["pdf"],
               "input_files": {"studio/document.vsz": "a" * 64}}
    command = ProjectCommand.create("native_export", "original", project_id=before["project_id"],
        expected_generation=before["generation"], read_set={"a.pdf": None}, write_set=["a.pdf"], request=request)
    record = ProjectCommands(store).execute(command, lambda: ProjectMutation({"a.pdf": b"exact old PDF"}, {}))
    return store, request, record


@pytest.mark.parametrize("registered", [True, False])
def test_export_replay_preserves_foreign_manual_output(tmp_path, registered):
    store, request, record = exported(tmp_path)
    if registered:
        publish_files(store, {"a.pdf": b"foreign registered writer"}, kind="save")
    else:
        (store.root / "a.pdf").write_bytes(b"foreign manual PDF")
    before = (store.root / "a.pdf").read_bytes()
    with pytest.raises(ProjectConflict, match="outside|not installed"):
        current_export(ProjectCommands(store), store, request, kind="native_export")
    assert (store.root / "a.pdf").read_bytes() == before
    assert store.query(record["command_id"])["phase"] == "complete"


def test_format_change_cannot_hide_matching_unknown_execution(tmp_path):
    store, request, _ = exported(tmp_path)
    before = store.snapshot()
    unknown = ProjectCommand.create("native_export", "uncertain", project_id=before["project_id"],
        expected_generation=before["generation"], read_set={"a.tiff": None}, write_set=["a.tiff"],
        request={**request, "formats": ["tiff_300"]})
    store.reserve(unknown.key, unknown.command_digest, expected_generation=unknown.expected_generation,
        read_set=dict(unknown.read_set), write_set=unknown.write_set, metadata=unknown.to_payload())
    store.mark_applying(unknown.key, unknown.command_digest)
    with pytest.raises(ProjectCommandUnknown):
        current_export(ProjectCommands(store), store, request, kind="native_export")
    assert len(store.commands()) == 2 and not (store.root / "a.tiff").exists()


def test_superseded_complete_export_gets_new_preimage_and_keeps_old_receipt(tmp_path):
    store, request, old = exported(tmp_path)
    before = store.snapshot()
    newer = ProjectCommand.create("native_export", "later-formats", project_id=before["project_id"],
        expected_generation=before["generation"], read_set={"a.pdf": before["files"]["a.pdf"]["sha256"]},
        write_set=["a.pdf"], request={**request, "formats": ["pdf", "tiff_300"]})
    later = ProjectCommands(store).execute(newer, lambda: ProjectMutation({"a.pdf": b"later exact PDF"}, {}))
    prior, fresh = current_export(ProjectCommands(store), store, request, kind="native_export")
    assert prior is None and fresh["output_predecessors"] == [later["command_id"]]
    assert fresh["output_preimage"]["a.pdf"]["sha256"] == store.snapshot()["files"]["a.pdf"]["sha256"]
    assert store.query(old["command_id"])["result"] == old["result"]
    current, _ = current_export(ProjectCommands(store), store, {**request, "formats": ["pdf", "tiff_300"]}, kind="native_export")
    assert current["command_id"] == later["command_id"]
