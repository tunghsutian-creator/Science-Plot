"""Discriminating physical layout and measured-bound publication QA checks."""

from copy import deepcopy

import pytest

from sciplot_core.plot_document.errors import DocumentError
from sciplot_core.plot_layout import (
    native_publication_qa, resolve_axis_text, resolve_guides,
    solve_layout, structural_publication_qa,
)


def grid(rows=2, columns=2):
    layout = {"kind": "grid", "rows": rows, "columns": columns,
        "cells": [{"view_id": f"view:{row}{column}", "row": row, "column": column,
                   "row_span": 1, "column_span": 1} for row in range(rows) for column in range(columns)],
        "column_weights": [1] * columns, "row_weights": [1] * rows, "resolve": [],
        "width_mm": 180, "height_mm": "auto", "gap_x_mm": 4, "gap_y_mm": 4,
        "outer_margins_mm": {"left": 3, "right": 3, "top": 3, "bottom": 3},
        "panel_min_height_mm": 45, "panel_label_height_mm": 6}
    views = [{"id": cell["view_id"], "panel_label": chr(65 + index)} for index, cell in enumerate(layout["cells"])]
    axes = [{"id": f"axis:{view['id']}:{side}", "view_id": view["id"],
             "scale_id": f"scale:{side}", "side": side, "visible": True,
             "label_visible": True, "label": "Frequency (Hz)" if side == "bottom" else "Modulus (Pa)",
             "ticks": [1, 10, 100], "tick_labels": ["1", "10", "100"],
             "style": {"font_family": "Arial", "font_size_pt": 8, "color": "#000000",
                       "line_width_pt": 0.7, "tick_length_pt": 3, "tick_direction": "in"}}
            for view in views for side in ("bottom", "left")]
    return layout, views, axes


def test_weighted_grid_is_physical_aligned_deterministic_and_auto_sized():
    specification, views, axes = grid()
    specification["column_weights"] = [1.0, 1.4]
    specification["row_weights"] = [1.0, 1.2]
    axes[-1]["label"] = "A substantially longer response label"
    result = solve_layout(specification, views, axes)
    assert result == solve_layout(deepcopy(specification), deepcopy(views), deepcopy(axes))
    first, second, third, fourth = result["panels"]
    assert second["cell_mm"][2] / first["cell_mm"][2] == pytest.approx(1.4)
    assert third["cell_mm"][3] / first["cell_mm"][3] == pytest.approx(1.2)
    assert first["plot_mm"][0] == third["plot_mm"][0]
    assert second["plot_mm"][0] == fourth["plot_mm"][0]
    assert first["plot_mm"][1] == second["plot_mm"][1]
    assert result["height_mm"] > 100
    assert all(panel["panel_label_mm"] is not None for panel in result["panels"])
    report = structural_publication_qa(result)
    assert report["status"] == "passed"
    assert report["native_text_checked"] is False


def test_shared_scale_suppression_requires_explicit_resolution_same_scale_and_alignment():
    specification, views, axes = grid()
    specification["resolve"] = [{"id": "resolve:x", "views": [view["id"] for view in views], "x": "shared", "y": "independent"}]
    resolved = solve_layout(specification, views, axes)
    assert resolved["panels"][0]["suppressed_axis_ids"] == ["axis:view:00:bottom"]
    assert resolved["panels"][2]["suppressed_axis_ids"] == []
    axes[4]["scale_id"] = "scale:independent"
    resolved = solve_layout(specification, views, axes)
    assert resolved["panels"][0]["suppressed_axis_ids"] == []


def test_shared_y_suppresses_only_inner_guide_with_same_scale():
    specification, views, axes = grid(1, 2)
    specification["resolve"] = [{"id": "resolve:y", "views": [view["id"] for view in views],
                                  "x": "independent", "y": "shared"}]
    resolved = solve_layout(specification, views, axes)
    assert resolved["panels"][0]["suppressed_axis_ids"] == []
    assert resolved["panels"][1]["suppressed_axis_ids"] == ["axis:view:01:left"]


def test_dual_scales_reserve_both_sides_without_scientific_type_cases():
    specification, views, axes = grid(1, 1)
    plain = solve_layout(specification, views, axes)
    right = deepcopy(axes[-1])
    right.update(id="axis:right", scale_id="scale:other", side="right", label="Dimensionless ratio")
    dual = solve_layout(specification, views, [*axes, right])
    assert dual["panels"][0]["plot_mm"][2] < plain["panels"][0]["plot_mm"][2]
    assert dual["panels"][0]["cell_mm"][2] == plain["panels"][0]["cell_mm"][2]


def test_insufficient_fixed_height_rejects_instead_of_collapsing_axes():
    specification, views, axes = grid()
    specification["height_mm"] = 20
    with pytest.raises(DocumentError, match="cannot contain"):
        solve_layout(specification, views, axes)


