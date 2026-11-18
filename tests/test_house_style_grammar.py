"""House authority is explicit, stable, complete and independently overrideable."""
from copy import deepcopy

import pytest

from sciplot_core.plot_document import DocumentError
from sciplot_core.plot_grammar import compile_figure, seal_ir_v2, split_figure_spec, validate_figure_spec
from sciplot_core.plot_ir import create_managed_document
from sciplot_core.plot_ir.figure_document import figure_spec
from sciplot_core.rendering_contract import contract_binding, require_binding
from sciplot_core.rendering_contract.registry import CURRENT_HOUSE_CONTRACT_ID, writer_binding
from test_figure_document import request_for_figure
from test_figure_grammar import example


def house():
    spec, data = example()
    spec['rendering_contract'] = contract_binding()
    spec['layout'] = {}
    spec['views'][0]['panel_label'] = None
    spec['theme'] = {'project': {}, 'figure': {}}
    return spec, data


def compile_(spec, data):
    return compile_figure(spec, data, scientific_hash='a' * 64, presentation_hash='b' * 64)


def test_creation_pins_house_but_does_not_rewrite_old_revisions(tmp_path):
    request = request_for_figure(tmp_path)
    request['template_definition']['figure_spec']['layout'] = {}
    doc = create_managed_document(request['template_definition'], request['data_binding'], plot_id='plot:test')
    spec = figure_spec(doc)
    assert spec['rendering_contract'] == contract_binding()
    request_spec = request['template_definition']['figure_spec']
    assert writer_binding(request_spec) == contract_binding(CURRENT_HOUSE_CONTRACT_ID)
    request_spec['guides'][0]['location'] = 'inside-best'
    assert writer_binding(request_spec) == contract_binding()
    request_spec['guides'][0]['location'] = 'top-right'
    request_spec['rendering_contract'] = writer_binding(request_spec)
    current = create_managed_document(request['template_definition'], request['data_binding'], plot_id='plot:current')
    assert figure_spec(current)['rendering_contract'] == contract_binding(CURRENT_HOUSE_CONTRACT_ID)
    old, data = example()
    historical = compile_(old, data)
    assert 'rendering_contract' not in historical
    assert historical['ir_hash'] == 'faebb65f064ce4bf8d8f0c027af848b99d7d82b76755a16d1088d7a7e7f2d2d1'
    assert historical['views'][0]['axes'][0]['style']['font_size_pt'] == 8
    assert 'rendering_contract' not in split_figure_spec(old)[1]


def test_default_physical_frame_and_traceable_style():
    spec, data = house()
    ir = compile_(spec, data)
    assert (ir['layout']['width_mm'], ir['layout']['height_mm']) == (60, 55)
    assert ir['layout']['panels'][0]['plot_mm'] == [14, 5.5, 41.5, 38.5]
    axis = ir['views'][0]['axes'][0]
    assert axis['style']['font_size_pt'] == 7
    assert axis['style']['line_width_pt'] == .8
    assert axis['style']['tick_length_pt'] == 2.8
    assert axis['style']['tick_color'] == '#000000'
    assert 'tick_labels' not in axis and 'tick_positions_mm' not in axis
    marks = ir['views'][0]['layers'][0]['marks']
    assert marks[0]['style']['line_width_pt'] == 1.2
    assert marks[1]['style']['marker_size_pt'] == 2
    assert ir['guides'][0]['style']['font_size_pt'] == 6
    assert 'rect_mm' not in ir['guides'][0]
    assert ir['style_provenance'][marks[0]['id']]['line_width_pt']['source_symbol']


def test_theme_scopes_change_presentation_only_and_do_not_mutate_geometry():
    spec, data = house()
    old_science, _ = split_figure_spec(spec)
    before = compile_(spec, data)
    spec['theme']['project']['axis'] = {'font_size_pt': 9}
    spec['theme']['figure']['line'] = {'line_width_pt': 1.6}
    view = spec['views'][0]
    view['style']['line'] = {'line_width_pt': 1.8}
    view['layers'][0]['marks'][0]['style']['line_width_pt'] = 2
    after = compile_(spec, data)
    assert split_figure_spec(spec)[0] == old_science
    assert before['layout'] == after['layout']
    mark = after['views'][0]['layers'][0]['marks'][0]
    assert mark['style']['line_width_pt'] == 2
    assert after['style_provenance'][mark['id']]['line_width_pt']['source'] == 'object override'


def test_panel_typography_provenance_matches_its_own_pinned_property():
    spec, data = house()
    spec['views'][0]['panel_label'] = 'A'
    ir = compile_(spec, data)
    view = ir['views'][0]
    trace = ir['style_provenance'][view['id'] + ':panel-label']
    contract = require_binding(spec['rendering_contract'])
    for field, property_key in (('font_weight', 'panel_label.weight'),
                                ('font_size_pt', 'panel_label.font_size_pt')):
        property_record = contract['properties'][property_key]
        assert view['panel_label_style'][field] == property_record['value']
        # Compare the complete source record: a new value over old font.weight
        # evidence would falsely label an explicit bold rule as an adapter default.
        assert trace[field] == {
            **property_record, 'source': 'RenderingStyleContract', 'contract_property': property_key,
            'contract_id': contract['contract_id'], 'content_hash': contract['content_hash'],
        }
    assert trace['font_weight']['status'] == 'specified'
    assert trace['font_weight']['source_file'].endswith('/policy/plot_contract.json')
    assert trace['font_size_pt']['source_symbol'] == 'UNIFIED_PANEL_LABEL_SIZE_PT'

    spec['theme']['project']['annotation'] = {'font_weight': 'normal', 'font_size_pt': 8}
    overridden = compile_(spec, data)
    override_trace = overridden['style_provenance'][view['id'] + ':panel-label']
    for field, value in (('font_weight', 'normal'), ('font_size_pt', 8)):
        assert overridden['views'][0]['panel_label_style'][field] == value
        assert override_trace[field] == {'value': value, 'source': 'project theme'}


