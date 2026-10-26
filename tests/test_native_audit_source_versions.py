"""Exact prepared-source versions survive both scientific snapshot boundaries."""

import json
from pathlib import Path

import pytest
from test_categorical_source_identity import written
from test_project_store import fixture_store

from sciplot_core.project_commands import PreparedSource, ProjectCommand, ProjectCommands, ProjectMutation
from sciplot_core.project_store.io import sha
from sciplot_core.project_store.runtime import project_runtime
from sciplot_core.source_coverage import file_snapshots
from sciplot_core.source_coverage import managed_documents
from sciplot_core.studio_core import native_scientific_audit as audit


@pytest.fixture
def prepared_source(tmp_path, monkeypatch):
    raw = tmp_path / "external/source.csv"
    raw.parent.mkdir()
    raw.write_text("Time,Stress\ns,Pa\nA,A\n0,10\n1,12\n2,11\n")
    original = raw.read_bytes()
    spec = written({"input": str(raw), "template": "curve"}, tmp_path, monkeypatch, "generated")
    native = tmp_path / "native/document.vsz"
    native.parent.mkdir()
    native.write_bytes(b"generated native boundary stub")
    spec_path = native.with_name("spec.json")
    spec_path.write_text(json.dumps(spec))
    store, _before = fixture_store(tmp_path)
    mutation = ProjectMutation({}, {}, prepared_sources=(PreparedSource("a" * 32, str(raw), sha(original), original, (), 0o644),))
    before = store.snapshot()
    command = ProjectCommand.create("attachment_import", "prepared-source", project_id=before["project_id"],
        expected_generation=before["generation"], read_set={}, write_set=[], request={"prepared_digest": mutation.prepared_digest})
    ProjectCommands(store).publish_prepared(command, mutation)
    # Only the native-consumption boundary is controlled. Source derivation,
    # exact native-spec source inventory and filesystem/version checks stay real.
    monkeypatch.setattr(audit, "_audit_exact_document_data", lambda **_kwargs: ({"unit_count": 1}, spec))
    return store, raw, original, native, spec_path, spec


def test_native_audit_uses_the_declared_version_for_capture_and_recapture(prepared_source, monkeypatch):
    store, raw, original, native, spec_path, _spec = prepared_source
    resolve = file_snapshots.resolve_source_path
    observed = []

    def checked(path, **kwargs):
        if Path(path) == raw:
            observed.append(kwargs.get("expected_sha256"))
        return resolve(path, **kwargs)

    monkeypatch.setattr(file_snapshots, "resolve_source_path", checked)
    before = store.snapshot()["generation"]
    with project_runtime(store):
        result = audit.audit_native_candidate(native, spec_path)
    assert result == {"status": "passed", "unit_count": 1, "prepared_unit_count": 1}
    assert observed == [sha(original), sha(original)]
    assert raw.read_bytes() == original
    assert store.snapshot()["generation"] == before


def run_audit(prepared, monkeypatch, consumer):
    store, raw, _original, native, spec_path, spec = prepared
    with project_runtime(store):
        if consumer == "native":
            return audit.audit_native_candidate(native, spec_path)
        monkeypatch.setattr(managed_documents, "_audit_exact_document_data",
                            lambda **_kwargs: ({"unit_count": 1}, spec))
        return managed_documents.verify_managed_document_sources({
            "veusz_documents": [str(native)], "data_snapshot_sources": [str(raw)]})


def test_managed_audit_uses_the_declared_version_for_capture_and_recapture(prepared_source, monkeypatch):
    _store, raw, original, _native, _spec_path, _spec = prepared_source
    resolve = file_snapshots.resolve_source_path
    observed = []

    def checked(path, **kwargs):
        if Path(path) == raw:
            observed.append(kwargs.get("expected_sha256"))
        return resolve(path, **kwargs)

    monkeypatch.setattr(file_snapshots, "resolve_source_path", checked)
    result = run_audit(prepared_source, monkeypatch, "managed")
    assert result["status"] == "passed" and result["document_count"] == 1
    assert result["documents"][0]["prepared_source_derivation"]["status"] == "passed"
    assert observed == [sha(original), sha(original)]


