"""Recovery plans are bound to published outcomes, never mutable receipt hints."""

import json

import pytest

from sciplot_core.project_store import FileProjectStore, ProjectStoreError
from sciplot_core.project_store import state


class Interrupted(RuntimeError):
    pass


def create(tmp_path):
    root = tmp_path / "project"
    root.mkdir()
    (root / "document.vsz").write_bytes(b"original")
    (root / "spec.json").write_bytes(b"original spec")
    store = FileProjectStore(root)
    return store, store.snapshot(import_legacy=True)


def publish(store, snapshot, key, data, *, monkeypatch=None, fault=None):
    store.reserve(key, key + "-digest", expected_generation=snapshot["generation"],
        read_set={"document.vsz": snapshot["files"]["document.vsz"]["sha256"]}, write_set=["document.vsz"])
    store.mark_applying(key, key + "-digest")
    if fault is None:
        return store.publish(key, key + "-digest", writes={"document.vsz": data}, result={"key": key})
    def stop(name):
        if name == fault:
            raise Interrupted(name)
    with monkeypatch.context() as scoped:
        scoped.setattr(state, "boundary", stop)
        with pytest.raises(Interrupted, match=fault):
            store.publish(key, key + "-digest", writes={"document.vsz": data}, result={"key": key})


def rewrite(store, key, **changes):
    path = store.root / ".sciplot_store" / state.command_path(key)
    record = json.loads(path.read_text())
    path.write_text(json.dumps({**record, **changes}))


def physical_files(root):
    return {str(path.relative_to(root)): (path.read_bytes(), path.stat().st_mtime_ns)
            for path in root.rglob("*") if path.is_file()}


def test_unpublished_generation_cannot_replace_the_committed_recovery_plan(tmp_path, monkeypatch):
    store, before = create(tmp_path)
    generations = store.root / ".sciplot_store/generations"
    existing = set(generations.glob("*.json"))
    publish(store, before, "unpublished-B", b"B must never become active", monkeypatch=monkeypatch, fault="after_generation")
    noise, = set(generations.glob("*.json")) - existing
    publish(store, before, "committed-A", b"A exact committed bytes", monkeypatch=monkeypatch, fault="after_head")
    rewrite(store, "committed-A", install_generation=noise.stem)
    unchanged = physical_files(store.root)
    with pytest.raises(ProjectStoreError):
        FileProjectStore(store.root).recover()
    assert physical_files(store.root) == unchanged
    assert (store.root / "document.vsz").read_bytes() == b"original"


@pytest.mark.parametrize("hint", ["install_parent", "install_files"])
def test_mutable_parent_or_installation_members_cannot_change_recovery(tmp_path, monkeypatch, hint):
    store, oldest = create(tmp_path)
    publish(store, oldest, "previous", b"previous committed")
    before = store.snapshot()
    publish(store, before, "pending", b"pending exact bytes", monkeypatch=monkeypatch, fault="after_head")
    if hint == "install_parent":
        # Outside bytes from an older ancestor are neither the immediate parent
        # nor this command's new state, and must never be overwritten.
        (store.root / "document.vsz").write_bytes(b"original")
        (store.root / "document.vsz").chmod(oldest["files"]["document.vsz"]["mode"])
        rewrite(store, "pending", install_parent=oldest["generation"])
    else:
        rewrite(store, "pending", install_files=[])
    unchanged = physical_files(store.root)
    with pytest.raises(ProjectStoreError):
        FileProjectStore(store.root).recover()
    assert physical_files(store.root) == unchanged
    assert (store.root / "document.vsz").read_bytes() == (b"original" if hint == "install_parent" else b"previous committed")


@pytest.mark.parametrize("changes", [
    {"kind": "foreign"}, {"version": 2}, {"project_id": "0" * 32},
    {"command_digest": "foreign"}, {"result": {"foreign": True}},
    {"review": {"foreign": True}}, {"metadata": {"foreign": True}},
    {"read_set": {}}, {"write_set": []}, {"projected_reads": [{"foreign": True}]},
    {"decision_id": "0" * 64}, {"accepted": False}, {"phase": "applying"},
    {"draft": {}}, {"pending_result": {"foreign": True}},
    {"namespace_origins": {"foreign": True}}, {"source_tree_origins": {"foreign": True}},
    {"install_generation": None}, {"install_parent": None},
    {"install_files": ["document.vsz", "spec.json"]},
])
def test_query_and_recovery_share_exact_immutable_receipt_validation(tmp_path, monkeypatch, changes):
    store, before = create(tmp_path)
    publish(store, before, "pending", b"new", monkeypatch=monkeypatch, fault="after_head")
    rewrite(store, "pending", **changes)
    unchanged = physical_files(store.root)
    for inspect in (lambda: store.query("pending"), store.commands, store.recover):
        with pytest.raises(ProjectStoreError):
            inspect()
        assert physical_files(store.root) == unchanged


