"""Ordinary preparation binds one current source revision without changing IO defaults."""
import hashlib
import json

import pytest

from sciplot_core.foundation.file_hashing import file_sha256
from sciplot_core.foundation.source_locations import resolve_source_path, selected_source_resolver
from sciplot_core.foundation.source_tree import source_tree_sha256
from sciplot_core.project_commands import PreparedSource, ProjectCommand, ProjectCommands, ProjectMutation, SourceTreeRead
from sciplot_core.project_store import FileProjectStore, ProjectConflict, ProjectStoreError
from sciplot_core.project_store.io import sha
from sciplot_core.project_store.runtime import project_runtime
from sciplot_core.studio_core import preparation_commands as commands

from test_project_query_source_versions import generation


def current_revision(tmp_path, *, directory=False):
    store, request, source, paths = generation(tmp_path, directory=directory)
    old_versions = {path: file_sha256(path) for path in paths}
    for index, path in enumerate(paths):
        path.write_text(f"x,y\n1,{index + 10}\n")
    if directory:
        unused = source / "notes.txt"
        unused.write_bytes(b"original unused input; not scientific data")
        paths.append(unused)
    inventory = {path.relative_to(source).as_posix() if directory else path.name: file_sha256(path) for path in paths}
    tree_sha = source_tree_sha256(source)
    artifacts = [{"kind": "file", "path": str(path), "sha256": file_sha256(path)} for path in paths if path.suffix == ".csv"]
    request = {**request, "resolved_figure_plan": {"source_sha256": tree_sha},
        "transform_ledger": {"steps": [{"input_artifacts": artifacts}]}}
    review = {"source": str(source), "source_kind": "directory" if directory else "file",
        "source_files": inventory, "source_tree_sha256": tree_sha}
    writes = {"plot_request.json": json.dumps(request).encode(), "source_update.json": json.dumps(review).encode(),
        "studio/spec.json": json.dumps({"series": [{"source_artifacts": artifacts}]}).encode()}
    before = store.snapshot()
    command = ProjectCommand.create("source_update", "exact-current-v1", project_id=before["project_id"],
        expected_generation=before["generation"], read_set={name: before["files"][name]["sha256"] for name in writes},
        write_set=sorted(writes), request=review, source_trees=[SourceTreeRead(str(source), tree_sha)])
    sources = tuple(PreparedSource(hashlib.sha256(str(path).encode()).hexdigest()[:32], str(path),
        file_sha256(path), path.read_bytes()) for path in paths)
    app = ProjectCommands(store)
    staged = app.preview(command, lambda: ProjectMutation(writes, {"review": review}, review=review, prepared_sources=sources))
    app.decide(command, decision_id=staged["decision_id"], accept=True)
    return store, source, paths, old_versions, tree_sha


def controlled_preparer(monkeypatch, source, paths, expected_tree, *, fail=False, drift=False):
    calls = []

    def prepare(candidate, **_options):
        calls.append(candidate.project_dir)
        assert source_tree_sha256(source) == expected_tree
        for path in paths:
            assert resolve_source_path(path).read_bytes()
        if drift:
            paths[0].write_bytes(b"raw changed after private preparation")
        if fail:
            raise ValueError("controlled deep preparation failure")
        document = candidate.project_dir / "studio/document.vsz"
        document.write_bytes(b"private native-port double; source IO is real")
        return {"kind": "sciplot_studio_prepare", "project_dir": str(candidate.project_dir),
            "request": str(candidate.project_dir / "plot_request.json"), "document": str(document)}

    monkeypatch.setattr(commands, "prepare_studio_candidate", prepare)
    monkeypatch.setattr(commands, "audit_studio_candidate", lambda *_args: ([], []))
    return calls


