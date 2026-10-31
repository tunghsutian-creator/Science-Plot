"""Finite checked-history reuse cannot retain bytes, authority, or old fences."""

from collections import Counter
from copy import deepcopy
import os
from uuid import uuid4

import pytest

from sciplot_core.project_store import FileProjectStore, ProjectStoreError, state
from sciplot_core.project_store.io import StoreIO, owned_io, sha
from sciplot_core.project_store.source_resolver import ProjectSourceResolver


def store_with_files(tmp_path):
    root = tmp_path / "project"
    root.mkdir()
    (root / "A.bin").write_bytes(b"A")
    (root / "B.bin").write_bytes(b"B")
    store = FileProjectStore(root)
    return store, store.snapshot(import_legacy=True)


def publish(store, writes):
    current = store.snapshot()
    key = uuid4().hex
    store.reserve(key, key, expected_generation=current["generation"],
                  read_set={name: current["files"].get(name, {}).get("sha256") for name in writes}, write_set=list(writes))
    store.publish(key, key, writes=writes, result={})


def count_reads(monkeypatch):
    reads, gets = Counter(), Counter()
    original_read, original_get = StoreIO.read, StoreIO.get
    def read(io, name):
        reads[name] += 1
        return original_read(io, name)
    def get(io, entry):
        gets[entry["sha256"]] += 1
        return original_get(io, entry)
    monkeypatch.setattr(StoreIO, "read", read)
    monkeypatch.setattr(StoreIO, "get", get)
    return reads, gets


def corrupt_object(store, entry):
    path = store.root / ".sciplot_store/objects" / entry["sha256"][:2] / entry["sha256"]
    before = path.stat()
    path.write_bytes(b"x" * before.st_size)
    os.utime(path, ns=(before.st_atime_ns, before.st_mtime_ns))


def test_finite_window_checks_history_once_but_consumes_each_actual_blob(tmp_path, monkeypatch):
    store, original = store_with_files(tmp_path)
    publish(store, {"A.bin": b"C"})
    snapshot = store.snapshot()
    reads, gets = count_reads(monkeypatch)
    with store._validation_window():
        for _ in range(3):
            assert store.snapshot()["generation"] == snapshot["generation"]
            assert store.read_bytes("A.bin") == b"C"
            assert store.read_bytes("A.bin", generation=original["generation"]) == b"A"
            assert len(store.commands()) == 1
        assert reads["head.json"] == 1
        assert sum(n for name, n in reads.items() if name.startswith("generations/")) == snapshot["sequence"] + 1
        assert gets[sha(b"A")] >= 3 and gets[sha(b"C")] >= 3
    store.snapshot()
    assert reads["head.json"] == 2


@pytest.mark.parametrize("role", ["snapshot", "head", "historical", "resolver", "state_head"])
def test_public_metadata_cannot_poison_a_window_proof_through_nested_aliases(tmp_path, role):
    store, old = store_with_files(tmp_path)
    publish(store, {"A.bin": b"C"})
    with store._validation_window():
        if role == "snapshot":
            value = store.snapshot()
        elif role == "resolver":
            value = ProjectSourceResolver(store).snapshot
        elif role == "state_head":
            value = state.head(owned_io(store.root))
        else:
            observation = store.observe_members(generation=old["generation"] if role == "historical" else None)
            value = observation.selected if role == "historical" else observation.head
        value["files"]["A.bin"] = deepcopy(value["files"]["B.bin"])
        assert store.read_bytes("A.bin") == b"C"
        assert store.read_bytes("A.bin", generation=old["generation"]) == b"A"


def test_window_exit_expires_borrowed_children_even_with_the_same_live_fd(tmp_path):
    store, _snapshot = store_with_files(tmp_path)
    with StoreIO(store.root, {}).locked() as io:
        with store._validation_window():
            child = state.checked_head(io)
            child.require(io, child.current)
        assert io.fd >= 0
        with pytest.raises(ProjectStoreError, match="boundary"):
            child.require(io, child.current)
        corrupt_object(store, child.current["files"]["B.bin"])
        with pytest.raises(ProjectStoreError, match="identity"):
            store.read_bytes("A.bin")


