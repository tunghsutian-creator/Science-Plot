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
    original_run = subprocess.run
    def observe_run(*args, **kwargs):
        try:
            return original_run(*args, **kwargs)
        except subprocess.CalledProcessError as error:
            print(error.stderr or error.stdout or str(error), file=sys.stderr)
            raise
    subprocess.run = observe_run
    def observe_popen(command, *args, **kwargs):
        process = original_popen(command, *args, **kwargs)
        if isinstance(command, (list, tuple)) and "sciplot_core.veusz_worker" in command:
            operation = next((item for item in command[command.index("sciplot_core.veusz_worker") + 1:]
                              if item in {"export", "export-document", "inspect-document-state", "edit-document", "audit-spec-data"}), "native-worker")
            owned_workers.append((process, operation))
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
    export_studio_document(document, formats=["pdf"], audit_spec_path=spec)
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
    starts = len(owned_workers)
    cached = export_studio_document(native, formats=["pdf"], audit_spec_path=specification)
    assert len(owned_workers) == starts
    assert all(Path(item["path"]).is_relative_to(moved) for item in cached["exports"])
    exported = export_studio_document(native, formats=["pdf", "tiff_300"], audit_spec_path=specification)
    assert exported["document_audit"]["status"] == "passed"
    assert {item["format"] for item in exported["exports"]} == {"pdf", "tiff_300"}
    assert all(Path(item["path"]).is_relative_to(moved) and file_sha256(Path(item["path"])) == item["sha256"]
               for item in exported["exports"])
    toggled = export_studio_document(native, formats=["pdf"], audit_spec_path=specification)
    assert {item["format"] for item in toggled["exports"]} == {"pdf"}
    starts = len(owned_workers)
    repeated = export_studio_document(native, formats=["pdf"], audit_spec_path=specification)
    assert repeated["project_command"]["command_id"] == toggled["project_command"]["command_id"]
    assert len(owned_workers) == starts
    assert read_edit_operation(moved, result["operation_id"])["result_is_current"]
    assert cold.snapshot()["project_id"] == identity
    assert native.read_bytes() == saved and specification.read_bytes() == spec_bytes
    assert (moved / "source/values.csv").read_bytes() == raw
    assert not (root / ".document_edit_history").exists()
    _external_output_scenario(root, cold, owned_workers)
    gui = FileProjectStore.import_bundle(cold.export_bundle(root / "gui-bundle"), root / "gui-project")
    _gui_save_scenario(root, gui)
    subprocess.Popen, subprocess.run = original_popen, original_run
    assert owned_workers and all(process.poll() is not None for process, _ in owned_workers)
    (root / "native-public-evidence.json").write_text(json.dumps({"pid": os.getpid(), "parent_pid": os.getppid(),
        "root": str(root), "workers": [{"pid": process.pid, "command": command, "returncode": process.returncode}
                                      for process, command in owned_workers],
        "project_id": identity, "generation": cold.snapshot()["generation"],
        "checks": ["actual_native_preview_apply", "sealed_archive", "public_cold_inspect", "public_cold_export",
                   "scientific_audit", "original_spec_native_raw_bytes", "single_generation_owner"]}))




def _external_output_scenario(root, source_store, workers):
    from sciplot_core.studio_core.external_native_export import export_external_native
    from sciplot_core.project_store import FileProjectStore, state
    source = source_store.root
    document = source / "studio/document.vsz"
    original = {p.relative_to(source).as_posix(): p.read_bytes() for p in source.rglob("*") if p.is_file()}
    original_head = source_store.snapshot()["generation"]
    output = root / "independent-output"
    result = export_external_native(document, formats=["pdf", "tiff_300"], output_root=output)
    assert result["standalone_export"]["export_ready"] is True
    before = {p.relative_to(output).as_posix(): p.read_bytes() for p in output.rglob("*")
              if p.is_file() and ".sciplot_store" not in p.parts}
    assert before and all(name.split("/")[0] in {"figures", "qa_inputs", "qa_report.json", "standalone_export_receipt.json"}
                          for name in before)
    assert not list((output / ".sciplot_store/sources").rglob("*.csv"))
    old_boundary = state.boundary
    def fail(name):
        if name == "before_head":
            raise OSError("generated standalone output publication failure")
        old_boundary(name)
    state.boundary = fail
    try:
        try:
            export_external_native(document, formats=["pdf"], output_root=output)
            raise AssertionError("Output failure was missed")
        except OSError as error:
            assert "generated standalone" in str(error)
    finally:
        state.boundary = old_boundary
    assert {p.relative_to(output).as_posix(): p.read_bytes() for p in output.rglob("*")
            if p.is_file() and ".sciplot_store" not in p.parts} == before
    calls = len(workers)
    recovered = export_external_native(document, formats=["pdf"], output_root=output)
    assert recovered["standalone_export"]["export_ready"] is True and len(workers) == calls
    assert {entry["format"] for entry in recovered["exports"]} == {"pdf"}
    assert source_store.snapshot()["generation"] == original_head
    assert {p.relative_to(source).as_posix(): p.read_bytes() for p in source.rglob("*") if p.is_file()} == original
    toggled = export_external_native(document, formats=["pdf", "tiff_300"], output_root=output)
    assert {item["format"] for item in toggled["exports"]} == {"pdf", "tiff_300"}
    starts = len(workers)
    repeated = export_external_native(document, formats=["pdf", "tiff_300"], output_root=output)
    assert repeated["output_command"]["command_id"] == toggled["output_command"]["command_id"]
    assert len(workers) == starts
    assert FileProjectStore(output).snapshot()["project_id"] != source_store.snapshot()["project_id"]
    (root / "external-output-evidence.json").write_text(json.dumps({"source_project": str(source),
        "output": str(output), "checks": ["explicit_output_preserves_source_head_and_all_bytes",
        "output_has_separate_artifact_authority", "no_raw_source_shipping", "old_complete_outputs_survive_failure",
        "retry_uses_same_frozen_candidate_without_native_rerun"]}))

