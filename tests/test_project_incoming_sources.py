"""Incoming live versions and reviewed sealed baselines share finite host IO."""
import json
import os
from contextlib import nullcontext
from pathlib import Path
import subprocess
import sys

import pytest

from sciplot_core.foundation.source_locations import literal_source_path, resolve_source_path, selected_source_resolver
from sciplot_core.foundation.source_tree import source_tree_sha256
from sciplot_core.project_commands import ProjectCommand, ProjectCommands, ProjectMutation
from sciplot_core.project_commands.resources import PreparedSource
from sciplot_core.project_store import ProjectConflict, ProjectStoreError
from sciplot_core.project_store.incoming_sources import SourceExpectation
from sciplot_core.project_store.io import digest, sha
from sciplot_core.project_store.runtime import incoming_source_runtime, project_candidate_runtime, project_runtime, sealed_source_runtime
from sciplot_core.project_store.worker_binding import native_runtime_binding, worker_project_runtime

from test_project_store import fixture_store


def changed_external(tmp_path):
    store, _ = fixture_store(tmp_path)
    raw = tmp_path / "incoming/same-incoming.csv"
    raw.parent.mkdir()
    old = b"x,y\n1,2\n"
    raw.write_bytes(old)
    identity = "a" * 32
    version = sha(old)
    mutation = ProjectMutation({}, {}, prepared_sources=(PreparedSource(identity, str(raw), version, old, (), 0o644),))
    before = store.snapshot()
    command = ProjectCommand.create("attachment_import", "register", project_id=before["project_id"],
        expected_generation=before["generation"], read_set={}, write_set=[], request={"prepared_digest": mutation.prepared_digest})
    ProjectCommands(store).publish_prepared(command, mutation)
    raw.write_bytes(b"x,y\n1,9\n")
    return store, raw, SourceExpectation(str(raw), identity, sha(raw.read_bytes())), SourceExpectation(str(raw), identity, version), old


def private_clone(store, tmp_path):
    private = tmp_path / "candidate"
    private.mkdir(mode=0o700)
    for name, entry in store.snapshot()["files"].items():
        target = private / name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(store.read_bytes(name))
        target.chmod(entry["mode"])
    return private


def test_same_literal_fresh_version_requires_explicit_host_scope_and_retains_science(tmp_path):
    store, raw, fresh, sealed, old = changed_external(tmp_path)
    before = store.snapshot()
    baseline = {name: store.read_bytes(name) for name in before["files"]}
    private = private_clone(store, tmp_path)
    with project_runtime(store):
        for version in (None, fresh.sha256, sealed.sha256):
            with pytest.raises((ProjectConflict, ProjectStoreError)):
                resolve_source_path(raw, expected_sha256=version)
    with incoming_source_runtime(store, [fresh], generation=before["generation"]):
        assert resolve_source_path(raw) == raw
        assert source_tree_sha256(raw) == digest({"kind": "file", "content_sha256": fresh.sha256})
        assert resolve_source_path(raw, expected_sha256=fresh.sha256, source_id=fresh.source_id) == raw
        with project_candidate_runtime(store, private):
            assert source_tree_sha256(raw) == digest({"kind": "file", "content_sha256": fresh.sha256})
            assert resolve_source_path(store.root / "raw/same.csv").read_bytes() == baseline["raw/same.csv"]
        with pytest.raises(ProjectConflict):
            resolve_source_path(raw, expected_sha256=sealed.sha256)
        with pytest.raises(ProjectConflict):
            resolve_source_path(raw, source_id="b" * 32)
    with project_runtime(store), pytest.raises(ProjectStoreError):
        resolve_source_path(raw)
    assert selected_source_resolver() is None
    assert store.resolve_source(sealed.source_id, sealed.sha256).read_bytes() == old
    assert store.snapshot() == before and {name: store.read_bytes(name) for name in baseline} == baseline
    assert raw.read_bytes() == b"x,y\n1,9\n"


def test_reviewed_sealed_baseline_reads_old_exact_bytes_and_keeps_original_literal(tmp_path):
    store, raw, fresh, sealed, old = changed_external(tmp_path)
    before = store.snapshot()
    with sealed_source_runtime(store, [sealed]):
        actual = resolve_source_path(raw)
        assert actual != raw and actual.read_bytes() == old
        assert literal_source_path(actual) == str(raw)
        assert source_tree_sha256(raw) == digest({"kind": "file", "content_sha256": sealed.sha256})
        with project_candidate_runtime(store, private_clone(store, tmp_path)):
            assert resolve_source_path(actual).read_bytes() == old
            assert literal_source_path(actual) == str(raw)
            assert source_tree_sha256(raw) == digest({"kind": "file", "content_sha256": sealed.sha256})
        with pytest.raises(ProjectConflict):
            resolve_source_path(raw, expected_sha256=fresh.sha256)
        with pytest.raises(ProjectConflict):
            resolve_source_path(raw, source_id="b" * 32)
        with pytest.raises(ProjectConflict):
            with incoming_source_runtime(store, [fresh]):
                pytest.fail("Baseline and incoming scopes must not overlap")
    with project_runtime(store), pytest.raises(ProjectStoreError):
        resolve_source_path(raw)
    assert raw.read_bytes() == b"x,y\n1,9\n" and store.snapshot() == before


