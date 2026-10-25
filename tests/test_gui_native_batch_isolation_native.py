"""Generated native drafts exercise the actual Veusz and Qt safety boundary."""

from __future__ import annotations

import json
from io import StringIO
import os
from pathlib import Path
import subprocess
import sys

import pytest

from sciplot_core.veusz_runtime import veusz_worker_environment

pytestmark = pytest.mark.comprehensive


def _native_scenario(root: Path) -> None:
    from types import SimpleNamespace

    from sciplot_core.studio_core.runtime import ensure_veusz_runtime_path
    from sciplot_core.studio_core.qt_compat import ensure_veusz_loader_compat

    ensure_veusz_runtime_path()
    from PyQt6 import QtCore, QtWidgets
    from veusz import qtall

    class FixtureSettings(QtCore.QSettings):
        def __init__(self, *_args, **_kwargs):
            super().__init__(str(root / "generated-qt-preferences.ini"), QtCore.QSettings.Format.IniFormat)
            self.setFallbacksEnabled(False)

    qtall.QSettings = FixtureSettings
    ensure_veusz_loader_compat()
    from veusz import document, widgets

    _ = widgets  # Native factory registration, without any user document.
    from veusz.document.operations import OperationMultiple, OperationSettingSet
    from veusz.document import CommandInterface

    from sciplot_core.assistant_operations import VeuszSettingOperation, VeuszSettingOperationBatch
    from sciplot_core.assistant_provider import AssistantProviderDescriptor, AssistantResponse
    from sciplot_core.studio_core.qt_window import _create_veusz_window
    from sciplot_gui.studio_assistant.bridge import attach_studio_assistant
    from sciplot_gui.studio_assistant.native_batch import (
        NativeBatchExecutionError, _document_text, apply_native_setting_batch, native_batch_blocker,
    )
    from sciplot_gui.studio_project.export_helpers import ExportHelpersMixin
    from sciplot_gui.studio_project.series_revision import SeriesRevisionMixin

    app = QtWidgets.QApplication([])
    size_path, label_path = "/page1/graph1/x/Label/size", "/page1/graph1/x/label"
    original_do, original_undo = OperationSettingSet.do, OperationSettingSet.undo
    evidence = {"pid": os.getpid(), "parent_pid": os.getppid(),
                "source": str(Path(__file__).resolve()), "root": str(root), "checks": [],
                "python": sys.version.split()[0], "executable": sys.executable,
                "qt": QtCore.qVersion(), "pyqt": QtCore.PYQT_VERSION_STR,
                "pyqt_compiled_qt": QtCore.QT_VERSION_STR,
                "veusz_document_source": str(Path(sys.modules["veusz.document.doc"].__file__).resolve())}

    def fail_second(self, native):
        original_do(self, native)
        if self.settingpath == label_path:
            raise RuntimeError("generated second-operation failure after mutation")

    # Control: actual unchanged Veusz has no compensation and has not appended Undo.
    raw = document.Document()
    raw.makeDefaultDoc()
    raw_before = raw.basewidget.getSaveText(saveall=True)
    raw_history = list(raw.historyundo)
    OperationSettingSet.do = fail_second
    try:
        try:
            raw.applyOperation(OperationMultiple([
                OperationSettingSet(size_path, "12pt"), OperationSettingSet(label_path, "changed")
            ], descr="Unsafe control"))
            raise AssertionError("Fault was not reached")
        except RuntimeError as exc:
            assert "generated second-operation" in str(exc)
        assert raw.resolveSettingPath(None, size_path).get() == "12pt"
        assert raw.basewidget.getSaveText(saveall=True) != raw_before
        assert raw.historyundo == raw_history
        evidence["checks"].append("actual_unguarded_partial_effect_without_undo")
    finally:
        OperationSettingSet.do = original_do

    window = _create_veusz_window(None)
    native = window.document
    commands = CommandInterface(native)
    commands.SetData("generated_x", [0., 1., 2.])
    commands.SetData("generated_y", [3., 5., 4.])
    commands.Add("xy", name="opaque_curve", widget="/page1/graph1")
    commands.Set("/page1/graph1/opaque_curve/xData", "generated_x")
    commands.Set("/page1/graph1/opaque_curve/yData", "generated_y")
    commands.Set("/page1/graph1/opaque_curve/PlotLine/color", "#7812ab")
    target = root / "generated.vsz"
    native.save(str(target))
    saved_bytes = target.read_bytes()
    window.filename = str(target)
    native.clearHistory()
    commands.Set("/page1/graph1/y/label", "Unsaved manual label (N)")
    commands.Set("/page1/graph1/y/Label/size", "9pt")
    native.undoOperation()  # Pre-existing Redo must also survive a failed apply.
    provider = SimpleNamespace(descriptor=AssistantProviderDescriptor(
        provider_id="generated-native-fault", display_name="Generated native fault fixture",
        capabilities=("veusz_setting_operation_batch",)),
        generate=lambda *_args, **_kw: (_ for _ in ()).throw(AssertionError("No model call allowed")))
    bridge = attach_studio_assistant(window, target, provider=provider)
    window.show()
    bridge.set_selected_widget(native.resolveWidgetPath(None, "/page1/graph1/x"))
    for _ in range(8):
        app.processEvents()

    def stage_proposal():
        request = bridge.build_request("Make the selected label larger and clarify its text")
        fields = {item["setting_path"]: item for item in request.context["editing_capabilities"]["allowed_operations"]}
        operations = tuple(VeuszSettingOperation.set_setting(
            target_id=fields[path]["target_id"], setting_path=path, value=value,
            expected_value=fields[path]["current_value"], require_expected_value=True,
        ) for path, value in ((size_path, "12pt"), (label_path, "Generated axis (s)")))
        batch = VeuszSettingOperationBatch(base_revision=request.base_revision, operations=operations,
                                          provider=request.provider_id, rationale="Generated test only")
        bridge._pending_request = request
        bridge._provider_response(AssistantResponse(
            request_id=request.request_id, transaction_id=request.transaction_id,
            provider_id=request.provider_id, request_sha256=request.payload_sha256,
            status="proposal", understanding="Generated test only", proposal_kind="veusz_setting_operation_batch",
            proposal=batch.to_dict(),
        ))
        assert bridge.pending_batch == batch

    stage_proposal()
    before_text = _document_text(native)
    before_tree = native.basewidget.getSaveText(saveall=True)
    before_revision, before_modified = native.changeset, native.isModified()
    before_history = list(native.historyundo), list(native.historyredo)
    size_setting = native.resolveSettingPath(None, size_path)
    assert size_setting.isReference()
    original_reference = size_setting.getReference().value
    OperationSettingSet.do = fail_second
    try:
        assert bridge.accept_pending() is None
    finally:
        OperationSettingSet.do = original_do
    assert native_batch_blocker(native) is None
    assert native._sciplot_native_setting_batch_adapter.last_failure is not None, bridge.status_label.text()
    assert native._sciplot_native_setting_batch_adapter.last_failure["restored"] is True
    assert _document_text(native) == before_text
    assert native.basewidget.getSaveText(saveall=True) == before_tree
    assert (native.historyundo, native.historyredo) == before_history
    assert (native.changeset, native.isModified()) == (before_revision, before_modified)
    assert size_setting.isReference() and size_setting.getReference().value == original_reference
    assert native.resolveSettingPath(None, "/page1/graph1/y/label").get() == "Unsaved manual label (N)"
    assert native.data["generated_x"].data.tolist() == [0., 1., 2.]
    assert native.data["generated_y"].data.tolist() == [3., 5., 4.]
    assert target.read_bytes() == saved_bytes
    evidence["checks"].append("gui_apply_failure_restores_raw_reference_manual_draft_history_and_data")

    stage_proposal()
    result = bridge.accept_pending()
    assert result is not None, bridge.status_label.text()
    assert len(native.historyundo) == len(before_history[0]) + 1
    assert native.historyundo[:-1] == before_history[0]
    assert native.historyredo == []
    applied = _document_text(native)

    def fail_undo(self, doc):
        original_undo(self, doc)
        if self.settingpath == size_path:
            raise RuntimeError("generated Undo failure after mutation")

    OperationSettingSet.undo = fail_undo
    try:
        window.vzactions["edit.undo"].trigger()
        assert "complete native draft was restored" in window._sciplot_native_batch_error
    finally:
        OperationSettingSet.undo = original_undo
    assert _document_text(native) == applied and native.canUndo() and not native.canRedo()
    window.vzactions["edit.undo"].trigger()
    assert _document_text(native) == before_text and native.canRedo()
    redo_baseline = list(native.historyundo), list(native.historyredo), native.changeset
    OperationSettingSet.do = fail_second
    try:
        window.vzactions["edit.redo"].trigger()
    finally:
        OperationSettingSet.do = original_do
    assert _document_text(native) == before_text
    assert (native.historyundo, native.historyredo, native.changeset) == redo_baseline
    window.vzactions["edit.redo"].trigger()
    assert _document_text(native) == applied
    evidence["checks"].append("actual_qt_undo_redo_failures_restore_and_retry")

    # Successful Save As and native export preserve the manual/opaque state.
    success_save = root / "successful-save-as.vsz"
    window.fileSaveDialog = lambda *_args: str(success_save)
    assert window.slotFileSaveAs() is True
    success_bytes = success_save.read_bytes()
    reopened = document.Document()
    reopened.load(str(success_save), callbackunsafe=lambda: False)
    assert reopened.resolveSettingPath(None, "/page1/graph1/y/label").get() == "Unsaved manual label (N)"
    assert reopened.resolveSettingPath(None, "/page1/graph1/opaque_curve/PlotLine/color").get() == "#7812ab"
    assert reopened.data["generated_y"].data.tolist() == [3., 5., 4.]
    commands.Export(str(root / "successful.pdf"), page=[0])
    assert (root / "successful.pdf").stat().st_size > 100
    evidence["checks"].append("successful_one_undo_save_as_export_and_opaque_native_reopen")

    from veusz.document import export as native_export
    from veusz.dialogs.stylesheet import StylesheetDialog

    def pdf_printer(path):
        printer = qtall.QPrinter()
        printer.setOutputFormat(qtall.QPrinter.OutputFormat.PdfFormat)
        printer.setOutputFileName(str(path))
        return printer

    successful_print = root / "successful-print.pdf"
    native_export.printPages(native, pdf_printer(successful_print), [0], setsizes=True)
    assert successful_print.stat().st_size > 100
    original_print_dialog = qtall.QPrintDialog
    print_target = root / "successful-command-print.pdf"
    print_approval = None
    print_dialog_entries = []

    class ApprovedPrintDialog:
        """Supply dialog consent; retain the actual native printer and renderer."""

        def __init__(self, printer, _parent):
            printer.setOutputFormat(qtall.QPrinter.OutputFormat.PdfFormat)
            printer.setOutputFileName(str(print_target))

        def setMinMax(self, *_args):
            pass

        def exec(self):
            print_dialog_entries.append(str(print_target))
            if print_approval is not None:
                print_approval()
            return True

        def printRange(self):
            return qtall.QAbstractPrintDialog.PrintRange.AllPages

    qtall.QPrintDialog = ApprovedPrintDialog
    commands.Print()
    assert print_target.stat().st_size > 100
    print_target = root / "successful-alias-print.pdf"
    document.printDialog(window, native)
    assert print_target.stat().st_size > 100
    print_target = root / "successful-window-print.pdf"
    window.slotFilePrint()
    assert print_target.stat().st_size > 100
    styles = StylesheetDialog(window, native)
    existing_style = root / "existing.vst"
    window.fileSaveDialog = lambda *_args: str(existing_style)
    styles.saveButton.click()
    assert "Set(" in existing_style.read_text()
    existing_style.write_bytes(b"existing stylesheet must not be truncated")
    existing_print = root / "existing-print.pdf"
    existing_print.write_bytes(b"existing print must not be overwritten")

    # Open the native export dialog before failure; its existing output is protected.
    dialog = window.slotFileExport()
    existing_exporter = document.AsyncExport(native)
    existing_export = root / "existing.pdf"
    existing_export.write_bytes(b"existing export must not be removed")
    dialog.editFileName.setText(str(existing_export))
    dialog.checkOverwrite.setChecked(True)
    def quarantine_draft():
        current_size = native.resolveSettingPath(None, size_path)
        original_set = current_size.set

        def failed_restore(value):
            if value == "12pt":
                raise RuntimeError("generated restoration failure")
            return original_set(value)

        current_size.set = failed_restore
        OperationSettingSet.do = fail_second
        try:
            try:
                apply_native_setting_batch(native, [OperationSettingSet(size_path, "14pt"),
                                                   OperationSettingSet(label_path, "quarantined")],
                                           description="Generated quarantine")
                raise AssertionError("Fault did not execute")
            except NativeBatchExecutionError as exc:
                assert not exc.restored
        finally:
            current_size.set = original_set
            OperationSettingSet.do = original_do

    # The native print dialog's modal loop is already active when failure occurs.
    print_target = existing_print
    print_approval = quarantine_draft
    window.vzactions["file.print"].trigger()
    assert print_dialog_entries[-1] == str(existing_print)
    assert "quarantined" in window._sciplot_native_batch_error
    qtall.QPrintDialog = original_print_dialog
    assert native_batch_blocker(native) is not None and native.isModified()
    assert native._sciplot_native_setting_batch_adapter.last_failure["restoration_error"]
    missing_output_guards = []
    try:
        native_export.printPages(native, pdf_printer(existing_print), [0], setsizes=True)
        missing_output_guards.append("printPages accepted quarantined draft")
    except OSError as exc:
        assert "quarantined" in str(exc)
    style_stream = StringIO()
    try:
        native.exportStyleSheet(style_stream)
        missing_output_guards.append("exportStyleSheet accepted quarantined draft")
    except OSError as exc:
        assert "quarantined" in str(exc)
    styles.saveButton.click()
    if existing_style.read_bytes() != b"existing stylesheet must not be truncated":
        missing_output_guards.append("existing stylesheet dialog truncated output")
    if existing_print.read_bytes() != b"existing print must not be overwritten":
        missing_output_guards.append("printPages overwrote existing output")
    assert not missing_output_guards, missing_output_guards
    assert style_stream.getvalue() == ""
    quarantined_text = _document_text(native)
    assert window.slotFileSave() is False
    assert window.slotFileSaveAs() is False
    assert success_save.read_bytes() == success_bytes and target.read_bytes() == saved_bytes
    denied_target = root / "denied.vsz"
    denied_stream = StringIO()
    for port in (lambda: native.save(str(denied_target)), lambda: commands.Save(str(denied_target)),
                 lambda: native.save(str(denied_target), mode="hdf5"),
                 lambda: native.saveToFile(denied_stream), lambda: native.saveToHDF5File(None),
                 lambda: commands.Export(str(existing_export), page=[0]),
                 lambda: existing_exporter.add(str(existing_export), [0]),
                 commands.Print, lambda: document.printDialog(window, native)):
        try:
            port()
            raise AssertionError("Quarantined port accepted")
        except OSError as exc:
            assert "quarantined" in str(exc)
    assert not denied_target.exists()
    assert denied_stream.getvalue() == ""
    dialog.accept()
    assert existing_export.read_bytes() == b"existing export must not be removed"
    assert window.slotFileExport() is False
    assert window.slotFilePrint() is False
    window.vzactions["file.print"].trigger()
    window.vzactions["edit.undo"].trigger()
    window.vzactions["edit.redo"].trigger()
    assert _document_text(native) == quarantined_text
    assert bridge._document_context_blocker() == native_batch_blocker(native)
    assert bridge.accept_pending() is None
    assert "quarantined" in ExportHelpersMixin._assistant_export_blocker(SimpleNamespace(document=native))
    try:
        SeriesRevisionMixin.save_or_commit_current_document(SimpleNamespace(document=native), denied_target)
        raise AssertionError("Project save admitted quarantined draft")
    except RuntimeError as exc:
        assert "quarantined" in str(exc)
    evidence["checks"].append("quarantine_blocks_native_save_save_as_command_export_open_dialog_project_save_and_qt_history")
    native.load(str(success_save), callbackunsafe=lambda: False)
    assert native_batch_blocker(native) is None
    # Quarantine can also arise while the stylesheet filename picker is open.
    def choose_stylesheet_after_failure(*_args):
        quarantine_draft()
        return str(existing_style)

    window.fileSaveDialog = choose_stylesheet_after_failure
    styles.saveButton.click()
    assert native_batch_blocker(native) is not None
    assert existing_style.read_bytes() == b"existing stylesheet must not be truncated"
    native.load(str(success_save), callbackunsafe=lambda: False)
    assert native_batch_blocker(native) is None
    evidence["checks"].append("print_alias_qt_existing_modal_and_stylesheet_existing_dialog_picker_preserve_outputs")
    commands.Save(str(root / "after-explicit-reload.vsz"))
    evidence["checks"].append("explicit_successful_reload_releases_quarantine")
    window.document.setModified(False)
    styles.close()
    dialog.close()
    window.close()
    app.quit()
    print(json.dumps(evidence, sort_keys=True))


def test_generated_native_batch_failure_isolation_and_gui_ports(tmp_path: Path):
    code = "from pathlib import Path; from test_gui_native_batch_isolation_native import _native_scenario; import sys; _native_scenario(Path(sys.argv[1]))"
    result = subprocess.run([sys.executable, "-c", code, str(tmp_path)], text=True,
                            capture_output=True, env=veusz_worker_environment(), timeout=90)
    assert result.returncode == 0, result.stdout + result.stderr
    evidence = json.loads(result.stdout.strip().splitlines()[-1])
    assert len(evidence["checks"]) == 7
    assert evidence["parent_pid"] == os.getpid()
    print(json.dumps(evidence, sort_keys=True))
