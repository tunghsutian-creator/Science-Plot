"""Offline project IO retains sealed literals, exact bytes and scoped authority."""
import json
from pathlib import Path
import subprocess
import sys

import pytest

from sciplot_core.foundation.file_hashing import file_sha256
from sciplot_core.foundation.source_locations import resolve_source_path, selected_source_resolver
from sciplot_core.native_process import PersistentWorker, run_worker
from sciplot_core.project_store import FileProjectStore, ProjectStoreError
from sciplot_core.project_store.runtime import project_runtime, literal_runtime_path
from sciplot_core.project_store.worker_binding import native_runtime_binding
from sciplot_core.source_coverage.artifacts import _current_source_artifact
from sciplot_core.source_coverage.file_snapshots import stable_file_snapshot, _assert_snapshot_current
from sciplot_core.source_tables import read_raw_table


def moved_project(tmp_path):
    original = tmp_path / "original"
    original.mkdir()
    table = original / "raw/table.csv"
    table.parent.mkdir()
    table.write_text("Time,Signal\ns,V\n0,2\n1,4\n")
    spec = {"source_artifacts": [{"path": str(table), "sha256": file_sha256(table)}]}
    (original / "spec.json").write_text(json.dumps(spec))
    store = FileProjectStore(original)
    before = store.snapshot(import_legacy=True)
    bundle = store.export_bundle(tmp_path / "bundle")
    cold = FileProjectStore.import_bundle(bundle, tmp_path / "moved")
    original.rename(tmp_path / "original-offline")
    return table, spec, before, cold


def test_offline_raw_reads_snapshots_artifacts_keep_original_identity(tmp_path):
    original, spec, before, store = moved_project(tmp_path)
    assert not original.exists()
    with project_runtime(store):
        actual = resolve_source_path(original, expected_sha256=spec["source_artifacts"][0]["sha256"])
        assert actual == store.root / "raw/table.csv" and literal_runtime_path(actual) == str(original)
        snapshot = stable_file_snapshot(original, label="relocated raw source")
        assert snapshot["path"] == original and snapshot["bytes"] == actual.read_bytes()
        assert _current_source_artifact(str(original), snapshot["sha256"], label="source") == spec["source_artifacts"][0]
        assert read_raw_table(original).iloc[-1].tolist() == ["1", "4"]
        _assert_snapshot_current(snapshot, label="relocated raw source")
    assert selected_source_resolver() is None and resolve_source_path(original) == original
    assert store.snapshot()["generation"] == before["generation"]
    assert json.loads(store.read_bytes("spec.json")) == spec


def test_known_namespace_cannot_reconnect_an_unregistered_same_name(tmp_path):
    original, spec, _, store = moved_project(tmp_path)
    unregistered = original.parent / "unregistered.csv"
    (store.root / "raw/unregistered.csv").write_bytes((store.root / "raw/table.csv").read_bytes())
    with project_runtime(store), pytest.raises(ProjectStoreError):
        resolve_source_path(unregistered)
    with project_runtime(store), pytest.raises(ProjectStoreError):
        resolve_source_path(original, expected_sha256="0" * 64)
    assert selected_source_resolver() is None


def test_host_private_audit_copies_outside_registered_namespaces_keep_local_io(tmp_path):
    original, _, _, store = moved_project(tmp_path)
    audit = tmp_path / "audit-private/copy.csv"
    audit.parent.mkdir()
    audit.write_bytes((store.root / "raw/table.csv").read_bytes())
    with project_runtime(store):
        assert resolve_source_path(audit) == audit
        assert stable_file_snapshot(audit, label="private copy")["path"] == audit
    assert not original.exists()


def test_cold_worker_binding_is_private_exact_and_not_a_scientific_wire_field(tmp_path):
    original, _, _, store = moved_project(tmp_path)
    argv = ["inspect-document-state", str(original)]
    script = """import json,sys
from pathlib import Path
from sciplot_core.project_store.worker_binding import worker_project_runtime
from sciplot_core.foundation.source_locations import resolve_source_path,selected_source_resolver
reference=json.loads(sys.argv[1]); argv=json.loads(sys.argv[2])
with worker_project_runtime(reference,argv):
    print(json.dumps({'bytes':resolve_source_path(argv[1]).read_text()}))
assert selected_source_resolver() is None
"""
    with project_runtime(store), native_runtime_binding(argv) as reference:
        assert reference is not None and Path(reference["path"]).stat().st_mode & 0o077 == 0
        result = subprocess.run([sys.executable, "-c", script, json.dumps(reference), json.dumps(argv)], text=True, capture_output=True, check=True)
        assert json.loads(result.stdout)["bytes"].endswith("1,4\n")
        wrong = subprocess.run([sys.executable, "-c", script, json.dumps(reference), json.dumps([*argv, "--unexpected"])], text=True, capture_output=True)
        assert wrong.returncode != 0 and "different command" in wrong.stderr
    assert not Path(reference["path"]).exists()


