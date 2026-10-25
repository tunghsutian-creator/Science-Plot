"""Observed raw input versions advance immutable witnesses without raw writes."""

import hashlib
import pytest

from sciplot_core.project_commands import ProjectCommand, ProjectCommands, ProjectMutation
from sciplot_core.project_commands.resources import NativeAdoption, PreparedFile, PreparedSource, SourceAdoption
from sciplot_core.project_store import FileProjectStore, ProjectConflict
from sciplot_core.project_store import state


def fixture_observation(tmp_path):
    root = tmp_path / "project"
    root.mkdir()
    raw = root / "source.csv"
    raw.write_bytes(b"old input")
    store = FileProjectStore(root)
    before = store.snapshot(import_legacy=True)
    old_sha = hashlib.sha256(raw.read_bytes()).hexdigest()
    identity = before["files"]["source.csv"]["file_id"]
    raw.write_bytes(b"new input")
    version = hashlib.sha256(raw.read_bytes()).hexdigest()
    mutation = ProjectMutation({"semantic/state.json": PreparedFile(b'{"source":"new"}', 0o600)}, {},
        prepared_sources=(PreparedSource(identity, str(raw), version, raw.read_bytes(), ("A",), 0o644),))
    command = ProjectCommand.create("semantic_record", "observe-source", project_id=before["project_id"],
        expected_generation=before["generation"], read_set={"source.csv": old_sha, "semantic/state.json": None},
        write_set=["semantic/state.json"], request={"prepared_digest": mutation.prepared_digest},
        source_adoptions=[SourceAdoption("source.csv", identity, old_sha, version)])
    return store, before, raw, identity, command, mutation


def test_source_observation_preserves_original_inode_mode_mtime_and_complete_history(tmp_path):
    store, before, raw, identity, command, mutation = fixture_observation(tmp_path)
    alias = tmp_path / "input-alias.csv"
    alias.hardlink_to(raw)
    original = raw.stat()
    result = ProjectCommands(store).publish_prepared(command, mutation)
    assert result["phase"] == "complete"
    after = raw.stat()
    assert (after.st_ino, after.st_mode, after.st_mtime_ns, after.st_nlink) == (
        original.st_ino, original.st_mode, original.st_mtime_ns, original.st_nlink)
    assert raw.read_bytes() == b"new input" == alias.read_bytes()
    current = store.snapshot()
    assert current["outside_changes"] == {}
    assert current["input_resources"] == ["source.csv"]
    assert store.read_bytes("source.csv", generation=before["generation"]) == b"old input"
    old_sha = before["files"]["source.csv"]["sha256"]
    with pytest.raises(ProjectConflict):
        store.resolve_path(raw, expected_sha256=old_sha, source_id=identity)
    frozen = store.resolve_path(raw, expected_sha256=old_sha, source_id=identity, generation=before["generation"])
    assert frozen.read_bytes() == b"old input"
    assert raw.read_bytes() == b"new input"
    raw.write_bytes(b"third outside input")
    current_sha = current["files"]["source.csv"]["sha256"]
    with pytest.raises(ProjectConflict):
        store.resolve_path(raw, expected_sha256=current_sha, source_id=identity, generation=current["generation"])
    assert store.snapshot()["outside_changes"]["source.csv"] == hashlib.sha256(raw.read_bytes()).hexdigest()
    store.recover()
    assert raw.read_bytes() == b"third outside input"


def test_sealed_observation_refuses_new_raw_drift_at_head_without_restoring_original(tmp_path, monkeypatch):
    store, before, raw, _identity, command, mutation = fixture_observation(tmp_path)
    def boundary(name):
        if name == "before_head":
            raw.write_bytes(b"outside third input")
    monkeypatch.setattr(state, "boundary", boundary)
    with pytest.raises(ProjectConflict):
        ProjectCommands(store).publish_prepared(command, mutation)
    assert store.snapshot()["generation"] == before["generation"]
    assert not (store.root / "semantic/state.json").exists()
    assert raw.read_bytes() == b"outside third input"


def test_explicit_native_prepared_mode_mismatch_cannot_adopt_unobserved_permissions(tmp_path):
    root = tmp_path / "project"
    root.mkdir()
    native = root / "manual.vsz"
    native.write_bytes(b"old")
    store = FileProjectStore(root)
    before = store.snapshot(import_legacy=True)
    native.write_bytes(b"manual")
    observed = hashlib.sha256(b"manual").hexdigest()
    adoption = NativeAdoption("manual.vsz", before["files"]["manual.vsz"]["sha256"], observed, observed)
    command = ProjectCommand.create("native_import", "import", project_id=before["project_id"],
        expected_generation=before["generation"], read_set={"manual.vsz": adoption.before_sha256},
        write_set=["manual.vsz"], request={}, native_adoptions=[adoption])
    with pytest.raises(ProjectConflict):
        ProjectCommands(store).execute(command, lambda: ProjectMutation({"manual.vsz": PreparedFile(b"manual", 0o700)}, {}))
    assert native.read_bytes() == b"manual"
    assert native.stat().st_mode & 0o777 == 0o644


def test_readonly_capture_and_cold_refresh_keep_exact_original_binding(tmp_path):
    store, before, raw, identity, _command, _mutation = fixture_observation(tmp_path)
    store.export_bundle(tmp_path / "bundle")
    cold = FileProjectStore.import_bundle(tmp_path / "bundle", tmp_path / "cold")
    store.root.rename(tmp_path / "original-offline")
    current = cold.snapshot()
    selected = cold.root / "source.csv"
    selected.write_bytes(b"cold newly observed bytes")
    prior = before["files"]["source.csv"]["sha256"]
    observed = cold.capture_source_observation("source.csv", source_id=identity, before_sha256=prior)
    assert observed["locator"] == str(raw)
    assert observed["data"] == selected.read_bytes()
    assert observed["path"] == str(selected)
    assert cold.snapshot()["generation"] == current["generation"]
    source = PreparedSource(identity, observed["locator"], observed["version"], observed["data"],
        tuple(observed["aliases"]), observed["mode"])
    mutation = ProjectMutation({"semantic/state.json": b"cold state"}, {}, prepared_sources=(source,))
    command = ProjectCommand.create("semantic_record", "cold observe", project_id=current["project_id"],
        expected_generation=current["generation"], read_set={"source.csv": prior, "semantic/state.json": None},
        write_set=["semantic/state.json"], request={"prepared_digest": mutation.prepared_digest},
        source_adoptions=[SourceAdoption("source.csv", identity, prior, observed["version"])])
    original = selected.stat()
    ProjectCommands(cold).publish_prepared(command, mutation)
    assert selected.stat().st_mtime_ns == original.st_mtime_ns
    assert selected.read_bytes() == observed["data"]
    assert cold.snapshot()["outside_changes"] == {}
    from sciplot_core.project_store import commands
    from sciplot_core.project_store.io import StoreIO
    with StoreIO(cold.root, {}).locked() as io:
        frozen = commands.capture_sources(io, [{"source_id": identity, "path": str(raw), "version": observed["version"]}])
        commands.verify_sources(io, frozen)
    assert cold.resolve_path(str(raw), source_id=identity, expected_sha256=observed["version"]) == selected
