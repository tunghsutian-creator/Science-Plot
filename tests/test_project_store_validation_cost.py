"""One checked history per operation, with fresh receipt/object authority."""

from collections import Counter
import json
import os
from copy import deepcopy
from uuid import uuid4

import pytest

from sciplot_core.project_store import FileProjectStore, ProjectStoreError
from sciplot_core.project_store.io import StoreIO, sha
from sciplot_core.project_store import state


def populated(tmp_path, count=8):
    root = tmp_path / "project"
    root.mkdir()
    (root / "document.vsz").write_bytes(b"initial")
    store = FileProjectStore(root)
    snapshot = store.snapshot(import_legacy=True)
    for number in range(count):
        key = f"command-{number}"
        store.reserve(key, key, expected_generation=snapshot["generation"],
            read_set={"document.vsz": snapshot["files"]["document.vsz"]["sha256"]}, write_set=["document.vsz"])
        store.publish(key, key, writes={"document.vsz": str(number).encode()}, result={"number": number})
        snapshot = store.snapshot()
    return store, snapshot


@pytest.mark.parametrize("entry", ["commands", "recover"])
def test_one_operation_reads_history_linearly_and_keeps_complete_receipt_census(tmp_path, monkeypatch, entry):
    store, snapshot = populated(tmp_path)
    reads = Counter()
    original = StoreIO.read
    def observed(io, name):
        reads[name] += 1
        return original(io, name)
    monkeypatch.setattr(StoreIO, "read", observed)
    getattr(store, entry)()
    generations = sum(count for name, count in reads.items() if name.startswith("generations/"))
    assert generations <= 2 * (snapshot["sequence"] + 1), reads
    assert {state.command_path(key) for key in snapshot["commands"]} <= set(reads)


@pytest.mark.parametrize("change", ["receipt", "missing", "history", "blob"])
def test_a_new_read_revalidates_receipt_history_and_exact_blob_without_mtime_trust(tmp_path, change):
    store, snapshot = populated(tmp_path, 3)
    assert len(store.commands()) == 3
    if change in {"receipt", "missing"}:
        path = store.root / ".sciplot_store" / state.command_path("command-0")
    elif change == "history":
        path = store.root / ".sciplot_store/generations" / (snapshot["parent"] + ".json")
    else:
        record = store.query("command-0")
        entry = record["draft"]["writes"]["document.vsz"]
        path = store.root / ".sciplot_store/objects" / entry["sha256"][:2] / entry["sha256"]
    stat = path.stat()
    if change == "missing":
        path.unlink()
    elif change == "blob":
        path.write_bytes(b"foreign")
    else:
        value = json.loads(path.read_text())
        value["result" if change == "receipt" else "origin"] = "foreign"
        path.write_text(json.dumps(value))
    if path.exists():
        os.utime(path, ns=(stat.st_atime_ns, stat.st_mtime_ns))
    with pytest.raises(ProjectStoreError):
        store.commands()


def test_checked_history_excludes_unpublished_bytes_and_expires_after_nested_writes(tmp_path):
    store, snapshot = populated(tmp_path, 2)
    with store._checked_locked() as (io, current, checked):
        candidate = deepcopy(current)
        candidate.update(generation=uuid4().hex, parent=current["generation"], parent_sha256=state.digest(current),
                         sequence=current["sequence"] + 1)
        state.write_generation(io, candidate)
        with pytest.raises(ProjectStoreError, match="boundary"):
            state.reachable(io, current, snapshot["generation"], checked=checked)
        refreshed = state.checked_head(io)
        with pytest.raises(ProjectStoreError, match="not committed"):
            state.reachable(io, refreshed.current, candidate["generation"], checked=refreshed)
        store.reserve("nested", "nested", expected_generation=current["generation"], read_set={}, write_set=[])
        store.publish("nested", "nested", writes={}, result={})
        with pytest.raises(ProjectStoreError, match="boundary"):
            state.reachable(io, refreshed.current, current["generation"], checked=refreshed)
        assert store.snapshot()["sequence"] == snapshot["sequence"] + 1
    with pytest.raises(ProjectStoreError, match="boundary"):
        checked.require(io, current)


def test_public_snapshot_has_no_writable_history_authority_alias(tmp_path):
    store, snapshot = populated(tmp_path, 2)
    snapshot["files"]["document.vsz"]["sha256"] = "0" * 64
    assert store.snapshot()["outside_changes"] == {}
    assert len(store.commands()) == 2


