"""SourceUpdate selects exact reviewed old and explicitly incoming new epochs."""
import json

import pytest

from sciplot_core.foundation.file_hashing import file_sha256
from sciplot_core.foundation.source_locations import resolve_source_path
from sciplot_core.project_commands import PreparedSource, ProjectCommand, ProjectCommands, ProjectMutation
from sciplot_core.project_store import FileProjectStore
from sciplot_core.project_store.runtime import project_runtime
from sciplot_core.studio_core.source_update_files import file_inventory
from sciplot_core.studio_core.source_update_sources import baseline_scope, incoming_scope


def selected(tmp_path, *, directory=False):
    source = tmp_path / "incoming.csv"
    if directory:
        source.mkdir()
        member = source / source.name
    else:
        member = source
    member.write_bytes(b"original source epoch")
    root = tmp_path / "project"
    (root / "studio").mkdir(parents=True)
    (root / "plot_request.json").write_text("{}")
    digest = file_sha256(member)
    (root / "studio/spec.json").write_text(json.dumps({"series": [{"source_artifacts": [
        {"path": str(member), "sha256": digest}]}]}))
    store = FileProjectStore(root)
    before = store.snapshot(import_legacy=True)
    review = {"source": str(source), "source_kind": "directory" if directory else "file",
              "source_files": file_inventory(source)}
    command = ProjectCommand.create("source_update", "register-reviewed-baseline", project_id=before["project_id"],
        expected_generation=before["generation"], read_set={"source_update.json": None}, write_set=["source_update.json"], request={})
    ProjectCommands(store).execute(command, lambda: ProjectMutation({"source_update.json": json.dumps(review).encode()}, {},
        prepared_sources=(PreparedSource("a" * 32, str(member), digest, member.read_bytes()),)))
    return store, source, member, digest


@pytest.mark.parametrize("directory", [False, True])
def test_same_origin_new_bytes_are_explicitly_fresh_while_baseline_reads_the_sealed_old_epoch(tmp_path, directory):
    store, source, member, old = selected(tmp_path, directory=directory)
    snapshot = store.snapshot()
    member.write_bytes(b"explicitly confirmed incoming new epoch")
    incoming = file_inventory(source)
    with project_runtime(store):
        with pytest.raises(ValueError, match="exact registered version"):
            resolve_source_path(member)
        with baseline_scope(store, snapshot):
            assert resolve_source_path(member).read_bytes() == b"original source epoch"
        with incoming_scope(store, snapshot, source, incoming):
            assert resolve_source_path(member).read_bytes() == b"explicitly confirmed incoming new epoch"
        with pytest.raises(ValueError, match="exact registered version"):
            resolve_source_path(member)
    assert store.resolve_source("a" * 32, old).read_bytes() == b"original source epoch"
    assert set(store.snapshot()["sources"]["a" * 32]) == {old}
    assert len(store.commands()) == 1


def test_incoming_source_alias_cannot_reuse_an_observation_taken_before_replacement(tmp_path):
    store, source, member, old = selected(tmp_path)
    snapshot = store.snapshot()
    member.write_bytes(b"confirmed fresh bytes")
    incoming = file_inventory(source)
    target = tmp_path / "foreign.csv"
    target.write_bytes(member.read_bytes())
    member.unlink()
    member.symlink_to(target)
    with incoming_scope(store, snapshot, source, incoming):
        with pytest.raises((ValueError, OSError)):
            resolve_source_path(member)
    assert store.resolve_source("a" * 32, old).read_bytes() == b"original source epoch"
    assert target.read_bytes() == b"confirmed fresh bytes"