def test_pool_resets_project_scope_after_every_command_including_failure(tmp_path):
    original, _, _, store = moved_project(tmp_path)
    script = """import json
from sciplot_core.veusz_worker import persistent,cli
from sciplot_core.foundation.source_locations import resolve_source_path,selected_source_resolver
class App:
    def quit(self):pass
persistent._application=lambda:App()
def main(argv):
    if argv[1]=='NO_PROJECT':
        assert selected_source_resolver() is None
        print(json.dumps({'scope':None}));return 0
    path=resolve_source_path(argv[1])
    print(json.dumps({'bytes':path.read_text()}))
    if len(argv)>2:raise ValueError('synthetic command failure')
    return 0
cli.main=main
persistent.serve()
"""
    worker = PersistentWorker(worker_command=[sys.executable, "-c", script])
    command = [sys.executable, "-m", "sciplot_core.veusz_worker", "inspect-document-state", str(original)]
    try:
        with worker.activate():
            with project_runtime(store):
                first = run_worker(command, timeout=30)
                failed = run_worker([*command, "FAIL"], timeout=30)
            clear = run_worker([*command[:4], "NO_PROJECT"], timeout=30)
        assert first.returncode == 0 and failed.returncode == 1
        assert json.loads(clear.stdout) == {"scope": None} and worker.starts == 1
    finally:
        worker.close()


def test_offline_replicate_audit_rederives_original_cells_without_resealing(tmp_path):
    from copy import deepcopy
    from sciplot_core.source_coverage.managed_documents import _verify_prepared_data
    from test_replicate_disclosure_audit import _source, _spec

    original = tmp_path / "original"
    original.mkdir()
    source = _source(original)
    spec = _spec(source)
    (original / "spec.json").write_text(json.dumps(spec))
    store = FileProjectStore(original)
    store.snapshot(import_legacy=True)
    cold = FileProjectStore.import_bundle(store.export_bundle(tmp_path / "bundle"), tmp_path / "moved")
    original.rename(tmp_path / "original-offline")
    before = deepcopy(spec)
    with project_runtime(cold):
        snapshot = stable_file_snapshot(source, label="offline replicate original")
        result = _verify_prepared_data(spec, [snapshot])
    assert result["status"] == "passed" and result["replicate_disclosure_verification"]["status"] == "passed"
    assert spec == before and json.loads(cold.read_bytes("spec.json")) == before


@pytest.mark.parametrize("format", ["csv", "xlsx"])
def test_offline_categorical_original_cells_namespace_and_disclosure_are_exact(tmp_path, monkeypatch, format):
    from copy import deepcopy
    import pandas as pd
    from sciplot_core.categorical_plan import build_categorical_preview
    from sciplot_core.source_coverage.managed_documents import _verify_prepared_data
    from test_categorical_source_identity import written

    original = tmp_path / "original"
    original.mkdir()
    source = original / ("literal." + format)
    rows = [["Sample", "Condition", "Strength (MPa)"], ["A || exact", "wet", 1],
            ["A || exact", "wet", 2], ["B/exact", "wet", 3], ["B/exact", "wet", 4]]
    if format == "csv":
        source.write_text("\n".join(",".join(map(str, row)) for row in rows) + "\n")
    else:
        pd.DataFrame(rows).to_excel(source, header=False, index=False, sheet_name="Original")
    binding = {"source_sha256": file_sha256(source), "mode": "mean_sample_sd_n", "sample_column": 0,
               "condition_column": 1, "value_columns": [{"column_index": 2}],
               "table_selection": {"sheet": None if format == "csv" else "Original", "header_rows": [0],
                                   "data_start_row": 1, "data_end_row": len(rows)}}
    plan = build_categorical_preview(source, request={"categorical_binding": binding})
    request = {"input": str(source), "template": plan["template"], **plan["source_options"]}
    spec = written(request, original, monkeypatch, "drawing")
    before = deepcopy(spec)
    store = FileProjectStore(original)
    store.snapshot(import_legacy=True)
    cold = FileProjectStore.import_bundle(store.export_bundle(tmp_path / "bundle"), tmp_path / "moved")
    original.rename(tmp_path / "original-offline")
    with project_runtime(cold):
        snapshot = stable_file_snapshot(source, label="offline categorical original")
        result = _verify_prepared_data(spec, [snapshot])
    assert result["status"] == "passed" and result["replicate_disclosure_verification"]["status"] == "passed"
    assert spec == before and spec["source_request"]["categorical_binding"]["source_namespace"] == str(source)
