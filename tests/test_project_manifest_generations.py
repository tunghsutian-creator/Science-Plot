"""Manifest mirrors and complete ZIP candidates share the generation head."""

import json
from io import BytesIO
from zipfile import ZipFile
import pytest

from sciplot_core.project_manifest import (
    _manifest_store,
    commit_intake_project_manifest,
    stage_intake_project_manifest,
)
from sciplot_core.project_store import FileProjectStore
from sciplot_core.project_store.adapters import publish_files


def test_staging_zip_uses_pending_whole_project_without_installing(tmp_path):
    root = tmp_path / "project"
    root.mkdir()
    (root / "source.csv").write_bytes(b"old source")
    (root / "intake_manifest.json").write_text('{"project_slug":"project"}')
    store = _manifest_store(root, {"project_slug": "project"})
    before = store.snapshot(import_legacy=True)
    payload = {"project_slug": "project", "new_run": "runs/new/result.json"}
    overlay = {"source.csv": b"new source", "runs/new/result.json": b"new result"}
    staged = stage_intake_project_manifest(root, payload, store=store, project_writes=overlay)
    assert store.snapshot()["generation"] == before["generation"]
    assert (root / "source.csv").read_bytes() == b"old source"
    assert not (root / "runs").exists()
    with ZipFile(BytesIO(staged["@snapshot/project.zip"])) as archive:
        assert archive.read("project/source.csv") == b"new source"
        assert archive.read("project/runs/new/result.json") == b"new result"
        assert json.loads(archive.read("project/intake_manifest.json")) == payload
    publish_files(store, {**overlay, **staged}, kind="publish")
    assert (root / "source.csv").read_bytes() == b"new source"
    assert (tmp_path / "project.zip").read_bytes() == staged["@snapshot/project.zip"]


def test_cold_project_adds_only_finite_local_snapshot_capability(tmp_path):
    root = tmp_path / "origin"
    root.mkdir()
    (root / "intake_manifest.json").write_text('{"project_slug":"portable"}')
    store = FileProjectStore(root)
    store.snapshot(import_legacy=True)
    store.export_bundle(tmp_path / "bundle")
    cold = FileProjectStore.import_bundle(tmp_path / "bundle", tmp_path / "cold")
    payload = {"project_slug": "portable", "cold": True}
    commit_intake_project_manifest(cold.root, payload)
    selected = _manifest_store(cold.root, payload)
    staged = stage_intake_project_manifest(cold.root, payload, store=selected)
    publish_files(selected, staged, kind="publish")
    reopened = FileProjectStore(cold.root)
    assert reopened.location_members == {"snapshot": ("portable.zip",)}
    assert reopened.locations["snapshot"] == cold.root / ".sciplot_resources/snapshot"
    assert reopened.read_bytes("@snapshot/portable.zip") == staged["@snapshot/portable.zip"]
    assert not (tmp_path / "portable.zip").exists()


def test_pure_run_registration_preserves_inputs_and_all_scientific_metadata(tmp_path):
    from copy import deepcopy
    from sciplot_core.workflow.project_state import _project_manifest_after_run

    existing = {"project_slug": "existing", "studio": {"status": "prepared"}}
    run = {"created_at": "saved", "output": str(tmp_path / "run"), "figures": ["exact.pdf"],
           "study_model": {"source_id": "unchanged"}, "transform_ledger": {"pin": "same"},
           "publication_qa": {"status": "passed"}, "qa": {"status": "passed"}}
    before_existing, before_run = deepcopy(existing), deepcopy(run)
    result = _project_manifest_after_run(existing, run)
    assert existing == before_existing and run == before_run
    assert result["studio"] == {"status": "prepared"}
    assert result["last_run"]["figures"] == ["exact.pdf"]
    assert result["study_model"] == result["last_run"]["study_model"] == run["study_model"]
    assert result["transform_ledger"] == run["transform_ledger"]
    result["study_model"]["source_id"] = "private result change"
    assert run == before_run


