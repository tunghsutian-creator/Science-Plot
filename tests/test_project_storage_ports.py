"""Physical Studio adapters consume the single scoped source locator owner."""

import json
from pathlib import Path
import subprocess

from sciplot_core.foundation.file_hashing import file_sha256
from sciplot_core.project_store import FileProjectStore
from sciplot_core.project_store.runtime import project_runtime
from sciplot_core.studio_core import persistence
from sciplot_core.studio_core.source_snapshots import _studio_metric_source, _studio_snapshot_sources


def moved_project(tmp_path):
    root = tmp_path / "project"
    table = root / "source/plotting_data.csv"
    table.parent.mkdir(parents=True)
    table.write_bytes(b"x,y\n1,2\n3,4\n")
    native = root / "studio/document.vsz"
    native.parent.mkdir()
    native.write_bytes(b"fixed native bytes")
    (root / "plot_request.json").write_bytes(b"{}")
    store = FileProjectStore(root)
    store.snapshot(import_legacy=True)
    cold = FileProjectStore.import_bundle(store.export_bundle(tmp_path / "bundle"), tmp_path / "cold")
    root.rename(tmp_path / "origin-offline")
    return root, table, native, cold


def test_studio_snapshot_and_metric_directory_use_exact_cold_members(tmp_path):
    root, table, _native, cold = moved_project(tmp_path)
    artifact = {"path": str(table), "sha256": file_sha256(cold.root / "source/plotting_data.csv"), "role": "output"}
    ledger = {"steps": [{"output_artifacts": [artifact]}]}
    before = json.dumps(ledger, sort_keys=True)
    with project_runtime(cold):
        sources = _studio_snapshot_sources(root / "source", project_dir=cold.root, transform_ledger=ledger)
        assert sources == [cold.root / "source/plotting_data.csv"]
        metric = _studio_metric_source(root / "source")
        assert metric is not None and metric.read_bytes() == b"x,y\n1,2\n3,4\n"
    assert json.dumps(ledger, sort_keys=True) == before
    assert not root.exists()


def test_unit_migration_cold_command_carries_exact_selected_runtime_without_native_replay(tmp_path, monkeypatch):
    _root, _table, native, cold = moved_project(tmp_path)
    monkeypatch.setattr("sciplot_core.veusz_runtime.needs_veusz_worker_process", lambda: True)
    calls = []
    def run(argv, **kwargs):
        assert "--project-runtime" in argv and "migrate-unit-labels" in argv
        value = json.loads(Path(argv[4]).read_text())
        assert value["project"]["project_id"] == cold.snapshot()["project_id"]
        assert argv[-1] == str(cold.root / "studio/document.vsz")
        calls.append(kwargs)
        return subprocess.CompletedProcess(argv, 0, '{"status":"observed"}', '')
    monkeypatch.setattr(persistence.subprocess, "run", run)
    with project_runtime(cold):
        assert persistence.migrate_studio_document_unit_labels(native) == {"status": "observed"}
    assert len(calls) == 1 and calls[0]["check"] is True
    assert (cold.root / "studio/document.vsz").read_bytes() == b"fixed native bytes"