def test_valid_pending_recovery_and_stale_receipt_never_roll_back_later_head(tmp_path, monkeypatch):
    store, before = create(tmp_path)
    publish(store, before, "first", b"first", monkeypatch=monkeypatch, fault="after_head")
    pending_record = json.loads((store.root / ".sciplot_store" / state.command_path("first")).read_text())
    receipt = store.query("first")
    assert receipt["phase"] == "accepted" and receipt["projection_pending"] is True
    assert store.recover()["phase"] == "complete"
    assert (store.root / "document.vsz").read_bytes() == b"first"
    publish(store, store.snapshot(), "later", b"later exact bytes")
    later_head = (store.root / ".sciplot_store/head.json").read_bytes()
    rewrite(store, "first", **pending_record)
    target_before = (store.root / "document.vsz").stat().st_mtime_ns
    assert store.recover()["phase"] == "complete"
    assert (store.root / "document.vsz").read_bytes() == b"later exact bytes"
    assert (store.root / "document.vsz").stat().st_mtime_ns == target_before
    assert (store.root / ".sciplot_store/head.json").read_bytes() == later_head
    assert store.query("first")["generation"] == receipt["committed_generation"]
    assert store.query("later")["phase"] == "complete"


def test_disjoint_later_head_preserves_the_original_pending_resource_plan(tmp_path, monkeypatch):
    store, before = create(tmp_path)
    publish(store, before, "first", b"first", monkeypatch=monkeypatch, fault="after_head")
    pending_record = json.loads((store.root / ".sciplot_store" / state.command_path("first")).read_text())
    store.recover()
    newer = store.snapshot()
    store.reserve("disjoint", "digest", expected_generation=newer["generation"],
        read_set={"spec.json": newer["files"]["spec.json"]["sha256"]}, write_set=["spec.json"])
    store.publish("disjoint", "digest", writes={"spec.json": b"new spec"}, result={})
    head = (store.root / ".sciplot_store/head.json").read_bytes()
    rewrite(store, "first", **pending_record)
    (store.root / "document.vsz").write_bytes(b"original")
    (store.root / "document.vsz").chmod(before["files"]["document.vsz"]["mode"])
    assert store.recover()["phase"] == "complete"
    assert (store.root / "document.vsz").read_bytes() == b"first"
    assert (store.root / "spec.json").read_bytes() == b"new spec"
    assert (store.root / ".sciplot_store/head.json").read_bytes() == head


@pytest.mark.parametrize("old_bytes", [b"original", b"first"])
@pytest.mark.parametrize("later_bytes", [b"latest author owns this resource", None], ids=["write", "delete"])
def test_old_receipt_cannot_reacquire_a_resource_written_by_a_descendant(tmp_path, monkeypatch, old_bytes, later_bytes):
    store, before = create(tmp_path)
    publish(store, before, "first", b"first", monkeypatch=monkeypatch, fault="after_head")
    pending_record = json.loads((store.root / ".sciplot_store" / state.command_path("first")).read_text())
    store.recover()
    own_mode = store.snapshot()["files"]["document.vsz"]["mode"]
    publish(store, store.snapshot(), "later", later_bytes)
    rewrite(store, "first", **pending_record)
    (store.root / "document.vsz").write_bytes(old_bytes)
    (store.root / "document.vsz").chmod(before["files"]["document.vsz"]["mode"] if old_bytes == b"original" else own_mode)
    unchanged = physical_files(store.root)
    with pytest.raises(ProjectStoreError):
        store.recover()
    assert physical_files(store.root) == unchanged


@pytest.mark.parametrize("corrupt", [False, True])
def test_cold_relocation_checks_receipts_before_materializing_any_active_bytes(tmp_path, monkeypatch, corrupt):
    import sciplot_core.project_store.projection as projection

    store, before = create(tmp_path)
    publish(store, before, "pending", b"exact portable native", monkeypatch=monkeypatch, fault="after_head")
    # Export intentionally requires completed projections. The import fault below
    # is the supported cold boundary; it leaves no active target bytes yet.
    assert store.recover()["phase"] == "complete"
    bundle = store.export_bundle(tmp_path / "bundle")
    target = tmp_path / "cold"
    with monkeypatch.context() as scoped:
        def interrupted(_io, _current):
            raise Interrupted("before cold projection")
        scoped.setattr(projection, "relocate", interrupted)
        with pytest.raises(Interrupted, match="before cold projection"):
            FileProjectStore.import_bundle(bundle, target)
    cold = FileProjectStore(target)
    assert not (target / "document.vsz").exists()
    assert not (target / "spec.json").exists()
    if corrupt:
        rewrite(cold, "pending", install_files=[])
        unchanged = physical_files(target)
        with pytest.raises(ProjectStoreError):
            cold.recover()
        assert physical_files(target) == unchanged
        assert not (target / "document.vsz").exists()
    else:
        assert cold.recover()["phase"] == "complete"
        assert (target / "document.vsz").read_bytes() == b"exact portable native"
        assert cold.query("pending")["phase"] == "complete"
        assert cold.snapshot()["outside_changes"] == {}