def test_manifest_read_preserves_explicit_host_caps_and_needs_no_unrelated_projection(tmp_path):
    root = tmp_path / "project"
    root.mkdir()
    (root / "intake_manifest.json").write_text('{"project_slug":"project"}')
    delivery = tmp_path / "delivery"
    delivery.mkdir()
    selected = FileProjectStore(root, locations={"delivery": delivery})
    selected.snapshot(import_legacy=True)
    publish_files(selected, {"@delivery/result.pdf": b"exact delivery"}, kind="publish")
    from sciplot_core.project_manifest import read_intake_project_manifest
    assert read_intake_project_manifest(root, store=selected) == {"project_slug": "project"}
    assert read_intake_project_manifest(root) == {"project_slug": "project"}
    assert selected.locations == {"delivery": delivery}
    assert (delivery / "result.pdf").read_bytes() == b"exact delivery"


def test_zip_and_project_seal_same_candidate_bytes_and_executable_mode(tmp_path):
    from sciplot_core.project_commands.resources import PreparedFile

    root = tmp_path / "project"
    root.mkdir()
    (root / "intake_manifest.json").write_text('{"project_slug":"project"}')
    store = _manifest_store(root, {"project_slug": "project"})
    store.snapshot(import_legacy=True)
    candidate = tmp_path / "candidate.command"
    candidate.write_bytes(b"#!/bin/sh\nexit 0\n")
    candidate.chmod(0o755)
    captured = candidate.read_bytes()
    staged = stage_intake_project_manifest(root, {"project_slug": "project"}, store=store,
        project_writes={"launch.command": candidate})
    assert staged["launch.command"] == PreparedFile(captured, 0o755)
    candidate.write_bytes(b"changed after archive staging")
    publish_files(store, {"launch.command": candidate, **staged}, kind="publish")
    assert (root / "launch.command").read_bytes() == captured
    assert (root / "launch.command").stat().st_mode & 0o777 == 0o755
    with ZipFile(BytesIO(staged["@snapshot/project.zip"])) as archive:
        assert archive.read("project/launch.command") == captured
        assert archive.getinfo("project/launch.command").external_attr >> 16 & 0o777 == 0o755


@pytest.mark.parametrize("fault", [None, "missing-adoption", "old-hash", "observed-hash", "write-bytes", "mode", "source", "unknown"])
def test_native_adoption_zip_is_the_same_frozen_single_generation_mutation(tmp_path, fault):
    from dataclasses import replace
    from sciplot_core.project_commands import NativeAdoption, ProjectCommand, ProjectCommands, ProjectMutation, MembershipRead
    from sciplot_core.project_store import ProjectConflict
    from sciplot_core.project_store.io import sha

    root = tmp_path / "project"
    native, source = root / "studio/document.vsz", root / "raw/original.csv"
    native.parent.mkdir(parents=True)
    source.parent.mkdir()
    native.write_bytes(b"registered native")
    source.write_bytes(b"original scientific cells")
    payload = {"project_slug": "project"}
    (root / "intake_manifest.json").write_text(json.dumps(payload))
    store = _manifest_store(root, payload)
    before = store.snapshot(import_legacy=True)
    observed = b"observed and domain-audited presentation"
    native.write_bytes(observed)
    proof = NativeAdoption("studio/document.vsz", before["files"]["studio/document.vsz"]["sha256"], sha(observed), "a" * 64)
    if fault == "old-hash":
        proof = replace(proof, before_sha256="b" * 64)
    elif fault == "observed-hash":
        proof = replace(proof, observed_sha256="c" * 64)
    elif fault == "mode":
        native.chmod(0o600 if native.stat().st_mode & 0o777 != 0o600 else 0o644)
    elif fault == "source":
        source.write_bytes(b"tampered scientific cells")
    elif fault == "unknown":
        (root / "unknown.txt").write_bytes(b"unregistered member")
    overlay = {"studio/document.vsz": b"not the audited bytes" if fault == "write-bytes" else native}
    physical = {name: path.read_bytes() for name, path in (("native", native), ("source", source))}
    kwargs = dict(store=store, project_writes=overlay, native_adoptions=[] if fault == "missing-adoption" else [proof])
    if fault not in {None, "unknown"}:
        with pytest.raises(ProjectConflict):
            stage_intake_project_manifest(root, payload, **kwargs)
        assert store.snapshot()["generation"] == before["generation"] and not store.commands()
    else:
        staged = stage_intake_project_manifest(root, payload, **kwargs)
        assert store.snapshot()["generation"] == before["generation"] and not store.commands()
        with ZipFile(BytesIO(staged["@snapshot/project.zip"])) as archive:
            assert archive.read("project/studio/document.vsz") == observed
            assert archive.read("project/raw/original.csv") == physical["source"]
            assert "project/unknown.txt" not in archive.namelist()
        command = ProjectCommand.create("native_import", "audited-native-and-zip-one-head", project_id=before["project_id"],
            expected_generation=before["generation"], read_set={name: before["files"].get(name, {}).get("sha256")
                for name in set(before["files"]) | set(staged)}, write_set=list(staged), request={}, native_adoptions=[proof],
            read_memberships=[MembershipRead.capture(before["files"], "")])
        if fault == "unknown":
            with pytest.raises(ProjectConflict):
                ProjectCommands(store).execute(command, lambda: ProjectMutation(staged, {}))
            assert store.snapshot()["generation"] == before["generation"] and (root / "unknown.txt").read_bytes() == b"unregistered member"
        else:
            ProjectCommands(store).execute(command, lambda: ProjectMutation(staged, {}))
            after = store.snapshot()
            assert after["sequence"] == before["sequence"] + 1 and not after["outside_changes"]
            assert "studio/document.vsz" not in after.get("input_resources", [])
            assert all(entry.get("locator") != str(native) for versions in after["sources"].values() for entry in versions.values())
            assert len(store.commands()) == 1 and store.read_bytes("@snapshot/project.zip") == staged["@snapshot/project.zip"]
    assert native.read_bytes() == physical["native"] and source.read_bytes() == physical["source"]


