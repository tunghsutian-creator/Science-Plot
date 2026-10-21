"""Literal legacy native primitive controls for the shared data geometry owner."""
from copy import deepcopy

import pytest

from sciplot_core.foundation.json_hashing import canonical_json_sha256
from sciplot_core.plot_backends.figure_marks import mark_geometry

CASES = ("line", "point", "bar", "bar_outline", "errorbar", "band", "vertical", "horizontal", "text", "interpolated")


def geometry_fixture(case):
    columns = {name: {"values": values} for name, values in {
        "x": [1, 2, None, 4, 5], "y": [2, None, 6, 8, 10],
        "low": [1, 3, None, 7, 9], "high": [3, 5, None, 9, 11]}.items()}
    layer = {"id": "layer:control", "dataset_id": "raw:control", "x_scale": "scale:x", "y_scale": "scale:y",
             "mappings": {"x": "x", "y": "y", "y_low": "low", "y_high": "high"}}
    ir = {"datasets": {"raw:control": {"columns": columns}}, "scales": [
        {"id": "scale:x", "domain": [1, 5], "transform": "linear", "direction": "ascending"},
        {"id": "scale:y", "domain": [1, 11], "transform": "linear", "direction": "ascending"}],
        "layout": {"panels": [{"view_id": "view:control", "plot_mm": [0, 0, 100, 50]}]}}
    mark = {"id": "mark:control", "type": case, "style": {}}
    if case in {"bar", "bar_outline"}:
        mark.update(type="bar", baseline=1, width_data=2)
        mark["style"] = {"border_width_pt": 1, "baseline_border_visible": case != "bar_outline"}
    elif case == "errorbar":
        mark["style"] = {"cap_width_pt": 4}
    elif case in {"vertical", "horizontal"}:
        mark.update(type="rule", orientation=case)
    elif case == "text":
        mark["text"] = "Anchor"
    elif case == "interpolated":
        mark.update(type="line", interpolation={"method": "pchip", "subdivisions": 4,
            "purpose": "display", "boundary": "preserve_gaps"})
    return ir, {"id": "view:control"}, layer, mark


# Captured from f7063a7's unchanged figure_marks.py. These are compatibility
# assertions for generated controls, not replacements for any native golden.
LEGACY_HASHES = {
    "line": "da52a9d4e30d2341c45c6d820bdfbbc784abb0b7535bc744172607b9d5ece2c7",
    "point": "da52a9d4e30d2341c45c6d820bdfbbc784abb0b7535bc744172607b9d5ece2c7",
    "bar": "c4571dc2cdec39a00f5a6180e3fcbc000f0f30d74d2497fa4d03f4b3879159b1",
    "bar_outline": "975f6460e8d09b335cc1b89eb29ccd55d2c19f3b4934b3132f490d67d44b0012",
    "errorbar": "ec94b8e09d61d91ea14b7e0b5e97850969ac4a5dc018211f453c0b4259ef574f",
    "band": "13eaf385676aaac95bc18471850bf3ca0908c7af1537be2b4bf74357980a9456",
    "vertical": "218ac4548599ba16d429cc87bd1f94cb9593f6cd91b1512e3be5400f5046e8b9",
    "horizontal": "42434a1fd0b601a8128c2441e586fee3d0edac8f6b19f153309a9bd24b96bda8",
    "text": "54e6fe9a871fe380786f10925fcb77a7ac11ed8b8743ff8f1ea277b53afaf8de",
    "interpolated": "770023db2863dea17e9482669b008c8aee0089149ddd7e6e95e0fd14722d793b"}


@pytest.mark.parametrize("case", CASES)
def test_legacy_primitive_dictionary_order_and_numeric_types_are_exact(case):
    ir, view, layer, mark = geometry_fixture(case)
    original = deepcopy(ir)
    variants = []
    for transform, direction in (("linear", "ascending"), ("linear", "descending"),
                                 ("log", "ascending"), ("log", "descending")):
        for scale in ir["scales"]:
            scale.update(transform=transform, direction=direction)
        variants.append(mark_geometry(ir, view, layer, mark))
    assert canonical_json_sha256(variants, allow_nan=False) == LEGACY_HASHES[case]
    assert ir["datasets"] == original["datasets"]


def test_literal_band_breaks_ignore_missing_centre_but_preserve_original_bounds():
    assert mark_geometry(*geometry_fixture("band")) == [
        {"xPos": [1, 2, 2, 1], "yPos": [1, 3, 5, 3]},
        {"xPos": [4, 5, 5, 4], "yPos": [7, 9, 11, 9]}]


def test_literal_three_sided_bar_outlines_precede_fill_without_new_rounding():
    primitives = mark_geometry(*geometry_fixture("bar_outline"))
    assert primitives[:4] == [
        {"xPos": [0.0], "yPos": [1], "xPos2": [0.0], "yPos2": [2]},
        {"xPos": [2.0], "yPos": [1], "xPos2": [2.0], "yPos2": [2]},
        {"xPos": [0.0], "yPos": [2], "xPos2": [2.0], "yPos2": [2]},
        {"xPos": [0.0, 2.0, 2.0, 0.0], "yPos": [1, 1, 2, 2]}]
