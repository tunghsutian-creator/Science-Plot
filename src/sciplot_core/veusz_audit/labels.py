"""Collect visible semantic labels, direct labels, and legend widgets."""

from __future__ import annotations

from typing import Any

from sciplot_core.veusz_audit.measurements import _setting_hidden


def collect_semantic_labels(
    ordered_widgets: list[tuple[str, Any]],
    state_by_path: dict[str, dict[str, Any]],
) -> tuple[list[dict[str, Any]], dict[str, set[str]], dict[str, list[Any]]]:
    semantic_labels: list[dict[str, Any]] = []

    direct_label_texts_by_parent: dict[str, set[str]] = {}

    visible_keys_by_parent: dict[str, list[Any]] = {}

    for widget_path, widget in ordered_widgets:
        if widget_path not in state_by_path:
            continue
        widget_type = str(getattr(widget, "typename", ""))
        if widget_type in {"axis", "colorbar"}:
            label = str(
                widget.settings.setdict.get("label").val
                if "label" in widget.settings.setdict
                else ""
            ).strip()
            label_group = widget.settings.setdict.get("Label")
            if label and (label_group is None or not _setting_hidden(label_group)):
                semantic_labels.append(
                    {"path": widget_path, "role": "axis_label", "text": label}
                )
        elif widget_type == "label":
            label = str(
                widget.settings.setdict.get("label").val
                if "label" in widget.settings.setdict
                else ""
            ).strip()
            text_group = widget.settings.setdict.get("Text")
            if label and (text_group is None or not _setting_hidden(text_group)):
                semantic_labels.append(
                    {"path": widget_path, "role": "free_label", "text": label}
                )
                parent_path = (
                    str(widget.parent.path) if widget.parent is not None else ""
                )
                direct_label_texts_by_parent.setdefault(parent_path, set()).add(label)
        elif widget_type == "key":
            if _setting_hidden(widget.settings):
                continue
            parent_path = str(widget.parent.path) if widget.parent is not None else ""
            visible_keys_by_parent.setdefault(parent_path, []).append(widget)
            title = str(
                widget.settings.setdict.get("title").val
                if "title" in widget.settings.setdict
                else ""
            ).strip()
            if title:
                semantic_labels.append(
                    {"path": widget_path, "role": "key_title", "text": title}
                )
    return semantic_labels, direct_label_texts_by_parent, visible_keys_by_parent
