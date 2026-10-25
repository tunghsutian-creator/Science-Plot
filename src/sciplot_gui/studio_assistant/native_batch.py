"""Failure isolation for live desktop Assistant setting batches.

Veusz remains the document and Undo owner. This adapter admits only its concrete
setting-set operation, preserves raw references, and verifies the complete native
save representation after compensation. An uncertain draft stays open but cannot
be mutated, saved or exported until an explicit successful native reload.
"""

from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass
import errno
from importlib import import_module
from io import StringIO
from typing import Any, Callable


class NativeBatchExecutionError(RuntimeError):
    def __init__(self, action: str, *, restored: bool, cause: BaseException):
        self.restored = restored
        self.reason_code = "native_batch_restored" if restored else "native_batch_quarantined"
        detail = (
            "The complete native draft was restored, including earlier unsaved work."
            if restored else
            "Restoration could not be verified. This draft is quarantined: save, "
            "export and further edits are blocked. Reload the saved document or "
            "close and explicitly discard this draft to continue."
        )
        super().__init__(f"Native setting batch {action} failed: {cause}. {detail}")


class _SettingBatch:
    """One native Undo entry, always executed through its document adapter."""

    def __init__(self, operations: list[Any], description: str):
        self.operations = tuple(operations)
        self.descr = description

    def do(self, document: Any) -> None:
        for operation in self.operations:
            operation.do(document)

    def undo(self, document: Any) -> None:
        for operation in reversed(self.operations):
            operation.undo(document)


def _copy_value(value: Any) -> Any:
    # Copy reference paths, never a reference's cached resolved widget/Qt graph.
    if type(value).__module__ == "veusz.setting.reference":
        reference = import_module("veusz.setting.reference")
        if type(value) not in (reference.Reference, reference.ReferenceMultiple):
            raise TypeError("Unsupported native setting reference")
        return type(value)(deepcopy(value.value))
    return deepcopy(value)


def _raw_value(setting: Any) -> Any:
    if setting.isReference():
        return _copy_value(setting.getReference())
    # Backward-compatibility alias settings override get() to forward through
    # legacy paths, some of which are intentionally absent in the stylesheet.
    # Snapshot storage, without resolving aliases or evaluating references.
    return _copy_value(setting._val if hasattr(setting, "_val") else setting.get())


def _setting_text(setting: Any) -> str:
    if setting.isReference():
        value = setting.getReference()
        return f"{type(value).__qualname__}:{value.value!r}"
    if hasattr(setting, "_val"):
        # Include readonly and alias storage, which saveText may omit.
        return str(import_module("veusz.utils").rrepr(setting._val))
    # Pure protocol fixtures use the same non-truncating save representation.
    return str(setting.saveText(True))


def _document_text(document: Any) -> str:
    """Use native serializers without saveToFile's setModified(False) side effect."""
    stream = StringIO()
    stream.write(f"compatibility={document.compatlevel!r}\n")
    links: dict[Any, Any] = {}
    for _name, dataset in sorted(document.data.items()):
        dataset.saveLinksToSavedDoc(stream, links, relpath=None)
    for name, dataset in sorted(document.data.items()):
        dataset.saveToFile(stream, name)
    document.saveDatasetTags(stream)
    document.evaluate.saveCustomDefinitions(stream)
    stream.write(document.basewidget.getSaveText(saveall=True))
    return stream.getvalue()


