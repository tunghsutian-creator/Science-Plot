"""Only one explicit imported complete tree can satisfy a sealed directory read."""

import json
import os
from pathlib import Path
import subprocess
import sys

import pytest

from sciplot_core.foundation.source_locations import (
    literal_source_path,
    resolve_source_path,
    selected_source_resolver,
)
from sciplot_core.foundation.source_tree import source_tree_sha256
from sciplot_core.project_commands import (
    PreparedSource,
    ProjectCommand,
    ProjectCommands,
    ProjectMutation,
    SourceTreeRead,
)
from sciplot_core.project_store import (
    FileProjectStore,
    ProjectConflict,
    ProjectStoreError,
)
from sciplot_core.project_store.incoming_sources import (
    SourceExpectation,
    expectation_payload,
    source_expectation_scope,
)
from sciplot_core.project_store.io import sha
from sciplot_core.project_store.runtime import (
    project_candidate_runtime,
    project_runtime,
    sealed_source_runtime,
)
from sciplot_core.project_store.sealed_source_trees import SealedSourceTree
from sciplot_core.project_store.worker_binding import (
    native_runtime_binding,
    worker_project_runtime,
)

from test_project_store import fixture_store


def test_existing_sixty_four_file_capacity_composes_with_one_complete_tree(tmp_path, monkeypatch):
    store, before = fixture_store(tmp_path)
    source = tmp_path / "sixty-four-inputs"
    source.mkdir()
    prepared = []
    for index in range(64):
        path = source / f"member-{index:02d}.csv"
        data = f"tiny,{index}\n".encode()
        path.write_bytes(data)
        path.chmod(0o644)
        prepared.append(PreparedSource(f"{index + 1:032x}", str(path), sha(data), data, (), 0o644))
    tree = SourceTreeRead(str(source), source_tree_sha256(source))
    resource = "studio/document.vsz"
    command = ProjectCommand.create("source_update", "sixty-four-files", project_id=before["project_id"],
        expected_generation=before["generation"], read_set={resource: before["files"][resource]["sha256"]},
        write_set=[resource], request={}, source_trees=[tree])
    app = ProjectCommands(store)
    review = app.preview(command, lambda: ProjectMutation({resource: b"64 captured inputs"}, {}, prepared_sources=tuple(prepared)))
    app.decide(command, decision_id=review["decision_id"], accept=True)
    cold = FileProjectStore.import_bundle(store.export_bundle(tmp_path / "bundle-64"), tmp_path / "cold-64")
    source.rename(tmp_path / "offline-64")
    scopes = [SourceExpectation(item.locator, item.source_id, item.version) for item in prepared]
    argv = ["read-complete-tree", str(source)]
    with sealed_source_runtime(cold, scopes), native_runtime_binding(argv) as reference:
        wire = json.loads(Path(reference["path"]).read_bytes())["project"]["source_expectations"]
        assert set(wire) == {"mode", "sources"} and len(wire["sources"]) == 64
        assert resolve_source_path(prepared[-1].locator).read_bytes() == prepared[-1].data
    witness = SealedSourceTree(command.key, command.command_digest, review["decision_id"], tree)
    with sealed_source_runtime(cold, scopes, trees=(witness,)), native_runtime_binding(argv) as reference:
        assert Path(reference["path"]).stat().st_size < 65536
        monkeypatch.setattr(os, "getppid", os.getpid)
        with worker_project_runtime(reference, argv):
            assert source_tree_sha256(source) == tree.tree_sha256
            assert len(list(resolve_source_path(source).glob("*.csv"))) == 64
    with pytest.raises(ProjectStoreError):
        with sealed_source_runtime(cold, []):
            pytest.fail("An empty files-and-trees scope cannot grant source IO")


def test_tree_payload_keeps_an_independent_finite_limit_and_rejects_empty_scope():
    witness = SealedSourceTree("exact-command", "a" * 64, "b" * 64, SourceTreeRead("/exact/source", "c" * 64))
    with pytest.raises(ProjectStoreError):
        expectation_payload({"mode": "sealed", "sources": [], "trees": [witness.to_payload()] * 65})
    with pytest.raises(ProjectStoreError):
        expectation_payload({"mode": "sealed", "sources": [], "trees": []})


