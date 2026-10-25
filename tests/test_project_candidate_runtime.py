"""Trusted mutable candidate IO retains original science and one project owner."""
import json
import os
import subprocess
import sys

import pytest

from sciplot_core.foundation.source_locations import resolve_source_path, literal_source_path, selected_source_resolver
from sciplot_core.project_store import FileProjectStore, ProjectConflict, ProjectStoreError
from sciplot_core.project_store.io import sha
from sciplot_core.project_store.runtime import project_candidate_runtime, selected_project_store
from sciplot_core.project_store.worker_binding import native_runtime_binding, worker_project_runtime


def fixture_candidate(tmp_path):
    root = tmp_path / "project"
    root.mkdir()
    (root / "raw").mkdir()
    (root / "raw/source.csv").write_bytes(b"x,y\n1,2\n")
    (root / "studio").mkdir()
    (root / "studio/document.vsz").write_bytes(b"native original")
    store = FileProjectStore(root)
    snapshot = store.snapshot(import_legacy=True)
    private = tmp_path / "private"
    private.mkdir(mode=0o700)
    for logical, entry in snapshot["files"].items():
        path = private / logical
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(store.read_bytes(logical))
        path.chmod(entry["mode"])
    return store, snapshot, private


def test_candidate_preserves_source_uuid_literal_and_original_snapshot_while_building(tmp_path):
    store, snapshot, private = fixture_candidate(tmp_path)
    source = store.root / "raw/source.csv"
    entry = snapshot["files"]["raw/source.csv"]
    before = {name: store.read_bytes(name) for name in snapshot["files"]}
    with project_candidate_runtime(store, private) as selected:
        assert selected_project_store() is store
        actual = resolve_source_path(source, expected_sha256=entry["sha256"], source_id=entry["file_id"])
        assert actual == private / "raw/source.csv" and literal_source_path(actual) == str(source)
        (private / "studio/document.vsz").write_bytes(b"native candidate")
        assert resolve_source_path(store.root / "studio/document.vsz").read_bytes() == b"native candidate"
        derived = private / "studio/processed/generated.csv"
        derived.parent.mkdir()
        derived.write_bytes(b"derived candidate")
        assert literal_source_path(derived) == str(store.root / "studio/processed/generated.csv")
        assert resolve_source_path(store.root / "studio/processed/generated.csv", expected_sha256=sha(derived.read_bytes())) == derived
        assert resolve_source_path(store.root) == private
        assert selected.snapshot["project_id"] == snapshot["project_id"]
    assert selected_source_resolver() is None
    assert not (private / ".sciplot_store").exists()
    assert store.snapshot()["generation"] == snapshot["generation"]
    assert {name: store.read_bytes(name) for name in before} == before


@pytest.mark.parametrize("drift", ["raw", "mode", "source_id", "version", "unknown", "symlink", "hardlink", "dotdot", "directory-version"])
def test_candidate_rejects_scientific_drift_aliases_and_unknown_members(tmp_path, drift):
    store, snapshot, private = fixture_candidate(tmp_path)
    source = store.root / "raw/source.csv"
    entry = snapshot["files"]["raw/source.csv"]
    with project_candidate_runtime(store, private), pytest.raises((ProjectConflict, ProjectStoreError, OSError)):
        if drift == "raw":
            (private / "raw/source.csv").write_bytes(b"changed raw")
            resolve_source_path(source)
        elif drift == "mode":
            (private / "raw/source.csv").chmod(0o700)
            resolve_source_path(source)
        elif drift in {"source_id", "version"}:
            resolve_source_path(source, source_id="wrong" if drift == "source_id" else entry["file_id"],
                                expected_sha256="0" * 64 if drift == "version" else entry["sha256"])
        elif drift == "unknown":
            resolve_source_path(store.root / "unregistered.csv")
        elif drift == "directory-version":
            resolve_source_path(store.root / "raw", expected_sha256="0" * 64)
        elif drift == "dotdot":
            resolve_source_path(store.root / "raw/../studio/document.vsz")
        else:
            target = private / "studio/alias.vsz"
            if drift == "symlink":
                target.symlink_to(store.root / "studio/document.vsz")
            else:
                target.hardlink_to(store.root / "studio/document.vsz")
            resolve_source_path(target)
    assert selected_source_resolver() is None
    assert store.read_bytes("raw/source.csv") == b"x,y\n1,2\n"


