"""Generated native public callers retain science through offline project moves."""

from __future__ import annotations

import json
import os
from pathlib import Path
import shutil
import subprocess
import sys

import pytest

from sciplot_core.veusz_runtime import veusz_worker_environment

pytestmark = pytest.mark.comprehensive


def _public_native_scenario(root: Path) -> None:
    from sciplot_core.foundation.file_hashing import file_sha256
    from sciplot_core.project_store import FileProjectStore
    from sciplot_core.render import render_to_dir
    from sciplot_core.studio_core.document_edit import preview_document_edit, apply_document_edit
    from sciplot_core.studio_core.document_edit_commit import read_edit_operation
    from sciplot_core.studio_core.export_execution import export_studio_document
    from sciplot_core.studio_core.project_query import inspect_project

    owned_workers = []
    original_popen = subprocess.Popen
    def observe_popen(command, *args, **kwargs):
        process = original_popen(command, *args, **kwargs)
        if isinstance(command, (list, tuple)) and "sciplot_core.veusz_worker" in command:
            owned_workers.append((process, command[command.index("sciplot_core.veusz_worker") + 1]))
        return process
    subprocess.Popen = observe_popen

    original = root / "original"
    source = original / "source/values.csv"
    source.parent.mkdir(parents=True)
    source.write_text("Time,Force\ns,N\nA,A\n0,1\n1,3\n2,2\n")
    raw = source.read_bytes()
    rendered = render_to_dir(source, template="curve", output_dir=root / "private-render",
                             export_formats=(), options={"size": "60x55"})
    studio = original / "studio"
    studio.mkdir()
    document, spec = studio / "document.vsz", studio / "spec.json"
    shutil.copy2(rendered["veusz_documents"][0], document)
    shutil.copy2(rendered["veusz_specs"][0], spec)
    (original / "plot_request.json").write_text(json.dumps({"input": str(source), "template": "curve"}))
    before, spec_bytes = document.read_bytes(), spec.read_bytes()
    detail = inspect_project(original, figure_id="primary", native=True)
    field = next(item for item in detail["selected_figure"]["objects"]["/page1/graph1/x"]["editable_fields"]
                 if item["field_id"] == "axis_label_size")
    review = preview_document_edit(original, [{"object_path": "/page1/graph1/x", "setting_path": field["setting_path"],
        "expected_value": field["current_value"], "value": "10pt"}], output_dir=root / "preview",
        expected_document_sha256=file_sha256(document))
    result = apply_document_edit(original, review)
    assert result["result_is_current"] and Path(result["archive"]).read_bytes() == before
    assert source.read_bytes() == raw and spec.read_bytes() == spec_bytes
    saved = document.read_bytes()
    store = FileProjectStore(original)
    identity = store.snapshot()["project_id"]
    bundle = store.export_bundle(root / "bundle")
    cold = FileProjectStore.import_bundle(bundle, root / "moved")
    original.rename(root / "original-offline")
    assert not source.exists()
    moved = cold.root
    native, specification = moved / "studio/document.vsz", moved / "studio/spec.json"
    inspected = inspect_project(moved, figure_id="primary", native=True)
    assert inspected["selected_figure"]["objects"]["/page1/graph1/x"]["settings"]["Label/size"] == "10pt"
    assert inspected["source"]["prepared"]["current"] is True
    exported = export_studio_document(native, formats=["pdf", "tiff_300"], audit_spec_path=specification)
    assert exported["document_audit"]["status"] == "passed"
    assert {item["format"] for item in exported["exports"]} == {"pdf", "tiff_300"}
    assert all(Path(item["path"]).is_relative_to(moved) and file_sha256(Path(item["path"])) == item["sha256"]
               for item in exported["exports"])
    assert read_edit_operation(moved, result["operation_id"])["result_is_current"]
    assert cold.snapshot()["project_id"] == identity
    assert native.read_bytes() == saved and specification.read_bytes() == spec_bytes
    assert (moved / "source/values.csv").read_bytes() == raw
    assert not (root / ".document_edit_history").exists()
    subprocess.Popen = original_popen
    assert owned_workers and all(process.poll() is not None for process, _ in owned_workers)
    (root / "native-public-evidence.json").write_text(json.dumps({"pid": os.getpid(), "parent_pid": os.getppid(),
        "root": str(root), "workers": [{"pid": process.pid, "command": command, "returncode": process.returncode}
                                      for process, command in owned_workers],
        "project_id": identity, "generation": cold.snapshot()["generation"],
        "checks": ["actual_native_preview_apply", "sealed_archive", "public_cold_inspect", "public_cold_export",
                   "scientific_audit", "original_spec_native_raw_bytes", "single_generation_owner"]}))


def test_public_native_edit_and_cold_open_export_use_same_generation(tmp_path):
    completed = subprocess.run([sys.executable, __file__, str(tmp_path)], env=veusz_worker_environment(),
                               text=True, capture_output=True, timeout=120)
    assert completed.returncode == 0, completed.stdout + completed.stderr
    assert json.loads((tmp_path / "native-public-evidence.json").read_text())["checks"]


if __name__ == "__main__":
    _public_native_scenario(Path(sys.argv[1]).resolve())