def test_nested_window_and_admission_lifetimes_do_not_close_the_parent(tmp_path):
    store, _snapshot = store_with_files(tmp_path)
    with store._validation_window():
        io = owned_io(store.root)
        parent = state.checked_head(io)
        with store._validation_window():
            child = state.checked_head(io)
        with pytest.raises(ProjectStoreError, match="boundary"):
            child.require(io, child.current)
        parent.require(io, parent.current)
        with pytest.raises(RuntimeError, match="nested failure"):
            with store._validation_window():
                failed = state.checked_head(io)
                raise RuntimeError("nested failure")
        with pytest.raises(ProjectStoreError, match="boundary"):
            failed.require(io, failed.current)
        parent.require(io, parent.current)
        assert store.read_bytes("A.bin") == b"A"


def test_window_cannot_survive_reacquiring_the_same_io_and_fd(tmp_path):
    store, _snapshot = store_with_files(tmp_path)
    io = StoreIO(store.root, {})
    with io.locked():
        proof = state.checked_head(io)
        window = state.validation_window(io, proof)
        window.__enter__()
    try:
        with io.locked():
            with pytest.raises(ProjectStoreError, match="boundary"):
                state.checked_head(io)
    finally:
        window.__exit__(None, None, None)
        proof.close()


@pytest.mark.parametrize("write", ["metadata", "blob", "failed_blob"])
def test_persistent_writes_and_failed_write_attempts_require_fresh_history(tmp_path, monkeypatch, write):
    store, snapshot = store_with_files(tmp_path)
    reads, _gets = count_reads(monkeypatch)
    with store._validation_window():
        io = owned_io(store.root)
        old = state.checked_head(io)
        assert reads["head.json"] == 1
        if write == "metadata":
            io.write("diagnostic.json", {"value": "new"})
        elif write == "blob":
            io.put(b"new blob")
        else:
            corrupt_object(store, snapshot["files"]["A.bin"])
            with pytest.raises(ProjectStoreError, match="conflicting bytes"):
                io.put(b"A")
        with pytest.raises(ProjectStoreError, match="boundary"):
            old.require(io, old.current)
        if write == "failed_blob":
            with pytest.raises(ProjectStoreError, match="identity"):
                store.read_bytes("B.bin")
        else:
            assert store.read_bytes("B.bin") == b"B"
        assert reads["head.json"] == 2


@pytest.mark.parametrize("failed", [False, True])
def test_external_fence_rechecks_unconsumed_objects_even_with_preserved_mtime(tmp_path, failed):
    store, snapshot = store_with_files(tmp_path)
    with store._validation_window():
        io = owned_io(store.root)
        assert store.read_bytes("A.bin") == b"A"
        if failed:
            with pytest.raises(RuntimeError, match="external failure"):
                with io.validation_fence():
                    corrupt_object(store, snapshot["files"]["B.bin"])
                    raise RuntimeError("external failure")
        else:
            with io.validation_fence():
                corrupt_object(store, snapshot["files"]["B.bin"])
        with pytest.raises(ProjectStoreError, match="identity"):
            store.read_bytes("A.bin")


def test_real_source_verification_fence_does_not_reuse_history_after_external_io(tmp_path, monkeypatch):
    from sciplot_core.project_store import commands

    store, snapshot = store_with_files(tmp_path)
    raw = tmp_path / "original.csv"
    raw.write_bytes(b"1,2\n")
    version = sha(raw.read_bytes())
    source = {"sha256": version, "version": version, "size": raw.stat().st_size, "locator": str(raw)}
    original = commands.read_file
    def read_file(fd, name, *, owned=False):
        value = original(fd, name, owned=owned)
        corrupt_object(store, snapshot["files"]["B.bin"])
        return value
    monkeypatch.setattr(commands, "read_file", read_file)
    with store._validation_window():
        assert store.read_bytes("A.bin") == b"A"
        commands.verify_sources(owned_io(store.root), {"source": {version: source}})
        with pytest.raises(ProjectStoreError, match="identity"):
            store.read_bytes("A.bin")


