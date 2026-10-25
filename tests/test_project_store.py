"""Complete project generations and exact command outcomes, using synthetic bytes."""

from pathlib import Path
from uuid import uuid4

import pytest

from sciplot_core.project_store import (
    FileProjectStore, ProjectCommandConflict, ProjectConflict, ProjectStoreError,
)


def fixture_store(tmp_path):
    root = tmp_path / "project"
    root.mkdir()
    for name, data in {"studio/document.vsz": b"native old", "studio/spec.json": b'{"science":1}',
                       "raw/same.csv": b"x,y\n1,2\n", "intake_manifest.json": b'{"version":1}',
                       ".sciplot_documents/plot/revisions/0.json": b'{"sealed":"history"}'}.items():
        path = root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)
    store = FileProjectStore(root)
    return store, store.snapshot(import_legacy=True)


def reserve(store, snapshot, key="edit", names=("studio/document.vsz", "studio/spec.json")):
    reads = {name: snapshot["files"].get(name, {}).get("sha256") for name in names}
    return store.reserve(key, key + "-digest", expected_generation=snapshot["generation"],
                         read_set=reads, write_set=list(names), metadata={"kind": "synthetic"})


def test_complete_generation_cas_and_one_authoritative_head(tmp_path):
    store, before = fixture_store(tmp_path)
    assert before["sequence"] == 0 and len(before["sources"]) == 1
    reserve(store, before)
    store.mark_applying("edit", "edit-digest")
    outcome = store.publish("edit", "edit-digest", writes={
        "studio/document.vsz": b"native new", "studio/spec.json": b'{"science":1,"style":2}'}, result={"ok": True})
    after = store.snapshot()
    assert after["project_id"] == before["project_id"]
    assert after["sequence"] == 1 and after["parent"] == before["generation"]
    assert set(after["files"]) == set(before["files"])
    assert outcome["phase"] == "complete" and outcome["result"] == {"ok": True}
    assert store.read_bytes("studio/document.vsz") == b"native new"
    assert store.read_bytes("studio/document.vsz", generation=before["generation"]) == b"native old"
    assert store.query("edit")["generation"] == after["generation"]
    replay = store.publish("edit", "edit-digest", writes={}, result={"must": "not execute"})
    assert replay["result"] == outcome["result"] and store.snapshot()["sequence"] == 1


def test_live_preparation_is_admitted_once_and_unknown_is_not_reexecuted(tmp_path):
    store, snapshot = fixture_store(tmp_path)
    reserve(store, snapshot)
    assert store.mark_applying("edit", "edit-digest")["phase"] == "applying"
    with pytest.raises(ProjectCommandConflict):
        store.mark_applying("edit", "edit-digest")
    assert FileProjectStore(store.root).query("edit")["phase"] == "unknown"
    assert store.recover()["unknown_commands"] == ["edit"]
    with pytest.raises(ProjectCommandConflict):
        store.reserve("edit", "different", expected_generation=snapshot["generation"], read_set={}, write_set=[])


def test_preview_freezes_bytes_artifacts_and_exact_decision_across_reopen(tmp_path):
    store, snapshot = fixture_store(tmp_path)
    reserve(store, snapshot)
    store.mark_applying("edit", "edit-digest")
    candidate = tmp_path / "candidate.vsz"
    candidate.write_bytes(b"frozen candidate")
    staged = store.stage("edit", "edit-digest", writes={"studio/document.vsz": candidate,
        "studio/spec.json": b'{"science":1}'}, result={"preview": True}, review={"audit": "passed"},
        artifacts={"preview.png": b"synthetic image"})
    candidate.unlink()
    assert store.read_bytes("studio/document.vsz") == b"native old"
    assert Path(staged["staged_paths"]["studio/document.vsz"]).read_bytes() == b"frozen candidate"
    assert Path(staged["artifact_paths"]["preview.png"]).read_bytes() == b"synthetic image"
    reopened = FileProjectStore(store.root)
    assert reopened.query("edit")["decision_id"] == staged["decision_id"]
    with pytest.raises(ProjectCommandConflict):
        reopened.decide("edit", "edit-digest", decision_id="foreign", accept=True)
    reopened.decide("edit", "edit-digest", decision_id=staged["decision_id"], accept=True)
    outcome = reopened.publish_staged("edit", "edit-digest")
    assert outcome["phase"] == "complete"
    assert reopened.read_bytes("studio/document.vsz") == b"frozen candidate"
    with pytest.raises(ProjectCommandConflict):
        reopened.decide("edit", "edit-digest", decision_id=staged["decision_id"], accept=False)