@pytest.mark.parametrize("mode", ["incoming", "sealed"])
@pytest.mark.parametrize("failure", ["unknown-id", "wrong-literal", "duplicate", "unknown-version", "file-drift", "symlink", "parent-symlink", "exit"])
def test_expectations_are_exact_finite_verified_and_exception_scoped(tmp_path, mode, failure):
    store, raw, fresh, sealed, _ = changed_external(tmp_path)
    context = incoming_source_runtime if mode == "incoming" else sealed_source_runtime
    selected = fresh if mode == "incoming" else sealed
    sources = [selected]
    if failure == "unknown-id":
        sources = [SourceExpectation(str(raw), "b" * 32, selected.sha256)]
    elif failure == "wrong-literal":
        sources = [SourceExpectation(str(tmp_path / "other.csv"), selected.source_id, selected.sha256)]
    elif failure == "duplicate":
        sources *= 2
    elif failure == "unknown-version":
        sources = [SourceExpectation(str(raw), selected.source_id, "0" * 64)]
    elif failure in {"file-drift", "symlink", "parent-symlink"}:
        actual = raw if mode == "incoming" else store.resolve_source(sealed.source_id, sealed.sha256)
        if failure == "file-drift":
            actual.chmod(0o600)
            actual.write_bytes(b"unreviewed")
        elif failure == "symlink":
            actual.unlink()
            actual.symlink_to(store.root / "raw/same.csv")
        else:
            parent = actual.parent
            moved = parent.with_name(parent.name + "-moved")
            parent.rename(moved)
            parent.symlink_to(moved, target_is_directory=True)
    with pytest.raises((ProjectConflict, ProjectStoreError, OSError, ValueError)):
        with context(store, sources):
            if failure == "exit":
                raise ValueError("host exit")
            resolve_source_path(raw)
    assert selected_source_resolver() is None


def test_incoming_does_not_grant_other_literal_project_resource_or_other_project(tmp_path):
    store, raw, fresh, _, _ = changed_external(tmp_path)
    own = store.snapshot()["files"]["raw/same.csv"]
    with pytest.raises(ProjectConflict):
        with incoming_source_runtime(store, [SourceExpectation(str(store.root / "raw/same.csv"), own["file_id"], own["sha256"])]):
            pytest.fail("Project inputs cannot bypass candidate protection")
    with incoming_source_runtime(store, [fresh]):
        with pytest.raises((ProjectConflict, ProjectStoreError)):
            resolve_source_path(tmp_path / "other.csv", source_id=fresh.source_id, expected_sha256=fresh.sha256)
        other_root = tmp_path / "other"
        other_root.mkdir()
        other, _ = fixture_store(other_root)
        with project_runtime(other), pytest.raises((ProjectConflict, ProjectStoreError)):
            resolve_source_path(raw, source_id=fresh.source_id, expected_sha256=fresh.sha256)


@pytest.mark.parametrize("mode", ["incoming", "sealed"])
def test_each_resolution_rechecks_exact_bytes_inside_same_scope(tmp_path, mode):
    store, raw, fresh, sealed, _ = changed_external(tmp_path)
    context, source = (incoming_source_runtime, fresh) if mode == "incoming" else (sealed_source_runtime, sealed)
    with context(store, [source]):
        actual = resolve_source_path(raw)
        actual.chmod(0o600)
        actual.write_bytes(b"changed during selected scope")
        with pytest.raises((ProjectConflict, ProjectStoreError)):
            resolve_source_path(raw)


@pytest.mark.parametrize("field,value", [("literal", "relative.csv"), ("literal", "/one/../raw.csv"),
    ("literal", "/one/./raw.csv"), ("literal", "/one//raw.csv"), ("literal", "/one/\x00.csv"),
    ("source_id", "A" * 32), ("source_id", "alias"), ("sha256", "unknown"), ("sha256", None)])
def test_source_expectation_rejects_noncanonical_identity_and_paths(field, value):
    payload = {"literal": "/explicit/raw.csv", "source_id": "a" * 32, "sha256": "b" * 64}
    payload[field] = value
    with pytest.raises(ProjectStoreError):
        SourceExpectation.from_payload(payload)


