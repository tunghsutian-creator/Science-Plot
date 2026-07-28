"""Probe Veusz MainWindow close safety without changing project documents."""

from __future__ import annotations

import tempfile
from pathlib import Path
from typing import Any


def _mainwindow_close_safety_probe(window: Any) -> dict[str, bool]:
    """Exercise close decisions without actually destroying the probe window."""

    from veusz import qtall as qt

    class ProbeCloseEvent:
        def __init__(self) -> None:
            self.accepted = False
            self.ignored = False

        def accept(self) -> None:
            self.accepted = True
            self.ignored = False

        def ignore(self) -> None:
            self.accepted = False
            self.ignored = True

        def isAccepted(self) -> bool:
            return self.accepted

    original_query = window.queryOverwrite
    original_save = window.slotFileSave
    original_filename = str(getattr(window, "filename", "") or "")
    results: dict[str, bool] = {}

    def exercise(
        decision: Any,
        *,
        filename: Path | None,
        save: Any,
    ) -> tuple[ProbeCloseEvent, bool]:
        window.document.setModified(True)
        window.filename = "" if filename is None else str(filename)
        window.queryOverwrite = lambda: decision
        window.slotFileSave = save
        event = ProbeCloseEvent()
        window.closeEvent(event)
        return event, bool(window.document.isModified())

    try:
        cancel_event, cancel_modified = exercise(
            qt.QMessageBox.StandardButton.Cancel,
            filename=None,
            save=lambda: None,
        )
        results["cancel_keeps_window"] = cancel_event.ignored and cancel_modified

        with tempfile.TemporaryDirectory(prefix="sciplot_close_probe_") as raw:
            root = Path(raw)
            failed_path = root / "missing" / "failed.vsz"
            failed_event, failed_modified = exercise(
                qt.QMessageBox.StandardButton.Save,
                filename=failed_path,
                save=lambda: None,
            )
            results["save_failure_keeps_window"] = (
                failed_event.ignored and failed_modified and not failed_path.exists()
            )

            def exceptional_save() -> None:
                raise OSError("synthetic close-save failure")

            exception_event, exception_modified = exercise(
                qt.QMessageBox.StandardButton.Save,
                filename=failed_path,
                save=exceptional_save,
            )
            close_save_error = getattr(
                window,
                "_sciplot_close_save_error",
                None,
            )
            results["save_exception_keeps_window"] = (
                exception_event.ignored
                and exception_modified
                and isinstance(close_save_error, dict)
                and close_save_error.get("state") == "save_exception"
                and close_save_error.get("error", {}).get("type") == "OSError"
            )

            save_as_event, save_as_modified = exercise(
                qt.QMessageBox.StandardButton.Save,
                filename=None,
                save=lambda: None,
            )
            results["save_as_cancel_keeps_window"] = (
                save_as_event.ignored and save_as_modified
            )

            saved_path = root / "saved.vsz"

            def successful_save() -> None:
                saved_path.write_text("SciPlot close safety probe\n", encoding="utf-8")
                window.document.setModified(False)

            saved_event, saved_modified = exercise(
                qt.QMessageBox.StandardButton.Save,
                filename=saved_path,
                save=successful_save,
            )
            results["save_success_closes"] = (
                saved_event.accepted and not saved_modified and saved_path.is_file()
            )

        discard_event, discard_modified = exercise(
            qt.QMessageBox.StandardButton.Discard,
            filename=None,
            save=lambda: None,
        )
        results["discard_closes"] = discard_event.accepted and not discard_modified
    finally:
        window.queryOverwrite = original_query
        window.slotFileSave = original_save
        window.filename = original_filename
        window.document.setModified(False)

    return results
