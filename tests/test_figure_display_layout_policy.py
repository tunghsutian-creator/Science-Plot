"""Secondary-axis allocation is opt-in presentation; old house geometry survives."""
from copy import deepcopy

import pytest

from sciplot_core.plot_document import DocumentError
from sciplot_core.plot_grammar import merge_figure_spec, split_figure_spec
from sciplot_core.rendering_contract import contract_binding, contract_value
from test_figure_grammar import example, resolve

POLICY = "decorated_secondary_sides_v1"


def dual_figure():
    spec, raw = example()
    spec["rendering_contract"] = contract_binding()
    right = deepcopy(spec["views"][0]["axes"][-1])
    right.update(id="axis:right", side="right", label="Second guide")
    spec["views"][0]["axes"].append(right)
    return spec, raw


def test_axis_allocation_policy_is_optional_lossless_presentation_only():
    plain, _ = dual_figure()
    opted = {**deepcopy(plain), "axis_layout_policy": POLICY}
    science, presentation = split_figure_spec(opted)
    assert science == split_figure_spec(plain)[0]
    assert presentation != split_figure_spec(plain)[1]
    assert merge_figure_spec(science, presentation) == opted
    assert merge_figure_spec(*split_figure_spec(plain)) == plain
    with pytest.raises(DocumentError):
        split_figure_spec({**plain, "axis_layout_policy": "silently_resize_old_projects"})


def test_old_valid_dual_without_policy_retains_exact_house_margins_and_trace():
    spec, raw = dual_figure()
    old = resolve(spec, raw)
    cell, plot = (old["layout"]["panels"][0][key] for key in ("cell_mm", "plot_mm"))
    assert cell[0] + cell[2] - plot[0] - plot[2] == pytest.approx(contract_value("frame.right_mm"))
    assert plot[1] - cell[1] == pytest.approx(contract_value("frame.top_mm"))
    assert "figure:additional_axis_layout" not in old["style_provenance"]
    spec["axis_layout_policy"] = POLICY
    new = resolve(spec, raw)
    new_cell, new_plot = (new["layout"]["panels"][0][key] for key in ("cell_mm", "plot_mm"))
    assert new_cell[0] + new_cell[2] - new_plot[0] - new_plot[2] > contract_value("frame.right_mm")
    trace = new["style_provenance"]["figure:additional_axis_layout"]
    assert trace["policy"] == POLICY
    assert trace["base_margins_mm"]["right"] == contract_value("frame.right_mm")
    assert trace["panels"][0]["margins_mm"]["right"] > trace["base_margins_mm"]["right"]
    assert trace["native_text_verified"] is False
