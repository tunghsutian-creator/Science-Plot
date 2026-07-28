"""Create and configure the SciPlot-owned docks on a Veusz MainWindow."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Callable

from sciplot_core.studio_core.persistence import (
    atomic_save_veusz_document,
)

from sciplot_core.studio_core.context import (
    _project_context_for_document,
)

from sciplot_core.studio_core.qt_compat import (
    ensure_veusz_qsettings_compat,
    _ensure_veusz_examples_menu_compat,
    _ensure_veusz_loader_compat,
)

StudioWindowPresentation = Callable[[Any, Path | None], None]
_studio_window_presentation: StudioWindowPresentation | None = None


def configure_studio_window_presentation(
    presentation: StudioWindowPresentation | None,
) -> None:
    """Install the entry-layer presentation hook used for newly opened windows."""

    global _studio_window_presentation
    _studio_window_presentation = presentation


def _attach_studio_window_presentation(
    window: Any,
    document_path: Path | None,
) -> None:
    if _studio_window_presentation is not None:
        _studio_window_presentation(window, document_path)


def _create_veusz_window(document_path: Path | None) -> Any:
    ensure_veusz_qsettings_compat()
    from veusz.windows.mainwindow import MainWindow

    _ensure_veusz_loader_compat()
    _ensure_veusz_examples_menu_compat(MainWindow)
    _ensure_veusz_mainwindow_compat(MainWindow)
    window = MainWindow()
    if document_path is not None:
        window.openFileInWindow(str(document_path))
    else:
        window.setupDefaultDoc("graph")
        _configure_sciplot_window(window, None)
    if window not in MainWindow.windows:
        MainWindow.windows.append(window)
    return window


def _ensure_veusz_mainwindow_compat(main_window_type: type[Any]) -> None:
    """Install SciPlot's fail-closed save and integrated window factory.

    Upstream Veusz accepts a close event after ``slotFileSave()`` even when
    saving failed or Save As was cancelled.  That is unsafe for a daily editing
    surface because a still-modified document can disappear.  The adapter also
    keeps File/Open, Recent, and drag-created windows inside the same SciPlot
    MainWindow integration instead of silently dropping the Project and AI
    docks.
    """

    if getattr(main_window_type, "_sciplot_mainwindow_compat", False):
        return

    from veusz import qtall as qt

    original_close_event = main_window_type.closeEvent
    original_open_file_in_window = main_window_type.openFileInWindow
    original_slot_file_save_as = main_window_type.slotFileSaveAs
    original_update_titlebar = main_window_type.updateTitlebar

    def readable_filename(window: Any) -> Path | None:
        filename = str(getattr(window, "filename", "") or "").strip()
        if not filename:
            return None
        candidate = Path(filename).expanduser()
        try:
            resolved = candidate.resolve()
            if not resolved.is_file():
                return None
            with resolved.open("rb") as handle:
                handle.read(1)
        except OSError:
            return None
        return resolved

    def record_close_save_error(
        window: Any,
        *,
        state: str,
        message: str,
        exc: Exception | None = None,
    ) -> None:
        error_type = type(exc).__name__ if exc is not None else "RuntimeError"
        window._sciplot_close_save_error = {
            "state": state,
            "error": {
                "type": error_type,
                "message": message,
            },
        }

    def record_save_error(window: Any, *, target: Path | None, exc: Exception) -> None:
        message = str(exc) or type(exc).__name__
        window._sciplot_save_error = {
            "state": "atomic_save_failed",
            "target": str(target) if target is not None else None,
            "error": {
                "type": type(exc).__name__,
                "message": message,
            },
        }
        try:
            window.updateStatusbar(f"Save failed: {message}")
        except (AttributeError, RuntimeError):
            pass
        handler = getattr(window, "_sciplot_save_error_handler", None)
        if callable(handler):
            handler(window._sciplot_save_error)
            return
        qt.QMessageBox.critical(
            window,
            "Error — SciPlot Studio",
            "Unable to save the Veusz document without risking the current "
            f"file.\n\n{message}",
        )

    def save_to_target(window: Any, target: Path) -> bool:
        old_window_filename = str(getattr(window, "filename", "") or "")
        try:
            receipt = atomic_save_veusz_document(window.document, target)
        except Exception as exc:
            window.filename = old_window_filename
            record_save_error(window, target=target, exc=exc)
            return False
        saved_path = str(receipt["target"])
        window.filename = saved_path
        window._sciplot_atomic_save_receipt = receipt
        window._sciplot_save_error = None
        try:
            window.updateTitlebar()
            if receipt.get("reopen_validated") is True:
                window.updateStatusbar(f"Saved to {saved_path}")
            else:
                window.updateStatusbar(
                    "Saved atomically, but secure-mode structural validation "
                    "was unavailable; SciPlot export remains blocked."
                )
        except Exception:
            pass
        return True

    def slot_file_save(window: Any) -> bool:
        filename = str(getattr(window, "filename", "") or "").strip()
        if not filename:
            return bool(window.slotFileSaveAs())
        return save_to_target(window, Path(filename))

    def slot_file_save_as(window: Any) -> bool:
        filters = ["Veusz document files (*.vsz)"]
        if original_slot_file_save_as.__globals__.get("h5py") is not None:
            filters.append("Veusz HDF5 document files (*.vszh5)")
        filename = window.fileSaveDialog(filters, "Save as")
        if not filename:
            return False
        return save_to_target(window, Path(str(filename)))

    def close_event(window: Any, event: Any) -> None:
        # The event starts fail-closed.  Only a confirmed discard or a save
        # that leaves an unmodified document at a readable target may reach
        # Veusz's normal close path.
        event.ignore()
        discard_requested = False
        if window.document.isModified():
            decision = window.queryOverwrite()
            if decision == qt.QMessageBox.StandardButton.Cancel:
                return
            if decision == qt.QMessageBox.StandardButton.Save:
                window._sciplot_close_save_error = None
                try:
                    window.slotFileSave()
                except Exception as exc:
                    window.document.setModified(True)
                    record_close_save_error(
                        window,
                        state="save_exception",
                        message=str(exc) or type(exc).__name__,
                        exc=exc,
                    )
                    return
                saved_path = readable_filename(window)
                if window.document.isModified() or saved_path is None:
                    window.document.setModified(True)
                    record_close_save_error(
                        window,
                        state="save_incomplete",
                        message=(
                            "Veusz did not leave an unmodified document at a "
                            "readable save target; the window remains open."
                        ),
                    )
                    return
            elif decision == qt.QMessageBox.StandardButton.Discard:
                discard_requested = True
                # Let the upstream close path persist geometry/settings without
                # showing the same prompt a second time.
                window.document.setModified(False)

        try:
            original_close_event(window, event)
        finally:
            if discard_requested and not event.isAccepted():
                window.document.setModified(True)

    def update_titlebar(window: Any) -> None:
        original_update_titlebar(window)
        filename = str(getattr(window, "filename", "") or "").strip()
        title_label = Path(filename).stem if filename else "Untitled"
        window.setWindowTitle(f"{title_label} — SciPlot Studio")
        for attribute in (
            "_sciplot_project_bridge",
            "_sciplot_assistant_bridge",
        ):
            bridge = getattr(window, attribute, None)
            handler = getattr(bridge, "handle_document_context_changed", None)
            if callable(handler):
                handler()

    def open_file_in_window(window: Any, filename: str) -> Any:
        result = original_open_file_in_window(window, filename)
        loaded_filename = str(getattr(window, "filename", "") or "").strip()
        if loaded_filename:
            _configure_sciplot_window(
                window,
                Path(loaded_filename).expanduser().resolve(),
            )
        return result

    @classmethod
    def create_window(
        cls: type[Any],
        filename: str | None = None,
        mode: str = "graph",
    ) -> Any:
        window = cls()
        if filename:
            window.openFileInWindow(str(filename))
        else:
            window.setupDefaultDoc(mode)
            _configure_sciplot_window(window, None)
        window.show()
        if window not in cls.windows:
            cls.windows.append(window)
        return window

    close_event._sciplot_fail_closed = True  # type: ignore[attr-defined]
    slot_file_save._sciplot_atomic_save = True  # type: ignore[attr-defined]
    slot_file_save_as._sciplot_atomic_save_as = True  # type: ignore[attr-defined]
    update_titlebar._sciplot_titlebar = True  # type: ignore[attr-defined]
    open_file_in_window._sciplot_integrated_open = True  # type: ignore[attr-defined]
    create_window.__func__._sciplot_integrated_factory = True  # type: ignore[attr-defined]
    main_window_type.closeEvent = close_event
    main_window_type.slotFileSave = slot_file_save
    main_window_type.slotFileSaveAs = slot_file_save_as
    main_window_type.updateTitlebar = update_titlebar
    main_window_type.openFileInWindow = open_file_in_window
    main_window_type.CreateWindow = create_window
    main_window_type._sciplot_mainwindow_compat = True


def _configure_sciplot_window(
    window: Any,
    document_path: Path | None,
) -> None:
    resolved_document = (
        document_path.expanduser().resolve() if document_path is not None else None
    )
    _attach_studio_window_presentation(window, resolved_document)
    if resolved_document is None:
        title_label = "Untitled"
    else:
        context = _project_context_for_document(resolved_document)
        if context is None:
            title_label = resolved_document.stem
        else:
            figure_id = str(context.get("figure_id") or "").strip()
            title_label = context["project_dir"].name
            if figure_id:
                title_label = f"{title_label} — {figure_id}"
    window.setWindowTitle(f"{title_label} — SciPlot Studio")
    try:
        window.treeedit.doInitialWidgetSelect()
    except (AttributeError, RuntimeError):
        pass
    if not getattr(window, "_sciplot_size_initialized", False):
        window.resize(1200, 820)
        window._sciplot_size_initialized = True
