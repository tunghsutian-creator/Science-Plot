"""Validate the closed rectangle, polygon, and line overlay inventory."""

from __future__ import annotations

from typing import Any

from sciplot_core.veusz_worker.visual_matchers import (
    _line_record_matches_contract,
    _polygon_record_matches_contract,
    _rect_record_matches_contract,
)
from sciplot_core.veusz_worker.widget_bindings import _visible_data_bindings


def audit_overlay_inventory(
    loaded_document: Any,
    spec: dict[str, Any],
    visual: dict[str, Any] | None,
) -> set[str]:
    from sciplot_core.performance_veusz import (
        performance_line_contracts,
        performance_polygon_contracts,
    )
    from sciplot_core.studio_core.guide_contracts import (
        categorical_line_contracts,
        reference_guide_line_contracts,
        reference_guide_rect_contracts,
    )
    from sciplot_core.studio_core.legend_contracts import (
        categorical_component_legend_rect_contracts,
        categorical_grouped_bar_fill_rect_contracts,
        curve_factor_legend_condition_rect_contracts,
        curve_factor_legend_line_contracts,
    )

    rect_records = _visible_data_bindings(
        loaded_document,
        widget_type="rect",
        setting_names=(
            "positioning",
            "xPos",
            "yPos",
            "width",
            "height",
            "clip",
            "Fill/color",
            "Fill/hide",
            "Fill/transparency",
            "Border/hide",
        ),
    )

    expected_rects: list[dict[str, Any]] = [
        {
            "path": "/page1/page_export_background",
            "name": "page_export_background",
            "positioning": "relative",
            "xPos": [0.5],
            "yPos": [0.5],
            "width": [1.0],
            "height": [1.0],
            "clip": True,
            "fill_color": "white",
            "fill_hide": False,
            "fill_transparency": 0,
            "border_hide": True,
        }
    ]

    expected_rects.extend(
        (
            {**contract, "path": f"/page1/graph1/{contract['name']}"}
            for contract in reference_guide_rect_contracts(spec)
        )
    )

    expected_rects.extend(
        (
            {**contract, "path": f"/page1/graph1/{contract['name']}"}
            for contract in categorical_component_legend_rect_contracts(spec)
        )
    )

    expected_rects.extend(
        (
            {**contract, "path": f"/page1/graph1/{contract['name']}"}
            for contract in categorical_grouped_bar_fill_rect_contracts(spec)
        )
    )

    expected_rects.extend(
        (
            {**contract, "path": f"/page1/graph1/{contract['name']}"}
            for contract in curve_factor_legend_condition_rect_contracts(spec)
        )
    )

    if visual is not None and str(visual["colorbar_background_color"]).strip():
        expected_rects.append(
            {
                "path": "/page1/graph1/field_colorbar_background",
                "name": "field_colorbar_background",
                "positioning": "relative",
                "xPos": [visual["colorbar_background_x_fraction"]],
                "yPos": [visual["colorbar_background_y_fraction"]],
                "width": [visual["colorbar_background_width_fraction"]],
                "height": [visual["colorbar_background_height_fraction"]],
                "clip": True,
                "fill_color": visual["colorbar_background_color"],
                "fill_hide": False,
                "fill_transparency": visual["colorbar_background_transparency"],
                "border_hide": True,
            }
        )

    actual_rects_by_path = {str(record["path"]): record for record in rect_records}

    expected_rects_by_path = {str(record["path"]): record for record in expected_rects}

    if (
        len(actual_rects_by_path) != len(rect_records)
        or set(actual_rects_by_path) != set(expected_rects_by_path)
        or any(
            (
                not _rect_record_matches_contract(
                    actual_rects_by_path[path], expected=expected
                )
                for path, expected in expected_rects_by_path.items()
            )
        )
    ):
        raise ValueError(
            "Exact-current Veusz shape inventory differs from the closed page, reference-guide, and scalar colorbar-background contract."
        )

    polygon_records = _visible_data_bindings(
        loaded_document,
        widget_type="polygon",
        setting_names=(
            "positioning",
            "xAxis",
            "yAxis",
            "xPos",
            "yPos",
            "hide",
            "Line/color",
            "Line/width",
            "Line/style",
            "Line/transparency",
            "Line/hide",
            "Fill/color",
            "Fill/transparency",
            "Fill/hide",
        ),
    )

    expected_polygons = [
        {
            **contract,
            "path": f"/page1/{contract['name']}"
            if contract.get("parent") == "page"
            else f"/page1/graph1/{contract['name']}",
        }
        for contract in performance_polygon_contracts(spec)
    ]

    actual_polygons_by_path = {
        str(record["path"]): record for record in polygon_records
    }

    expected_polygons_by_path = {
        str(record["path"]): record for record in expected_polygons
    }

    if (
        len(actual_polygons_by_path) != len(polygon_records)
        or set(actual_polygons_by_path) != set(expected_polygons_by_path)
        or any(
            (
                not _polygon_record_matches_contract(
                    actual_polygons_by_path[path], expected=expected
                )
                for path, expected in expected_polygons_by_path.items()
            )
        )
    ):
        raise ValueError(
            "Exact-current Veusz polygon inventory differs from the closed performance-comparison geometry contract."
        )

    allowed_polygon_paths = set(expected_polygons_by_path)

    line_records = _visible_data_bindings(
        loaded_document,
        widget_type="line",
        setting_names=(
            "positioning",
            "xAxis",
            "yAxis",
            "mode",
            "xPos",
            "yPos",
            "xPos2",
            "yPos2",
            "clip",
            "hide",
            "Line/color",
            "Line/width",
            "Line/style",
            "Line/transparency",
            "Line/hide",
            "arrowleft",
            "arrowright",
            "Fill/hide",
        ),
    )

    expected_lines = [
        {**contract, "path": f"/page1/graph1/{contract['name']}"}
        for contract in categorical_line_contracts(spec)
        + curve_factor_legend_line_contracts(spec)
        + reference_guide_line_contracts(spec)
        + performance_line_contracts(spec)
    ]

    actual_lines_by_path = {str(record["path"]): record for record in line_records}

    expected_lines_by_path = {str(record["path"]): record for record in expected_lines}

    if (
        len(actual_lines_by_path) != len(line_records)
        or set(actual_lines_by_path) != set(expected_lines_by_path)
        or any(
            (
                not _line_record_matches_contract(
                    actual_lines_by_path[path], expected=expected
                )
                for path, expected in expected_lines_by_path.items()
            )
        )
    ):
        raise ValueError(
            "Exact-current Veusz native line inventory differs from its closed categorical/reference geometry and style contract."
        )
    return allowed_polygon_paths
