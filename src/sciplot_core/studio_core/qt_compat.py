"""Install narrow compatibility shims required by the upstream Veusz Qt runtime."""

from __future__ import annotations

from pathlib import Path
from typing import Any


def ensure_veusz_qsettings_compat() -> None:
    """Keep Veusz settings scoped to Veusz on macOS.

    Native QSettings includes the macOS global preference domain as a fallback.
    Veusz evaluates every returned value as one of its own settings, producing
    dozens of misleading ``Error interpreting item Apple...`` messages.  The
    adapter disables only that fallback and leaves Veusz's own preferences
    readable and writable.
    """
    from veusz import qtall as qt

    current = qt.QSettings
    if getattr(current, "_sciplot_fallbacks_disabled", False):
        return

    class SciPlotQSettings(current):
        _sciplot_fallbacks_disabled = True

        def __init__(self, *args: Any, **kwargs: Any) -> None:
            super().__init__(*args, **kwargs)
            self.setFallbacksEnabled(False)

    qt.QSettings = SciPlotQSettings


def _ensure_veusz_examples_menu_compat(main_window_type: type[Any]) -> None:
    """Treat the intentionally omitted upstream examples directory as optional."""
    from veusz import utils

    current = main_window_type.populateExamplesMenu
    if getattr(current, "_sciplot_missing_examples_safe", False):
        return

    def populate_examples_menu(window: Any) -> Any:
        if not Path(str(utils.exampleDirectory)).is_dir():
            return None
        return current(window)

    populate_examples_menu._sciplot_missing_examples_safe = True  # type: ignore[attr-defined]
    main_window_type.populateExamplesMenu = populate_examples_menu


def _ensure_veusz_loader_compat() -> None:
    """Keep Veusz script loading alive when optional import commands are absent."""
    from importlib import import_module

    # The upstream Veusz application imports this package during its startup
    # thread.  SciPlot constructs MainWindow directly, so repeat the same
    # registration step before loading a saved document.  Without it, native
    # Veusz dumps containing ImportString2D/ImportStringND fail with NameError.
    import_module("veusz.dataimport")

    from veusz import document as veusz_document
    from veusz.document import mime
    from veusz.document.commandinterface import CommandInterface, registerImportCommand

    for command_name in ("ImportString2D", "ImportStringND"):
        if (
            not hasattr(CommandInterface, command_name)
            or command_name not in CommandInterface.import_commands
            or CommandInterface.import_filenamearg.get(command_name) != -1
        ):
            raise RuntimeError(
                f"Veusz saved-data command {command_name} is unavailable in this Studio runtime."
            )

    if hasattr(CommandInterface, "ImportFITSFile"):
        pass
    else:

        def _missing_import_fits(self: Any, *_args: Any, **_kwargs: Any) -> None:
            raise RuntimeError(
                "Veusz FITS import support is unavailable in this SciPlot Studio runtime."
            )

        CommandInterface.ImportFITSFile = _missing_import_fits

    def _sciplot_import_string(
        self: Any,
        descriptor: str,
        dstring: str,
        useblocks: bool = False,
    ) -> tuple[list[str], dict[str, int]]:
        dataset_name = str(descriptor).split("(", 1)[0].strip()
        if not dataset_name:
            raise ValueError(
                f"Unsupported Veusz ImportString descriptor: {descriptor!r}"
            )
        values: list[float] = []
        invalid = 0
        for line in str(dstring).splitlines():
            text = line.strip()
            if not text or (useblocks and text.lower() == "no"):
                continue
            try:
                values.append(float(text))
            except ValueError:
                invalid += 1
        self.SetData(dataset_name, values)
        return [dataset_name], ({dataset_name: invalid} if invalid else {})

    if hasattr(CommandInterface, "ImportString"):
        if "ImportString" not in CommandInterface.import_commands:
            CommandInterface.import_commands.append("ImportString")
        CommandInterface.import_filenamearg["ImportString"] = -1
    else:
        registerImportCommand("ImportString", _sciplot_import_string, filenamearg=-1)

    if getattr(mime, "_sciplot_safe_clipboard", False):
        return
    original_get_clipboard_widget_mime = mime.getClipboardWidgetMime

    def _clipboard_mimedata() -> Any:
        clipboard = mime.qt.QApplication.clipboard()
        if clipboard is None:
            return None
        return clipboard.mimeData()

    def _safe_is_clipboard_data_mime() -> bool:
        mimedata = _clipboard_mimedata()
        return bool(mimedata is not None and mime.datamime in mimedata.formats())

    def _safe_get_clipboard_widget_mime() -> Any:
        if _clipboard_mimedata() is None:
            return None
        return original_get_clipboard_widget_mime()

    mime.isClipboardDataMime = _safe_is_clipboard_data_mime
    mime.getClipboardWidgetMime = _safe_get_clipboard_widget_mime
    veusz_document.isClipboardDataMime = _safe_is_clipboard_data_mime
    veusz_document.getClipboardWidgetMime = _safe_get_clipboard_widget_mime
    mime._sciplot_safe_clipboard = True


ensure_veusz_loader_compat = _ensure_veusz_loader_compat
