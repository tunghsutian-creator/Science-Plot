"""Publication source identity survives a host-bound private project image."""

import hashlib
import pytest

from sciplot_core.project_store import FileProjectStore, ProjectConflict
from sciplot_core.project_store.runtime import project_candidate_runtime
from sciplot_core.publication.artifacts import artifact_record
from sciplot_core.publication.transform_ledger import build_transform_ledger


def prepared(tmp_path):
    project = tmp_path / "project"
    project.mkdir()
    source = project / "source.csv"
    source.write_bytes(b"x,y\n1,2\n3,4\n")
    store = FileProjectStore(project)
    snapshot = store.snapshot(import_legacy=True)
    candidate = tmp_path / "candidate"
    candidate.mkdir(mode=0o700)
    for name, entry in snapshot["files"].items():
        path = candidate / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(store.read_bytes(name))
        path.chmod(entry["mode"])
    return store, source, candidate


def test_candidate_artifact_and_ledger_keep_original_literal_and_actual_source_bytes(tmp_path):
    store, source, candidate = prepared(tmp_path)
    expected = hashlib.sha256(source.read_bytes()).hexdigest()
    with project_candidate_runtime(store, candidate):
        artifact = artifact_record(candidate / "source.csv", artifact_id="raw", role="input")
        ledger = build_transform_ledger({}, request={}, input_path=candidate / "source.csv")
    assert artifact["path"] == str(source)
    assert artifact["sha256"] == expected
    assert artifact["table_shape"] == [3, 2]
    assert ledger["source_root"] == str(source)
    assert ledger["steps"][0]["input_artifacts"][0]["path"] == str(source)
    assert ledger["steps"][0]["input_artifacts"][0]["sha256"] == expected
    assert str(candidate) not in str(ledger)
    assert artifact_record(source, artifact_id="raw", role="input") == artifact


def test_source_artifact_refuses_mutated_candidate_before_recording_provenance(tmp_path):
    store, _source, candidate = prepared(tmp_path)
    with project_candidate_runtime(store, candidate):
        (candidate / "source.csv").write_bytes(b"x,y\n1,999\n")
        with pytest.raises(ProjectConflict):
            artifact_record(candidate / "source.csv", artifact_id="raw", role="input")
