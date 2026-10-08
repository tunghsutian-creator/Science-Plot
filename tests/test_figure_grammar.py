"""Scientific grammar invariants independent of backend rendering."""
from copy import deepcopy
import json
from pathlib import Path

import pytest

from sciplot_core.plot_document import DocumentError
from sciplot_core.plot_grammar import compile_figure, split_figure_spec, merge_figure_spec
from sciplot_core.plot_ir import validate_ir


def example():
    spec = json.loads((Path(__file__).parent / "fixtures/figure_spec_v2.json").read_text())
    datasets = {"raw:A": {"id": "raw:A", "columns": {
        "column:0": {"label": "Frequency", "unit": "Hz", "values": [0., 5., 10.]},
        "column:1": {"label": "Modulus", "unit": "Pa", "values": [1., 5., 15.]}},
        "provenance": {"sources": [{"source_id": "raw:A", "sha256": "a" * 64, "table_selection": {"sheet": None, "header_rows": [0], "data_start_row": 2, "data_end_row": 5, "unit_row": 1}, "column_indices": {"column:0": 0, "column:1": 1}, "rows": [2, 3, 4]}], "transforms": []}}}
    return spec, datasets


def resolve(spec, datasets):
    return compile_figure(spec, datasets, scientific_hash="a" * 64, presentation_hash="b" * 64)


def test_lossless_projection_theme_and_data_anchor_identity():
    spec, datasets = example()
    spec["annotations"] = [{"id": "annotation:peak", "space": "data", "view_id": "view:A",
        "x_scale": "scale:x", "y_scale": "scale:y", "x": 5, "y": 15, "text": "Peak", "visible": True, "style": {}}]
    science, presentation = split_figure_spec(spec)
    assert merge_figure_spec(science, presentation) == spec
    changed = deepcopy(spec)
    changed["theme"]["figure"] = {"line": {"line_width_pt": 1.2}}
    assert split_figure_spec(changed)[0] == science
    first = resolve(spec, datasets)
    changed["scales"][0]["domain"] = [0, 20]
    second = resolve(changed, datasets)
    assert second["annotations"][0]["x"] == first["annotations"][0]["x"]
    assert second["annotations"][0]["position_mm"] != first["annotations"][0]["position_mm"]
    assert validate_ir(first) == first
    tampered = deepcopy(first)
    tampered["views"][0]["layers"][0]["marks"][0]["style"]["line_width_pt"] = 3
    with pytest.raises(DocumentError):
        validate_ir(tampered)


@pytest.mark.parametrize("mutation", ["log", "unit", "missing", "semantic", "native", "empty", "capability"])
def test_preflight_rejects_scientific_and_unsupported_state(mutation):
    spec, datasets = example()
    if mutation == "log":
        spec["scales"][0].update(transform="log", domain=[0.1, 10])
        spec["views"][0]["axes"][0]["ticks"] = [1, 10]
    elif mutation == "unit":
        datasets["raw:A"]["columns"]["column:1"]["unit"] = "MPa"
    elif mutation == "missing":
        spec["views"][0]["layers"][0]["mappings"]["y"] = "column:9"
    elif mutation == "semantic":
        spec["views"][0]["layers"][0]["mapping_semantics"]["y"] = "temperature"
    elif mutation == "native":
        spec["views"][0]["layers"][0]["native_path"] = "/page/graph"
    elif mutation == "empty":
        datasets["raw:A"]["columns"]["column:1"]["values"] = [None] * 3
    else:
        spec["scales"][0]["transform"] = "symlog"
    with pytest.raises(DocumentError):
        resolve(spec, datasets)


def test_shared_scales_and_legend_resolution_are_explicit():
    from sciplot_core.plot_grammar import validate_figure_spec

    spec, _ = example()
    second = deepcopy(spec['views'][0])
    second.update(id='view:B', panel_label='B')
    for axis in second['axes']:
        axis['id'] += '-B'
    for layer in second['layers']:
        layer['id'] += '-B'
        for mark in layer['marks']:
            mark['id'] += '-B'
    spec['views'].append(second)
    spec['composition'].update(kind='vconcat', rows=2, row_weights=[1,2])
    spec['composition']['cells'].append({'view_id':'view:B','row':1,'column':0,'row_span':1,'column_span':1})
    with pytest.raises(DocumentError, match='explicit shared'):
        validate_figure_spec(spec)
    spec['composition']['resolve'] = [{'id':'resolve:AB','views':['view:A','view:B'],'x':'shared','y':'shared','legend':'shared'}]
    with pytest.raises(DocumentError, match='Shared legend'):
        validate_figure_spec(spec)
    guide = spec['guides'][0]
    guide.pop('view_id')
    guide.update(scope='figure', location='top', layer_ids=[], order=[], columns=2)
    validate_figure_spec(spec)
    ir = resolve(spec, example()[1])
    assert len(ir['guides'][0]['entries']) == 2
    assert ir['layout']['panels'][0]['suppressed_axis_ids'] == ['axis:xb']
    spec['composition']['resolve'][0]['legend'] = 'independent'
    with pytest.raises(DocumentError, match='Independent legends'):
        validate_figure_spec(spec)


def test_style_precedence_resolves_every_scope_before_backend():
    spec, data = example()
    view = spec['views'][0]
    layer = view['layers'][0]
    mark = layer['marks'][0]
    spec['theme']['project']={'line':{'line_width_pt':1,'line_color':'#111111'}}
    spec['theme']['figure']={'line':{'line_width_pt':2}}
    view['style']={'line':{'line_width_pt':3}}
    layer['style']={'line':{'line_width_pt':4}}
    mark['style']={'line_width_pt':5}
    ir=resolve(spec,data)
    style=ir['views'][0]['layers'][0]['marks'][0]['style']
    assert style['line_width_pt']==5 and style['line_color']=='#111111'
    assert set(style)=={'line_width_pt','line_color','line_style','line_join'}


@pytest.mark.parametrize('bounds', [[None,None,None],[1.,None,2.]])
def test_empty_or_disconnected_band_is_not_a_visible_layer(bounds):
    spec,data=example()
    layer=spec['views'][0]['layers'][0]
    layer['marks']=[{'id':'mark:band','type':'band','style':{}}]
    layer['mappings'].update(y_low='column:2',y_high='column:3')
    data['raw:A']['columns']['column:2']={'label':'Low','unit':'Pa','values':bounds}
    data['raw:A']['columns']['column:3']={'label':'High','unit':'Pa','values':bounds}
    with pytest.raises(DocumentError, match='(complete|consecutive)'):
        resolve(spec,data)
