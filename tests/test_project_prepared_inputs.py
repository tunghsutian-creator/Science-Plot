"""Only explicitly imported sealed inputs can replace offline preview originals."""

import json
from pathlib import Path
from uuid import uuid4

import pytest

from sciplot_core.foundation.source_tree import source_tree_sha256
from sciplot_core.project_commands import PreparedSource, ProjectCommand, ProjectCommands, ProjectMutation, SourceTreeRead
from sciplot_core.project_store import FileProjectStore, ProjectConflict, ProjectStoreError, state
from sciplot_core.project_store.io import digest, sha

from test_project_store import fixture_store


def preview_inputs(tmp_path, *, directory=False, capture=True, wrong=None):
    store, before = fixture_store(tmp_path)
    source = tmp_path / ("incoming" if directory else "incoming.csv")
    if directory:
        source.mkdir()
        (source / "nested").mkdir()
        (source / "empty").mkdir()
        for name in ("a.csv", "nested/b.csv"):
            (source / name).write_bytes(("exact new source " + name).encode())
        files = sorted(path for path in source.rglob("*") if path.is_file())
    else:
        source.write_bytes(b"exact new source version outside current generation")
        files = [source]
    prepared = []
    for path in files if capture else []:
        path.chmod(0o644)
        data = b"wrong captured version" if wrong == "sha" else path.read_bytes()
        prepared.append(PreparedSource(uuid4().hex, str(path), sha(data), data, (),
                                      0o600 if wrong == "mode" else path.stat().st_mode & 0o777))
    prepared = tuple(prepared[:-1] if wrong == "missing" else prepared)
    name = "studio/document.vsz"
    tree = SourceTreeRead(str(source), source_tree_sha256(source))
    command = ProjectCommand.create("source_update", "pending input " + uuid4().hex, project_id=before["project_id"],
        expected_generation=before["generation"], read_set={name: before["files"][name]["sha256"]}, write_set=[name],
        request={}, source_trees=[tree])
    review = ProjectCommands(store).preview(command, lambda: ProjectMutation({name: b"sealed new native"}, {},
        prepared_sources=prepared))
    return store, source, command, review, prepared


def tree_path(store, command, review):
    guard = command.source_trees[0]
    return store.prepared_tree_path(command.key, command.command_digest, decision_id=review["decision_id"],
                                   locator=guard.locator, tree_sha256=guard.tree_sha256)


def input_path(store, command, review, source):
    return store.prepared_input_path(command.key, command.command_digest, decision_id=review["decision_id"],
        locator=source.locator, expected_sha256=source.version, source_id=source.source_id)


@pytest.mark.parametrize("directory", [False, True])
def test_exact_pending_inputs_survive_explicit_bundle_without_publishing_source_versions(tmp_path, directory):
    store, source, command, review, prepared = preview_inputs(tmp_path, directory=directory)
    original_proof = review["source_tree_origins"]
    cold = FileProjectStore.import_bundle(store.export_bundle(tmp_path / "bundle"), tmp_path / "cold")
    source.rename(tmp_path / "offline-original")
    store.root.rename(tmp_path / "offline-project")
    for item in prepared:
        with pytest.raises(ProjectStoreError):
            cold.resolve_source(item.source_id, item.version)
    actual = tree_path(cold, command, review)
    assert actual.name == source.name
    assert source_tree_sha256(actual) == command.source_trees[0].tree_sha256
    if directory:
        assert (actual / "empty").is_dir()
    for item in prepared:
        assert input_path(cold, command, review, item).read_bytes() == item.data
    receipt = ProjectCommands(cold).decide(command, decision_id=review["decision_id"], accept=True)
    assert receipt["phase"] == "complete"
    assert receipt["source_tree_origins"] == original_proof
    assert cold.read_bytes("studio/document.vsz") == b"sealed new native"
    for item in prepared:
        assert cold.snapshot()["sources"][item.source_id][item.version]["locator"] == item.locator


