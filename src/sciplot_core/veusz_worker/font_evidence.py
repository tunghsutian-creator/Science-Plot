"""Opt-in font preflight for an already-loaded native document.

This is deliberately outside the render recipe. A Qt screen font match is not
evidence of the face, glyph fallback, or font file used by a PDF/paint device.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any


def _unobserved(reason: str) -> dict[str, str]:
    return {"status": "unobserved", "reason": reason}


def _setting(document: Any, path: str) -> Any:
    return document.resolveSettingPath(None, path).get()


_SETTING_ERRORS = (AttributeError, KeyError, RuntimeError, TypeError, ValueError)


def _optional_setting(document: Any, path: str) -> Any:
    try:
        return _setting(document, path)
    except _SETTING_ERRORS:
        return None


def _requested_font(document: Any, setting_path: str) -> dict[str, Any]:
    try:
        family = _setting(document, setting_path)
    except _SETTING_ERRORS:
        return _unobserved("native_setting_could_not_be_resolved")
    if not isinstance(family, str) or not family.strip() or len(family) > 256:
        return _unobserved("native_setting_is_not_a_bounded_font_family")

    prefix = setting_path[:-len("font")]
    requested: dict[str, Any] = {"status": "observed", "family": family}
    for suffix in ("style", "bold", "italic"):
        value = _optional_setting(document, prefix + suffix)
        valid_style = isinstance(value, str) and len(value) <= 256
        valid_toggle = isinstance(value, bool)
        if (suffix == "style" and valid_style) or (suffix != "style" and valid_toggle):
            requested[suffix] = value
    return requested


def _qt_screen_match(requested: dict[str, Any]) -> dict[str, Any]:
    """Query the existing GUI application's screen font, without creating one."""
    try:
        from PyQt6.QtGui import QFont, QFontInfo, QGuiApplication
    except (ImportError, OSError, RuntimeError):
        return _unobserved("qt_gui_unavailable")

    try:
        if not isinstance(QGuiApplication.instance(), QGuiApplication):
            return _unobserved("qt_gui_application_unavailable")
        font = QFont(requested["family"])
        if requested.get("style"):
            font.setStyleName(requested["style"])
        for setting, setter in (("bold", font.setBold), ("italic", font.setItalic)):
            if setting in requested:
                setter(requested[setting])
        match = QFontInfo(font)
        return {
            "status": "observed", "query": "QFontInfo(QFont)",
            "family": match.family(), "style_name": match.styleName(),
            "weight": int(match.weight()), "italic": bool(match.italic()),
            "exact_match": bool(match.exactMatch()),
        }
    except (AttributeError, OSError, RuntimeError, TypeError, ValueError):
        return _unobserved("qt_screen_font_query_failed")


def collect_font_preflight(
    document: Any,
    widgets: dict[str, dict[str, Any]],
    *,
    screen_match: Callable[[dict[str, Any]], dict[str, Any]] = _qt_screen_match,
) -> dict[str, Any]:
    """Observe resolved saved settings and a qualified Qt *screen* query.

    Caller must already own the native document/app lifecycle. No rendering,
    font file lookup, global Qt configuration, or document mutation occurs.
    """
    requests: list[dict[str, Any]] = []
    matches: dict[tuple[Any, ...], dict[str, Any]] = {}
    for widget_path, widget in sorted(widgets.items()):
        settings = widget.get("settings") if isinstance(widget, dict) else None
        if not isinstance(settings, dict):
            continue
        for suffix in sorted(key for key in settings if isinstance(key, str)):
            if suffix != "font" and not suffix.endswith("/font"):
                continue
            setting_path = f"{widget_path.rstrip('/')}/{suffix}"
            requested = _requested_font(document, setting_path)
            if requested["status"] == "observed":
                key = tuple(requested.get(name) for name in ("family", "style", "bold", "italic"))
                if key not in matches:
                    try:
                        matches[key] = screen_match(requested)
                    except (AttributeError, OSError, RuntimeError, TypeError, ValueError):
                        matches[key] = _unobserved("qt_screen_font_query_failed")
                screen = matches[key]
            else:
                screen = _unobserved("requested_family_unobserved")
            requests.append({"setting_path": setting_path, "requested": requested,
                             "qt_screen_match": screen})
    return {
        "kind": "sciplot_font_preflight", "version": 1,
        "scope": "saved_native_settings_and_qt_screen_queries_only",
        "requests": requests,
        "native_paint_font": _unobserved("no_native_paint_device_or_glyph_runs_inspected"),
        "resolved_font_file": _unobserved("qt_screen_match_does_not_identify_rendered_font_file_bytes"),
        "cross_environment_portability": "unestablished",
    }
