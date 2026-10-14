"""Read-only Qt font inventory, available only on a native worker main thread."""

import threading


def font_families() -> dict[str, object]:
    """Reject the wrong thread before importing Qt or creating its application."""
    if threading.current_thread() is not threading.main_thread():
        raise RuntimeError("The native font catalog requires the worker process main thread.")
    from PyQt6.QtGui import QGuiApplication
    from sciplot_core.native_settings import _font_families

    application = QGuiApplication.instance() or QGuiApplication([])
    if not isinstance(application, QGuiApplication):
        raise RuntimeError("A native GUI application is required for the font catalog.")
    return {"kind": "sciplot_native_font_catalog", "version": 1, "families": _font_families()}