@pytest.mark.parametrize("drift", ["members", "roots", "locations", "backups"])
def test_capability_drift_is_not_silently_refreshed_after_an_epoch_change(tmp_path, drift):
    store, _snapshot = store_with_files(tmp_path)
    with store._validation_window():
        io = owned_io(store.root)
        io.write("diagnostic.json", {})
        if drift == "members":
            io.location_members["foreign"] = ("outside",)
        elif drift == "roots":
            io.root_fds["foreign"] = io.fd
        elif drift == "locations":
            io.locations["foreign"] = store.root
        else:
            io.namespace_backups["foreign"] = store.root
        try:
            with pytest.raises(ProjectStoreError, match="boundary"):
                state.checked_head(io)
        finally:
            io.location_members.pop("foreign", None)
            io.root_fds.pop("foreign", None)
            io.locations.pop("foreign", None)
            io.namespace_backups.pop("foreign", None)


def test_actual_fingerprint_window_ends_before_the_next_backend_call(tmp_path, monkeypatch):
    from sciplot_core.plot_backends import veusz_identity
    from sciplot_core.studio_core import project_command_scope

    store, _snapshot = store_with_files(tmp_path)
    monkeypatch.setattr(project_command_scope, "project_store", lambda project: store)
    actual = veusz_identity.existing_file_sha256
    observations = []
    def existing_file_sha256(path):
        io = owned_io(store.root)
        observations.append(io is not None and io._checked_window is not None)
        return actual(path)
    monkeypatch.setattr(veusz_identity, "existing_file_sha256", existing_file_sha256)
    binding = {"project": str(store.root), "document": str(store.root / "A.bin"),
               "files": {str(store.root / "A.bin"): sha(b"A"), str(store.root / "B.bin"): sha(b"B")},
               "source_trees": {}}
    fingerprint = veusz_identity.fingerprint(binding)
    assert all(observations) and len(observations) == 2
    assert fingerprint["files"] == binding["files"]
    assert owned_io(store.root) is None


@pytest.mark.parametrize("replay", [False, True])
def test_window_does_not_preempt_the_existing_pending_repair_owner(tmp_path, monkeypatch, replay):
    store, snapshot = store_with_files(tmp_path)
    store.reserve("interrupted", "interrupted", expected_generation=snapshot["generation"],
                  read_set={"A.bin": snapshot["files"]["A.bin"]["sha256"]}, write_set=["A.bin"])
    def interrupt(name):
        if name == "after_head":
            raise RuntimeError("head interruption")
    with monkeypatch.context() as scoped:
        scoped.setattr(state, "boundary", interrupt)
        with pytest.raises(RuntimeError, match="head interruption"):
            store.publish("interrupted", "interrupted", writes={"A.bin": b"C"}, result={})
    assert (store.root / "A.bin").read_bytes() == b"A"
    with store._validation_window():
        key = "interrupted" if replay else "next"
        record = store.reserve(key, key, expected_generation=snapshot["generation"],
                               read_set={"B.bin": snapshot["files"]["B.bin"]["sha256"]}, write_set=[])
        assert record["phase"] == ("complete" if replay else "reserved")
        assert store.read_bytes("A.bin") == b"C"
    assert (store.root / "A.bin").read_bytes() == b"C"