@pytest.mark.parametrize("mode", ["incoming", "sealed"])
def test_worker_binding_keeps_exact_mode_and_clears_unbound_requests(tmp_path, monkeypatch, mode):
    store, raw, fresh, sealed, old = changed_external(tmp_path)
    context, source = (incoming_source_runtime, fresh) if mode == "incoming" else (sealed_source_runtime, sealed)
    argv = ["inspect-document-state", str(raw)]
    with context(store, [source]), native_runtime_binding(argv) as reference:
        monkeypatch.setattr(os, "getppid", os.getpid)
        with worker_project_runtime(reference, argv):
            assert resolve_source_path(raw).read_bytes() == (raw.read_bytes() if mode == "incoming" else old)
        # An ordinary project descriptor must not inherit the enclosing test's capability.
        with project_runtime(store):
            from sciplot_core.project_store.incoming_sources import without_source_expectations
            with without_source_expectations(), native_runtime_binding(argv) as ordinary:
                pass_bytes = Path(ordinary["path"]).read_bytes()
            with native_runtime_binding(argv) as unbound:
                Path(unbound["path"]).chmod(0o600)
                Path(unbound["path"]).write_bytes(pass_bytes)
                unbound["sha256"] = sha(pass_bytes)
                with worker_project_runtime(unbound, argv), pytest.raises(ProjectStoreError):
                    resolve_source_path(raw)
        with worker_project_runtime(None, argv):
            assert selected_source_resolver() is None
        with pytest.raises(ProjectConflict, match="different command"):
            with worker_project_runtime(reference, [*argv, "wrong"]):
                pytest.fail("An expectation cannot authorize another argv")
    assert selected_source_resolver() is None


@pytest.mark.parametrize("change", ["unknown-field", "mode", "identity", "literal", "unbounded", "parent"])
def test_worker_refuses_forged_or_unclosed_expectations(tmp_path, monkeypatch, change):
    store, raw, fresh, _, _ = changed_external(tmp_path)
    argv = ["inspect-document-state", str(raw)]
    with incoming_source_runtime(store, [fresh]), native_runtime_binding(argv) as reference:
        monkeypatch.setattr(os, "getppid", os.getpid)
        path = Path(reference["path"])
        value = json.loads(path.read_bytes())
        cap = value["project"]["source_expectations"]
        if change == "unknown-field":
            cap["sources"][0]["allow_drift"] = True
        elif change == "mode":
            cap["mode"] = "latest"
        elif change == "identity":
            cap["sources"][0]["source_id"] = "b" * 32
        elif change == "literal":
            cap["sources"][0]["literal"] = str(raw.parent)
        elif change == "unbounded":
            cap["sources"] *= 65
        else:
            value["parent_pid"] += 1
        path.chmod(0o600)
        data = json.dumps(value).encode()
        path.write_bytes(data)
        reference["sha256"] = sha(data)
        with pytest.raises((ProjectStoreError, ProjectConflict)):
            with worker_project_runtime(reference, argv):
                pytest.fail("Invalid host capability admitted")
    assert selected_source_resolver() is None


@pytest.mark.comprehensive
@pytest.mark.parametrize("mode", ["incoming", "sealed"])
@pytest.mark.parametrize("candidate", [False, True])
def test_actual_child_inherits_only_host_bound_version_then_clears(tmp_path, mode, candidate):
    store, raw, fresh, sealed, old = changed_external(tmp_path)
    context, source = (incoming_source_runtime, fresh) if mode == "incoming" else (sealed_source_runtime, sealed)
    argv = ["inspect-document-state", str(raw)]
    script = """import json,sys
from sciplot_core.project_store.worker_binding import worker_project_runtime
from sciplot_core.foundation.source_locations import resolve_source_path,literal_source_path,selected_source_resolver
reference=json.loads(sys.argv[1]);argv=json.loads(sys.argv[2])
with worker_project_runtime(reference,argv):
 path=resolve_source_path(argv[1]);print(json.dumps({'bytes':path.read_text(),'literal':literal_source_path(path)}))
assert selected_source_resolver() is None
"""
    private = project_candidate_runtime(store, private_clone(store, tmp_path)) if candidate else nullcontext()
    with context(store, [source]), private, native_runtime_binding(argv) as reference:
        child = subprocess.run([sys.executable, "-c", script, json.dumps(reference), json.dumps(argv)],
                               text=True, capture_output=True, check=True, timeout=30)
    assert json.loads(child.stdout) == {"bytes": (raw.read_bytes() if mode == "incoming" else old).decode(), "literal": str(raw)}
    assert selected_source_resolver() is None