def test_raw_snapshot_dictionary_cannot_mint_checked_history(tmp_path):
    store, snapshot = populated(tmp_path, 1)
    with store._checked_locked() as (io, _current, _checked):
        with pytest.raises(ProjectStoreError, match="fully verified"):
            state.CheckedHead(io, snapshot, {snapshot["generation"]: snapshot})


def test_completed_read_validation_cannot_be_used_as_an_installation_plan(tmp_path):
    import sciplot_core.project_store.projection as projection

    store, _snapshot = populated(tmp_path, 2)
    physical = (store.root / "document.vsz").read_bytes()
    with store._checked_locked() as (io, current, _checked):
        record = state.command(io, "command-0")
        with pytest.raises(ProjectStoreError, match="completed receipt"):
            projection.project(io, record, current)
    assert (store.root / "document.vsz").read_bytes() == physical


def test_empty_recovery_rejects_an_expired_explicit_context(tmp_path):
    import sciplot_core.project_store.projection as projection

    store, _snapshot = populated(tmp_path, 0)
    with store._checked_locked() as (io, current, checked):
        checked.close()
        with pytest.raises(ProjectStoreError, match="boundary"):
            projection.recover(io, current, checked=checked)


def test_failed_nested_read_admission_closes_its_proof_while_parent_fd_is_live(tmp_path, monkeypatch):
    import sciplot_core.project_store.projection as projection

    store, _snapshot = populated(tmp_path, 0)
    original, captured = state.checked_head, []
    def observe(io):
        checked = original(io)
        captured.append(checked)
        return checked
    def refused(*_args):
        raise RuntimeError("read admission stopped")
    with store._checked_locked(allow_pending=True) as (io, current, parent):
        with monkeypatch.context() as scoped:
            scoped.setattr(state, "checked_head", observe)
            scoped.setattr(projection, "pending", refused)
            with pytest.raises(RuntimeError, match="read admission stopped"), store._checked_locked():
                pass
        failed = captured[-1]
        with pytest.raises(ProjectStoreError, match="boundary"):
            failed.require(io, failed.current)
        parent.require(io, current)


def test_direct_io_history_proof_cannot_cross_a_reopened_lease_with_reused_fd(tmp_path):
    store, _snapshot = populated(tmp_path, 0)
    io = StoreIO(store.root, {})
    with io.locked():
        checked = state.checked_head(io)
    with io.locked():
        with pytest.raises(ProjectStoreError, match="boundary"):
            checked.require(io, checked.current)


@pytest.mark.parametrize("entry", ["query", "missing", "reserve", "stage", "decide", "publish", "publish_staged"])
def test_one_admission_shares_history_with_all_read_and_replay_helpers(tmp_path, monkeypatch, entry):
    store, snapshot = populated(tmp_path, 2)
    receipt = store.query("command-1")
    reads, objects = Counter(), Counter()
    original_read, original_get = StoreIO.read, StoreIO.get
    def read(io, name):
        reads[name] += 1
        return original_read(io, name)
    def get(io, item):
        objects[item["sha256"]] += 1
        return original_get(io, item)
    with StoreIO(store.root, {}).locked() as io:
        fd, epoch = io.fd, io.validation_epoch
        monkeypatch.setattr(StoreIO, "read", read)
        monkeypatch.setattr(StoreIO, "get", get)
        for number in range(2):
            if entry in {"query", "missing"}:
                result = store.query("absent" if entry == "missing" else "command-1")
                assert result is None if entry == "missing" else result == receipt
            elif entry == "reserve":
                result = store.reserve("command-1", "command-1", expected_generation=snapshot["generation"],
                                       read_set={}, write_set=[])
            elif entry == "stage":
                result = store.stage("command-1", "command-1", writes={}, result={}, review={})
            elif entry == "decide":
                result = store.decide("command-1", "command-1", decision_id=receipt["decision_id"], accept=True)
            elif entry == "publish_staged":
                result = store.publish_staged("command-1", "command-1")
            else:
                result = store.publish("command-1", "command-1", writes={}, result={})
            if entry != "missing":
                assert result["result"] == receipt["result"]
                assert result["generation"] == receipt["generation"]
                assert state.command_path("command-1") in reads
            assert reads["head.json"] == number + 1
            assert sum(count for name, count in reads.items() if name.startswith("generations/")) == (
                number + 1) * (snapshot["sequence"] + 1)
            assert io.fd == fd and io.validation_epoch == epoch
        # Each public call is a fresh window even under the very same live FD.
        assert objects[snapshot["files"]["document.vsz"]["sha256"]] >= 2