def _snapshot_project(tmp_path):
    root = tmp_path / "project"
    root.mkdir()
    payload = {"project_slug": "project"}
    (root / "intake_manifest.json").write_text(json.dumps(payload))
    (root / "source.csv").write_bytes(b"x,y\n1,2\n")
    (root / "launch.command").write_bytes(b"#!/bin/sh\nexit 0\n")
    (root / "launch.command").chmod(0o755)
    (root / "remove.txt").write_bytes(b"removed from candidate")
    store = _manifest_store(root, payload)
    original = store.snapshot(import_legacy=True)
    publish_files(store, {"old.txt": b"old generation"}, kind="publish")
    return store, payload, original


def test_snapshot_observes_finite_retained_members_once_and_keeps_exact_archive(tmp_path, monkeypatch):
    from collections import Counter
    from sciplot_core import project_manifest
    from sciplot_core.project_commands.resources import PreparedFile
    from sciplot_core.project_store.io import StoreIO

    store, payload, _original = _snapshot_project(tmp_path)
    publish_files(store, {"@snapshot/project.zip": b"previous archive"}, kind="publish")
    (store.root / "unregistered.txt").write_bytes(b"not a generation member")
    before = store.snapshot()
    writes = {"remove.txt": None, "old.txt": PreparedFile(b"replacement", 0o640),
              "new.txt": PreparedFile(b"new member", 0o600)}
    reads, observations = Counter(), []
    read, observe = StoreIO.read, store.observe_members

    def counted(io, name):
        reads[name] += 1
        return read(io, name)

    def observed(names=(), **kwargs):
        observations.append((tuple(names), kwargs))
        return observe(names, **kwargs)

    with monkeypatch.context() as scoped:
        scoped.setattr(StoreIO, "read", counted)
        scoped.setattr(store, "observe_members", observed)
        first = project_manifest._stage_snapshot(store, payload, writes)
    retained = tuple(name for name in before["files"] if not name.startswith("@") and name not in writes)
    assert observations == [((), {"import_legacy": False}),
                            (retained, {"generation": before["generation"], "projection": False})]
    assert reads["head.json"] == 2
    assert first == project_manifest._stage_snapshot(store, payload, writes)
    with ZipFile(BytesIO(first)) as archive:
        assert set(archive.namelist()) == {"project/" + name for name in (*retained, "old.txt", "new.txt")}
        assert archive.read("project/source.csv") == b"x,y\n1,2\n"
        assert archive.read("project/launch.command") == b"#!/bin/sh\nexit 0\n"
        assert archive.read("project/old.txt") == b"replacement"
        assert archive.read("project/new.txt") == b"new member"
        assert archive.getinfo("project/launch.command").external_attr >> 16 & 0o777 == 0o755
        assert archive.getinfo("project/old.txt").external_attr >> 16 & 0o777 == 0o640
    assert store.snapshot() == before
    assert (store.root / "remove.txt").read_bytes() == b"removed from candidate"