def _gui_save_scenario(root, store):
    from PyQt6 import QtCore, QtWidgets
    from sciplot_core.studio_core.runtime import ensure_veusz_runtime_path
    from sciplot_core.studio_core.qt_compat import ensure_veusz_loader_compat
    ensure_veusz_runtime_path()
    from veusz import qtall
    class Settings(QtCore.QSettings):
        def __init__(self, *_args, **_kwargs):
            super().__init__(str(root / "gui-test-preferences.ini"), QtCore.QSettings.Format.IniFormat)
            self.setFallbacksEnabled(False)
    qtall.QSettings = Settings
    ensure_veusz_loader_compat()
    from veusz.document import CommandInterface
    from veusz.document.operations import OperationSettingSet
    from sciplot_core.studio_core.qt_window import _create_veusz_window
    from sciplot_core.project_store import ProjectConflict
    from sciplot_core.project_store.adapters import publish_files
    from sciplot_gui.studio_assistant import native_batch
    from sciplot_core.studio_core.persistence import atomic_save_veusz_document
    app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
    target = store.root / "studio/document.vsz"
    window = _create_veusz_window(target)
    window._sciplot_save_error_handler = lambda _error: None
    document = window.document
    assert document._sciplot_project_store.root == store.root
    commands = CommandInterface(document)
    binding = document._sciplot_project_read_set
    publish_files(document._sciplot_project_store, {"studio/exports/unrelated.pdf": b"unrelated B export"}, kind="export")
    assert document._sciplot_project_read_set is binding
    commands.Set("/page1/graph1/y/label", "Unsaved manual native label (N)")
    history = list(document.historyundo)
    receipt = document.save(str(target))
    assert receipt["project_command"]["phase"] == "complete"
    assert document.historyundo == history and not document.isModified()
    commands.Set("/page1/graph1/y/label", "Command Save native label (N)")
    commands.Save(str(target))
    assert not document.isModified()
    commands.Set("/page1/graph1/y/label", "Unsaved draft must survive conflict (N)")
    history = list(document.historyundo)
    foreign = target.read_bytes() + b"\n# independent same-figure native save\n"
    publish_files(document._sciplot_project_store, {"studio/document.vsz": foreign}, kind="save")
    try:
        document.save(str(target))
        raise AssertionError("A stale GUI baseline overwrote the foreign native save")
    except ProjectConflict:
        pass
    assert target.read_bytes() == foreign and document.historyundo == history and document.isModified()
    window.slotFileSave()
    assert window._sciplot_save_error and document.isModified() and target.read_bytes() == foreign
    original_do, original_restore = OperationSettingSet.do, native_batch._Snapshot.restore
    def fail(self, doc):
        original_do(self, doc)
        raise RuntimeError("generated native partial mutation")
    def restore_failure(*_args):
        raise RuntimeError("generated unprovable restoration")
    OperationSettingSet.do, native_batch._Snapshot.restore = fail, restore_failure
    try:
        try:
            native_batch.apply_native_setting_batch(document,
                [OperationSettingSet("/page1/graph1/x/Label/size", "14pt")], description="Generated quarantine")
            raise AssertionError("Generated quarantine fault was missed")
        except native_batch.NativeBatchExecutionError as error:
            assert not error.restored
    finally:
        OperationSettingSet.do, native_batch._Snapshot.restore = original_do, original_restore
    forbidden = root / "quarantined-save-as.vsz"
    for action in (lambda: document.save(str(target)), lambda: commands.Save(str(target)),
                   lambda: atomic_save_veusz_document(document, target), lambda: document.save(str(forbidden))):
        try:
            action()
            raise AssertionError("A quarantined native draft was saved")
        except OSError as error:
            assert "quarantined" in str(error)
    window.slotFileSave()
    assert target.read_bytes() == foreign and not forbidden.exists() and document.isModified()
    # Explicitly discard only this generated test draft after all assertions.
    document.setModified(False)
    window.close()
    app.processEvents()
    (root / "gui-save-evidence.json").write_text(json.dumps({"project": str(store.root),
        "checks": ["real_gui_load_baseline", "unrelated_B_does_not_rebase_A", "direct_native_save_one_generation",
                   "command_interface_save", "same_A_conflict_preserves_unsaved_Undo", "Qt_save_failure_boundary",
                   "quarantine_blocks_direct_command_atomic_save_and_save_as"]}))

def test_public_native_edit_and_cold_open_export_use_same_generation(tmp_path):
    completed = subprocess.run([sys.executable, __file__, str(tmp_path)], env=veusz_worker_environment(),
                               text=True, capture_output=True, timeout=120)
    assert completed.returncode == 0, completed.stdout + completed.stderr
    assert json.loads((tmp_path / "native-public-evidence.json").read_text())["checks"]


if __name__ == "__main__":
    _public_native_scenario(Path(sys.argv[1]).resolve())
