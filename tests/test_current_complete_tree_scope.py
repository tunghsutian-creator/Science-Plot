"""A current complete-tree author does not promote ordinary file capabilities."""

from contextlib import nullcontext
from dataclasses import replace
import os

import pytest

from sciplot_core.foundation.file_hashing import file_sha256
from sciplot_core.foundation.source_locations import resolve_source_path, selected_source_resolver
from sciplot_core.foundation.source_tree import source_tree_sha256
from sciplot_core.project_commands import SourceTreeRead
from sciplot_core.project_store import FileProjectStore, ProjectStoreError
from sciplot_core.project_store.incoming_sources import SourceExpectation
from sciplot_core.project_store.io import StoreIO
from sciplot_core.project_store.runtime import (
    incoming_source_runtime, inspect_runtime_source_tree, project_candidate_runtime, project_runtime,
)
from sciplot_core.project_store.sealed_source_trees import SealedSourceTree
from sciplot_core.project_store.worker_binding import native_runtime_binding, worker_project_runtime
from sciplot_core.studio_core.preparation_source_runtime import current_preparation_runtime, _current_tree_command

from test_current_preparation_sources import current_revision
from test_project_incoming_sources import private_clone
from test_project_query_readonly_sources import inventory, no_views


def selected_tree(store, source, paths, expected):
    snapshot = store.snapshot()
    tree = SealedSourceTree(*_current_tree_command(store, snapshot, SourceTreeRead(str(source), expected)))
    files = []
    for path in paths:
        version = file_sha256(path)
        identity = next(identity for identity, versions in snapshot["sources"].items()
                        if versions.get(version, {}).get("locator") == str(path))
        files.append(SourceExpectation(str(path), identity, version))
    return tree, files


@pytest.mark.parametrize("candidate", [False, True])
def test_committed_live_whole_tree_preserves_empty_directory_and_is_read_only(tmp_path, monkeypatch, candidate):
    store, source, paths, _old, expected = current_revision(tmp_path, directory=True, rheology=True)
    witness, files = selected_tree(store, source, paths, expected)
    private = private_clone(store, tmp_path) if candidate else None
    original = inventory(tmp_path)
    no_views(monkeypatch)
    monkeypatch.setattr(StoreIO, "write", lambda *_args, **_kwargs: pytest.fail("Read-only tree observation wrote metadata"))
    with incoming_source_runtime(store, files, trees=(witness,)):
        with project_candidate_runtime(store, private) if private else nullcontext():
            assert inspect_runtime_source_tree(source, allowed={path.relative_to(source).as_posix() for path in paths}) == expected
            assert resolve_source_path(source) == source
            assert source_tree_sha256(source) == expected and (source / "empty").is_dir()
            with pytest.raises(ProjectStoreError):
                inspect_runtime_source_tree(source, allowed={paths[0].name})
    assert inventory(tmp_path) == original and selected_source_resolver() is None
    with project_runtime(store), pytest.raises(ProjectStoreError, match="exact registered version"):
        resolve_source_path(paths[0])


def test_even_all_file_expectations_cannot_promote_their_parent_to_a_tree(tmp_path):
    store, source, paths, _old, expected = current_revision(tmp_path, directory=True, rheology=True)
    _witness, files = selected_tree(store, source, paths, expected)
    with incoming_source_runtime(store, files), pytest.raises(ProjectStoreError, match="parent source directory"):
        inspect_runtime_source_tree(source, allowed={path.relative_to(source).as_posix() for path in paths})
    assert selected_source_resolver() is None