def test_snapshot_with_no_retained_members_still_materializes_only_overlays(tmp_path):
    from sciplot_core.project_manifest import _stage_snapshot
    from sciplot_core.project_commands.resources import PreparedFile

    store, payload, _original = _snapshot_project(tmp_path)
    before = store.snapshot()
    writes = dict.fromkeys(before["files"])
    writes["only.txt"] = PreparedFile(b"only new member", 0o600)
    result = _stage_snapshot(store, payload, writes)
    with ZipFile(BytesIO(result)) as archive:
        assert archive.namelist() == ["project/only.txt"]
        assert archive.read("project/only.txt") == b"only new member"
    assert store.snapshot() == before


@pytest.mark.parametrize("fault", ["missing-object", "object", "history", "mode", "source", "unreachable"])
def test_snapshot_batch_keeps_original_generation_and_byte_refusals(tmp_path, monkeypatch, fault):
    import os
    from sciplot_core.project_manifest import _stage_snapshot
    from sciplot_core.project_store import ProjectStoreError

    store, payload, _original = _snapshot_project(tmp_path)
    snapshot = store.snapshot()
    if fault in {"missing-object", "object"}:
        key = snapshot["files"]["source.csv"]["sha256"]
        path = store.root / ".sciplot_store/objects" / key[:2] / key
    elif fault == "history":
        path = store.root / ".sciplot_store/generations" / (snapshot["parent"] + ".json")
    else:
        path = store.root / "source.csv"
    stat = path.stat()
    if fault == "missing-object":
        path.unlink()
    elif fault == "object":
        path.write_bytes(b"x" * stat.st_size)
    elif fault == "history":
        value = json.loads(path.read_bytes())
        value["origin"] = "foreign history"
        path.write_text(json.dumps(value))
    elif fault == "mode":
        path.chmod(0o600 if stat.st_mode & 0o777 != 0o600 else 0o644)
    elif fault == "source":
        path.write_bytes(b"x,y\n9,9\n")
    else:
        snapshot["generation"] = "f" * 32
        monkeypatch.setattr(store, "snapshot", lambda: snapshot)
    if path.exists() and fault != "mode":
        os.utime(path, ns=(stat.st_atime_ns, stat.st_mtime_ns))
    with pytest.raises((ProjectStoreError, OSError)):
        _stage_snapshot(store, payload, {})
    assert not (tmp_path / "project.zip").exists()


@pytest.mark.parametrize("outer_lease", [False, True])
def test_snapshot_callback_has_no_borrowed_proof_and_next_admission_is_fresh(tmp_path, outer_lease):
    from contextlib import nullcontext
    from sciplot_core.project_manifest import _stage_snapshot
    from sciplot_core.project_store import ProjectStoreError
    from sciplot_core.project_store.io import StoreIO, owned_io
    from sciplot_core.foundation.project_archives import write_project_archive

    store, payload, _original = _snapshot_project(tmp_path)
    before = store.snapshot()
    key = before["files"]["source.csv"]["sha256"]
    object_path = store.root / ".sciplot_store/objects" / key[:2] / key

    def writer(candidate, _payload):
        active = owned_io(store.root)
        assert active is None or active._checked_window is None
        object_path.write_bytes(b"foreign object")
        with pytest.raises(ProjectStoreError, match="identity"):
            store.read_bytes("source.csv")
        write_project_archive(candidate, candidate.parent / "project.zip")

    with StoreIO(store.root, store.locations, store.location_members).locked() if outer_lease else nullcontext():
        result = _stage_snapshot(store, payload, {}, writer)
        with ZipFile(BytesIO(result)) as archive:
            assert archive.read("project/source.csv") == b"x,y\n1,2\n"
        with pytest.raises(ProjectStoreError, match="identity"):
            publish_files(store, {"@snapshot/project.zip": result}, kind="publish")
    assert not (tmp_path / "project.zip").exists()
