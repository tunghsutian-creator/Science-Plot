"""Coordinate one exact-current Veusz document audit."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from sciplot_core.foundation.file_hashing import file_sha256
from sciplot_core.materials_rules import (
    scientific_unit_expression_contract,
    unit_solidus_violations,
)
from sciplot_core.veusz_audit.categories import collect_categorical_graphs
from sciplot_core.veusz_audit.labels import collect_semantic_labels
from sciplot_core.veusz_audit.layout import collect_layout_inventory
from sciplot_core.veusz_audit.legend_geometry import collect_legend_geometry
from sciplot_core.veusz_audit.direct_label_geometry import collect_direct_label_geometry
from sciplot_core.veusz_audit.segmented_legend_geometry import collect_segmented_legend_geometry
from sciplot_core.veusz_audit.pages import collect_page_geometry
from sciplot_core.veusz_audit.series import collect_series_inventory
from sciplot_core.veusz_audit.strokes import collect_stroke_inventory
from sciplot_core.veusz_audit.widget_tree import _iter_widgets


def _audit_document(path: Path) -> dict[str, Any]:
    from veusz import dataimport, document, widgets

    from veusz.document.painthelper import PaintHelper

    _ = dataimport, widgets

    resolved = path.expanduser().resolve()

    if not resolved.exists() or not resolved.is_file():
        raise FileNotFoundError(f"Veusz document not found: {resolved}")

    source_sha256 = file_sha256(resolved)
    doc = document.Document()

    doc.load(str(resolved))

    widgets_by_path, ordered_widgets = _iter_widgets(doc)
    state_by_path, pages = collect_page_geometry(doc, PaintHelper)
    graphs, grids, auxiliaries, axes = collect_layout_inventory(
        ordered_widgets, state_by_path
    )
    categorical_graphs = collect_categorical_graphs(graphs, ordered_widgets)
    legend_geometry = collect_legend_geometry(ordered_widgets, state_by_path)
    direct_geometry = collect_direct_label_geometry(ordered_widgets, state_by_path)
    segmented_geometry = collect_segmented_legend_geometry(ordered_widgets, state_by_path)
    (
        semantic_labels,
        direct_label_texts_by_parent,
        visible_keys_by_parent,
    ) = collect_semantic_labels(ordered_widgets, state_by_path)
    series, color_scales, series_labels = collect_series_inventory(
        doc,
        ordered_widgets,
        state_by_path,
        direct_label_texts_by_parent,
        visible_keys_by_parent,
    )
    semantic_labels.extend(series_labels)
    stroke_items, unsupported_strokes, active_strokes = collect_stroke_inventory(
        doc, widgets_by_path, state_by_path
    )
    performance_document = any(
        str(getattr(widget, "name", "")).startswith("performance_")
        for _widget_path, widget in ordered_widgets
    )

    if performance_document:
        for graph in graphs:
            graph["role"] = "performance_plot"
            graph_widget = widgets_by_path[str(graph["path"])]
            children = list(graph_widget.children)
            ring_widgets = [
                widget for widget in children
                if widget.typename == "polygon"
                and str(widget.name).startswith("performance_radar_ring_")
            ]
            rings = {str(widget.name) for widget in ring_widgets}
            ring_point_counts = {
                len(widget.settings.xPos) for widget in ring_widgets
                if len(widget.settings.xPos) == len(widget.settings.yPos)
                and widget.settings.positioning == "axes"
            }
            axis_count = next(iter(ring_point_counts)) - 1 if len(ring_point_counts) == 1 else 0
            spokes = {
                str(widget.name) for widget in children if widget.typename == "line"
                and str(widget.name).startswith("performance_radar_spoke_")
                and widget.settings.positioning == "axes"
            }
            hidden_axes = {
                str(widget.name) for widget in children if widget.typename == "axis"
                and not widget.settings.label
                and all(widget.settings.setdict[group].hide for group in
                        ("Line", "MajorTicks", "MinorTicks", "Label", "TickLabels"))
            }
            # Identify the actual native radar scaffold per graph. A free-text
            # label or another performance graph cannot select radar margins.
            radar_graph = (
                rings == {f"performance_radar_ring_{index}" for index in range(1, 5)}
                and axis_count >= 3
                and spokes == {f"performance_radar_spoke_{index}" for index in range(1, axis_count + 1)}
                and hidden_axes == {"x", "y"}
            )
            graph["performance_template"] = "polar_curve" if radar_graph else "scatter"

    unit_expression_violations = [
        {
            "path": str(item.get("path") or ""),
            "role": str(item.get("role") or ""),
            "text": str(item.get("text") or ""),
            **violation,
        }
        for item in semantic_labels
        for violation in unit_solidus_violations(item.get("text"))
    ]

    if file_sha256(resolved) != source_sha256:
        raise ValueError("The native document changed while its geometry was being audited.")

    return {
        "kind": "sciplot_veusz_document_audit",
        "version": 1,
        "path": str(resolved),
        "sha256": source_sha256,
        "page_count": len(pages),
        "pages": pages,
        "grids": grids,
        "graphs": graphs,
        "axes": axes,
        "categorical_graphs": categorical_graphs,
        "auxiliaries": auxiliaries,
        "semantic_labels": semantic_labels,
        "unit_expression_contract": {
            **scientific_unit_expression_contract(),
            "coverage_complete": True,
            "passed": not unit_expression_violations,
            "violations": unit_expression_violations,
        },
        "series": series,
        "legend_geometry": legend_geometry,
        "direct_label_geometry": direct_geometry,
        "segmented_legend_geometry": segmented_geometry,
        "performance_comparison": performance_document,
        "color_scales": color_scales,
        "stroke_inventory": {
            "coverage_complete": not unsupported_strokes,
            "active_count": len(active_strokes),
            "items": stroke_items,
            "unsupported": unsupported_strokes,
        },
    }