def test_palette_identity_does_not_follow_z_order_and_historical_sort_retained():
    spec, data = house()
    second = deepcopy(spec['views'][0]['layers'][0])
    second['id'] = 'layer:B'
    for mark in second['marks']:
        mark['id'] += '-B'
    second['z_order'] = -1
    spec['views'][0]['layers'].append(second)
    ir = compile_(spec, data)
    colors = {layer['id']: layer['marks'][0]['style']['line_color'] for layer in ir['views'][0]['layers']}
    spec['views'][0]['layers'][0]['z_order'] = -2
    assert {layer['id']: layer['marks'][0]['style']['line_color'] for layer in compile_(spec, data)['views'][0]['layers']} == colors
    spec.pop('rendering_contract')
    spec['layout'] = example()[0]['layout']
    spec['views'][0]['layers'][0]['z_order'] = 2
    assert compile_(spec, data)['views'][0]['layers'][0]['id'] == 'layer:B'


def test_contract_roles_and_incomplete_historical_layout_rejected():
    spec, _ = house()
    spec['rendering_contract'] = contract_binding('sciplot-figure-composition-v1')
    with pytest.raises(DocumentError):
        validate_figure_spec(spec)
    spec.pop('rendering_contract')
    with pytest.raises(DocumentError, match='contract'):
        validate_figure_spec(spec)
    spec, _ = example()
    spec['views'][0]['axes'][0]['style']['major_tick_width_pt'] = 2
    with pytest.raises(DocumentError, match='contract'):
        validate_figure_spec(spec)


def test_impossible_fixed_frame_rejected_without_resize():
    spec, data = house()
    spec['layout'] = {'width_mm': 15, 'height_mm': 10}
    with pytest.raises(DocumentError, match='dimensions'):
        compile_(spec, data)


@pytest.mark.parametrize('channel', ['axis_weight', 'legend_weight', 'point_opacity', 'ignored_tick_labels'])
def test_incomplete_or_ignored_visual_ir_cannot_reach_backend(channel):
    spec, data = house()
    ir = compile_(spec, data)
    if channel == 'axis_weight':
        ir['views'][0]['axes'][0]['style'].pop('font_weight')
    elif channel == 'legend_weight':
        ir['guides'][0]['style'].pop('font_weight')
    elif channel == 'point_opacity':
        ir['views'][0]['layers'][0]['marks'][1]['style'].pop('marker_opacity')
    else:
        ir['views'][0]['axes'][0]['tick_labels'] = ['unrepresented']
    with pytest.raises(DocumentError):
        seal_ir_v2(ir)

def test_current_minor_ticks_match_retained_edge_cases_and_separate_the_old_pin(monkeypatch):
    import json

    from sciplot_core.rendering_contract import contract_value, legacy_algorithms
    from sciplot_core.rendering_contract.current_ticks import log_minor_ticks

    binding = contract_binding(CURRENT_HOUSE_CONTRACT_ID)
    multipliers = tuple(contract_value("axis.log_minor_multipliers", binding))
    cases = [
        (1., 100., "linear", (1., 100.)),
        (None, 100., "log", ()),
        (0., 100., "log", ()),
        (-1., 100., "log", ()),
        (1., float("inf"), "log", ()),
        (1., 100., "log", ()),
        (100., 1., "log", (10., 1., 100.)),
        (1., 100., "log", (10.,)),
        (1., 100., "log", (float("nan"), 10., 10.)),
        (1e-12, 1e-8, "log", (0., 1e-11, 1e-9, 1.)),
    ]
    for low, high, scale, major in cases:
        old = legacy_algorithms.log_minor_ticks(low, high, scale=scale, major_ticks=major)
        assert log_minor_ticks(low, high, scale=scale, major_ticks=major, multipliers=multipliers) == old

    saved, data = house()
    assert compile_(json.loads(json.dumps(saved)), data)["ir_hash"] == (
        "4c9ddf6cc1925da14241ee064379747944273305caa77ebc3293b775ac1ee1d7")
    inside = deepcopy(saved)
    inside["guides"][0]["location"] = "inside-best"
    assert compile_(json.loads(json.dumps(inside)), data)["ir_hash"] == (
        "170fcc4241936111c94cb3576012b0710f71ac837c05642a99ed255e696fee06")
    current = {**saved, "rendering_contract": binding}
    old_pin = legacy_algorithms.require_legacy_algorithms

    def drift(_binding):
        raise ValueError("unavailable historical bytes")

    with monkeypatch.context() as changed:
        changed.setattr(legacy_algorithms, "require_legacy_algorithms", drift)
        ir = compile_(current, data)
        assert ir["style_provenance"]["rendering:algorithm_binding"]["algorithm_id"] == (
            "sciplot-current-log-minor-ticks-v1")
        assert "rendering:legacy_legend_binding" not in ir["style_provenance"]
        with pytest.raises(DocumentError) as error:
            compile_(saved, data)
        assert error.value.reason_code == "rendering_contract_algorithm_drift"
        current["guides"][0]["location"] = "inside-best"
        with pytest.raises(DocumentError) as error:
            compile_(current, data)
        assert error.value.reason_code == "rendering_contract_algorithm_drift"

    reopened = json.loads(json.dumps(current))
    ir = compile_(reopened, data)
    assert ir["style_provenance"]["rendering:legacy_legend_binding"] == old_pin(contract_binding())
    assert compile_(current, data) == ir