def test_prepared_replay_recovers_its_exact_after_head_interruption_inside_the_window(tmp_path, monkeypatch):
    from sciplot_core.project_commands import ProjectCommand, ProjectCommands, ProjectMutation

    store, snapshot = store_with_files(tmp_path)
    candidate = ProjectMutation({"A.bin": b"C"}, {"candidate": "prepared"})
    command = ProjectCommand.create("semantic_record", "prepared-replay", project_id=snapshot["project_id"],
        expected_generation=snapshot["generation"], read_set={"A.bin": snapshot["files"]["A.bin"]["sha256"]},
        write_set=["A.bin"], request={"prepared_digest": candidate.prepared_digest})
    app = ProjectCommands(store)
    def interrupt(name):
        if name == "after_head":
            raise RuntimeError("prepared head interruption")
    with monkeypatch.context() as scoped:
        scoped.setattr(state, "boundary", interrupt)
        with pytest.raises(RuntimeError, match="prepared head interruption"), store._validation_window():
            app.publish_prepared(command, candidate)
    assert (store.root / "A.bin").read_bytes() == b"A"
    with store._validation_window():
        replayed = app.publish_prepared(command, candidate)
    assert replayed["phase"] == "complete" and replayed["replayed"] is True
    assert (store.root / "A.bin").read_bytes() == b"C"
    assert store.query(command.key)["result"] == candidate.result


def test_fingerprint_keeps_its_original_pending_projection_rejection(tmp_path, monkeypatch):
    from sciplot_core.plot_backends import veusz_identity
    from sciplot_core.studio_core import project_command_scope

    store, snapshot = store_with_files(tmp_path)
    store.reserve("pending", "pending", expected_generation=snapshot["generation"],
                  read_set={"A.bin": snapshot["files"]["A.bin"]["sha256"]}, write_set=["A.bin"])
    def interrupt(name):
        if name == "after_head":
            raise RuntimeError("pending head")
    with monkeypatch.context() as scoped:
        scoped.setattr(state, "boundary", interrupt)
        with pytest.raises(RuntimeError, match="pending head"):
            store.publish("pending", "pending", writes={"A.bin": b"C"}, result={})
    monkeypatch.setattr(project_command_scope, "project_store", lambda project: store)
    with pytest.raises(ProjectStoreError, match="recover"):
        veusz_identity.fingerprint({"project": str(store.root), "document": str(store.root / "A.bin"),
                                   "files": {str(store.root / "A.bin"): sha(b"A")}, "source_trees": {}})
    assert (store.root / "A.bin").read_bytes() == b"A"


def test_prepared_publication_uses_the_window_after_source_capture_and_reduces_history_reads(tmp_path, monkeypatch):
    from contextlib import contextmanager
    from test_project_member_observation import project
    from sciplot_core.project_lifecycle import attached_repository

    counts = {}
    captured = []
    actual_sources = attached_repository.prepared_sources
    def prepared_sources(store, sources, *, force=frozenset()):
        io = owned_io(store.root)
        captured.append(io is None or io._checked_window is None)
        return actual_sources(store, sources, force=force)
    def observed_read(reads, actual_read):
        def read(io, name):
            reads[name] += 1
            return actual_read(io, name)
        return read
    monkeypatch.setattr(attached_repository, "prepared_sources", prepared_sources)
    for enabled in (False, True):
        store, repository, _snapshot = project(tmp_path / str(enabled))
        reads = Counter()
        actual_read = StoreIO.read
        @contextmanager
        def no_window(self):
            yield
        with monkeypatch.context() as scoped:
            scoped.setattr(StoreIO, "read", observed_read(reads, actual_read))
            if not enabled:
                scoped.setattr(FileProjectStore, "_validation_window", no_window)
            repository.write(repository.attachment.root / "new.json", {"value": "prepared"})
        counts[enabled] = reads["head.json"]
        assert repository.read(repository.attachment.root / "new.json") == {"value": "prepared"}
        assert store.snapshot()["projection_status"] == "current"
        assert all(record["phase"] == "complete" for record in store.commands())
    assert all(captured) and len(captured) == 2
    assert counts[True] < counts[False], counts
    print(f"prepared_publication_history_reads={counts}")