@pytest.mark.parametrize("directory", [False, True])
def test_current_live_preparation_uses_exact_v1_once_and_keeps_default_no_sha_closed(tmp_path, monkeypatch, directory):
    store, source, paths, old, expected = current_revision(tmp_path, directory=directory)
    before = store.snapshot()
    with project_runtime(store), pytest.raises(ProjectStoreError, match="exact registered version"):
        resolve_source_path(paths[0])
    calls = controlled_preparer(monkeypatch, source, paths, expected)
    result = commands.prepare_studio_generation(store.root)
    assert len(calls) == 1 and not calls[0].exists()
    assert store.snapshot()["sequence"] == before["sequence"] + 1
    assert result["project_command"]["generation"] == store.snapshot()["generation"]
    for path, version in old.items():
        identity = hashlib.sha256(str(path).encode()).hexdigest()[:32]
        assert sha(store.resolve_source(identity, version).read_bytes()) == version
    assert json.loads(store.read_bytes("plot_request.json"))["input"] == str(source)
    assert selected_source_resolver() is None
    with project_runtime(store), pytest.raises(ProjectStoreError, match="exact registered version"):
        resolve_source_path(paths[0])


@pytest.mark.parametrize("during", [False, True])
def test_live_drift_never_uses_a_sealed_version_or_publishes(tmp_path, monkeypatch, during):
    store, source, paths, _old, expected = current_revision(tmp_path)
    before = store.snapshot()
    calls = controlled_preparer(monkeypatch, source, paths, expected, drift=during)
    if not during:
        paths[0].write_bytes(b"unconfirmed live source revision")
    with project_runtime(store) as original:
        with pytest.raises(ProjectConflict, match="expectation|version"):
            commands.prepare_studio_generation(store.root)
        assert selected_source_resolver() is original
    assert len(calls) == int(during)
    assert store.snapshot() == before
    assert not (store.root / "studio/document.vsz").exists()


def test_current_cold_file_uses_only_explicit_local_v1_and_preserves_original_literal(tmp_path, monkeypatch):
    store, source, paths, _old, expected = current_revision(tmp_path)
    cold = FileProjectStore.import_bundle(store.export_bundle(tmp_path / "bundle"), tmp_path / "cold")
    source.rename(tmp_path / "original-offline")
    calls = controlled_preparer(monkeypatch, source, paths, expected)
    commands.prepare_studio_generation(cold.root)
    assert len(calls) == 1 and not source.exists()
    assert json.loads(cold.read_bytes("plot_request.json"))["input"] == str(source)
    assert selected_source_resolver() is None


def test_cold_cache_missing_current_binding_does_not_select_old_version(tmp_path, monkeypatch):
    store, source, paths, old, expected = current_revision(tmp_path)
    cold = FileProjectStore.import_bundle(store.export_bundle(tmp_path / "bundle"), tmp_path / "cold")
    source.rename(tmp_path / "original-offline")
    metadata = cold.root / ".sciplot_store/local_sources.json"
    bindings = json.loads(metadata.read_bytes())
    identity = hashlib.sha256(str(paths[0]).encode()).hexdigest()[:32]
    bindings["versions"][identity] = {old[paths[0]]: old[paths[0]]}
    metadata.write_text(json.dumps(bindings))
    before = cold.snapshot()
    calls = controlled_preparer(monkeypatch, source, paths, expected)
    with pytest.raises(ProjectConflict, match="exact current canonical source version"):
        commands.prepare_studio_generation(cold.root)
    assert not calls and cold.snapshot() == before
    assert selected_source_resolver() is None


def test_failed_preparation_restores_source_scope_without_publishing(tmp_path, monkeypatch):
    store, source, paths, _old, expected = current_revision(tmp_path)
    before = store.snapshot()
    controlled_preparer(monkeypatch, source, paths, expected, fail=True)
    with pytest.raises(ValueError, match="controlled deep preparation failure"):
        commands.prepare_studio_generation(store.root)
    assert store.snapshot() == before and selected_source_resolver() is None


def test_complete_current_cold_directory_resolves_same_input_tree_in_deep_preparation(tmp_path, monkeypatch):
    store, source, paths, _old, expected = current_revision(tmp_path, directory=True)
    cold = FileProjectStore.import_bundle(store.export_bundle(tmp_path / "bundle"), tmp_path / "cold")
    source.rename(tmp_path / "original-offline")
    calls = controlled_preparer(monkeypatch, source, paths, expected)
    commands.prepare_studio_generation(cold.root)
    assert len(calls) == 1 and not source.exists()
