"""Collect plotted series and continuous color-scale audit records."""

from __future__ import annotations

from typing import Any

from sciplot_core.veusz_audit.colors import _group_color
from sciplot_core.veusz_audit.measurements import _rounded, _setting_hidden


def collect_series_inventory(
    doc: Any,
    ordered_widgets: list[tuple[str, Any]],
    state_by_path: dict[str, dict[str, Any]],
    direct_label_texts_by_parent: dict[str, set[str]],
    visible_keys_by_parent: dict[str, list[Any]],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]]]:
    semantic_labels: list[dict[str, Any]] = []
    series: list[dict[str, Any]] = []

    color_scales: list[dict[str, Any]] = []

    for widget_path, widget in ordered_widgets:
        state = state_by_path.get(widget_path)
        if state is None:
            continue
        if (
            str(getattr(widget, "typename", "")) == "image"
            and "colorMap" in widget.settings.setdict
        ):
            color_map = str(widget.settings.setdict["colorMap"].val)
            inverted = (
                bool(widget.settings.setdict.get("colorInvert").val)
                if "colorInvert" in widget.settings.setdict
                else False
            )
            entries = doc.evaluate.getColormap(color_map, inverted)
            control_colors = []
            for entry in entries:
                if len(entry) < 4 or float(entry[0]) < 0:
                    continue
                blue, green, red, alpha = (float(value) for value in entry[:4])
                control_colors.append(
                    {
                        "rgb": [
                            _rounded(red / 255.0),
                            _rounded(green / 255.0),
                            _rounded(blue / 255.0),
                        ],
                        "alpha": _rounded(alpha / 255.0),
                    }
                )
            color_scales.append(
                {
                    "path": widget_path,
                    "page": state["page"],
                    "graph_path": str(widget.parent.path)
                    if widget.parent is not None
                    else "",
                    "name": color_map,
                    "inverted": inverted,
                    "control_colors": control_colors,
                }
            )
        if "PlotLine" not in widget.settings.setdict:
            continue
        helper = state["helper"]
        plot_line = widget.settings.setdict["PlotLine"]
        marker_setting = widget.settings.setdict.get("marker")
        marker = str(marker_setting.val if marker_setting is not None else "none")
        marker_fill = widget.settings.setdict.get("MarkerFill")
        marker_line = widget.settings.setdict.get("MarkerLine")
        plot_visible = not _setting_hidden(plot_line)
        marker_selected = marker.casefold() not in {"", "none"}
        marker_fill_visible = (
            marker_selected
            and marker_fill is not None
            and not _setting_hidden(marker_fill)
        )
        marker_line_visible = (
            marker_selected
            and marker_line is not None
            and not _setting_hidden(marker_line)
        )
        marker_visible = marker_fill_visible or marker_line_visible

        plot_color = _group_color(doc, plot_line, widget=widget, helper=helper)
        marker_fill_color = _group_color(doc, marker_fill, widget=widget, helper=helper)
        marker_line_color = _group_color(doc, marker_line, widget=widget, helper=helper)
        rendered_colors: list[dict[str, Any]] = []
        if plot_visible:
            rendered_colors.append({"role": "plot_line", "color": plot_color})
        if marker_fill_visible:
            rendered_colors.append({"role": "marker_fill", "color": marker_fill_color})
        if marker_line_visible:
            rendered_colors.append({"role": "marker_line", "color": marker_line_color})
        color = (
            plot_color
            if plot_visible
            else marker_fill_color
            if marker_fill_visible
            else marker_line_color
        )
        label = str(
            widget.settings.setdict.get("key").val
            if "key" in widget.settings.setdict
            else ""
        ).strip()
        parent_path = str(widget.parent.path) if widget.parent is not None else ""
        direct_labelled = bool(label) and label in direct_label_texts_by_parent.get(
            parent_path, set()
        )
        series.append(
            {
                "path": widget_path,
                "page": state["page"],
                "graph_path": parent_path,
                "widget_type": str(
                    getattr(widget, "typename", widget.__class__.__name__)
                ),
                "label": label or str(widget.name),
                "color": color,
                "rendered_colors": rendered_colors,
                "plot_line_visible": plot_visible,
                "line_style": str(plot_line.setdict.get("style").val)
                if "style" in plot_line.setdict
                else None,
                "marker_visible": marker_visible,
                "marker_fill_visible": marker_fill_visible,
                "marker_line_visible": marker_line_visible,
                "marker": marker,
                "direct_labelled": direct_labelled,
            }
        )
        if label and visible_keys_by_parent.get(parent_path):
            semantic_labels.append(
                {"path": widget_path, "role": "series_key", "text": label}
            )
    return series, color_scales, semantic_labels