@pytest.mark.parametrize("consumer", ["native", "managed"])
@pytest.mark.parametrize("digest", [None, "", "not-a-sha", "f" * 64])
def test_audit_rejects_missing_or_wrong_declared_versions(prepared_source, monkeypatch, consumer, digest):
    store, raw, original, _native, _spec_path, spec = prepared_source
    spec["series"][0]["source_artifacts"][0]["sha256"] = digest
    before = store.snapshot()["generation"]
    with pytest.raises(ValueError, match="exact SHA256|version do not resolve uniquely"):
        run_audit(prepared_source, monkeypatch, consumer)
    assert raw.read_bytes() == original and store.snapshot()["generation"] == before


@pytest.mark.parametrize("consumer", ["native", "managed"])
def test_audit_rejects_changed_values_despite_valid_source_version(prepared_source, monkeypatch, consumer):
    _store, raw, original, _native, _spec_path, spec = prepared_source
    spec["series"][0]["y_values"][1] += 1
    with pytest.raises(ValueError, match="values, axes, or sample identities"):
        run_audit(prepared_source, monkeypatch, consumer)
    assert raw.read_bytes() == original


@pytest.mark.parametrize("consumer", ["native", "managed"])
def test_audit_rejects_source_drift_after_real_derivation(prepared_source, monkeypatch, consumer):
    store, raw, original, _native, _spec_path, _spec = prepared_source
    owner = audit if consumer == "native" else managed_documents
    derive = owner._verify_prepared_data
    derived = []

    def change_after_derivation(spec, snapshots):
        result = derive(spec, snapshots)
        derived.append(result)
        raw.write_bytes(original.replace(b"1,12", b"1,13"))
        return result

    monkeypatch.setattr(owner, "_verify_prepared_data", change_after_derivation)
    before = store.snapshot()["generation"]
    with pytest.raises(ValueError, match="source.*changed|source.*differs|source bytes|source version"):
        run_audit(prepared_source, monkeypatch, consumer)
    assert len(derived) == 1 and derived[0]["status"] == "passed"
    assert store.snapshot()["generation"] == before


@pytest.mark.parametrize("failure", ["missing", "changed", "alias"])
def test_exact_snapshot_rejects_live_source_loss_drift_or_alias(prepared_source, failure):
    store, raw, original, _native, _spec_path, _spec = prepared_source
    if failure == "changed":
        raw.write_bytes(original.replace(b"0,10", b"0,11"))
    else:
        raw.unlink()
        if failure == "alias":
            foreign = raw.with_name("foreign.csv")
            foreign.write_bytes(original)
            raw.symlink_to(foreign)
    with project_runtime(store), pytest.raises((ValueError, OSError)):
        file_snapshots.stable_file_snapshot(raw, label="known version", expected_sha256=sha(original))


def test_exact_snapshot_refuses_unregistered_same_named_project_member(prepared_source):
    store, _raw, original, _native, _spec_path, _spec = prepared_source
    foreign = store.root / "unregistered/source.csv"
    foreign.parent.mkdir()
    foreign.write_bytes(original)
    with project_runtime(store), pytest.raises(ValueError, match="no exact preserved locator"):
        file_snapshots.stable_file_snapshot(foreign, label="foreign member", expected_sha256=sha(original))


def test_missing_version_stays_refused_for_a_registered_external_source(prepared_source):
    store, raw, _original, _native, _spec_path, _spec = prepared_source
    with project_runtime(store), pytest.raises(ValueError, match="exact registered version hash"):
        file_snapshots.stable_file_snapshot(raw, label="missing proof")


def test_generic_first_attestation_keeps_snapshot_schema_and_currentness(tmp_path):
    source = tmp_path / "new.csv"
    source.write_bytes(b"x,y\n1,2\n")
    snapshot = file_snapshots.stable_file_snapshot(source, label="first observation")
    assert set(snapshot) == {"path", "identity", "bytes", "sha256"}
    assert snapshot["path"] == source and snapshot["sha256"] == sha(source.read_bytes())
    file_snapshots._assert_snapshot_current(snapshot, label="first observation")
    source.write_bytes(b"x,y\n1,3\n")
    with pytest.raises(ValueError, match="changed during exact-current audit"):
        file_snapshots._assert_snapshot_current(snapshot, label="first observation")
