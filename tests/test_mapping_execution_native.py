"""Real current mapping creation, source expansion, and offline saved publication."""
import json
import os
from pathlib import Path
import subprocess

import pytest

from sciplot_core.native_process.session import _close_workers
from sciplot_core.project_host_factory import project_store
from sciplot_core.project_store import FileProjectStore
from sciplot_core.studio import export_project_document
from sciplot_core.task_storage import load_task
from test_task_raw_replicate_mapping_native import (
    test_raw_subset_then_same_project_group_expansion_keeps_native_science_and_style as _current_native_mapping,
)

pytestmark = pytest.mark.comprehensive


def test_current_confirmed_mapping_native_expansion_and_offline_publication_keep_the_exact_science(tmp_path, monkeypatch):
    starts, popen = [], subprocess.Popen

    def observe(*args, **kwargs):
        process = popen(*args, **kwargs)
        starts.append(process)
        return process

    monkeypatch.setattr(subprocess, "Popen", observe)
    try:
        print("mapping-native: real public create, full source update, native style and raw arrays", flush=True)
        _current_native_mapping(tmp_path)
        project = Path(load_task(tmp_path / "create")["project"])
        repository = project_store(project, with_snapshot=True)
        before = repository.snapshot()
        native, spec, request = (repository.read_bytes(name) for name in
            ("studio/document.vsz", "studio/spec.json", "plot_request.json"))
        reference = json.loads(request)["data_mapping_execution"]
        assert any(entry["locator"] == reference for versions in before["sources"].values() for entry in versions.values())
        _close_workers()
        assert starts and all(process.poll() is not None for process in starts)
        cold = FileProjectStore.import_bundle(repository.export_bundle(tmp_path / "bundle"), tmp_path / "cold")
        project.rename(tmp_path / "project-offline")
        for name in ("create", "update", "measurements.csv"):
            (tmp_path / name).rename(tmp_path / (name + "-offline"))
        assert not Path(reference).exists()
        print("mapping-native: public saved cold export, full confirmation replay, native audit and one head", flush=True)
        exported = export_project_document(project_dir=cold.root, formats=["pdf", "tiff_300"])
        assert exported.ready_to_use, exported.run_payload
        assert {item["format"] for item in exported.exports} == {"pdf", "tiff_300"}
        assert all(Path(item["path"]).is_file() for item in exported.exports)
        assert cold.read_bytes("studio/document.vsz") == native
        assert cold.read_bytes("studio/spec.json") == spec
        assert cold.read_bytes("plot_request.json") == request
        current = cold.snapshot()
        assert current["generation"] != before["generation"] and current["sources"] == before["sources"]
        record = cold.commands()[-1]
        assert record["phase"] == "complete" and record["generation"] == current["generation"]
        manifests = [name for name in record["draft"]["writes"] if name.startswith("runs/") and name.endswith("/manifest.json")]
        assert len(manifests) == 1
        scientific = json.loads(cold.read_bytes(manifests[0]))["result"]["scientific_data_verification"]
        assert scientific["status"] == "passed", scientific
        (tmp_path / "mapping-native-evidence.json").write_text(json.dumps({"pid": os.getpid(),
            "parent_pid": os.getppid(), "project_id": current["project_id"], "generation": current["generation"],
            "command_id": record["command_id"], "source_count": len(current["sources"]),
            "execution": reference, "audit_status": scientific["status"], "checks": [
                "public_current_confirmation", "prepublication_child_byte_witness", "full_source_expansion",
                "scientific_arrays_units_masks", "manual_native_style_preserved", "official_bundle_import",
                "original_task_source_project_offline", "public_cold_complete_publication", "immutable_source_versions",
                "exact_native_spec_request", "full_numeric_and_native_audit"]}, indent=2))
    finally:
        _close_workers()
        assert all(process.poll() is not None for process in starts)
        (tmp_path / "mapping-native-workers.json").write_text(json.dumps([
            {"pid": process.pid, "returncode": process.returncode} for process in starts], indent=2))
