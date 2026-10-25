"""Controlled setting-operation failures, without a provider or user project."""

from __future__ import annotations

from types import ModuleType, SimpleNamespace
from io import StringIO
import sys

import pytest

from sciplot_gui.studio_assistant.proposal_application import ProposalApplicationMixin
from sciplot_gui.studio_assistant.native_batch import (
    NativeBatchExecutionError,
    apply_native_setting_batch,
    native_batch_blocker,
)


class Setting:
    def __init__(self, value):
        self.value = value

    def get(self):
        return self.value

    def isReference(self):
        return False

    def set(self, value):
        self.value = value

    def saveText(self, _all):
        return repr(self.value)


class SettingOperation:
    def __init__(self, path, value):
        self.settingpath, self.value = path, value

    def do(self, document):
        setting = document.settings[self.settingpath]
        self.oldvalue = setting.get()
        setting.set(self.value)

    def undo(self, document):
        document.settings[self.settingpath].set(self.oldvalue)


class Multiple:
    def __init__(self, operations, descr):
        self.operations, self.descr = operations, descr

    def do(self, document):
        for operation in self.operations:
            operation.do(document)

    def undo(self, document):
        for operation in reversed(self.operations):
            operation.undo(document)


class Document:
    def __init__(self):
        self.settings = {"first": Setting("original"), "second": Setting("original"),
                         "manual": Setting("unsaved manual work")}
        self.historyundo = [object()]
        self.historyredo = []
        self.historybatch = []
        self.suspendupdates = []
        self.changeset, self.modified, self.filename = 17, True, "original.vsz"
        self.compatlevel, self.data = 1, {}
        self.basewidget = SimpleNamespace(getSaveText=lambda **_kw: repr({
            key: setting.value for key, setting in self.settings.items()}))
        self.evaluate = SimpleNamespace(saveCustomDefinitions=lambda _stream: None)
        self.signalModified = SimpleNamespace(emit=lambda _value: None)
        self.saved = []

    def resolveSettingPath(self, _root, path):
        return self.settings[path]

    def walkNodes(self, callback, **_kw):
        for path, setting in self.settings.items():
            callback(path, setting)

    def saveDatasetTags(self, _stream):
        pass

    def applyOperation(self, operation, redoing=False):
        operation.do(self)
        self.changeset += 1
        self.historyundo = self.historyundo[-9:] + [operation]
        if not redoing:
            self.historyredo = []

    def undoOperation(self):
        operation = self.historyundo.pop()
        operation.undo(self)
        self.changeset += 1
        self.historyredo.append(operation)

    def redoOperation(self):
        operation = self.historyredo.pop()
        return self.applyOperation(operation, redoing=True)

    def save(self, filename, *_args):
        self.saved.append(filename)

    def saveToFile(self, stream):
        stream.write(self.basewidget.getSaveText())

    def saveToHDF5File(self, _stream):
        self.saved.append("hdf5")

    def load(self, _filename, **_kwargs):
        self.settings["first"].set("reloaded")


@pytest.fixture
def native(monkeypatch):
    module = ModuleType("veusz.document.operations")
    module.OperationSettingSet = SettingOperation
    module.OperationMultiple = Multiple
    monkeypatch.setitem(sys.modules, module.__name__, module)
    export = ModuleType("veusz.document.export")
    export.AsyncExport = type("AsyncExport", (), {"add": lambda self, *_args: self.doc.saved.append("export")})
    monkeypatch.setitem(sys.modules, export.__name__, export)
    return Document()


def proposal_context(document, operations):
    text = SimpleNamespace(setText=lambda _text: None, setPlainText=lambda _text: None)
    request = SimpleNamespace(base_revision=document.changeset,
                              visual_preview={"sha256": "before"})
    return SimpleNamespace(
        document=document, _document_context_blocker=lambda: None,
        _pending_batch=SimpleNamespace(batch_id="controlled", base_revision=document.changeset),
        _pending_request=request, _pending_response=None,
        _request_targets_current_selection=lambda _request: True,
        _prepare_native_operations=lambda *_args, **_kwargs: (operations, []),
        _record_history=lambda **_kwargs: None, _clear_pending=lambda: None,
        status_label=text, proposal_view=text,
        requestRejected=SimpleNamespace(emit=lambda _value: None),
    )