@pytest.mark.parametrize("wrong", ["command", "digest", "decision", "tree", "uncommitted", "origins"])
def test_live_whole_tree_requires_exact_committed_author_decision_and_origins(tmp_path, wrong):
    store, source, paths, _old, expected = current_revision(tmp_path, directory=True, rheology=True)
    witness, files = selected_tree(store, source, paths, expected)
    if wrong == "command":
        witness = replace(witness, command_id="not-the-current-author")
    elif wrong == "digest":
        witness = replace(witness, command_digest="0" * 64)
    elif wrong == "decision":
        witness = replace(witness, decision_id="0" * 64)
    elif wrong == "tree":
        witness = replace(witness, tree=SourceTreeRead(str(source), "0" * 64))
    else:
        from sciplot_core.project_store import state

        with store._locked() as (io, _head):
            record = state.command(io, witness.command_id)
            if wrong == "uncommitted":
                record["phase"] = "needs_review"
            else:
                record["source_tree_origins"][str(source)]["members"].pop("empty")
            state.save_command(io, record)
    before = inventory(tmp_path)
    with pytest.raises(ProjectStoreError):
        with incoming_source_runtime(store, files, trees=(witness,)):
            pytest.fail("An unbound complete-tree scope was admitted")
    assert inventory(tmp_path) == before and selected_source_resolver() is None


@pytest.mark.parametrize("change", ["bytes", "empty-mode", "empty-missing", "empty-extra", "extra-file", "symlink", "inode", "exit"])
def test_live_tree_rechecks_complete_original_namespace_on_each_read(tmp_path, change):
    store, source, paths, _old, expected = current_revision(tmp_path, directory=True, rheology=True)
    witness, files = selected_tree(store, source, paths, expected)
    snapshot = store.snapshot()
    with pytest.raises((ProjectStoreError, RuntimeError)):
        with incoming_source_runtime(store, files, trees=(witness,)):
            assert inspect_runtime_source_tree(source) == expected
            if change == "bytes":
                paths[-1].write_bytes(b"unconfirmed unused note")
            elif change == "empty-mode":
                empty = source / "empty"
                empty.chmod((empty.stat().st_mode & 0o777) ^ 0o200)
            elif change == "empty-missing":
                (source / "empty").rmdir()
            elif change == "empty-extra":
                (source / "unadmitted-empty").mkdir()
            elif change == "extra-file":
                (source / "unadmitted.txt").write_bytes(b"extra")
            elif change == "symlink":
                (source / "alias.csv").symlink_to(paths[0])
            elif change == "inode":
                replacement = source / "replacement"
                replacement.write_bytes(paths[-1].read_bytes())
                replacement.chmod(paths[-1].stat().st_mode & 0o777)
                replacement.replace(paths[-1])
            else:
                raise RuntimeError("controlled host exception")
            resolve_source_path(source)
    assert selected_source_resolver() is None and store.snapshot() == snapshot


def test_current_complete_tree_forwards_exact_existing_closed_worker_contract(tmp_path, monkeypatch):
    store, source, _paths, _old, expected = current_revision(tmp_path, directory=True, rheology=True)
    argv = ["inspect-current-complete-tree", str(source)]
    with current_preparation_runtime(store, store.snapshot()), native_runtime_binding(argv) as reference:
        monkeypatch.setattr(os, "getppid", os.getpid)
        with worker_project_runtime(reference, argv):
            assert inspect_runtime_source_tree(source) == expected
            assert resolve_source_path(source) == source and (source / "empty").is_dir()
    assert selected_source_resolver() is None


def test_live_scope_cannot_fall_back_to_imported_tree_after_original_drift(tmp_path):
    store, source, paths, _old, expected = current_revision(tmp_path, directory=True, rheology=True)
    cold = FileProjectStore.import_bundle(store.export_bundle(tmp_path / "bundle"), tmp_path / "cold")
    witness, files = selected_tree(cold, source, paths, expected)
    # The explicit imported view is valid, but an incoming scope still requires
    # the original admitted inode, mode and complete membership.
    assert witness.view(cold).is_dir()
    paths[-1].write_bytes(b"changed live unused input")
    with pytest.raises(ProjectStoreError):
        with incoming_source_runtime(cold, files, trees=(witness,)):
            pytest.fail("A cached old version replaced the changed live input")