def test_nested_read_proof_ownership_is_separate_from_the_parent(tmp_path):
    store, _snapshot = populated(tmp_path, 0)
    with store._checked_locked() as (io, current, parent):
        with store._checked_locked() as (inner_io, inner_current, child):
            assert inner_io is io and child is not parent
            child.require(io, inner_current)
            parent.require(io, current)
        parent.require(io, current)
        with pytest.raises(ProjectStoreError, match="boundary"):
            child.require(io, inner_current)
        with pytest.raises(ProjectStoreError, match="boundary"):
            parent.require(io, deepcopy(current))


@pytest.mark.parametrize("change", ["receipt", "missing", "history", "blob"])
def test_external_round_trip_in_same_lease_rechecks_bytes_even_with_preserved_mtime(tmp_path, change):
    store, snapshot = populated(tmp_path, 2)
    with StoreIO(store.root, {}).locked() as io:
        receipt = store.query("command-0")
        fd, epoch = io.fd, io.validation_epoch
        if change in {"receipt", "missing"}:
            path = store.root / ".sciplot_store" / state.command_path("command-0")
        elif change == "history":
            path = store.root / ".sciplot_store/generations" / (snapshot["parent"] + ".json")
        else:
            entry = receipt["draft"]["writes"]["document.vsz"]
            path = store.root / ".sciplot_store/objects" / entry["sha256"][:2] / entry["sha256"]
        before, data = path.stat(), path.read_bytes()
        if change == "missing":
            path.unlink()
        else:
            # Same length as well as same mtime; no stat-only PASS may survive.
            changed = data.replace(b'"number": 0', b'"number": 9') if change == "receipt" else (
                data.replace(b'explicit_legacy_import', b'foreign__legacy_import') if change == "history" else b"x" * len(data))
            if changed == data:  # This historical generation was authored by publication.
                changed = data.replace(b'"sequence": 1', b'"sequence": 9')
            assert changed != data and len(changed) == len(data)
            path.write_bytes(changed)
            os.utime(path, ns=(before.st_atime_ns, before.st_mtime_ns))
        assert io.fd == fd and io.validation_epoch == epoch
        with pytest.raises(ProjectStoreError):
            store.query("command-0")


@pytest.mark.parametrize("change", ["put", "existing_put", "failed_put", "members", "roots", "locations", "backups"])
def test_checked_window_rejects_blob_mutation_or_capability_rebinding(tmp_path, change):
    store, _snapshot = populated(tmp_path, 0)
    with store._checked_locked() as (io, current, checked):
        if change == "put":
            io.put(b"new immutable candidate")
        elif change == "existing_put":
            entry = current["files"]["document.vsz"]
            path = store.root / ".sciplot_store/objects" / entry["sha256"][:2] / entry["sha256"]
            before = path.stat()
            io.put(b"initial")
            assert path.read_bytes() == b"initial" and path.stat().st_mtime_ns == before.st_mtime_ns
        elif change == "failed_put":
            entry = current["files"]["document.vsz"]
            path = store.root / ".sciplot_store/objects" / entry["sha256"][:2] / entry["sha256"]
            path.write_bytes(b"foreign")
            with pytest.raises(ProjectStoreError, match="conflicting bytes"):
                io.put(b"initial")
        elif change == "members":
            io.location_members["outside"] = ("neighbor",)
        elif change == "roots":
            io.root_fds["outside"] = io.fd
        elif change == "locations":
            io.locations["outside"] = store.root
        else:
            io.namespace_backups["outside"] = store.root
        try:
            with pytest.raises(ProjectStoreError, match="boundary"):
                checked.require(io, current)
        finally:
            # These direct test mutations must not alter the lease's own cleanup.
            io.root_fds.pop("outside", None)
            io.location_members.pop("outside", None)
            io.locations.pop("outside", None)
            io.namespace_backups.pop("outside", None)


