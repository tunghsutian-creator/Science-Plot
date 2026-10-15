"""Explicit sparse/span extensions of the deterministic physical solver."""

from copy import deepcopy

import pytest

from sciplot_core.plot_document.errors import DocumentError
from sciplot_core.plot_layout import solve_layout, structural_publication_qa

from test_figure_layout import grid


def subset(layout, views, axes, ids):
    layout["cells"] = [cell for cell in layout["cells"] if cell["view_id"] in ids]
    return layout, [view for view in views if view["id"] in ids], [axis for axis in axes if axis["view_id"] in ids]


def test_sparse_empty_tracks_preserve_physical_grid_and_require_opt_in():
    layout, views, axes = subset(*grid(3, 3), {"view:11"})
    with pytest.raises(DocumentError) as captured:
        solve_layout(layout, views, axes)
    assert captured.value.reason_code == "figure_layout_empty_cell"
    layout["capabilities"] = ["sparse"]
    result = solve_layout(layout, views, [])
    assert result == solve_layout(deepcopy(layout), deepcopy(views), [])
    panel = result["panels"][0]
    assert panel["cell_mm"][0] == pytest.approx(3 + (180 - 6 - 8) / 3 + 4)
    assert panel["cell_mm"][1] == 52
    assert result["height_mm"] == 149
    assert structural_publication_qa(result)["status"] == "passed"


def test_explicit_sparse_layout_can_resolve_empty_page_with_positive_tracks():
    layout, views, axes = subset(*grid(2, 3), set())
    layout["capabilities"] = ["sparse"]
    result = solve_layout(layout, views, [])
    assert result["panels"] == []
    assert result["height_mm"] == 100


def test_spanning_panel_requires_capability_and_counts_every_covered_cell():
    layout, views, axes = subset(*grid(), {"view:00", "view:10", "view:11"})
    layout["cells"][0]["column_span"] = 2
    with pytest.raises(DocumentError) as captured:
        solve_layout(layout, views, axes)
    assert captured.value.reason_code == "figure_layout_span_unsupported"
    layout["capabilities"] = ["spans"]
    result = solve_layout(layout, views, axes)
    first, second, third = result["panels"]
    assert first["cell_mm"][2] == 174
    assert second["cell_mm"][2] + third["cell_mm"][2] + 4 == first["cell_mm"][2]
    assert first["plot_mm"][0] == second["plot_mm"][0]
    assert first["plot_mm"][0] + first["plot_mm"][2] == pytest.approx(third["plot_mm"][0] + third["plot_mm"][2])
    assert structural_publication_qa(result)["status"] == "passed"


@pytest.mark.parametrize("mutation", ["interior_overlap", "right_bounds", "bottom_bounds", "fractional_span", "negative_span"])
def test_span_validation_rejects_interior_overlap_and_invalid_extents(mutation):
    layout, views, axes = grid()
    layout["capabilities"] = ["sparse", "spans"]
    cell = layout["cells"][0]
    if mutation == "interior_overlap":
        cell.update(row_span=2, column_span=2)
    elif mutation == "right_bounds":
        layout["cells"][1]["column_span"] = 2
    elif mutation == "bottom_bounds":
        layout["cells"][2]["row_span"] = 2
    elif mutation == "fractional_span":
        cell["row_span"] = 1.0
    else:
        cell["row_span"] = -1
    with pytest.raises(DocumentError):
        solve_layout(layout, views, axes)


def test_span_uses_weighted_track_sum_and_internal_gaps_in_both_directions():
    layout, views, axes = subset(*grid(3, 3), {"view:00", "view:22"})
    layout["cells"][0].update(row_span=2, column_span=2)
    layout.update(capabilities=["sparse", "spans"], row_weights=[1, 2, 3], column_weights=[2, 3, 1], height_mm=200)
    result = solve_layout(layout, views, [])
    first, last = result["panels"]
    assert first["cell_mm"][2] == pytest.approx((180 - 6 - 8) * 5 / 6 + 4)
    assert first["cell_mm"][3] == pytest.approx((200 - 6 - 8) * 3 / 6 + 4)
    assert first["cell_mm"][0] + first["cell_mm"][2] + 4 == pytest.approx(last["cell_mm"][0])
    assert first["cell_mm"][1] + first["cell_mm"][3] + 4 == pytest.approx(last["cell_mm"][1])


def test_automatic_height_reserves_spanning_axis_decorations():
    layout, views, axes = subset(*grid(2, 2), {"view:00"})
    layout["cells"][0].update(row_span=2, column_span=2)
    layout.update(capabilities=["spans"], panel_min_height_mm=1)
    axes[-1]["label"] = "Response label whose length sets a tall minimum plot"
    result = solve_layout(layout, views, axes)
    assert result["height_mm"] > 60
    assert result["panels"][0]["plot_mm"][3] > 40
    assert structural_publication_qa(result)["status"] == "passed"


def test_shared_axes_require_matching_span_extents_before_suppression():
    layout, views, axes = subset(*grid(2, 2), {"view:00", "view:10", "view:11"})
    layout["cells"][0]["column_span"] = 2
    layout.update(capabilities=["spans"], resolve=[{"id": "resolve:x", "views": [view["id"] for view in views], "x": "shared"}])
    result = solve_layout(layout, views, axes)
    assert result["panels"][0]["suppressed_axis_ids"] == []
    layout, views, axes = subset(*grid(2, 2), {"view:00", "view:10"})
    for cell in layout["cells"]:
        cell["column_span"] = 2
    layout.update(capabilities=["spans"], resolve=[{"id": "resolve:x", "views": [view["id"] for view in views], "x": "shared"}])
    result = solve_layout(layout, views, axes)
    assert result["panels"][0]["suppressed_axis_ids"] == ["axis:view:00:bottom"]


@pytest.mark.parametrize("capabilities", [["unknown"], ["sparse", "sparse"], "sparse"])
def test_grid_capability_set_is_closed(capabilities):
    layout, views, axes = grid()
    layout["capabilities"] = capabilities
    with pytest.raises(DocumentError):
        solve_layout(layout, views, axes)
