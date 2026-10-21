"""A typed presentation delta projects the existing complete guide order."""

from copy import deepcopy
import json

import pytest
from test_figure_document import request_for_figure

from sciplot_core.foundation.file_hashing import file_sha256
from sciplot_core.plot_engine.figure_updates import current_edit_value, figure_edit_descriptor
from sciplot_core.plot_engine.managed_resolution import resolve_science, resolved_metadata
from sciplot_core.plot_engine.managed_state import resolved_ir
from sciplot_core.plot_engine.managed_updates import prepare_update
from sciplot_core.plot_ir import create_managed_document
from sciplot_core.plot_ir.figure_document import figure_spec, store_spec


LAYERS = ['layer:curve:1', 'layer:curve:2', 'layer:curve:3']


def legend_request(tmp_path):
    request = request_for_figure(tmp_path)
    request.update(rule_id='ordinary_xy', idempotency_key='create-three-original-curves')
    source = request['data_binding']['data_sources'][0]
    path = tmp_path / 'figure.csv'
    path.write_text('Frequency,Modulus,Modulus,Modulus\nHz,Pa,Pa,Pa\n1,2,3,4\n2,4,5,6\n3,6,7,8\n')
    source['sha256'] = file_sha256(path)
    spec = request['template_definition']['figure_spec']
    prototype = spec['views'][0]['layers'][0]
    layers, slots = [], {}
    for index, identifier in enumerate(LAYERS):
        layer = deepcopy(prototype)
        layer.update(id=identifier, mappings={'x': 'column:0', 'y': f'column:{index+1}'},
                     label=f'Curve {index+1}', legend={'visible': True, 'label': f'Curve {index+1}'}, z_order=index)
        for position, mark in enumerate(layer['marks']):
            mark['id'] = f'{identifier}:mark:{position}'
        layers.append(layer)
        slots[identifier] = {'series_id': identifier, 'sample': f'Original response {index+1}',
            'x': {'source_id': 'raw:A', 'column': 'Frequency', 'column_index': 0},
            'y': {'source_id': 'raw:A', 'column': 'Modulus', 'column_index': index+1}, 'x_unit': 'Hz', 'y_unit': 'Pa'}
    spec['views'][0]['layers'] = layers
    spec['guides'][0].update(layer_ids=[], order=[], labels={})
    request['data_binding']['slots'] = slots
    return request


def legend_document(tmp_path):
    request = legend_request(tmp_path)
    document = create_managed_document(request['template_definition'], request['data_binding'], plot_id='same-ordered-plot')
    document = resolved_metadata(document, rule_id=request['rule_id'], executors={})
    return resolve_science(tmp_path / 'store', document)[0]


def order_patch(document, order, *, key='order-legend', target='guide:legend'):
    return {'plot_id': document['plot_id'], 'base_revision': document['revision'], 'idempotency_key': key,
        'intent_class': 'presentation', 'changes': [{'op': 'set', 'target': [target], 'property': 'legend.order', 'value': order}]}


def test_full_summary_and_selective_wire_contract_expose_complete_order_and_current_value(tmp_path, monkeypatch):
    from test_managed_description_scopes import _service
    from sciplot_core.plot_engine import service as service_module
    from sciplot_core.plot_protocol import rpc

    document = legend_document(tmp_path)
    description_root = tmp_path / 'description-fixture'
    description_root.mkdir()
    service, root, _original = _service(description_root, monkeypatch)
    service_module.load_head(root)['document'] = document
    full = service.describe(root)
    summary = service.describe(root, description={'scope': 'summary'})
    edit = service.describe(root, description={'scope': 'edit', 'target': 'guide:legend', 'property': 'legend.order'})
    descriptor = full['figure_edit_contract']['guide:legend']['legend.order']
    assert descriptor['risk'] == 'review' and descriptor['value_schema']['items']['enum'] == LAYERS
    assert 'legend.order' in summary['edit_targets']['guide:legend']['properties']
    assert all(summary['edit_targets'][identifier]['label'] == f'Curve {index+1}' for index, identifier in enumerate(LAYERS))
    assert edit['figure_edit_contract'] == {'guide:legend': {'legend.order': descriptor}}
    assert edit['current_value'] == [] and edit['next_step']['intent_class'] == 'review'
    decoded = json.loads(rpc.encode({'jsonrpc': '2.0', 'id': 'legend-order', 'result': edit}))
    assert decoded['result'] == edit
    ordered, _, _, _ = prepare_update(document, order_patch(document, list(reversed(LAYERS))))
    service_module.load_head(root)['document'] = ordered
    current = service.describe(root, description={'scope': 'edit', 'target': 'guide:legend', 'property': 'legend.order'})
    assert current['current_value'] == list(reversed(LAYERS))
    assert set(current['figure_edit_contract']['guide:legend']['legend.order']['value_schema']['items']['enum']) == set(LAYERS)