def test_gui_second_operation_failure_restores_entire_live_draft(native, monkeypatch):
    """The previous OperationMultiple path leaves first='changed' here."""
    first = SettingOperation("first", "changed")
    second = SettingOperation("second", "changed")
    original_do = SettingOperation.do

    def fail_second(self, document):
        if self is second:
            raise RuntimeError("controlled second operation failure")
        original_do(self, document)

    monkeypatch.setattr(SettingOperation, "do", fail_second)
    before_history = list(native.historyundo)
    result = ProposalApplicationMixin.accept_pending(proposal_context(native, [first, second]))
    assert result is None
    assert native.settings["first"].get() == "original"
    assert native.settings["second"].get() == "original"
    assert native.settings["manual"].get() == "unsaved manual work"
    assert native.historyundo == before_history
    assert native.changeset == 17 and native.modified is True


def apply(document):
    operations = [SettingOperation("first", "changed"), SettingOperation("second", "changed")]
    apply_native_setting_batch(document, operations, description="Controlled batch")
    return operations


@pytest.mark.parametrize("action", ["apply", "undo", "redo"])
@pytest.mark.parametrize("raise_after_mutation", [False, True])
def test_failed_lifecycle_restores_full_draft_history_and_retry(
    native, monkeypatch, action, raise_after_mutation,
):
    if action == "apply":
        operations = [SettingOperation("first", "changed"), SettingOperation("second", "changed")]
        def execute():
            return apply_native_setting_batch(native, operations, description="Controlled batch")
        failing, method_name = operations[1], "do"
    else:
        operations = apply(native)
        if action == "redo":
            native.undoOperation()
        execute = native.undoOperation if action == "undo" else native.redoOperation
        failing = operations[0] if action == "undo" else operations[1]
        method_name = "undo" if action == "undo" else "do"
    baseline = {key: setting.value for key, setting in native.settings.items()}
    histories = (list(native.historyundo), list(native.historyredo))
    revision = native.changeset
    original = getattr(SettingOperation, method_name)

    def fault(self, document):
        if self is failing and not raise_after_mutation:
            raise RuntimeError("controlled lifecycle failure")
        original(self, document)
        if self is failing:
            raise RuntimeError("controlled partial-current-operation failure")

    monkeypatch.setattr(SettingOperation, method_name, fault)
    with pytest.raises(NativeBatchExecutionError) as caught:
        execute()
    assert caught.value.restored is True
    assert native_batch_blocker(native) is None
    assert {key: setting.value for key, setting in native.settings.items()} == baseline
    assert (native.historyundo, native.historyredo) == histories
    assert native.changeset == revision and native.modified is True
    assert native.filename == "original.vsz"
    monkeypatch.setattr(SettingOperation, method_name, original)
    execute()
    assert native.settings["first"].value == ("original" if action == "undo" else "changed")


def test_success_is_one_undo_step_and_manual_operations_remain_native(native):
    earlier = native.historyundo[0]
    apply(native)
    assert len(native.historyundo) == 2 and native.historyundo[0] is earlier
    assert native.historyundo[-1].descr == "Controlled batch"
    native.undoOperation()
    assert native.settings["first"].value == "original"
    assert native.settings["second"].value == "original"
    native.redoOperation()
    native.applyOperation(SettingOperation("manual", "further manual work"))
    native.undoOperation()
    assert native.settings["manual"].value == "unsaved manual work"
    native.save("allowed.vsz")
    assert native.saved == ["allowed.vsz"]