def interrupted_head(tmp_path, monkeypatch):
    store, snapshot = populated(tmp_path, 0)
    store.reserve("pending", "pending", expected_generation=snapshot["generation"],
                  read_set={"document.vsz": snapshot["files"]["document.vsz"]["sha256"]}, write_set=["document.vsz"])
    def interrupt(name):
        if name == "after_head":
            raise RuntimeError("head interruption")
    with monkeypatch.context() as scoped:
        scoped.setattr(state, "boundary", interrupt)
        with pytest.raises(RuntimeError, match="head interruption"):
            store.publish("pending", "pending", writes={"document.vsz": b"pending"}, result={"pending": True})
    return store


def test_recovery_borrows_only_its_pre_mutation_head_and_refreshes_after_receipt_save(tmp_path, monkeypatch):
    store = interrupted_head(tmp_path, monkeypatch)
    reads = Counter()
    original = StoreIO.read
    def read(io, name):
        reads[name] += 1
        return original(io, name)
    monkeypatch.setattr(StoreIO, "read", read)
    assert store.recover()["phase"] == "complete"
    assert reads["head.json"] == 2  # Initial admission and fresh proof after receipt save.
    assert (store.root / "document.vsz").read_bytes() == b"pending"
    assert store.query("pending")["result"] == {"pending": True}


def test_relocation_external_io_ends_proof_even_without_an_epoch_change(tmp_path, monkeypatch):
    import sciplot_core.project_store.projection as projection

    store = interrupted_head(tmp_path, monkeypatch)
    def external_round_trip(io, current):
        epoch = io.validation_epoch
        entry = current["files"]["document.vsz"]
        path = store.root / ".sciplot_store/objects" / entry["sha256"][:2] / entry["sha256"]
        before = path.stat()
        path.write_bytes(b"foreign")
        os.utime(path, ns=(before.st_atime_ns, before.st_mtime_ns))
        assert io.validation_epoch == epoch
        return True  # Physical relocation performed; no old proof may be borrowed.
    monkeypatch.setattr(projection, "relocate", external_round_trip)
    with pytest.raises(ProjectStoreError, match="identity"):
        store.recover()
    assert (store.root / "document.vsz").read_bytes() == b"initial"


@pytest.mark.parametrize("boundary", ["after_head", "before_projection"])
def test_publication_and_physical_install_fences_reject_preserved_mtime_external_changes(tmp_path, monkeypatch, boundary):
    store, snapshot = populated(tmp_path, 0)
    store.reserve("pending", "pending", expected_generation=snapshot["generation"],
                  read_set={"document.vsz": snapshot["files"]["document.vsz"]["sha256"]}, write_set=["document.vsz"])
    def change(name):
        if name != boundary:
            return
        if boundary == "after_head":
            path = store.root / ".sciplot_store/objects" / sha(b"pending")[:2] / sha(b"pending")
        else:
            path = store.root / "document.vsz"
        before = path.stat()
        path.write_bytes(b"foreign")
        os.utime(path, ns=(before.st_atime_ns, before.st_mtime_ns))
    monkeypatch.setattr(state, "boundary", change)
    with pytest.raises(ProjectStoreError):
        store.publish("pending", "pending", writes={"document.vsz": b"pending"}, result={})
    assert (store.root / "document.vsz").read_bytes() == (b"initial" if boundary == "after_head" else b"foreign")


@pytest.mark.parametrize("helper", ["public", "project", "recover"])
def test_failed_helper_closes_only_its_owned_head_proof(tmp_path, monkeypatch, helper):
    from sciplot_core.project_store import commands, projection

    store, _snapshot = populated(tmp_path, 1)
    captured, original = [], state.checked_head
    def capture(io):
        checked = original(io)
        captured.append(checked)
        return checked
    with store._checked_locked() as (io, current, parent):
        monkeypatch.setattr(state, "checked_head", capture)
        with pytest.raises(ProjectStoreError):
            if helper == "public":
                commands.public(io, {"kind": "foreign"})
            elif helper == "project":
                projection.project(io, {"phase": "accepted"}, {**current, "generation": "0" * 32})
            else:
                projection.recover(io, {**current, "generation": "0" * 32})
        assert len(captured) == 1
        with pytest.raises(ProjectStoreError, match="boundary"):
            captured[0].require(io, captured[0].current)
        parent.require(io, current)