def test_order_hide_show_and_automatic_reset_change_presentation_without_scientific_execution(tmp_path):
    document = legend_document(tmp_path)
    original = deepcopy(document)
    before = resolved_ir(tmp_path / 'store', document)
    ordered, diff, risk, execute = prepare_update(document, order_patch(document, [LAYERS[2], LAYERS[1], LAYERS[0]]))
    assert risk == 'review' and not execute and diff[0]['before'] == []
    assert ordered['scientific_hash'] == document['scientific_hash'] and ordered['presentation_hash'] != document['presentation_hash']
    assert current_edit_value(figure_spec(ordered), 'guide:legend', 'legend.order') == [LAYERS[2], LAYERS[1], LAYERS[0]]
    assert [entry['layer_id'] for entry in resolved_ir(tmp_path / 'store', ordered)['guides'][0]['entries']] == [LAYERS[2], LAYERS[1], LAYERS[0]]
    hidden, _, _, _ = prepare_update(ordered, {'plot_id': ordered['plot_id'], 'base_revision': ordered['revision'],
        'idempotency_key': 'hide-middle', 'intent_class': 'presentation', 'changes': [{'op': 'set', 'target': [LAYERS[1]],
        'property': 'series.visible', 'value': False}]})
    assert [entry['layer_id'] for entry in resolved_ir(tmp_path / 'store', hidden)['guides'][0]['entries']] == [LAYERS[2], LAYERS[0]]
    assert figure_edit_descriptor(figure_spec(hidden), 'guide:legend', 'legend.order')['value_schema']['items']['enum'] == [LAYERS[2], LAYERS[1], LAYERS[0]]
    with pytest.raises(ValueError) as omitted_hidden:
        prepare_update(hidden, order_patch(hidden, [LAYERS[2], LAYERS[0]], key='omit-hidden-member'))
    assert omitted_hidden.value.reason_code == 'figure_guide_order'
    shown, _, _, _ = prepare_update(hidden, {'plot_id': hidden['plot_id'], 'base_revision': hidden['revision'],
        'idempotency_key': 'show-middle', 'intent_class': 'presentation', 'changes': [{'op': 'set', 'target': [LAYERS[1]],
        'property': 'series.visible', 'value': True}]})
    assert [entry['layer_id'] for entry in resolved_ir(tmp_path / 'store', shown)['guides'][0]['entries']] == [LAYERS[2], LAYERS[1], LAYERS[0]]
    reset, _, reset_risk, execute = prepare_update(shown, order_patch(shown, [], key='automatic-order'))
    assert reset_risk == 'review' and not execute
    assert [entry['layer_id'] for entry in resolved_ir(tmp_path / 'store', reset)['guides'][0]['entries']] == LAYERS
    assert resolved_ir(tmp_path / 'store', reset)['datasets'] == before['datasets']
    assert reset['scientific_hash'] == document['scientific_hash'] and document == original


@pytest.mark.parametrize('order,code', [([LAYERS[0]], 'figure_guide_order'),
    ([LAYERS[0], LAYERS[0], LAYERS[2]], 'figure_edit_invalid_value'),
    ([LAYERS[0], 'layer:unknown', LAYERS[2]], 'figure_edit_invalid_value'),
    (['Curve 3', 'Curve 2', 'Curve 1'], 'figure_edit_invalid_value'),
    ('layer:curve:1', 'figure_edit_invalid_value')])
def test_order_rejects_omitted_duplicate_unknown_label_or_wrong_type_atomically(tmp_path, order, code):
    document = legend_document(tmp_path)
    original = deepcopy(document)
    with pytest.raises(ValueError) as error:
        prepare_update(document, order_patch(document, order))
    assert error.value.reason_code == code and document == original