def cold_tree(tmp_path, *, complete=True, imported=True, capture_all=True):
    store, _ = fixture_store(tmp_path)
    source = tmp_path / "original-input-directory"
    (source / "nested").mkdir(parents=True)
    (source / "empty").mkdir()
    names = ("a.csv", "nested/b.csv", "unused-notes.txt")
    identities = {
        name: character * 32 for name, character in zip(names, "abc", strict=True)
    }
    old = {}
    for name in names:
        old[name] = ("preserved v0 " + name).encode()
        (source / name).write_bytes(old[name])
        (source / name).chmod(0o644)
    prepared_v0 = tuple(
        PreparedSource(
            identities[name], str(source / name), sha(old[name]), old[name], (), 0o644
        )
        for name in names
    )
    initial = ProjectMutation({}, {}, prepared_sources=prepared_v0)
    before = store.snapshot()
    register = ProjectCommand.create(
        "attachment_import",
        "register-v0",
        project_id=before["project_id"],
        expected_generation=before["generation"],
        read_set={},
        write_set=[],
        request={"prepared_digest": initial.prepared_digest},
    )
    ProjectCommands(store).publish_prepared(register, initial)
    for name in names:
        (source / name).write_bytes(("exact captured v1 " + name).encode())
    captured = tuple(
        PreparedSource(
            identities[name],
            str(source / name),
            sha((source / name).read_bytes()),
            (source / name).read_bytes(),
            (),
            0o644,
        )
        for name in names
        if capture_all or name != "unused-notes.txt"
    )
    before = store.snapshot()
    guard = SourceTreeRead(str(source), source_tree_sha256(source))
    resource = "studio/document.vsz"
    command = ProjectCommand.create(
        "source_update",
        "full-current-tree",
        project_id=before["project_id"],
        expected_generation=before["generation"],
        read_set={resource: before["files"][resource]["sha256"]},
        write_set=[resource],
        request={"input": str(source)},
        source_trees=[guard],
    )
    app = ProjectCommands(store)
    review = app.preview(
        command,
        lambda: ProjectMutation(
            {resource: b"verified source revision"}, {}, prepared_sources=captured
        ),
    )
    if complete:
        app.decide(command, decision_id=review["decision_id"], accept=True)
    witness = SealedSourceTree(
        command.key, command.command_digest, review["decision_id"], guard
    )
    if not imported:
        return store, source, witness, captured, old
    cold = FileProjectStore.import_bundle(
        store.export_bundle(tmp_path / "bundle"), tmp_path / "cold-project"
    )
    source.rename(tmp_path / "offline-original-input")
    store.root.rename(tmp_path / "offline-original-project")
    return cold, source, witness, captured, old


@pytest.mark.parametrize("complete", [False, True])
def test_full_tree_with_unused_notes_and_empty_directory_resolves_without_source_rewrite(
    tmp_path, complete
):
    store, source, witness, prepared, old = cold_tree(tmp_path, complete=complete)
    before = store.snapshot()
    request = witness.tree.to_payload()
    file_scopes = (
        [
            SourceExpectation(item.locator, item.source_id, item.version)
            for item in prepared
        ]
        if complete
        else []
    )
    with sealed_source_runtime(store, file_scopes, trees=(witness,)):
        actual = resolve_source_path(source)
        assert source_tree_sha256(source) == witness.tree.tree_sha256
        assert source_tree_sha256(actual) == witness.tree.tree_sha256
        assert sorted(
            path.relative_to(actual).as_posix()
            for path in actual.rglob("*")
            if path.is_file()
        ) == ["a.csv", "nested/b.csv", "unused-notes.txt"]
        assert (actual / "empty").is_dir() and (
            actual / "unused-notes.txt"
        ).read_bytes().startswith(b"exact captured v1")
        assert literal_source_path(actual) == str(source)
        assert literal_source_path(actual / "nested/b.csv") == str(
            source / "nested/b.csv"
        )
        assert (
            resolve_source_path(actual / "nested/b.csv").read_bytes()
            == prepared[1].data
        )
        if complete:
            assert (
                resolve_source_path(
                    actual / "nested/b.csv",
                    source_id=prepared[1].source_id,
                    expected_sha256=prepared[1].version,
                ).read_bytes()
                == prepared[1].data
            )
        else:
            with pytest.raises(ProjectConflict):
                resolve_source_path(
                    actual / "nested/b.csv",
                    source_id=prepared[1].source_id,
                    expected_sha256=prepared[1].version,
                )
    assert (
        selected_source_resolver() is None
        and store.snapshot() == before
        and witness.tree.to_payload() == request
    )
    assert not source.exists()
    for item in prepared:
        assert (
            store.resolve_source(
                item.source_id,
                sha(old[Path(item.locator).relative_to(source).as_posix()]),
            )
            .read_bytes()
            .startswith(b"preserved v0")
        )
        if not complete:
            assert item.version not in store.snapshot()["sources"][item.source_id]
    with project_runtime(store):
        assert (
            resolve_source_path(source) == source and source_tree_sha256(source) is None
        )