@pytest.mark.parametrize("failure", ["clone", "root-alias", "root-mode", "root-replacement", "own-head"])
def test_candidate_root_is_host_private_exact_and_never_a_second_store(tmp_path, failure):
    store, _snapshot, private = fixture_candidate(tmp_path)
    if failure == "clone":
        (private / "studio/document.vsz").write_bytes(b"incomplete or changed clone")
    elif failure == "root-alias":
        link = tmp_path / "link"
        link.symlink_to(private, target_is_directory=True)
        private = link
    elif failure == "root-mode":
        private.chmod(0o755)
    with pytest.raises((ProjectConflict, ProjectStoreError)):
        with project_candidate_runtime(store, private):
            if failure == "root-replacement":
                private.rename(tmp_path / "moved-private")
                private.mkdir(mode=0o700)
            elif failure == "own-head":
                (private / ".sciplot_store").mkdir()
            resolve_source_path(private / "studio/document.vsz")
    assert selected_source_resolver() is None


def test_candidate_external_registered_sources_keep_the_original_exact_host_scope(tmp_path):
    store, snapshot, private = fixture_candidate(tmp_path)
    delivery = tmp_path / "delivery"
    delivery.mkdir()
    target = delivery / "result.pdf"
    target.write_bytes(b"exact existing delivery")
    from sciplot_core.project_store.resources import ResourceRoot
    scoped = FileProjectStore(store.root, locations={"delivery": ResourceRoot(delivery, ("result.pdf",))})
    # Existing store has no registered delivery member: candidate cannot mint it.
    with project_candidate_runtime(scoped, private, generation=snapshot["generation"]), pytest.raises(ProjectStoreError):
        resolve_source_path(target)
    assert target.read_bytes() == b"exact existing delivery"


@pytest.mark.comprehensive
def test_candidate_binding_cold_and_pooled_children_reset_without_private_identity_leak(tmp_path):
    from sciplot_core.native_process import PersistentWorker, run_worker
    store, snapshot, private = fixture_candidate(tmp_path)
    source = store.root / "raw/source.csv"
    script = """import json
from sciplot_core.veusz_worker import persistent,cli
from sciplot_core.foundation.source_locations import resolve_source_path,literal_source_path,selected_source_resolver
class App:
 def quit(self):pass
persistent._application=lambda:App()
def main(argv):
 if argv[1]=='NO_PROJECT':
  assert selected_source_resolver() is None
  print(json.dumps({'scope':None}));return 0
 path=resolve_source_path(argv[1])
 print(json.dumps({'data':path.read_text(),'literal':literal_source_path(path)}))
 if len(argv)>2:raise ValueError('synthetic candidate failure')
 return 0
cli.main=main
persistent.serve()
"""
    command = [sys.executable, "-m", "sciplot_core.veusz_worker", "inspect-document-state", str(source)]
    worker = PersistentWorker(worker_command=[sys.executable, "-c", script])
    try:
        with project_candidate_runtime(store, private), native_runtime_binding(command[3:]) as reference:
            cold_script = """import json,sys
from sciplot_core.project_store.worker_binding import worker_project_runtime
from sciplot_core.foundation.source_locations import resolve_source_path,literal_source_path,selected_source_resolver
with worker_project_runtime(json.loads(sys.argv[1]),json.loads(sys.argv[2])):
 path=resolve_source_path(sys.argv[3]);print(json.dumps({'data':path.read_text(),'literal':literal_source_path(path)}))
assert selected_source_resolver() is None
"""
            cold = subprocess.run([sys.executable, "-c", cold_script, json.dumps(reference), json.dumps(command[3:]), str(source)],
                                  capture_output=True, text=True, check=True)
            assert json.loads(cold.stdout) == {"data": "x,y\n1,2\n", "literal": str(source)}
            with worker.activate():
                first = run_worker(command, timeout=30)
                failed = run_worker([*command, "FAIL"], timeout=30)
        with worker.activate():
            cleared = run_worker([*command[:4], "NO_PROJECT"], timeout=30)
        assert first.returncode == 0 and failed.returncode == 1
        assert json.loads(first.stdout) == json.loads(cold.stdout)
        assert json.loads(cleared.stdout) == {"scope": None} and worker.starts == 1
        assert store.snapshot()["generation"] == snapshot["generation"]
    finally:
        worker.close()
    assert selected_source_resolver() is None


def test_candidate_worker_refuses_unbound_closed_fields_and_replaced_directory(tmp_path, monkeypatch):
    store, _snapshot, private = fixture_candidate(tmp_path)
    argv = ["inspect-document-state", str(store.root / "raw/source.csv")]
    with project_candidate_runtime(store, private), native_runtime_binding(argv) as reference:
        monkeypatch.setattr(os, "getppid", lambda: os.getpid())
        private.rename(tmp_path / "private-old")
        private.mkdir(mode=0o700)
        with pytest.raises(ProjectConflict, match="replaced"):
            with worker_project_runtime(reference, argv):
                pytest.fail("Replaced directory was admitted")
    assert selected_source_resolver() is None