@dataclass
class _Snapshot:
    settings: list[tuple[str, Any, Any, str]]
    native_text: str
    metadata: dict[str, Any]
    histories: dict[str, list[Any]]
    operation_state: list[tuple[Any, dict[str, Any]]]

    @classmethod
    def capture(cls, document: Any, batch: _SettingBatch) -> _Snapshot:
        settings: list[tuple[str, Any, Any, str]] = []
        document.walkNodes(
            lambda path, node: settings.append((path, node, _raw_value(node), _setting_text(node))),
            nodetypes=("setting",),
        )
        return cls(
            settings=settings, native_text=_document_text(document),
            metadata={name: getattr(document, name) for name in ("changeset", "modified", "filename")},
            histories={name: list(getattr(document, name)) for name in (
                "historyundo", "historyredo", "historybatch", "suspendupdates")},
            operation_state=[(operation, {key: _copy_value(value) for key, value in vars(operation).items()})
                             for operation in batch.operations],
        )

    def restore(self, document: Any) -> None:
        for path, node, value, text in self.settings:
            if document.resolveSettingPath(None, path) is not node:
                raise RuntimeError(f"Native setting identity changed at {path}")
            if _setting_text(node) != text:
                node.set(_copy_value(value))
        for operation, state in self.operation_state:
            vars(operation).clear()
            vars(operation).update(state)
        for name, value in self.metadata.items():
            setattr(document, name, value)
        for name, value in self.histories.items():
            setattr(document, name, list(value))
        self.verify(document)

    def verify(self, document: Any) -> None:
        current: list[tuple[str, Any, str]] = []
        document.walkNodes(lambda path, node: current.append((path, node, _setting_text(node))),
                           nodetypes=("setting",))
        expected = [(path, node, text) for path, node, _value, text in self.settings]
        if current != expected or _document_text(document) != self.native_text:
            raise RuntimeError("Complete native state differs from the pre-execution draft")
        if any(getattr(document, name) != value for name, value in self.metadata.items()):
            raise RuntimeError("Native document metadata was not restored")
        for name, value in self.histories.items():
            actual = getattr(document, name)
            if len(actual) != len(value) or any(a is not b for a, b in zip(actual, value, strict=True)):
                raise RuntimeError(f"Native {name} was not restored")


class NativeSettingBatchAdapter:
    """Per-live-document execution safety; no persisted scientific state."""

    def __init__(self, document: Any):
        self.document = document
        self.blocker: str | None = None
        self.last_failure: dict[str, Any] | None = None
        self._executing = False
        self._loading = False
        self._original = {name: getattr(document, name) for name in (
            "applyOperation", "undoOperation", "redoOperation", "save", "saveToFile",
            "saveToHDF5File", "exportStyleSheet", "load")}
        document.applyOperation = self._apply
        document.undoOperation = self._undo
        document.redoOperation = self._redo
        for name in ("save", "saveToFile", "saveToHDF5File", "exportStyleSheet"):
            setattr(document, name, self._guard_output(self._original[name]))
        document.load = self._load

    def require_usable(self) -> None:
        if self.blocker is not None:
            raise OSError(errno.EPERM, self.blocker)
        if self._executing:
            raise OSError(errno.EBUSY, "A native setting batch is executing; save and export are blocked.")

    def _guard_output(self, original: Callable[..., Any]) -> Callable[..., Any]:
        def guarded(*args: Any, **kwargs: Any) -> Any:
            self.require_usable()
            return original(*args, **kwargs)
        return guarded

    def _execute(self, action: str, batch: _SettingBatch, original: Callable[[], Any]) -> Any:
        self.require_usable()
        if self.document.historybatch:
            raise RuntimeError("Finish the current native history batch before applying an Assistant batch")
        snapshot = _Snapshot.capture(self.document, batch)
        self._executing = True
        try:
            return original()
        except BaseException as exc:
            restored = False
            restoration_error: str | None = None
            try:
                snapshot.restore(self.document)
                # Refresh native views using the original modified/revision state.
                self.document.signalModified.emit(self.document.modified)
                snapshot.verify(self.document)
                restored = True
            except BaseException as restore_exc:
                restoration_error = f"{type(restore_exc).__name__}: {restore_exc}"
            error = NativeBatchExecutionError(action, restored=restored, cause=exc)
            self.last_failure = {"action": action, "restored": restored,
                                 "reason_code": error.reason_code,
                                 "error": str(exc), "restoration_error": restoration_error}
            if not restored:
                self.blocker = str(error)
                # A failed clean draft must also take the native close-confirmation
                # path. Never let uncertain edits disappear as an unmodified file.
                self.document.modified = True
                try:
                    self.document.signalModified.emit(True)
                except Exception:
                    pass
            raise error from exc
        finally:
            self._executing = False

    def _apply(self, operation: Any, redoing: bool = False) -> Any:
        # Veusz redo delegates to self.applyOperation while _execute owns its snapshot.
        if self._executing:
            if not redoing or not isinstance(operation, _SettingBatch):
                raise RuntimeError("Reentrant native mutation during setting batch execution")
            return self._original["applyOperation"](operation, redoing=True)
        if not self._loading:
            self.require_usable()
        if isinstance(operation, _SettingBatch):
            return self._execute("apply", operation, lambda: self._original["applyOperation"](operation, redoing=redoing))
        return self._original["applyOperation"](operation, redoing=redoing)

    def _undo(self) -> Any:
        self.require_usable()
        if self.document.historyundo and isinstance(self.document.historyundo[-1], _SettingBatch):
            return self._execute("undo", self.document.historyundo[-1], self._original["undoOperation"])
        return self._original["undoOperation"]()

    def _redo(self) -> Any:
        self.require_usable()
        if self.document.historyredo and isinstance(self.document.historyredo[-1], _SettingBatch):
            return self._execute("redo", self.document.historyredo[-1], self._original["redoOperation"])
        return self._original["redoOperation"]()

    def _load(self, *args: Any, **kwargs: Any) -> Any:
        if self._executing or self._loading:
            raise RuntimeError("Cannot reload during native setting batch execution")
        self._loading = True
        try:
            result = self._original["load"](*args, **kwargs)
            _document_text(self.document)
            self.blocker = None
            self.last_failure = None
            return result
        finally:
            self._loading = False


