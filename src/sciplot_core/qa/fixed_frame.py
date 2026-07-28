"""Verify exact physical frame, margins, axes, and auxiliary envelopes."""

from __future__ import annotations

import math
from typing import Any

from sciplot_core.qa.audit_support import (
    _bounds_close,
)


def _fixed_frame_report(
    audit: dict[str, Any] | None, intent: dict[str, Any]
) -> dict[str, Any]:
    if not isinstance(audit, dict):
        return {
            "available": False,
            "coverage_complete": False,
            "passed": False,
            "reason": "exact_current_vsz_audit_unavailable",
            "documents": [],
        }
    from sciplot_core.contract import load_plot_contract, qa_profile
    from sciplot_core.publication import build_composite_layout

    contract = load_plot_contract()
    tolerance = float(qa_profile("alignment").get("frame_tolerance_mm", 0.05))
    expected_margins = {
        "left": float(contract.global_frame.left_margin_mm),
        "right": float(contract.global_frame.right_margin_mm),
        "bottom": float(contract.global_frame.bottom_margin_mm),
        "top": float(contract.global_frame.top_margin_mm),
    }
    documents = [item for item in audit.get("documents", []) if isinstance(item, dict)]
    issues: list[dict[str, Any]] = []
    all_graphs: list[dict[str, Any]] = []
    for document in documents:
        graphs = [item for item in document.get("graphs", []) if isinstance(item, dict)]
        all_graphs.extend(graphs)
        pages = {
            int(item["page"]): item
            for item in document.get("pages", [])
            if isinstance(item, dict)
        }
        for graph in graphs:
            graph_expected_margins = dict(expected_margins)
            if graph.get("role") == "performance_plot":
                from sciplot_core.policy import PERFORMANCE_PANEL_WIDTH_MM

                page = pages.get(int(graph.get("page") or 0))
                page_size = (
                    page.get("size_mm")
                    if isinstance(page, dict) and isinstance(page.get("size_mm"), list)
                    else []
                )
                if len(page_size) == 2:
                    graph_expected_margins["right"] = (
                        float(page_size[0])
                        - PERFORMANCE_PANEL_WIDTH_MM
                        + expected_margins["right"]
                    )
            margins = (
                graph.get("margins_mm")
                if isinstance(graph.get("margins_mm"), dict)
                else {}
            )
            margin_errors = {
                side: (
                    abs(float(margins[side]) - expected)
                    if margins.get(side) is not None
                    else float("inf")
                )
                for side, expected in graph_expected_margins.items()
            }
            if any(error > tolerance for error in margin_errors.values()):
                issues.append(
                    {
                        "id": "fixed_publication_frame_misaligned",
                        "path": graph.get("path"),
                        "expected_margins_mm": graph_expected_margins,
                        "margin_error_mm": margin_errors,
                    }
                )
            if str(graph.get("aspect") or "Auto").casefold() != "auto":
                issues.append(
                    {
                        "id": "fixed_publication_frame_aspect_override",
                        "path": graph.get("path"),
                    }
                )
            if graph.get("parent_type") == "page":
                page = pages.get(int(graph.get("page") or 0))
                if page is None or not _bounds_close(
                    graph.get("slot_bounds_mm"), page.get("bounds_mm"), tolerance
                ):
                    issues.append(
                        {
                            "id": "standalone_graph_slot_misaligned",
                            "path": graph.get("path"),
                        }
                    )
        graph_by_path = {str(item.get("path")): item for item in graphs}
        for auxiliary in document.get("auxiliaries", []):
            if not isinstance(auxiliary, dict) or auxiliary.get("type") != "colorbar":
                continue
            graph = graph_by_path.get(str(auxiliary.get("parent_path")))
            bounds = auxiliary.get("bounds_mm")
            frame = graph.get("plot_bounds_mm") if isinstance(graph, dict) else None
            contained = (
                isinstance(bounds, list)
                and isinstance(frame, list)
                and len(bounds) == len(frame) == 4
                and bounds[0] >= frame[0] - tolerance
                and bounds[1] >= frame[1] - tolerance
                and bounds[2] <= frame[2] + tolerance
                and bounds[3] <= frame[3] + tolerance
            )
            if not contained:
                issues.append(
                    {
                        "id": "colorbar_outside_standard_graph_frame",
                        "path": auxiliary.get("path"),
                    }
                )

    layout_id = str(intent.get("layout_id") or "").strip()
    layout_confirmed = (
        layout_id and str(intent.get("layout_status") or "").casefold() == "confirmed"
    )
    layout_evidence: dict[str, Any] | None = None
    if layout_confirmed:
        figure_layout = (
            intent.get("figure_layout")
            if isinstance(intent.get("figure_layout"), dict)
            else {}
        )
        height = float(figure_layout.get("canvas_height_mm") or 55.0)
        layout = build_composite_layout(layout_id, canvas_height_mm=height)
        standalone_single = (
            layout_id == "single_180"
            and len(documents) == 1
            and len(documents[0].get("pages", [])) == 1
            and _bounds_close(
                documents[0]["pages"][0].get("size_mm"),
                [
                    float(layout["nominal_content_width_mm"]),
                    float(layout["canvas_height_mm"]),
                ],
                tolerance,
            )
        )
        layout_evidence = {
            "layout_id": layout_id,
            "expected": layout,
            "actual_graphs": all_graphs,
            "assembly_state": (
                "standalone_180_module_for_external_assembly"
                if standalone_single
                else "native_composite_document"
            ),
        }
        if not standalone_single:
            if len(documents) != 1 or len(documents[0].get("pages", [])) != 1:
                issues.append({"id": "composite_requires_one_vsz_page"})
            else:
                page = documents[0]["pages"][0]
                expected_page = [
                    float(layout["canvas_width_mm"]),
                    float(layout["canvas_height_mm"]),
                ]
                if not _bounds_close(page.get("size_mm"), expected_page, tolerance):
                    issues.append(
                        {
                            "id": "composite_page_size_mismatch",
                            "actual": page.get("size_mm"),
                            "expected": expected_page,
                        }
                    )
            ordered_graphs = sorted(
                all_graphs,
                key=lambda item: float((item.get("slot_bounds_mm") or [math.inf])[0]),
            )
            slots = [item for item in layout.get("slots", []) if isinstance(item, dict)]
            if len(ordered_graphs) != len(slots):
                issues.append(
                    {
                        "id": "composite_slot_count_mismatch",
                        "actual": len(ordered_graphs),
                        "expected": len(slots),
                    }
                )
            else:
                for graph, slot in zip(ordered_graphs, slots, strict=True):
                    expected_bounds = [
                        float(slot["x_mm"]),
                        0.0,
                        float(slot["x_mm"]) + float(slot["width_mm"]),
                        float(layout["canvas_height_mm"]),
                    ]
                    if not _bounds_close(
                        graph.get("slot_bounds_mm"), expected_bounds, tolerance
                    ):
                        issues.append(
                            {
                                "id": "composite_slot_geometry_mismatch",
                                "path": graph.get("path"),
                                "actual": graph.get("slot_bounds_mm"),
                                "expected": expected_bounds,
                            }
                        )
    else:
        for document in documents:
            pages = [
                item for item in document.get("pages", []) if isinstance(item, dict)
            ]
            graphs = [
                item for item in document.get("graphs", []) if isinstance(item, dict)
            ]
            graph_counts_by_page = {
                int(page.get("page") or 0): sum(
                    int(graph.get("page") or 0) == int(page.get("page") or 0)
                    for graph in graphs
                )
                for page in pages
            }
            standalone_shape = (
                len(pages) == len(graphs)
                and all(count == 1 for count in graph_counts_by_page.values())
                and all(graph.get("parent_type") == "page" for graph in graphs)
            )
            if not standalone_shape:
                issues.append(
                    {
                        "id": "unconfirmed_multi_graph_layout",
                        "document": document.get("path"),
                        "page_count": len(pages),
                        "graph_count": len(graphs),
                        "graph_counts_by_page": graph_counts_by_page,
                        "parent_types": [graph.get("parent_type") for graph in graphs],
                    }
                )
    return {
        "available": bool(documents),
        "coverage_complete": bool(documents) and bool(all_graphs),
        "passed": bool(documents) and bool(all_graphs) and not issues,
        "tolerance_mm": tolerance,
        "expected_margins_mm": expected_margins,
        "layout": layout_evidence,
        "issues": issues,
        "documents": [
            {
                "path": item.get("path"),
                "sha256": item.get("sha256"),
                "pages": item.get("pages"),
                "graphs": item.get("graphs"),
                "grids": item.get("grids"),
                "auxiliaries": item.get("auxiliaries"),
            }
            for item in documents
        ],
    }