def test_order_targets_only_the_guides_selected_scope_and_retains_empty_reset(tmp_path):
    document = legend_document(tmp_path)
    spec = figure_spec(document)
    spec['guides'][0]['layer_ids'] = [LAYERS[0], LAYERS[2]]
    document = store_spec(document, spec)
    schema = figure_edit_descriptor(spec, 'guide:legend', 'legend.order')['value_schema']
    assert schema['items']['enum'] == [LAYERS[0], LAYERS[2]]
    with pytest.raises(ValueError) as scope_error:
        prepare_update(document, order_patch(document, [LAYERS[1], LAYERS[0], LAYERS[2]]))
    assert scope_error.value.reason_code == 'figure_edit_invalid_value'
    with pytest.raises(ValueError) as target_error:
        prepare_update(document, order_patch(document, LAYERS, target='view:A'))
    assert target_error.value.reason_code == 'document_unknown_target'
    candidate, _, _, _ = prepare_update(document, order_patch(document, [LAYERS[2], LAYERS[0]]))
    assert [entry['layer_id'] for entry in resolved_ir(tmp_path / 'store', candidate)['guides'][0]['entries']] == [LAYERS[2], LAYERS[0]]
    reset, _, _, _ = prepare_update(candidate, order_patch(candidate, []))
    assert [entry['layer_id'] for entry in resolved_ir(tmp_path / 'store', reset)['guides'][0]['entries']] == [LAYERS[0], LAYERS[2]]


def test_review_reject_accept_and_cold_service_replay_use_existing_transaction_owner(tmp_path):
    from test_managed_rollback import ManagedFixtureBackend
    from sciplot_core.plot_engine.service import PlotService
    from sciplot_core.plot_engine.storage import commit, load_head

    document = legend_document(tmp_path)
    backend = ManagedFixtureBackend(tmp_path / 'fake-native')
    _fake, binding = backend.initial()
    root = tmp_path / 'saved-plot'
    commit(root, document, binding, 'initial')
    service = PlotService(backend)
    before = load_head(root)
    rejected_request = order_patch(document, list(reversed(LAYERS)), key='reject-order')
    pending = service.patch(root, rejected_request)
    assert pending['status'] == 'needs_review' and pending['effective_risk'] == 'review' and load_head(root) == before
    assert service.patch(root, rejected_request)['decision_id'] == pending['decision_id']
    rejected = service.decide(root, {**pending['next_step']['request'], 'accept': False})
    assert rejected['status'] == 'rejected' and load_head(root) == before and backend.calls['apply'] == 0
    assert service.patch(root, rejected_request)['status'] == 'rejected'
    accepted_request = order_patch(document, list(reversed(LAYERS)), key='accept-order')
    preview = service.patch(root, accepted_request)
    accepted = service.decide(root, preview['next_step']['request'])
    assert accepted['ready_to_use'] and accepted['revision'] == 1
    current = load_head(root)
    assert current['document']['scientific_hash'] == before['document']['scientific_hash']
    cold = PlotService(backend)
    replay = cold.patch(root, accepted_request)
    assert replay['replayed'] and replay['ready_to_use'] and backend.calls['apply'] == 1
    assert load_head(root) == current


def test_view_legend_order_cannot_name_another_views_layer(tmp_path):
    document = legend_document(tmp_path)
    spec = figure_spec(document)
    other = deepcopy(spec['views'][0])
    other.update(id='view:B', layers=[other['layers'][2]])
    spec['views'][0]['layers'] = spec['views'][0]['layers'][:2]
    for axis, scale in zip(other['axes'], spec['scales'][:2], strict=True):
        projected = deepcopy(scale)
        projected['id'] += ':B'
        spec['scales'].append(projected)
        axis['id'] += ':B'
        axis['scale_id'] = projected['id']
        other['layers'][0][scale['dimension'] + '_scale'] = projected['id']
    spec['views'].append(other)
    spec['composition'].update(kind='hconcat', columns=2, column_weights=[1, 1], cells=[
        {'view_id': 'view:A', 'row': 0, 'column': 0, 'row_span': 1, 'column_span': 1},
        {'view_id': 'view:B', 'row': 0, 'column': 1, 'row_span': 1, 'column_span': 1}])
    document = store_spec(document, spec)
    descriptor = figure_edit_descriptor(spec, 'guide:legend', 'legend.order')
    assert descriptor['value_schema']['items']['enum'] == LAYERS[:2]
    with pytest.raises(ValueError) as error:
        prepare_update(document, order_patch(document, [LAYERS[2], LAYERS[0], LAYERS[1]]))
    assert error.value.reason_code == 'figure_edit_invalid_value'


def test_empty_eligible_legend_has_a_valid_reset_only_descriptor(tmp_path):
    from jsonschema import Draft202012Validator

    document = legend_document(tmp_path)
    spec = figure_spec(document)
    for layer in spec['views'][0]['layers']:
        layer['legend']['visible'] = False
    spec['guides'][0]['visible'] = False
    document = store_spec(document, spec)
    schema = figure_edit_descriptor(figure_spec(document), 'guide:legend', 'legend.order')['value_schema']
    Draft202012Validator.check_schema(schema)
    assert Draft202012Validator(schema).is_valid([])
    assert not Draft202012Validator(schema).is_valid([LAYERS[0]])