def native_batch_blocker(document: Any) -> str | None:
    adapter = getattr(document, "_sciplot_native_setting_batch_adapter", None)
    if adapter is None:
        return None
    if not isinstance(adapter, NativeSettingBatchAdapter):
        return "Native setting batch safety state is unavailable. Reload this document before saving or exporting."
    if adapter._executing:
        return "A native setting batch is executing; save and export are blocked."
    return adapter.blocker


def _require_document_output(document: Any) -> None:
    adapter = getattr(document, "_sciplot_native_setting_batch_adapter", None)
    if adapter is not None:
        adapter.require_usable()


def _install_output_guards() -> None:
    # Export dialogs can predate a failing batch. Guard the actual rendering
    # admission, shared by native File→Export and CommandInterface.Export.
    native_export: Any = import_module("veusz.document.export")
    exporter = native_export.AsyncExport
    if getattr(exporter.add, "_sciplot_native_batch_guard", False):
        return
    original = exporter.add

    def guarded(self: Any, *args: Any, **kwargs: Any) -> Any:
        _require_document_output(self.doc)
        return original(self, *args, **kwargs)

    guarded._sciplot_native_batch_guard = True  # type: ignore[attr-defined]
    exporter.add = guarded

    # Printing has a separate native renderer and can write PDF directly.
    # Guard before QPainter begins, keeping paintTo available to the canvas.
    original_print_pages = native_export.printPages
    original_print_dialog = native_export.printDialog

    def print_pages(document: Any, *args: Any, **kwargs: Any) -> Any:
        _require_document_output(document)
        return original_print_pages(document, *args, **kwargs)

    def print_dialog(parentwindow: Any, document: Any, *args: Any, **kwargs: Any) -> Any:
        _require_document_output(document)
        return original_print_dialog(parentwindow, document, *args, **kwargs)

    native_export.printPages = print_pages
    native_export.printDialog = print_dialog
    # MainWindow uses the package alias; CommandInterface uses the export module.
    native_document: Any = import_module("veusz.document")
    native_document.printDialog = print_dialog


def ensure_native_setting_batch_adapter(document: Any) -> NativeSettingBatchAdapter:
    adapter = getattr(document, "_sciplot_native_setting_batch_adapter", None)
    if adapter is None:
        _install_output_guards()
        adapter = NativeSettingBatchAdapter(document)
        document._sciplot_native_setting_batch_adapter = adapter
    if not isinstance(adapter, NativeSettingBatchAdapter):
        raise RuntimeError("Native setting batch safety state is unavailable")
    return adapter


def apply_native_setting_batch(document: Any, operations: list[Any], *, description: str) -> None:
    operation_type = import_module("veusz.document.operations").OperationSettingSet
    if not operations or any(type(operation) is not operation_type for operation in operations):
        raise TypeError("The native setting adapter accepts only concrete Veusz setting-set operations")
    paths = [operation.settingpath for operation in operations]
    if len(set(paths)) != len(paths):
        raise ValueError("A native setting batch cannot set the same setting twice")
    adapter = ensure_native_setting_batch_adapter(document)
    adapter.require_usable()
    document.applyOperation(_SettingBatch(operations, description))