@pytest.mark.parametrize("wrong", ["missing", "mode", "sha"])
def test_import_blocks_incomplete_or_wrong_exact_tree_capture(tmp_path, wrong):
    store, source, _command, _review, _prepared = preview_inputs(tmp_path, directory=True, wrong=wrong)
    original = {str(path.relative_to(source)): path.read_bytes() for path in source.rglob("*") if path.is_file()}
    with pytest.raises(ProjectConflict):
        FileProjectStore.import_bundle(store.export_bundle(tmp_path / "bundle"), tmp_path / "cold")
    assert {str(path.relative_to(source)): path.read_bytes() for path in source.rglob("*") if path.is_file()} == original


def test_import_blocks_missing_frozen_source_blob_even_with_matching_bundle_file_inventory(tmp_path):
    store, _source, _command, _review, prepared = preview_inputs(tmp_path)
    bundle = store.export_bundle(tmp_path / "bundle")
    version = prepared[0].version
    name = f"objects/{version[:2]}/{version}"
    (bundle / "store" / name).unlink()
    header = json.loads((bundle / "bundle.json").read_bytes())
    del header["members"][name]
    (bundle / "bundle.json").write_text(json.dumps(header))
    with pytest.raises(ProjectConflict, match="blob"):
        FileProjectStore.import_bundle(bundle, tmp_path / "cold")


def test_getters_are_readonly_and_bind_exact_command_decision_source_and_hash_kind(tmp_path):
    store, _source, command, review, prepared = preview_inputs(tmp_path)
    cold = FileProjectStore.import_bundle(store.export_bundle(tmp_path / "bundle"), tmp_path / "cold")
    item = prepared[0]
    def stamps():
        return {str(path.relative_to(cold.root)): (path.stat().st_ino, path.stat().st_mode, path.stat().st_mtime_ns)
                for path in cold.root.rglob("*")}
    before = stamps()
    assert tree_path(cold, command, review).name == Path(item.locator).name
    assert input_path(cold, command, review, item).read_bytes() == item.data
    assert stamps() == before
    base = {"decision_id": review["decision_id"], "locator": item.locator, "expected_sha256": item.version}
    for key, business, values in (
        ("unknown", command.command_digest, base),
        (command.key, "wrong digest", base),
        (command.key, command.command_digest, {**base, "decision_id": "wrong decision"}),
        (command.key, command.command_digest, {**base, "locator": item.locator + ".same-name"}),
        (command.key, command.command_digest, {**base, "expected_sha256": command.source_trees[0].tree_sha256}),
        (command.key, command.command_digest, {**base, "source_id": uuid4().hex}),
    ):
        with pytest.raises(ProjectConflict):
            cold.prepared_input_path(key, business, **values)
    with pytest.raises(ProjectConflict):
        cold.prepared_tree_path(command.key, command.command_digest, decision_id=review["decision_id"],
                                locator=item.locator, tree_sha256=item.version)
    assert stamps() == before