def test_managed_candidate_raw_reader_keeps_scientific_hash_uuid_and_cells(tmp_path):
    from copy import deepcopy
    from managed_plot_helpers import request_for_source
    from sciplot_core.plot_engine.managed_sources import load_sources
    from sciplot_core.plot_ir import create_managed_document
    from sciplot_core.plot_document import validate_document
    root = tmp_path / "project"
    root.mkdir()
    wire = request_for_source(root)
    store = FileProjectStore(root)
    snapshot = store.snapshot(import_legacy=True)
    identity = snapshot["files"]["A.csv"]["file_id"]
    def exact_source_identity(value):
        if isinstance(value, dict):
            return {key: exact_source_identity(item) for key, item in value.items()}
        if isinstance(value, list):
            return [exact_source_identity(item) for item in value]
        return identity if value == "A" else value
    document = create_managed_document(exact_source_identity(wire["template_definition"]),
                                      exact_source_identity(wire["data_binding"]), plot_id="candidate-science")
    baseline = deepcopy(document)
    original = load_sources(document, wire["rule_id"])
    private = tmp_path / "private"
    private.mkdir(mode=0o700)
    for logical, entry in snapshot["files"].items():
        target = private / logical
        target.write_bytes(store.read_bytes(logical))
        target.chmod(entry["mode"])
    with project_candidate_runtime(store, private):
        loaded = load_sources(document, wire["rule_id"])
        assert loaded == original
        assert loaded[identity]["columns"]["column:1"]["values"] == [2.0, 4.0, 8.0]
        assert document == baseline
        validate_document(document)
        assert str(private) not in json.dumps(document)
    assert selected_source_resolver() is None


@pytest.mark.parametrize("operation", ["save-spec", "compile-plot-ir"])
def test_candidate_worker_distinguishes_new_document_outputs_from_scientific_inputs(tmp_path, monkeypatch, operation):
    from sciplot_core.veusz_worker import cli
    from sciplot_core.veusz_worker import managed
    store, _snapshot, private = fixture_candidate(tmp_path)
    spec = private / "studio/new-spec.json"
    spec.write_text('{"generated":true}')
    output = store.root / "studio/new-stage/new.vsz"
    calls = []
    def render(*args):
        if operation == "save-spec":
            document, input_path = args
        else:
            input_path, document, _preview = args
        calls.append((input_path, document))
        assert input_path == spec and document == private / "studio/new-stage/new.vsz"
        assert document.parent.is_dir()
        document.write_bytes(b"private native output")
        return {"saved": str(document)}
    monkeypatch.setattr(cli, "save_spec", render)
    monkeypatch.setattr(managed, "compile_plot_ir", render)
    args = ([operation, str(output), str(spec)] if operation == "save-spec" else
            [operation, str(spec), str(output), "--preview", str(private / "preview.png")])
    with project_candidate_runtime(store, private):
        assert cli._execute(args) == 0
        assert resolve_source_path(output).read_bytes() == b"private native output"
    assert len(calls) == 1 and not output.exists() and selected_source_resolver() is None


@pytest.mark.parametrize("bad", ["missing-input", "source-output", "outside-output", "aliased-parent"])
def test_candidate_output_role_cannot_weaken_input_identity_or_private_root(tmp_path, monkeypatch, bad):
    from sciplot_core.veusz_worker import cli
    store, _snapshot, private = fixture_candidate(tmp_path)
    spec = private / "studio/spec.json"
    spec.write_bytes(b"spec")
    output = store.root / "studio/new.vsz"
    monkeypatch.setattr(cli, "save_spec", lambda *_a: pytest.fail("Refused input/output reached native execution"))
    if bad == "missing-input":
        spec = private / "studio/missing.json"
    elif bad == "source-output":
        output = store.root / "raw/source.csv"
    elif bad == "outside-output":
        output = tmp_path / "outside/document.vsz"
    else:
        (private / "studio/linked").symlink_to(store.root / "studio", target_is_directory=True)
        output = store.root / "studio/linked/new.vsz"
    with pytest.raises((ProjectConflict, ProjectStoreError, OSError)), project_candidate_runtime(store, private):
        cli._execute(["save-spec", str(output), str(spec)])
    assert not (store.root / "studio/new.vsz").exists()
    assert store.read_bytes("raw/source.csv") == b"x,y\n1,2\n"