def test_duplicate_cell_and_unassigned_view_reject():
    specification, views, axes = grid()
    specification["cells"][1]["column"] = 0
    with pytest.raises(DocumentError) as captured:
        solve_layout(specification, views, axes)
    assert captured.value.reason_code == "figure_layout_cell"


def test_zero_row_weight_rejects_with_structured_error():
    specification, views, axes = grid()
    specification["row_weights"][1] = 0
    with pytest.raises(DocumentError):
        solve_layout(specification, views, axes)


def test_figure_legend_reserves_space_and_resolves_exact_entry_anchors():
    specification, views, axes = grid(1, 1)
    guide = {"id": "guide:main", "view_id": None, "visible": True, "location": "bottom",
             "columns": 2, "style": {"font_size_pt": 8},
             "entries": [{"layer_id": "layer:a", "label": "Sample A"}, {"layer_id": "layer:b", "label": "Sample B"}]}
    plain = solve_layout(specification, views, axes)
    result = solve_layout(specification, views, axes, [guide])
    assert result["height_mm"] > plain["height_mm"]
    assert result["figure_guide_bounds_mm"] is not None
    resolved = resolve_guides(result, [guide])[0]
    assert resolved["rect_mm"] == result["figure_guide_bounds_mm"]
    assert resolved["entries"][1]["label_mm"][0] > resolved["entries"][0]["label_mm"][0]


def test_axis_labels_use_log_scale_and_reversed_domain_geometry():
    specification, views, axes = grid(1, 1)
    result = solve_layout(specification, views, axes)
    scales = [{"id": f"scale:{side}", "domain": [1, 100], "transform": "log", "direction": "descending"}
              for side in ("bottom", "left")]
    resolved = resolve_axis_text(result, axes, scales)
    points = resolved[0]["tick_positions_mm"]
    assert points[0][0] > points[1][0] > points[2][0]
    assert points[0][0] - points[1][0] == pytest.approx(points[1][0] - points[2][0])
    assert resolved[1]["label_angle"] == 90


def test_native_bounds_detect_canvas_axis_tick_legend_and_annotation_overflow():
    specification, views, axes = grid(1, 1)
    result = solve_layout(specification, views, axes)
    observations = [
        {"semantic_id": "label:outside", "role": "other", "bounds_mm": [-2, 0, 4, 3]},
        *[{"semantic_id": f"text:{role}", "role": role, "view_id": "view:00",
           "bounds_mm": [0, 0, 6, 6]} for role in ("axis_label", "tick_label", "legend", "annotation")],
    ]
    report = native_publication_qa(result, observations)
    codes = {item["code"] for item in report["hard"]}
    assert {"text_outside_canvas", "axis_label_clipping", "tick_label_clipping", "legend_outside_allowed_bounds", "annotation_outside_view"} <= codes
    assert report["status"] == "failed"
    assert report["native_text_checked"] is True


def test_missing_actual_text_evidence_cannot_pass_as_native_qa():
    specification, views, axes = grid(1, 1)
    result = solve_layout(specification, views, axes)
    report = native_publication_qa(result, [], expected_text_ids=["axis:x"])
    assert report["status"] == "failed"
    assert report["native_text_checked"] is False
    assert {issue["code"] for issue in report["hard"]} == {"native_text_measurements_missing", "expected_text_not_measured"}


def test_native_collision_is_soft_and_data_collision_not_claimed_without_points():
    specification, views, axes = grid(1, 1)
    result = solve_layout(specification, views, axes)
    x, y, _width, _height = result["panels"][0]["plot_mm"]
    observations = [{"semantic_id": f"annotation:{index}", "role": "annotation", "view_id": "view:00",
                     "bounds_mm": [x + 2, y + 2, 5, 3]} for index in range(2)]
    report = native_publication_qa(result, observations)
    assert report["status"] == "passed"
    assert report["soft"][0]["code"] == "text_collision"
    assert report["data_collision_checked"] is False
    report = native_publication_qa(result, observations, data_points=[{"view_id": "view:00", "x_mm": x + 3, "y_mm": y + 3}])
    assert report["data_collision_checked"] is True
    assert any(item["code"] == "text_data_collision" for item in report["soft"])


def test_bad_resolved_geometry_and_data_anchor_are_hard_failures():
    specification, views, axes = grid()
    result = solve_layout(specification, views, axes)
    result["panels"][1]["cell_mm"] = deepcopy(result["panels"][0]["cell_mm"])
    result["panels"][2]["plot_mm"][2] = -1
    report = structural_publication_qa(result, annotations=[{"id": "annotation:peak", "view_id": "view:00", "space": "data", "position_mm": [-1, -1]}])
    assert {"panel_overlap", "nonpositive_panel_dimensions", "annotation_outside_view"} <= {issue["code"] for issue in report["hard"]}
