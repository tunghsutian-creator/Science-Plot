"""Bind native Qt actions to the one per-document batch safety boundary."""

from __future__ import annotations

from importlib import import_module
from typing import Any

from sciplot_gui.studio_assistant.native_batch import (
    NativeBatchExecutionError,
    ensure_native_setting_batch_adapter,
    native_batch_blocker,
)


def _report(window: Any, error: BaseException) -> None:
    message = str(error)
    window._sciplot_native_batch_error = message
    window.updateStatusbar(message)
    assistant = getattr(window, "_sciplot_assistant_bridge", None)
    if assistant is not None:
        assistant.status_label.setText(message)
        assistant.proposal_view.setPlainText(message)
        assistant.requestRejected.emit(message)
        assistant._refresh_ask_button()


def _install_dialog_guard() -> None:
    ExportDialog = import_module("veusz.dialogs.export").ExportDialog

    if getattr(ExportDialog.accept, "_sciplot_native_batch_guard", False):
        return
    original = ExportDialog.accept

    def accept(dialog: Any) -> Any:
        blocker = native_batch_blocker(dialog.document)
        if blocker is not None:
            # Upstream accept unlinks an existing export before AsyncExport.add.
            # Reject before reaching that code, including a dialog already open
            # when execution or compensation failed.
            dialog.showMessage(blocker)
            return None
        return original(dialog)

    accept._sciplot_native_batch_guard = True  # type: ignore[attr-defined]
    ExportDialog.accept = accept


def bind_native_batch_window(window: Any) -> None:
    """Preserve native actions, catching execution errors at Qt slot boundaries."""
    ensure_native_setting_batch_adapter(window.document)
    if getattr(window, "_sciplot_native_batch_window_bound", False):
        return
    _install_dialog_guard()

    def bind(action_name: str, method_name: str) -> None:
        original = getattr(window, method_name)

        def guarded(*_args: Any) -> Any:
            blocker = native_batch_blocker(window.document)
            if blocker is not None:
                _report(window, OSError(blocker))
                return False
            try:
                return original()
            except NativeBatchExecutionError as exc:
                # An exception escaping a Qt signal callback can terminate the
                # application. The Document API still raises for direct callers.
                _report(window, exc)
                return False

        action = window.vzactions[action_name]
        action.triggered.disconnect(original)
        action.triggered.connect(guarded)
        setattr(window, method_name, guarded)

    for action_name, method_name in (
        ("edit.undo", "slotEditUndo"), ("edit.redo", "slotEditRedo"),
        ("file.save", "slotFileSave"), ("file.saveas", "slotFileSaveAs"),
        ("file.export", "slotFileExport"),
    ):
        bind(action_name, method_name)
    window._sciplot_native_batch_window_bound = True