def test_complete_witness_never_maps_an_undeclared_original_parent_or_cache_parent(tmp_path):
    store, source, witness, _prepared, _old = cold_tree(tmp_path)
    with sealed_source_runtime(store, [], trees=(witness,)):
        view = resolve_source_path(source)
        assert resolve_source_path(source.parent) == source.parent
        assert literal_source_path(source.parent) == str(source.parent)
        with pytest.raises(ProjectStoreError):
            resolve_source_path(view.parent)
        with pytest.raises(ProjectStoreError):
            literal_source_path(view.parent)


def test_candidate_scope_retains_complete_tree_and_original_member_literals(tmp_path):
    store, source, witness, _prepared, _old = cold_tree(tmp_path)
    private = tmp_path / "private-candidate"
    private.mkdir(mode=0o700)
    for logical, entry in store.snapshot()["files"].items():
        if logical.startswith("@"):
            continue
        path = private / logical
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(store.read_bytes(logical))
        path.chmod(entry["mode"])
    with (
        sealed_source_runtime(store, [], trees=(witness,)),
        project_candidate_runtime(store, private),
    ):
        view = resolve_source_path(source)
        assert source_tree_sha256(source) == witness.tree.tree_sha256
        assert (
            resolve_source_path(view / "nested/b.csv")
            .read_bytes()
            .startswith(b"exact captured v1")
        )
        assert literal_source_path(view / "nested/b.csv") == str(
            source / "nested/b.csv"
        )


@pytest.mark.parametrize(
    "wrong",
    [
        "key",
        "digest",
        "decision",
        "locator",
        "tree-hash",
        "file-hash",
        "duplicate",
        "incoming",
        "live",
        "partial",
    ],
)
def test_tree_scope_cannot_guess_history_parent_hash_kind_import_or_partial_members(
    tmp_path, wrong
):
    if wrong == "partial":
        with pytest.raises(ProjectConflict):
            cold_tree(tmp_path, capture_all=False, complete=False)
        return
    store, source, witness, prepared, _old = cold_tree(
        tmp_path, imported=wrong != "live"
    )
    values = {
        "command_id": witness.command_id,
        "command_digest": witness.command_digest,
        "decision_id": witness.decision_id,
        "tree": witness.tree,
    }
    if wrong == "key":
        values["command_id"] = "unknown-command"
    elif wrong == "digest":
        values["command_digest"] = "0" * 64
    elif wrong == "decision":
        values["decision_id"] = "0" * 64
    elif wrong == "locator":
        values["tree"] = SourceTreeRead(str(source.parent), witness.tree.tree_sha256)
    elif wrong in {"tree-hash", "file-hash"}:
        values["tree"] = SourceTreeRead(
            str(source), "0" * 64 if wrong == "tree-hash" else prepared[0].version
        )
    candidate = SealedSourceTree(**values)
    trees = (candidate, candidate) if wrong == "duplicate" else (candidate,)
    with pytest.raises((ProjectStoreError, ValueError)):
        if wrong == "incoming":
            with source_expectation_scope(
                store.snapshot(), "incoming", [], trees=trees, store=store
            ):
                pytest.fail("Incoming mode cannot acquire sealed tree authority")
        else:
            with sealed_source_runtime(store, [], trees=trees):
                pytest.fail("Unproven complete tree was admitted")


