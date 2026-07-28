"""Identify graphs whose categorical spatial identity is explicitly encoded."""

from __future__ import annotations

from typing import Any


def collect_categorical_graphs(
    graphs: list[dict[str, Any]],
    ordered_widgets: list[tuple[str, Any]],
) -> list[dict[str, Any]]:
    categorical_graphs: list[dict[str, Any]] = []

    for graph in graphs:
        graph_path = str(graph["path"])
        children = [
            (widget_path, widget)
            for widget_path, widget in ordered_widgets
            if widget.parent is not None and str(widget.parent.path) == graph_path
        ]
        x_axis = next(
            (
                widget
                for _, widget in children
                if str(getattr(widget, "typename", "")) == "axis"
                and str(widget.name) == "x"
            ),
            None,
        )
        label_provider = next(
            (
                (widget_path, widget)
                for widget_path, widget in children
                if str(getattr(widget, "typename", "")) == "xy"
                and str(widget.name) == "category_axis_label_provider"
            ),
            None,
        )
        axis_mode = (
            str(x_axis.settings.setdict["mode"].val)
            if x_axis is not None and "mode" in x_axis.settings.setdict
            else ""
        )
        label_dataset = (
            str(label_provider[1].settings.setdict["labels"].val)
            if label_provider is not None
            and "labels" in label_provider[1].settings.setdict
            else ""
        )
        if axis_mode.casefold() != "labels" or not label_dataset:
            continue
        boxplot_path = next(
            (
                widget_path
                for widget_path, widget in children
                if str(getattr(widget, "typename", "")) == "boxplot"
            ),
            None,
        )
        categorical_graphs.append(
            {
                "graph_path": graph_path,
                "page": graph["page"],
                "axis_mode": axis_mode,
                "category_label_provider_path": label_provider[0],
                "category_label_dataset": label_dataset,
                "boxplot_path": boxplot_path,
                "spatial_identity_explicit": True,
            }
        )
    return categorical_graphs
