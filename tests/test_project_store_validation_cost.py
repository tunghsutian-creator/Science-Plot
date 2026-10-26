"""One checked history per operation, with fresh receipt/object authority."""

from collections import Counter
import json
import os
from copy import deepcopy
from uuid import uuid4

import pytest

from sciplot_core.project_store import FileProjectStore, ProjectStoreError
from sciplot_core.project_store.io import StoreIO
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
    with store._locked(allow_pending=True) as (io, _current):
        with monkeypatch.context() as scoped:
            scoped.setattr(state, "checked_head", observe)
            scoped.setattr(projection, "pending", refused)
            with pytest.raises(RuntimeError, match="read admission stopped"), store._checked_locked():
                pass
        failed = captured[-1]
        with pytest.raises(ProjectStoreError, match="boundary"):
            failed.require(io, failed.current)


def test_direct_io_history_proof_cannot_cross_a_reopened_lease_with_reused_fd(tmp_path):
    store, _snapshot = populated(tmp_path, 0)
    io = StoreIO(store.root, {})
    with io.locked():
        checked = state.checked_head(io)
    with io.locked():
        with pytest.raises(ProjectStoreError, match="boundary"):
            checked.require(io, checked.current)
