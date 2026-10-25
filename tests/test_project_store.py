"""Complete project generations and exact command outcomes, using synthetic bytes."""

from pathlib import Path
from uuid import uuid4

import pytest

from sciplot_core.project_store import (
    FileProjectStore, ProjectCommandConflict, ProjectConflict, ProjectStoreError, ResourceRoot,
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


def test_finite_zip_resource_never_imports_or_admits_sibling_files(tmp_path, monkeypatch):
    from sciplot_core.project_store import io

    root = tmp_path / "project"
    root.mkdir()
    (root / "document.vsz").write_bytes(b"native")
    archive = tmp_path / "project.zip"
    archive.write_bytes(b"synthetic archive")
    secret = tmp_path / "same-name-private.csv"
    secret.write_bytes(b"do not read sibling")
    real_read = io.read_file

    def read(fd, name, **kwargs):
        assert name != secret.name, "Finite trusted root scanned an ungranted sibling."
        return real_read(fd, name, **kwargs)

    monkeypatch.setattr(io, "read_file", read)
    store = FileProjectStore(root, locations={"snapshot": ResourceRoot(tmp_path, (archive.name,))})
    snapshot = store.snapshot(import_legacy=True)
    assert set(snapshot["files"]) == {"document.vsz", "@snapshot/project.zip"}
    with pytest.raises(ProjectStoreError):
        store.logical_path(secret)
    with pytest.raises(ProjectStoreError):
        store.reserve("ungranted", "digest", expected_generation=snapshot["generation"],
                      read_set={"@snapshot/same-name-private.csv": None}, write_set=[])
    bundle = store.export_bundle(tmp_path / "bundle")
    cold = FileProjectStore.import_bundle(bundle, tmp_path / "cold")
    reopened = FileProjectStore(cold.root)
    assert reopened.location_members == {"snapshot": ("project.zip",)}
    assert reopened.read_bytes("@snapshot/project.zip") == b"synthetic archive"
    with pytest.raises(ProjectStoreError):
        reopened.logical_path(cold.root / ".sciplot_resources/snapshot/same-name-private.csv")


def test_selected_external_source_rechecked_at_accept_and_immediately_before_head(tmp_path, monkeypatch):
    from sciplot_core.project_store import state
    from sciplot_core.project_store.io import sha

    store, snapshot = fixture_store(tmp_path)
    source = tmp_path / "external.csv"
    source.write_bytes(b"original raw source")
    source_id = uuid4().hex
    source_version = sha(source.read_bytes())
    names = ("studio/document.vsz",)
    reserve(store, snapshot, "source-preview", names)
    staged = store.stage("source-preview", "source-preview-digest", writes={names[0]: b"candidate"}, result={},
        review={"source_versions": [{"source_id": source_id, "path": str(source), "version": source_version}]})
    store.decide("source-preview", "source-preview-digest", decision_id=staged["decision_id"], accept=True)
    source.write_bytes(b"foreign raw source")
    with pytest.raises(ProjectConflict, match="source changed"):
        store.publish_staged("source-preview", "source-preview-digest")
    assert store.read_bytes(names[0]) == b"native old"
    source.write_bytes(b"original raw source")

    def change_before_head(boundary):
        if boundary == "before_head":
            source.write_bytes(b"changed at publication edge")

    monkeypatch.setattr(state, "boundary", change_before_head)
    with pytest.raises(ProjectConflict, match="source changed"):
        store.publish_staged("source-preview", "source-preview-digest")
    assert store.snapshot()["generation"] == snapshot["generation"]
    assert source.read_bytes() == b"changed at publication edge"


def test_audited_native_import_adopts_only_exact_observed_native_bytes(tmp_path, monkeypatch):
    from sciplot_core.project_commands import ProjectCommand, ProjectCommands, ProjectMutation
    from sciplot_core.project_commands.contracts import NativeAdoption
    from sciplot_core.project_store.io import sha
    from sciplot_core.project_store import state

    store, before = fixture_store(tmp_path)
    name = "studio/document.vsz"
    outside = b"explicit manual native edit"
    (store.root / name).write_bytes(outside)
    command = ProjectCommand.create("native_import", "adopt", project_id=before["project_id"],
        expected_generation=before["generation"], read_set={name: before["files"][name]["sha256"]},
        write_set=[name], request={"audit": "owned domain audit"}, native_adoptions=[NativeAdoption(
            name, before["files"][name]["sha256"], sha(outside), sha(b"synthetic audit identity"))])
    receipt = ProjectCommands(store).execute(command, lambda: ProjectMutation({name: store.root / name}, {"adopted": True}))
    assert receipt["phase"] == "complete" and store.read_bytes(name) == outside
    assert (store.root / name).read_bytes() == outside
    next_before = store.snapshot()
    observed = b"second observed manual edit"
    (store.root / name).write_bytes(observed)
    next_command = ProjectCommand.create("native_import", "adopt-edge", project_id=before["project_id"],
        expected_generation=next_before["generation"], read_set={name: next_before["files"][name]["sha256"]},
        write_set=[name], request={}, native_adoptions=[NativeAdoption(
            name, next_before["files"][name]["sha256"], sha(observed), sha(b"second audit"))])

    def drift(boundary):
        if boundary == "before_head":
            (store.root / name).write_bytes(b"third outside bytes")

    monkeypatch.setattr(state, "boundary", drift)
    with pytest.raises(ProjectConflict):
        ProjectCommands(store).execute(next_command, lambda: ProjectMutation({name: store.root / name}, {}))
    assert (store.root / name).read_bytes() == b"third outside bytes"
    assert store.snapshot()["generation"] == next_before["generation"]


def test_shared_runtime_locators_preserve_literals_after_move_and_later_commits(tmp_path):
    store, before = fixture_store(tmp_path)
    literal = str(store.root / "raw/same.csv")
    expected = before["files"]["raw/same.csv"]["sha256"]
    bundle = store.export_bundle(tmp_path / "bundle")
    store.root.rename(tmp_path / "original-unavailable")
    cold = FileProjectStore.import_bundle(bundle, tmp_path / "new-root")
    actual = cold.resolve_path(literal, expected_sha256=expected)
    assert actual == cold.root / "raw/same.csv"
    assert actual.read_bytes() == b"x,y\n1,2\n"
    assert cold.literal_path(actual) == literal
    snapshot = cold.snapshot()
    reserve(cold, snapshot)
    cold.publish("edit", "edit-digest", writes={"studio/document.vsz": b"moved native change",
        "studio/spec.json": b'{"science":1}'}, result={})
    assert cold.resolve_path(literal, expected_sha256=expected) == actual
    assert cold.literal_path(actual) == literal
    same_name = tmp_path / "same.csv"
    same_name.write_bytes(b"x,y\n1,2\n")
    with pytest.raises(ProjectConflict):
        cold.resolve_path(same_name, expected_sha256=expected)
    with pytest.raises(ProjectStoreError):
        cold.literal_path(same_name)


def test_cold_mutation_reuses_only_registered_source_version_without_changing_provenance(tmp_path):
    from sciplot_core.project_store.io import sha

    store, snapshot = fixture_store(tmp_path)
    original = tmp_path / "outside.csv"
    original.write_bytes(b"source outside project")
    source = {"source_id": uuid4().hex, "path": str(original), "version": sha(original.read_bytes())}
    reserve(store, snapshot)
    store.publish("edit", "edit-digest", writes={"studio/document.vsz": b"first", "studio/spec.json": b"spec"},
                  result={}, sources=[source])
    preserved = store.snapshot()["sources"][source["source_id"]][source["version"]]
    bundle = store.export_bundle(tmp_path / "bundle")
    store.root.rename(tmp_path / "old-project-offline")
    original.rename(tmp_path / "original-offline.csv")
    cold = FileProjectStore.import_bundle(bundle, tmp_path / "cold-project")
    current = cold.snapshot()
    reserve(cold, current, "cold-edit")
    cold.publish("cold-edit", "cold-edit-digest", writes={"studio/document.vsz": b"cold new",
        "studio/spec.json": b"spec"}, result={}, sources=[source])
    assert cold.snapshot()["sources"][source["source_id"]][source["version"]] == preserved
    assert cold.resolve_path(source["path"], expected_sha256=source["version"], source_id=source["source_id"]).read_bytes() == b"source outside project"


def test_registered_directory_is_closed_and_generated_source_views_are_idempotent(tmp_path):
    from sciplot_core.foundation.source_tree import source_tree_sha256

    store, snapshot = fixture_store(tmp_path)
    original = store.root / "raw"
    tree_sha = source_tree_sha256(original)
    actual = store.resolve_path(original, expected_sha256=tree_sha)
    assert actual.is_dir() and actual != original
    assert sorted(path.relative_to(actual).as_posix() for path in actual.rglob("*") if path.is_file()) == ["same.csv"]
    assert source_tree_sha256(actual) == tree_sha
    assert store.resolve_path(actual, expected_sha256=tree_sha) == actual
    assert store.literal_path(actual) == str(original)
    assert store.resolve_path(actual / "same.csv") == actual / "same.csv"
    assert store.literal_path(actual / "same.csv") == str(original / "same.csv")
    identity = next(iter(snapshot["sources"]))
    version = next(iter(snapshot["sources"][identity]))
    view = store.resolve_source(identity, version)
    assert store.resolve_path(view, expected_sha256=version, source_id=identity) == view
    assert store.literal_path(view) == str(original / "same.csv")
    with pytest.raises(ProjectConflict):
        store.resolve_path(view, expected_sha256="0" * 64)
    (original / "unknown.csv").write_bytes(b"unregistered raw input")
    with pytest.raises(ProjectConflict, match="unregistered"):
        store.resolve_path(original)