@pytest.mark.parametrize("action", ["apply", "undo", "redo"])
def test_rollback_failure_quarantines_all_mutation_save_and_export_ports(native, monkeypatch, action):
    if action == "apply":
        operations = [SettingOperation("first", "changed"), SettingOperation("second", "changed")]
        def execute():
            return apply_native_setting_batch(native, operations, description="Fault")
        failing, method_name = operations[1], "do"
    else:
        operations = apply(native)
        if action == "redo":
            native.undoOperation()
        execute = native.undoOperation if action == "undo" else native.redoOperation
        failing = operations[0] if action == "undo" else operations[1]
        method_name = "undo" if action == "undo" else "do"
    original = getattr(SettingOperation, method_name)

    def corrupt(self, document):
        original(self, document)
        if self is failing:
            # Simulates a setting callback whose side effect cannot be restored.
            document.data["unexpected"] = object()
            raise RuntimeError("controlled un-restorable mutation")

    monkeypatch.setattr(SettingOperation, method_name, corrupt)
    with pytest.raises(NativeBatchExecutionError) as caught:
        execute()
    assert caught.value.restored is False
    assert "quarantined" in native_batch_blocker(native)
    assert native.modified is True
    assert native.settings["manual"].value == "unsaved manual work"
    stream = StringIO()
    exporter = sys.modules["veusz.document.export"].AsyncExport()
    exporter.doc = native
    for port in (
        lambda: native.save("never-written.vsz"), lambda: native.saveToFile(stream),
        lambda: native.saveToHDF5File(None), lambda: exporter.add("never-written.pdf", [0]),
        lambda: native.applyOperation(SettingOperation("manual", "blocked")),
        native.undoOperation, native.redoOperation,
        lambda: apply_native_setting_batch(native, operations, description="blocked proposal"),
    ):
        with pytest.raises(OSError, match="quarantined"):
            port()
    assert native.saved == [] and stream.getvalue() == ""
    native.data.clear()
    native.load("explicit-reload.vsz")
    assert native_batch_blocker(native) is None
    native.save("after-reload.vsz")
    assert native.saved == ["after-reload.vsz"]


def test_setting_restoration_exception_quarantines_even_with_matching_partial_state(native, monkeypatch):
    first, second = SettingOperation("first", "changed"), SettingOperation("second", "changed")
    original_do, original_set = SettingOperation.do, Setting.set

    def fail(self, document):
        original_do(self, document)
        if self is second:
            raise RuntimeError("controlled second failure")

    def fail_restore(self, value):
        if value == "original":
            raise RuntimeError("controlled rollback failure")
        original_set(self, value)

    monkeypatch.setattr(SettingOperation, "do", fail)
    monkeypatch.setattr(Setting, "set", fail_restore)
    with pytest.raises(NativeBatchExecutionError, match="quarantined"):
        apply_native_setting_batch(native, [first, second], description="Fault")
    assert "controlled rollback failure" in native._sciplot_native_setting_batch_adapter.last_failure["restoration_error"]


def test_snapshot_refusal_and_unknown_operation_have_no_mutation(native, monkeypatch):
    with pytest.raises(TypeError, match="concrete Veusz"):
        apply_native_setting_batch(native, [object()], description="unsupported")
    monkeypatch.setattr(native.basewidget, "getSaveText", lambda **_kwargs: (_ for _ in ()).throw(ValueError("snapshot refused")))
    with pytest.raises(ValueError, match="snapshot refused"):
        apply(native)
    assert native.settings["first"].value == "original"
    assert native_batch_blocker(native) is None


def test_native_history_batch_refused_before_mutation_and_failed_reload_keeps_quarantine(native, monkeypatch):
    native.historybatch.append(object())
    with pytest.raises(RuntimeError, match="Finish the current native history batch"):
        apply(native)
    assert native.settings["first"].value == "original"
    adapter = native._sciplot_native_setting_batch_adapter
    adapter.blocker = "quarantined controlled draft"
    monkeypatch.setitem(adapter._original, "load", lambda *_args, **_kw: (_ for _ in ()).throw(ValueError("failed reload")))
    with pytest.raises(ValueError, match="failed reload"):
        native.load("unreadable.vsz")
    assert native_batch_blocker(native) == "quarantined controlled draft"
