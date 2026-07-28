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

    doc = document.Document()

    doc.load(str(resolved))

    widgets_by_path, ordered_widgets = _iter_widgets(doc)
    state_by_path, pages = collect_page_geometry(doc, PaintHelper)
    graphs, grids, auxiliaries, axes = collect_layout_inventory(
        ordered_widgets, state_by_path
    )
    categorical_graphs = collect_categorical_graphs(graphs, ordered_widgets)
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

    return {
        "kind": "sciplot_veusz_document_audit",
        "version": 1,
        "path": str(resolved),
        "sha256": file_sha256(resolved),
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
        "performance_comparison": performance_document,
        "color_scales": color_scales,
        "stroke_inventory": {
            "coverage_complete": not unsupported_strokes,
            "active_count": len(active_strokes),
            "items": stroke_items,
            "unsupported": unsupported_strokes,
        },
    }