def test_unrelated_generations_merge_but_touched_external_bytes_never_overwrite(tmp_path):
    store, snapshot = fixture_store(tmp_path)
    reserve(store, snapshot, "a", ("studio/document.vsz",))
    reserve(store, snapshot, "b", ("studio/spec.json",))
    store.publish("b", "b-digest", writes={"studio/spec.json": b"independent B"}, result={})
    store.publish("a", "a-digest", writes={"studio/document.vsz": b"independent A"}, result={})
    assert store.read_bytes("studio/spec.json") == b"independent B"
    assert store.snapshot()["sequence"] == 2
    reserve(store, store.snapshot(), "c", ("studio/document.vsz",))
    target = store.root / "studio/document.vsz"
    target.write_bytes(b"outside native save")
    with pytest.raises(ProjectConflict):
        store.publish("c", "c-digest", writes={"studio/document.vsz": b"must not install"}, result={})
    assert target.read_bytes() == b"outside native save"


def test_explicit_absence_deletion_and_trusted_delivery_root(tmp_path):
    store, _snapshot = fixture_store(tmp_path)
    delivery = tmp_path / "delivery"
    delivery.mkdir()
    store = FileProjectStore(store.root, locations={"delivery": delivery})
    snapshot = store.snapshot()
    names = ("studio/spec.json", "@delivery/document.vsz")
    reserve(store, snapshot, "delivery", names)
    store.publish("delivery", "delivery-digest", writes={
        "studio/spec.json": None, "@delivery/document.vsz": b"delivery native"}, result={})
    assert not (store.root / "studio/spec.json").exists()
    assert (delivery / "document.vsz").read_bytes() == b"delivery native"
    assert store.logical_path(delivery / "document.vsz") == "@delivery/document.vsz"
    assert store.projection_path("@delivery/document.vsz") == delivery / "document.vsz"
    with pytest.raises(ProjectStoreError):
        store.logical_path(tmp_path / "untrusted/file")


def test_complete_portable_bundle_preserves_ids_native_history_and_source_versions(tmp_path):
    store, before = fixture_store(tmp_path)
    reserve(store, before)
    store.publish("edit", "edit-digest", writes={"studio/document.vsz": b"new native",
        "studio/spec.json": b'{"science":1}'}, result={"path_literal": str(store.root / "raw/same.csv")})
    bundle = store.export_bundle(tmp_path / "bundle")
    original_source_id = next(iter(before["sources"]))
    version = next(iter(before["sources"][original_source_id]))
    locator = before["sources"][original_source_id][version]["locator"]
    moved_original = tmp_path / "original-offline"
    store.root.rename(moved_original)
    relocated = FileProjectStore.import_bundle(bundle, tmp_path / "cold relocated")
    snapshot = relocated.snapshot()
    assert snapshot["project_id"] == before["project_id"]
    assert snapshot["sequence"] == 1 and snapshot["projection_status"] == "current"
    assert relocated.read_bytes("studio/document.vsz") == b"new native"
    assert relocated.read_bytes("studio/document.vsz", generation=before["generation"]) == b"native old"
    assert relocated.read_bytes(".sciplot_documents/plot/revisions/0.json") == b'{"sealed":"history"}'
    assert relocated.resolve_locator(locator, source_id=original_source_id, version=version).read_bytes() == b"x,y\n1,2\n"
    (tmp_path / "same.csv").write_bytes(b"different same-name bytes")
    with pytest.raises(ProjectConflict):
        relocated.resolve_locator(str(tmp_path / "same.csv"), source_id=original_source_id, version=version)
    with pytest.raises(ProjectStoreError):
        relocated.resolve_source(uuid4().hex, version)