def test_checked_proof_does_not_cross_thread_ownership(tmp_path):
    from concurrent.futures import ThreadPoolExecutor

    store, _snapshot = populated(tmp_path, 0)
    with store._checked_locked() as (io, current, checked):
        with ThreadPoolExecutor(max_workers=1) as worker:
            with pytest.raises(ProjectStoreError, match="boundary"):
                worker.submit(checked.require, io, current).result()
        checked.require(io, current)


def test_publication_rechecks_actual_original_source_after_staging(tmp_path, monkeypatch):
    root = tmp_path / "source-project"
    root.mkdir()
    (root / "document.vsz").write_bytes(b"initial")
    source = tmp_path / "original.csv"
    source.write_bytes(b"1,2\n")
    store = FileProjectStore(root)
    snapshot = store.snapshot(import_legacy=True)
    source_id, version = uuid4().hex, sha(source.read_bytes())
    store.reserve("source", "source", expected_generation=snapshot["generation"],
                  read_set={"document.vsz": snapshot["files"]["document.vsz"]["sha256"]}, write_set=["document.vsz"])
    staged = store.stage("source", "source", writes={"document.vsz": b"new"}, result={}, review={},
                         sources=[{"source_id": source_id, "version": version, "path": str(source)}])
    store.decide("source", "source", decision_id=staged["decision_id"], accept=True)
    reached = []
    def external_save(name):
        if name == "before_head":
            reached.append(name)
            before = source.stat()
            source.write_bytes(b"3,4\n")
            os.utime(source, ns=(before.st_atime_ns, before.st_mtime_ns))
    monkeypatch.setattr(state, "boundary", external_save)
    with pytest.raises(ProjectStoreError, match="source changed"):
        store.publish_staged("source", "source")
    assert reached == ["before_head"]
    assert store.snapshot()["generation"] == snapshot["generation"]
    assert (root / "document.vsz").read_bytes() == b"initial"
    assert source.read_bytes() == b"3,4\n"


@pytest.mark.parametrize("tamper", [False, True])
def test_historical_leaf_borrows_history_but_consumes_fresh_exact_object_each_time(tmp_path, monkeypatch, tamper):
    store, snapshot = populated(tmp_path, 3)
    receipt = store.query("command-0")
    reads, objects = Counter(), Counter()
    original_read, original_get = StoreIO.read, StoreIO.get
    def read(io, name):
        reads[name] += 1
        return original_read(io, name)
    def get(io, entry):
        objects[entry["sha256"]] += 1
        return original_get(io, entry)
    with StoreIO(store.root, {}).locked() as io:
        fd, epoch = io.fd, io.validation_epoch
        monkeypatch.setattr(StoreIO, "read", read)
        monkeypatch.setattr(StoreIO, "get", get)
        assert store.read_bytes("document.vsz", generation=receipt["generation"]) == b"0"
        historic = receipt["draft"]["writes"]["document.vsz"]
        if tamper:
            path = store.root / ".sciplot_store/objects" / historic["sha256"][:2] / historic["sha256"]
            before = path.stat()
            path.write_bytes(b"x")
            os.utime(path, ns=(before.st_atime_ns, before.st_mtime_ns))
            with pytest.raises(ProjectStoreError, match="identity"):
                store.read_bytes("document.vsz", generation=receipt["generation"])
        else:
            assert store.read_bytes("document.vsz", generation=receipt["generation"]) == b"0"
        assert io.fd == fd and io.validation_epoch == epoch
        assert reads["head.json"] == 2
        assert sum(count for name, count in reads.items() if name.startswith("generations/")) == 2 * (snapshot["sequence"] + 1)
        assert objects[historic["sha256"]] == 2
        assert objects[snapshot["files"]["document.vsz"]["sha256"]] == 2


@pytest.mark.parametrize("helper", ["public", "project", "recover"])
def test_failed_helper_borrow_cannot_close_its_callers_proof(tmp_path, monkeypatch, helper):
    from sciplot_core.project_store import commands, projection

    store, _snapshot = populated(tmp_path, 0)
    with store._checked_locked() as (io, current, checked):
        with pytest.raises(ProjectStoreError):
            if helper == "public":
                commands.public(io, {"kind": "foreign"}, checked=checked)
            elif helper == "project":
                projection.project(io, {"phase": "accepted"}, current, checked=checked)
            else:
                monkeypatch.setattr(state, "read_commands", lambda *_args, **_kwargs: [{"kind": "foreign"}])
                projection.recover(io, current, checked=checked)
        checked.require(io, current)