@pytest.mark.parametrize("owner", ["thread", "process"])
def test_window_proof_cannot_cross_process_or_thread_ownership(tmp_path, monkeypatch, owner):
    from concurrent.futures import ThreadPoolExecutor

    store, _snapshot = store_with_files(tmp_path)
    with store._validation_window():
        io = owned_io(store.root)
        parent = state.checked_head(io)
        if owner == "thread":
            with ThreadPoolExecutor(max_workers=1) as worker:
                with pytest.raises(ProjectStoreError, match="boundary"):
                    worker.submit(state.checked_head, io).result()
        else:
            current_pid = os.getpid()
            with monkeypatch.context() as scoped:
                scoped.setattr(state.os, "getpid", lambda: current_pid + 1)
                with pytest.raises(ProjectStoreError, match="boundary"):
                    state.checked_head(io)
        parent.require(io, parent.current)


def test_caught_actual_blob_failure_expires_cache_and_already_borrowed_children(tmp_path):
    store, snapshot = store_with_files(tmp_path)
    with store._validation_window():
        io = owned_io(store.root)
        assert store.read_bytes("A.bin") == b"A"
        child = state.checked_head(io)
        corrupt_object(store, snapshot["files"]["B.bin"])
        with pytest.raises(ProjectStoreError, match="identity"):
            store.read_bytes("B.bin")
        with pytest.raises(ProjectStoreError, match="boundary"):
            child.require(io, child.current)
        with pytest.raises(ProjectStoreError, match="identity"):
            store.read_bytes("A.bin")


def test_actual_metadata_io_failure_expires_proof_but_normal_absence_does_not(tmp_path, monkeypatch):
    store, _snapshot = store_with_files(tmp_path)
    reads, _gets = count_reads(monkeypatch)
    with store._validation_window():
        io = owned_io(store.root)
        child = state.checked_head(io)
        assert io.read("ordinary-absence.json") is None
        assert io.physical("ordinary-absence.bin") is None
        with pytest.raises(ProjectStoreError, match="not a member"):
            store.read_bytes("ordinary-absence.bin")
        child.require(io, child.current)
        assert reads["head.json"] == 1
        (store.root / ".sciplot_store/invalid.json").write_bytes(b"{invalid")
        with pytest.raises(ValueError):
            io.read("invalid.json")
        with pytest.raises(ProjectStoreError, match="boundary"):
            child.require(io, child.current)
        assert store.read_bytes("A.bin") == b"A"
        assert reads["head.json"] == 2


def test_failed_actual_physical_source_check_expires_proof_without_hiding_projection_drift(tmp_path, monkeypatch):
    from sciplot_core.project_store.locators import checked_member

    store, _snapshot = store_with_files(tmp_path)
    reads, _gets = count_reads(monkeypatch)
    with store._validation_window():
        io = owned_io(store.root)
        child = state.checked_head(io)
        (store.root / "B.bin").write_bytes(b"x")
        with pytest.raises(ProjectStoreError, match="resource view"):
            checked_member(io, child.current, "B.bin", None)
        with pytest.raises(ProjectStoreError, match="boundary"):
            child.require(io, child.current)
        assert store.read_bytes("A.bin") == b"A"
        assert reads["head.json"] == 2
        assert store.snapshot()["projection_status"] == "conflict"


def test_fingerprint_catch_continuation_cannot_borrow_history_after_a_bad_blob(tmp_path, monkeypatch):
    from sciplot_core.plot_backends import veusz_identity
    from sciplot_core.studio_core import project_command_scope

    store, _snapshot = store_with_files(tmp_path)
    publish(store, {"C.bin": b"C"})
    snapshot = store.snapshot()
    monkeypatch.setattr(project_command_scope, "project_store", lambda project: store)
    actual = veusz_identity.existing_file_sha256
    def existing_file_sha256(path):
        value = actual(path)
        if path == store.root / "A.bin":
            corrupt_object(store, snapshot["files"]["B.bin"])
        return value
    monkeypatch.setattr(veusz_identity, "existing_file_sha256", existing_file_sha256)
    binding = {"project": str(store.root), "document": str(store.root / "A.bin"), "source_trees": {},
               "files": {str(store.root / name): sha(value) for name, value in (("A.bin", b"A"), ("B.bin", b"B"), ("C.bin", b"C"))}}
    observed = veusz_identity.fingerprint(binding)
    assert observed["files"][str(store.root / "A.bin")] == sha(b"A")
    assert observed["files"][str(store.root / "B.bin")] is None
    assert observed["files"][str(store.root / "C.bin")] is None


