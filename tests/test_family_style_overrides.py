"""Historical family overrides stay explicit; global house resources never change."""
from copy import deepcopy

import pytest

from sciplot_core.plot_backends.figure_marks import mark_geometry, mark_nodes
from sciplot_core.plot_backends.figure_plan import drawing_plan
from sciplot_core.plot_document import DocumentError
from sciplot_core.plot_grammar import seal_ir_v2, split_figure_spec, validate_figure_spec
from sciplot_core.rendering_contract import load_contract
from test_house_style_grammar import compile_, house


def test_category_labels_roundtrip_without_changing_science_or_house():
    spec, data = house()
    science = split_figure_spec(spec)[0]
    pinned = load_contract()
    axis = spec['views'][0]['axes'][0]
    axis['tick_labels'] = [f'E{index}' for index, _ in enumerate(axis['ticks'])]
    ir = compile_(spec, data)
    resolved = ir['views'][0]['axes'][0]
    assert resolved['tick_notation'] == 'labels'
    assert resolved['tick_labels'] == axis['tick_labels']
    assert split_figure_spec(spec)[0] == science
    assert ir['style_provenance'][axis['id'] + ':tick_labels']['source'] == 'object override'
    assert load_contract() == pinned
    assert all('text-anchor' not in str(node) for node in drawing_plan(ir))


@pytest.mark.parametrize('problem', ['count', 'log', 'notation', 'unbound'])
def test_category_labels_reject_ambiguous_axis_representation(problem):
    spec, _ = house()
    axis = spec['views'][0]['axes'][0]
    axis['tick_labels'] = ['E'] * len(axis['ticks'])
    if problem == 'count':
        axis['tick_labels'].append('extra')
    elif problem == 'log':
        spec['scales'][0].update(transform='log', domain=[.1, 20])
        axis['ticks'] = [value + .1 for value in axis['ticks']]
    elif problem == 'notation':
        axis['style']['tick_notation'] = 'power10'
    else:
        spec.pop('rendering_contract')
    with pytest.raises(DocumentError):
        validate_figure_spec(spec)


def test_axis_italic_runs_retain_exact_text_and_presentation_identity():
    spec, data = house()
    science = split_figure_spec(spec)[0]
    axis = spec['views'][0]['axes'][1]
    axis.update(label='G′ (Pa)', label_runs=[{'text': 'G', 'italic': True},
                                          {'text': '′ (Pa)', 'italic': False}])
    ir = compile_(spec, data)
    assert split_figure_spec(spec)[0] == science
    native_axis = next(node for node in drawing_plan(ir) if node.get('semantic_id') == axis['id'])
    assert native_axis['settings']['label'] == r'\italic{G}′ (Pa)'
    altered = deepcopy(ir)
    altered['views'][0]['axes'][1]['label_runs'][0]['text'] = 'K'
    with pytest.raises(DocumentError, match='exact plain label'):
        seal_ir_v2(altered)


def test_numeric_metric_flow_cannot_hide_unused_category_labels():
    spec, data = house()
    ir = compile_(spec, data)
    ir['views'][0]['axes'][0]['tick_labels'] = ['unused']
    with pytest.raises(DocumentError, match='numeric mode'):
        seal_ir_v2(ir)


def test_three_sided_bar_keeps_baseline_border_absence_explicit():
    spec, data = house()
    layer = spec['views'][0]['layers'][0]
    layer['marks'] = [{'id': 'bar:historical', 'type': 'bar', 'baseline': 0., 'width_data': .32,
                      'style': {'baseline_border_visible': False}}]
    ir = compile_(spec, data)
    view, layer = ir['views'][0], ir['views'][0]['layers'][0]
    mark = layer['marks'][0]
    nodes = mark_nodes(ir, view, layer, mark)
    assert len(nodes) == 12  # Three source points, each with three edges and one fill.
    segments = [node['settings'] for node in nodes if node['type'] == 'line']
    assert len(segments) == 9
    assert not any(item['yPos'] == item['yPos2'] == [0.] for item in segments)
    assert all(node['settings']['Line/hide'] for node in nodes if node['type'] == 'polygon')
    mark['style'].pop('baseline_border_visible')
    assert len(mark_geometry(ir, view, layer, mark)) == 3
    assert all(node['type'] == 'polygon' for node in mark_nodes(ir, view, layer, mark))
