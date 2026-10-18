"""Display interpolation is presentation, with separately audited native arrays."""
from copy import deepcopy

import pytest

from sciplot_core.plot_backends.figure_marks import mark_geometry
from sciplot_core.plot_backends.native_primitives import dataset_name, native_datasets
from sciplot_core.plot_document import DocumentError
from sciplot_core.plot_grammar import merge_figure_spec, split_figure_spec
from sciplot_core.plot_grammar.ir import seal_ir_v2
from test_figure_grammar import example, resolve


def interpolated():
    spec, datasets = example()
    line = spec["views"][0]["layers"][0]["marks"][0]
    assert line["type"] == "line"
    line["interpolation"] = {"method": "pchip", "subdivisions": 4, "purpose": "display", "boundary": "preserve_gaps"}
    return spec, datasets


def test_interpolation_changes_presentation_only_and_raw_values_survive_compilation():
    spec, raw = interpolated()
    original = deepcopy(raw)
    plain = deepcopy(spec)
    plain["views"][0]["layers"][0]["marks"][0].pop("interpolation")
    science, presentation = split_figure_spec(spec)
    assert split_figure_spec(plain)[0] == science
    assert split_figure_spec(plain)[1] != presentation
    assert merge_figure_spec(science, presentation) == spec
    ir = resolve(spec, raw)
    assert ir["datasets"] == original and raw == original
    line, point = ir["views"][0]["layers"][0]["marks"]
    curve = ir["display_curves"][line["id"]]
    assert curve["source_dataset_id"] == "raw:A"
    assert curve["curve"]["original_indices"] == [0, 4, 8]
    assert len(curve["curve"]["x"]) == 9
    view, layer = ir["views"][0], ir["views"][0]["layers"][0]
    line_geometry = mark_geometry(ir, view, layer, line)[0]
    point_geometry = mark_geometry(ir, view, layer, point)[0]
    assert point_geometry == {"xData": dataset_name("raw:A", "column:0"), "yData": dataset_name("raw:A", "column:1")}
    assert line_geometry != point_geometry
    arrays = native_datasets(ir)
    assert arrays[line_geometry["xData"]] == curve["curve"]["x"]
    assert arrays[point_geometry["xData"]] == original["raw:A"]["columns"]["column:0"]["values"]


@pytest.mark.parametrize("mutation", ["values", "origin", "extra", "missing", "source"])
def test_ir_cannot_seal_forged_display_line_or_ignored_evidence(mutation):
    spec, raw = interpolated()
    ir = resolve(spec, raw)
    line = ir["views"][0]["layers"][0]["marks"][0]
    curve = ir["display_curves"][line["id"]]
    if mutation == "values":
        curve["curve"]["y"][1] = 123
    elif mutation == "origin":
        curve["curve"]["original_indices"] = [0, 1, 2]
    elif mutation == "extra":
        ir["display_curves"]["unbound"] = deepcopy(curve)
    elif mutation == "missing":
        ir.pop("display_curves")
    else:
        curve["source_dataset_id"] = "another"
    with pytest.raises(DocumentError):
        seal_ir_v2(ir)


def test_plain_historical_ir_has_no_display_fields_or_extra_arrays():
    spec, raw = example()
    ir = resolve(spec, raw)
    assert "display_curves" not in ir
    assert len(native_datasets(ir)) == 2


@pytest.mark.parametrize("field,value", [("purpose", "analysis"), ("subdivisions", 33), ("method", "spline"), ("boundary", "drop_duplicates")])
def test_closed_mark_contract_rejects_silent_smoothing_behaviour(field, value):
    spec, raw = interpolated()
    spec["views"][0]["layers"][0]["marks"][0]["interpolation"][field] = value
    with pytest.raises(DocumentError):
        resolve(spec, raw)