@pytest.mark.parametrize("failure", ["missing", "identity", "kind", "version"])
def test_required_generation_validation_failure_expires_history_but_bad_query_input_does_not(tmp_path, failure):
    import json

    store, old = store_with_files(tmp_path)
    publish(store, {"A.bin": b"C"})
    with store._validation_window():
        io = owned_io(store.root)
        child = state.checked_head(io)
        with pytest.raises(ProjectStoreError, match="identity"):
            state.generation(io, "invalid user identity")
        with pytest.raises(ProjectStoreError, match="not committed"):
            store.read_bytes("A.bin", generation=uuid4().hex)
        child.require(io, child.current)
        path = store.root / ".sciplot_store/generations" / (old["generation"] + ".json")
        if failure == "missing":
            path.unlink()
        else:
            value = json.loads(path.read_bytes())
            value[{"identity": "generation", "kind": "kind", "version": "version"}[failure]] = "bad"
            path.write_text(json.dumps(value))
        with pytest.raises(ProjectStoreError, match="generation is missing"):
            state.generation(io, old["generation"])
        with pytest.raises(ProjectStoreError, match="boundary"):
            child.require(io, child.current)
        with pytest.raises(ProjectStoreError, match="generation is missing"):
            store.read_bytes("A.bin")


def test_physical_identity_failure_expires_children_and_snapshot_keeps_its_negative_contract(tmp_path):
    store, snapshot = store_with_files(tmp_path)
    with store._validation_window():
        io = owned_io(store.root)
        child = state.checked_head(io)
        os.link(store.root / "B.bin", tmp_path / "outside-hardlink")
        with pytest.raises(ProjectStoreError, match="hard-linked"):
            io.physical("B.bin")
        with pytest.raises(ProjectStoreError, match="boundary"):
            child.require(io, child.current)
        observed = store.snapshot()
        assert observed["generation"] == snapshot["generation"]
        assert observed["projection_status"] == "conflict"
        assert "hard-linked" in observed["outside_metadata"]["B.bin"]
        assert store.read_bytes("A.bin") == b"A"


@pytest.mark.parametrize("drift", ["blob", "canonical"])
def test_projection_negative_cannot_hide_concurrent_canonical_corruption_or_replacement(tmp_path, monkeypatch, drift):
    import json
    from sciplot_core.project_store import ProjectConflict
    from sciplot_core.project_store.io import digest

    store, snapshot = store_with_files(tmp_path)
    actual = StoreIO.physical
    changed = False
    def physical(io, logical, *, owned=True):
        nonlocal changed
        if not changed:
            changed = True
            if drift == "blob":
                corrupt_object(store, snapshot["files"]["B.bin"])
            else:
                value = deepcopy(snapshot)
                for field in ("projection_status", "outside_changes", "outside_metadata"):
                    value.pop(field)
                value["origin"] = "changed canonical metadata"
                metadata = store.root / ".sciplot_store"
                (metadata / "generations" / (value["generation"] + ".json")).write_text(json.dumps(value))
                pointer = json.loads((metadata / "head.json").read_bytes())
                pointer["sha256"] = digest(value)
                (metadata / "head.json").write_text(json.dumps(pointer))
            # Use the actual integrity-failure path, caught by snapshot as data.
            os.link(store.root / logical, tmp_path / "outside-hardlink")
        return actual(io, logical, owned=owned)
    with store._validation_window():
        monkeypatch.setattr(StoreIO, "physical", physical)
        with pytest.raises(ProjectConflict, match="identity" if drift == "blob" else "canonical head changed"):
            store.snapshot()