@pytest.mark.parametrize("change", ["bytes", "mode", "missing", "extra", "alias", "inode"])
def test_cache_tampering_blocks_the_selected_tree_without_restoring_raw_or_publishing(tmp_path, change):
    store, source, command, review, _prepared = preview_inputs(tmp_path, directory=True)
    cold = FileProjectStore.import_bundle(store.export_bundle(tmp_path / "bundle"), tmp_path / "cold")
    view = tree_path(cold, command, review)
    source.rename(tmp_path / "offline-source")
    target = view / "a.csv"
    if change == "bytes":
        target.chmod(0o600)
        target.write_bytes(b"changed cache bytes")
        target.chmod(0o400)
    elif change == "mode":
        target.chmod(0o600)
    elif change == "inode":
        data = target.read_bytes()
        view.chmod(0o700)
        previous = target.stat()
        replacement = view / "replacement-fixture.csv"
        replacement.write_bytes(data)
        replacement.chmod(0o400)
        installed = replacement.stat()
        assert (installed.st_dev, installed.st_ino) != (previous.st_dev, previous.st_ino)
        replacement.replace(target)
        assert (target.stat().st_dev, target.stat().st_ino) == (installed.st_dev, installed.st_ino)
        view.chmod(0o500)
    else:
        view.chmod(0o700)
        if change == "missing":
            target.unlink()
        elif change == "extra":
            (view / "late.csv").write_bytes(b"not an admitted original member")
        else:
            (view / "alias.csv").symlink_to(view / "nested/b.csv")
        view.chmod(0o500)
    with pytest.raises(ProjectConflict):
        tree_path(cold, command, review)
    with pytest.raises(ProjectConflict):
        ProjectCommands(cold).decide(command, decision_id=review["decision_id"], accept=True)
    assert cold.read_bytes("studio/document.vsz") == b"native old"
    assert not source.exists()


def test_cold_source_view_never_rebinds_a_foreign_command_or_lost_import_index(tmp_path):
    store, _source, command, review, prepared = preview_inputs(tmp_path)
    cold = FileProjectStore.import_bundle(store.export_bundle(tmp_path / "bundle"), tmp_path / "cold")
    path = cold.root / ".sciplot_store/local_sources.json"
    payload = json.loads(path.read_bytes())
    key = digest(command.key)
    payload["prepared"][key]["command_digest"] = "foreign command digest"
    path.write_text(json.dumps(payload))
    with pytest.raises(ProjectConflict, match="exact command"):
        input_path(cold, command, review, prepared[0])
    del payload["prepared"][key]
    path.write_text(json.dumps(payload))
    with pytest.raises(ProjectConflict, match="complete frozen input binding"):
        tree_path(cold, command, review)


@pytest.mark.parametrize("move", [False, True])
def test_live_preview_never_uses_stored_bytes_to_hide_changed_or_moved_originals(tmp_path, monkeypatch, move):
    store, source, command, review, prepared = preview_inputs(tmp_path, directory=True)
    assert tree_path(store, command, review) is None
    assert input_path(store, command, review, prepared[0]) is None
    def changed(name):
        if name == "before_head":
            if move:
                source.rename(tmp_path / "moved-without-explicit-bundle")
            else:
                (source / "late.csv").write_bytes(b"new original member")
    monkeypatch.setattr(state, "boundary", changed)
    with pytest.raises(ProjectConflict):
        ProjectCommands(store).decide(command, decision_id=review["decision_id"], accept=True)
    assert store.read_bytes("studio/document.vsz") == b"native old"


def test_complete_captured_tree_reopens_from_exact_same_imported_port(tmp_path):
    store, source, command, review, _prepared = preview_inputs(tmp_path, directory=True)
    ProjectCommands(store).decide(command, decision_id=review["decision_id"], accept=True)
    bundle = store.export_bundle(tmp_path / "bundle")
    source.rename(tmp_path / "offline-original")
    cold = FileProjectStore.import_bundle(bundle, tmp_path / "cold")
    assert source_tree_sha256(tree_path(cold, command, review)) == command.source_trees[0].tree_sha256
    assert cold.query(command.key)["phase"] == "complete"


@pytest.mark.parametrize("change", ["source-version", "source-blob"])
def test_getter_and_head_refuse_lost_exact_version_or_changed_blob(tmp_path, change):
    store, _source, command, review, prepared = preview_inputs(tmp_path)
    cold = FileProjectStore.import_bundle(store.export_bundle(tmp_path / "bundle"), tmp_path / "cold")
    item = prepared[0]
    if change == "source-version":
        path = cold.root / ".sciplot_store/local_sources.json"
        local = json.loads(path.read_bytes())
        del local["versions"][item.source_id][item.version]
        path.write_text(json.dumps(local))
    else:
        path = cold.root / ".sciplot_store/objects" / item.version[:2] / item.version
        path.write_bytes(b"foreign blob bytes under old content name")
    with pytest.raises(ProjectConflict):
        input_path(cold, command, review, item)
    with pytest.raises(ProjectConflict):
        tree_path(cold, command, review)
    with pytest.raises(ProjectConflict):
        ProjectCommands(cold).decide(command, decision_id=review["decision_id"], accept=True)
    assert cold.read_bytes("studio/document.vsz") == b"native old"