@pytest.mark.parametrize(
    "change",
    [
        "unused-bytes",
        "member-mode",
        "missing",
        "extra",
        "symlink",
        "directory-mode",
        "inode",
        "scope-exception",
    ],
)
def test_every_directory_resolution_revalidates_complete_import_proof_and_clears_scope(
    tmp_path, change
):
    store, source, witness, _prepared, _old = cold_tree(tmp_path)
    before = store.snapshot()
    with pytest.raises((ProjectStoreError, OSError, RuntimeError)):
        with sealed_source_runtime(store, [], trees=(witness,)):
            view = resolve_source_path(source)
            target = view / "unused-notes.txt"
            if change == "unused-bytes":
                target.chmod(0o600)
                target.write_bytes(b"changed unused note")
                target.chmod(0o400)
            elif change == "member-mode":
                target.chmod(0o600)
            elif change in {"missing", "extra", "symlink", "inode"}:
                view.chmod(0o700)
                if change == "missing":
                    target.unlink()
                elif change == "extra":
                    (view / "late.csv").write_bytes(b"not captured")
                elif change == "symlink":
                    (view / "alias.csv").symlink_to(view / "a.csv")
                else:
                    data = target.read_bytes()
                    target.unlink()
                    target.write_bytes(data)
                    target.chmod(0o400)
                view.chmod(0o500)
            elif change == "directory-mode":
                (view / "empty").chmod(0o700)
            else:
                raise RuntimeError("controlled host exception")
            source_tree_sha256(source)
    assert selected_source_resolver() is None and store.snapshot() == before


@pytest.mark.parametrize(
    "change",
    [
        "unknown-field",
        "tree-field",
        "wrong-decision",
        "missing-trees",
        "wrong-argv",
        "wrong-parent",
    ],
)
def test_tree_worker_binding_is_closed_exact_and_cleared(tmp_path, monkeypatch, change):
    store, source, witness, _prepared, _old = cold_tree(tmp_path, complete=False)
    argv = ["read-complete-tree", str(source)]
    with (
        sealed_source_runtime(store, [], trees=(witness,)),
        native_runtime_binding(argv) as reference,
    ):
        monkeypatch.setattr(os, "getppid", os.getpid)
        path = Path(reference["path"])
        payload = json.loads(path.read_bytes())
        scope = payload["project"]["source_expectations"]
        if change == "unknown-field":
            scope["trees"][0]["allow_parent"] = True
        elif change == "tree-field":
            scope["trees"][0]["tree"]["members"] = ["a.csv"]
        elif change == "wrong-decision":
            scope["trees"][0]["decision_id"] = "0" * 64
        elif change == "missing-trees":
            del scope["trees"]
        elif change == "wrong-argv":
            argv.append("other")
        else:
            payload["parent_pid"] += 1
        data = json.dumps(payload).encode()
        path.chmod(0o600)
        path.write_bytes(data)
        reference["sha256"] = sha(data)
        with pytest.raises(ProjectStoreError):
            with worker_project_runtime(reference, argv):
                pytest.fail("Unbound or partial tree witness admitted")
    assert selected_source_resolver() is None


@pytest.mark.comprehensive
def test_actual_readonly_child_inherits_pending_full_tree_without_promoting_v1_sources(
    tmp_path,
):
    store, source, witness, prepared, _old = cold_tree(tmp_path, complete=False)
    before = store.snapshot()
    argv = ["read-complete-tree", str(source)]
    script = """import json,sys
from sciplot_core.project_store.worker_binding import worker_project_runtime
from sciplot_core.foundation.source_locations import resolve_source_path,literal_source_path,selected_source_resolver
from sciplot_core.foundation.source_tree import source_tree_sha256
reference=json.loads(sys.argv[1]);argv=json.loads(sys.argv[2])
with worker_project_runtime(reference,argv):
 view=resolve_source_path(argv[1]);print(json.dumps({'tree':source_tree_sha256(argv[1]),'literal':literal_source_path(view/'unused-notes.txt'),'notes':(view/'unused-notes.txt').read_text()}))
assert selected_source_resolver() is None
"""
    with (
        sealed_source_runtime(store, [], trees=(witness,)),
        native_runtime_binding(argv) as reference,
    ):
        child = subprocess.run(
            [sys.executable, "-c", script, json.dumps(reference), json.dumps(argv)],
            text=True,
            capture_output=True,
            check=True,
            timeout=30,
        )
    assert json.loads(child.stdout) == {
        "tree": witness.tree.tree_sha256,
        "literal": str(source / "unused-notes.txt"),
        "notes": "exact captured v1 unused-notes.txt",
    }
    assert store.snapshot() == before and all(
        item.version not in before["sources"][item.source_id] for item in prepared
    )
