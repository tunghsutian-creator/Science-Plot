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
    datasets["raw:A"]["columns"]["column:1"]["values"][0] = 99
    assert first["datasets"]["raw:A"]["columns"]["column:1"]["values"] == [1., 5., 15.]
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


def test_independent_band_binds_real_bounds_without_centre_or_gap_bridging(tmp_path):
    from sciplot_core.foundation.file_hashing import file_sha256
    from sciplot_core.plot_backends.figure_plan import drawing_plan
    from sciplot_core.plot_engine.contracts import validate_create
    from sciplot_core.plot_engine.managed_sources import load_sources
    from sciplot_core.plot_ir import compile_document, create_managed_document
    from sciplot_core.rendering_contract import contract_binding

    source = tmp_path / "independent-bounds.csv"
    source.write_text("Frequency,Lower,Upper\nHz,Pa,Pa\n"
                      "0,1,3\n1,2,4\n5,,12\n8,6,9\n10,7,11\n")
    digest = file_sha256(source)
    spec, _ = example()
    spec["rendering_contract"] = contract_binding()
    spec["guides"][0]["location"] = "inside-best"
    layer = spec["views"][0]["layers"][0]
    layer["mappings"] = {"x": "column:0", "y_low": "column:1", "y_high": "column:2"}
    layer["marks"] = [{"id": "mark:bounds", "type": "band", "style": {}}]
    template = {"kind": "sciplot_figure_template", "schema_version": 2,
                "template_id": "independent-band", "figure_spec": spec}
    binding = {"kind": "sciplot_binding", "schema_version": 1, "template_id": template["template_id"],
               "data_sources": [{"source_id": "raw:A", "path": str(source), "sha256": digest,
                                 "table_selection": {"sheet": None, "header_rows": [0], "unit_row": 1,
                                                     "data_start_row": 2, "data_end_row": 7}}],
               "slots": {layer["id"]: {"series_id": layer["id"], "sample": "Bounds",
                                      "x": {"source_id": "raw:A", "column": "Frequency", "column_index": 0},
                                      "y": {"source_id": "raw:A", "column": "Lower", "column_index": 1},
                                      "x_unit": "Hz", "y_unit": "Pa"}},
               "transforms": [], "guards": {}, "provenance": {}}
    wire = validate_create({"idempotency_key": "bounds", "rule_id": "ordinary_xy",
                            "template_definition": template, "data_binding": binding})
    document = create_managed_document(wire["template_definition"], wire["data_binding"], plot_id="bounds")
    data = load_sources(document, "ordinary_xy")
    ir = compile_document(document, data)
    assert validate_ir(ir) == ir
    resolved = ir["datasets"]["raw:A"]
    assert resolved["columns"]["column:1"]["values"] == [1, 2, None, 6, 7]
    assert resolved["columns"]["column:2"]["values"] == [3, 4, 12, 9, 11]
    assert resolved["provenance"]["sources"][0]["rows"] == [2, 3, 4, 5, 6]
    polygons = [node["settings"] for node in drawing_plan(ir) if node["type"] == "polygon"]
    assert [(node["xPos"], node["yPos"]) for node in polygons] == [
        ([0, 1, 1, 0], [1, 2, 4, 3]), ([8, 10, 10, 8], [6, 7, 11, 9]),
    ]
    layer["marks"].append({"id": "mark:centre", "type": "line", "style": {}})
    with pytest.raises(DocumentError, match="band-only"):
        create_managed_document(template, binding, plot_id="requires-centre")
    layer["marks"].pop()
    layer["mappings"]["x_high"] = "column:0"
    with pytest.raises(DocumentError):
        create_managed_document(template, binding, plot_id="no-implicit-alignment")
    assert file_sha256(source) == digest