@pytest.mark.parametrize("fault", ["cache-tamper", "interrupted"])
def test_final_head_boundary_rechecks_cold_cache_and_resumes_only_same_sealed_input(tmp_path, monkeypatch, fault):
    store, source, command, review, prepared = preview_inputs(tmp_path, directory=True)
    frozen_relative = f".sciplot_store/drafts/{digest(command.key)}/{review['decision_id']}.json"
    frozen_bytes = (store.root / frozen_relative).read_bytes()
    cold = FileProjectStore.import_bundle(store.export_bundle(tmp_path / "bundle"), tmp_path / "cold")
    before = cold.snapshot()
    view = tree_path(cold, command, review)
    target = view / "a.csv"
    captured = target.read_bytes()
    original = tmp_path / "offline-original"
    source.rename(original)
    originals = {str(path.relative_to(original)): (path.read_bytes(), path.stat().st_ino, path.stat().st_mode)
                 for path in original.rglob("*") if path.is_file()}
    boundary_calls = []

    class Interrupted(Exception):
        pass

    def stop(name):
        if name == "before_head":
            boundary_calls.append(name)
            assert (cold.root / "studio/document.vsz").read_bytes() == b"native old"
            if fault == "interrupted":
                raise Interrupted()
            target.chmod(0o600)
            target.write_bytes(b"foreign cache bytes installed at final head boundary")
            target.chmod(0o400)

    monkeypatch.setattr(state, "boundary", stop)
    with pytest.raises(Interrupted if fault == "interrupted" else ProjectConflict):
        ProjectCommands(cold).decide(command, decision_id=review["decision_id"], accept=True)
    assert boundary_calls == ["before_head"]
    assert cold.snapshot()["generation"] == before["generation"]
    assert cold.read_bytes("studio/document.vsz") == b"native old"
    assert cold.query(command.key)["phase"] == "accepted"
    assert (cold.root / frozen_relative).read_bytes() == frozen_bytes
    for item in prepared:
        with pytest.raises(ProjectStoreError):
            cold.resolve_source(item.source_id, item.version)
    monkeypatch.setattr(state, "boundary", lambda _name: None)
    if fault == "cache-tamper":
        with pytest.raises(ProjectConflict):
            ProjectCommands(cold).resume(command)
        assert target.read_bytes() == b"foreign cache bytes installed at final head boundary"
        assert cold.snapshot()["generation"] == before["generation"]
        # Explicit restoration of this private test cache preserves its admitted
        # inode. The Store never repairs originals or accepts a replacement inode.
        target.chmod(0o600)
        target.write_bytes(captured)
        target.chmod(0o400)
    completed = ProjectCommands(cold).resume(command)
    assert completed["phase"] == "complete"
    assert completed["decision_id"] == review["decision_id"]
    assert completed["source_tree_origins"] == review["source_tree_origins"]
    assert completed["draft"] == review["draft"]
    assert (cold.root / frozen_relative).read_bytes() == frozen_bytes
    assert cold.snapshot()["sequence"] == before["sequence"] + 1
    assert cold.read_bytes("studio/document.vsz") == b"sealed new native"
    assert len(cold.commands()) == 1
    assert not source.exists()
    assert originals == {str(path.relative_to(original)): (path.read_bytes(), path.stat().st_ino, path.stat().st_mode)
                         for path in original.rglob("*") if path.is_file()}
