"""Generated original-table appends retain one Managed scientific authority."""

from copy import deepcopy
from pathlib import Path

import pytest
from test_figure_document import request_for_figure

from sciplot_core.foundation.file_hashing import file_sha256
from sciplot_core.plot_document import seal_document
from sciplot_core.plot_engine.content_store import resolve_document_content
from sciplot_core.plot_engine.errors import EngineError
from sciplot_core.plot_engine.managed_resolution import resolve_science, resolved_metadata
from sciplot_core.plot_engine.managed_source_append import append_descriptor, append_targets
from sciplot_core.plot_engine.managed_state import resolved_ir
from sciplot_core.plot_engine.managed_updates import prepare_update
from sciplot_core.plot_ir import create_managed_document
from sciplot_core.plot_ir.figure_document import figure_spec, store_spec


def bound_document(tmp_path):
    request = request_for_figure(tmp_path)
    document = create_managed_document(request['template_definition'], request['data_binding'], plot_id='same-original-plot')
    document = resolved_metadata(document, rule_id=request['rule_id'], executors={})
    document, _ = resolve_science(tmp_path / 'store', document)
    return document


def append_request(document, tmp_path, name='B', *, samples=True):
    path = tmp_path / f'{name}.csv'
    # Non-numeric notes, duplicate/decreasing coordinates and a missing value
    # distinguish original column selection from a new synthetic/reordered plot.
    metadata = f'{name},{name},\n' if samples else ''
    path.write_text('Frequency,Modulus,Note\nHz,Pa,\n' + metadata +
                    '8,7,first\n5,,missing\n5,3,duplicate\n2,9,last\n')
    start = 3 if samples else 2
    source = {'source_id': f'raw:{name}', 'path': str(path), 'sha256': file_sha256(path),
              'table_selection': {'sheet': None, 'header_rows': [0], 'unit_row': 1,
                                  'data_start_row': start, 'data_end_row': start + 4}}
    if samples:
        source['table_selection']['sample_row'] = 2
    return {'plot_id': document['plot_id'], 'base_revision': document['revision'], 'idempotency_key': f'append-{name}',
            'intent_class': 'scientific', 'changes': [{'op': 'set', 'target': ['view:A'], 'property': 'source.append',
            'value': {'source': source, 'curves': [{'sample': name, 'x_column_index': 0, 'y_column_index': 1,
                      'label': f'Cooling {name}', 'color': '#cc3300', 'line_width_pt': 1.3}],
                      'source_context': 'User states this file is a cooling acquisition; preserve original observations.'}}]}


def _scientific_observation_case(tmp_path, operation='append'):
    from sciplot_core.plot_engine.current_unit_admission import prepare_current_update
    from sciplot_core.plot_engine.managed_state import make_binding, scientific_binding

    original = bound_document(tmp_path)
    root = tmp_path / 'store'
    binding = make_binding(root, original, output=tmp_path / 'output')
    if operation == 'append':
        request = append_request(original, tmp_path)
    else:
        source = original['scientific']['data_sources'][0]
        path = Path(source['path'])
        path.write_text(path.read_text().replace('5,5', '5,9'))
        request = {'plot_id': original['plot_id'], 'base_revision': original['revision'],
            'idempotency_key': 'reconfirm-A', 'intent_class': 'scientific', 'changes': [{'op': 'set',
            'target': ['source:' + source['source_id']], 'property': 'source.sha256', 'value': file_sha256(path)}]}
    candidate, diff, _risk, scientific = prepare_current_update(root, original, request)
    assert scientific and diff
    return original, binding, candidate, scientific_binding(binding, candidate)


@pytest.mark.parametrize('operation', ['append', 'source-refresh'])
def test_scientific_input_observation_uses_acknowledged_document_without_rebinding_native(tmp_path, operation):
    from sciplot_core.plot_engine.current import changed_inputs
    from sciplot_core.plot_engine.managed_backend import ManagedBackend
    from sciplot_core.plot_engine.managed_state import declared_host_files, read_canonical, require_inputs

    original, binding, candidate, guarded = _scientific_observation_case(tmp_path, operation)
    before = deepcopy((original, binding, candidate, guarded))
    backend = ManagedBackend.__new__(ManagedBackend)
    if operation == 'append':
        added = set(guarded['fingerprint']['files']) - set(binding['fingerprint']['files'])
        assert candidate['scientific']['data_sources'][-1]['path'] in added
        assert set(declared_host_files(candidate)) - set(declared_host_files(original))
        assert added <= set(changed_inputs(backend, guarded))  # Missing context stays fail-closed.
    else:
        with pytest.raises(EngineError) as error:
            require_inputs(original)
        assert error.value.reason_code == 'managed_inputs_changed'
    assert changed_inputs(backend, guarded, input_document=candidate) == []
    assert read_canonical(guarded) == original
    assert {key: guarded[key] for key in ('canonical_document', 'canonical_sha256', 'ir_path', 'ir_hash', 'document')} == {
        key: binding[key] for key in ('canonical_document', 'canonical_sha256', 'ir_path', 'ir_hash', 'document')}
    assert (original, binding, candidate, guarded) == before


@pytest.mark.parametrize('fault', ['unacknowledged-inputs', 'foreign-plot'])
def test_input_observation_context_cannot_authorize_another_input_closure(tmp_path, monkeypatch, fault):
    from sciplot_core.plot_engine import managed_backend

    original, _binding, candidate, guarded = _scientific_observation_case(tmp_path)
    context = original if fault == 'unacknowledged-inputs' else seal_document({**candidate, 'plot_id': 'foreign-plot'})
    monkeypatch.setattr(managed_backend, 'existing_file_sha256',
        lambda _path: pytest.fail('Unbound input roles reached file IO'))
    with pytest.raises(EngineError) as error:
        managed_backend.ManagedBackend.__new__(managed_backend.ManagedBackend).fingerprint(guarded, input_document=context)
    assert error.value.reason_code == 'managed_input_context_conflict'


def test_acknowledged_input_context_does_not_grant_refused_source_io(tmp_path):
    from sciplot_core.foundation.source_locations import source_location_scope
    from sciplot_core.plot_engine.current import changed_inputs
    from sciplot_core.plot_engine.managed_backend import ManagedBackend

    _original, _binding, candidate, guarded = _scientific_observation_case(tmp_path)
    appended = candidate['scientific']['data_sources'][-1]
    calls = []

    class Selected:
        def resolve_path(self, original, *, expected_sha256=None, source_id=None):
            calls.append((str(original), expected_sha256, source_id))
            if source_id == appended['source_id']:
                raise ValueError('This selected runtime does not authorize the appended source')
            return Path(original)

        def literal_path(self, actual):
            pytest.fail('Declared source roles are not reverse IO requests')

    before = deepcopy((candidate, guarded))
    with source_location_scope(Selected()), pytest.raises(ValueError, match='does not authorize'):
        changed_inputs(ManagedBackend.__new__(ManagedBackend), guarded, input_document=candidate)
    assert (appended['path'], appended['sha256'], appended['source_id']) in calls
    assert (candidate, guarded) == before


def test_candidate_input_context_keeps_original_native_mutation_guard(tmp_path):
    from sciplot_core.plot_engine.current import changed_inputs
    from sciplot_core.plot_engine.managed_backend import ManagedBackend
    from sciplot_core.plot_engine.storage import write

    _original, _binding, candidate, guarded = _scientific_observation_case(tmp_path)
    native = Path(guarded['document'])
    native.parent.mkdir(parents=True)
    native.write_bytes(b'original generated artifact, not a native scientific acceptance')
    write(native.parent / 'build.json', {'ir_hash': guarded['ir_hash'], 'document_sha256': file_sha256(native)})
    backend = ManagedBackend.__new__(ManagedBackend)
    assert changed_inputs(backend, guarded, input_document=candidate) == []
    native.write_bytes(native.read_bytes() + b' external mutation')
    assert changed_inputs(backend, guarded, input_document=candidate) == [str(native)]


def test_append_extends_source_bound_graph_without_changing_original_plot_or_presentation(tmp_path):
    document = bound_document(tmp_path)
    spec = figure_spec(document)
    old = spec['views'][0]['layers'][0]
    old['label'] = old['legend']['label'] = 'Original custom alias'
    old['marks'][0]['style'] = {'line_color': '#2277aa', 'line_width_pt': 1.8}
    spec['views'][0]['axes'][0]['label'] = 'Custom frequency display'
    spec['guides'][0]['labels'][old['id']] = 'Original legend alias'
    spec['guides'][0]['location'] = 'bottom-left'
    document = store_spec(document, spec)
    original = deepcopy(document)
    before = resolved_ir(tmp_path / 'store', document)
    request = append_request(document, tmp_path)
    source = Path(request['changes'][0]['value']['source']['path'])
    source_bytes = source.read_bytes()
    candidate, diff, risk, execute = prepare_update(document, request)
    assert risk == 'review' and execute and diff[0]['risk'] == 'scientific'
    assert document == original and candidate['plot_id'] == document['plot_id']
    assert candidate['scientific']['data_sources'][:-1] == document['scientific']['data_sources']
    for name, mapping in document['scientific']['mappings'].items():
        assert candidate['scientific']['mappings'][name] == mapping
    candidate, resolution = resolve_science(tmp_path / 'store', candidate)
    after = resolved_ir(tmp_path / 'store', candidate)
    new_id = diff[0]['after']['layer_ids'][0]
    layer = figure_spec(candidate)['views'][0]['layers'][-1]
    assert layer['id'] == new_id and layer['legend']['label'] == 'Cooling B'
    assert layer['marks'][0]['style'] == {'line_color': '#cc3300', 'line_width_pt': 1.3}
    for name, dataset in before['datasets'].items():
        assert after['datasets'][name] == dataset
    assert after['datasets']['raw:B']['columns']['column:0']['values'] == [8, 5, 5, 2]
    assert after['datasets']['raw:B']['columns']['column:1']['values'] == [7, None, 3, 9]
    assert set(after['datasets']['raw:B']['columns']) == {'column:0', 'column:1'}
    assert after['datasets']['raw:B']['provenance']['sources'][0]['rows'] == [3, 4, 5, 6]
    assert len(after['datasets']['raw:A']['columns']['column:0']['values']) == 3
    assert len(after['datasets'][layer['dataset_id']]['columns']['column:0']['values']) == 4
    final = figure_spec(candidate)
    assert final['views'][0]['layers'][0] == old
    assert final['views'][0]['axes'] == spec['views'][0]['axes'] and final['scales'] == spec['scales']
    assert final['guides'][0]['labels'] == spec['guides'][0]['labels']
    assert final['guides'][0]['order'] == [old['id'], new_id]
    assert candidate['scientific_hash'] != document['scientific_hash']
    archived = candidate['scientific']['provenance']['source_appends'][0]
    assert archived['source_context'] == request['changes'][0]['value']['source_context']
    assert archived['source_id'] == 'raw:B' and archived['sha256'] == file_sha256(source)
    assert source.read_bytes() == source_bytes and resolution['executed']


@pytest.mark.parametrize('problem,code', [
    ('intent', 'managed_append_scientific_intent_required'),
    ('unit', 'managed_append_unit_conflict'),
    ('quantity', 'managed_append_quantity_conflict'),
    ('sample', 'managed_append_sample_conflict'),
    ('hash', 'managed_append_source_changed'),
    ('unknown', 'managed_append_invalid_value'),
    ('duplicate', 'managed_append_duplicate_curve'),
    ('bounds', 'managed_append_table_rejected'),
    ('same_source', 'managed_append_source_exists'),
    ('same_coordinate', 'managed_append_coordinate_conflict'),
    ('mixed', 'managed_append_atomic_scope'),
])
def test_append_rejects_ambiguous_or_changed_scientific_facts_atomically(tmp_path, problem, code):
    document = bound_document(tmp_path)
    request = append_request(document, tmp_path)
    value = request['changes'][0]['value']
    source = Path(value['source']['path'])
    if problem == 'intent':
        request['intent_class'] = 'presentation'
    elif problem in {'unit', 'quantity'}:
        source.write_text(source.read_text().replace('Hz,Pa,', 'Hz,MPa,') if problem == 'unit'
                          else source.read_text().replace('Frequency,Modulus,', 'Frequency,Temperature,'))
        value['source']['sha256'] = file_sha256(source)
    elif problem == 'sample':
        value['curves'][0]['sample'] = 'Invented sample'
    elif problem == 'hash':
        source.write_text(source.read_text().replace('8,7,', '8,6,'))
    elif problem == 'unknown':
        value['normalize'] = True
    elif problem == 'duplicate':
        value['curves'].append(deepcopy(value['curves'][0]))
    elif problem == 'bounds':
        value['source']['table_selection']['data_end_row'] = 100
    elif problem == 'same_source':
        value['source']['source_id'] = 'raw:A'
    elif problem == 'same_coordinate':
        value['curves'][0]['y_column_index'] = 0
    elif problem == 'mixed':
        request['changes'].append({'op': 'set', 'target': ['axis:xb'], 'property': 'axis.label', 'value': 'changed'})
    original = deepcopy(document)
    with pytest.raises(ValueError) as error:
        prepare_update(document, request)
    assert error.value.reason_code == code
    assert document == original


def test_absent_original_sample_requires_explicit_identity_and_keeps_source_facts(tmp_path):
    document = bound_document(tmp_path)
    request = append_request(document, tmp_path, samples=False)
    candidate, _, _, _ = prepare_update(document, request)
    candidate, _ = resolve_science(tmp_path / 'store', candidate)
    mapping = list(candidate['scientific']['mappings'].values())[-1]
    assert mapping['sample'] == 'B'
    request['changes'][0]['value']['curves'][0].pop('sample')
    with pytest.raises(ValueError) as error:
        prepare_update(document, request)
    assert error.value.reason_code == 'managed_append_invalid_value'


def test_sequential_appends_keep_all_prior_sources_datasets_and_context(tmp_path):
    document = bound_document(tmp_path)
    first, _, _, _ = prepare_update(document, append_request(document, tmp_path))
    first, _ = resolve_science(tmp_path / 'store', first)
    original = resolve_document_content(tmp_path / 'store', first)
    second, _, _, _ = prepare_update(first, append_request(first, tmp_path, 'C'))
    second, _ = resolve_science(tmp_path / 'store', second)
    final = resolve_document_content(tmp_path / 'store', second)
    assert [source['source_id'] for source in final['scientific']['data_sources']] == ['raw:A', 'raw:B', 'raw:C']
    assert len(figure_spec(final)['views'][0]['layers']) == 3
    for name, dataset in original['scientific']['provenance']['datasets'].items():
        assert final['scientific']['provenance']['datasets'][name] == dataset
    assert final['scientific']['provenance']['source_appends'][:1] == original['scientific']['provenance']['source_appends']


def test_append_edit_contract_is_closed_and_specific_to_eligible_managed_views(tmp_path, monkeypatch):
    from test_managed_description_scopes import _service
    from sciplot_core.project_lifecycle import application as service_module

    service, root, document = _service(tmp_path, monkeypatch)
    document = resolved_metadata(document, rule_id='uvvis_spectrum', executors={})
    service_module.load_head(root)['document'] = document
    full = service.describe(root)
    summary = service.describe(root, description={'scope': 'summary'})
    edit = service.describe(root, description={'scope': 'edit', 'target': 'view:A', 'property': 'source.append'})
    assert full['figure_edit_contract']['view:A']['source.append'] == append_descriptor()
    assert 'source.append' in summary['edit_targets']['view:A']['properties']
    assert edit['figure_edit_contract'] == {'view:A': {'source.append': append_descriptor()}}
    assert edit['next_step']['intent_class'] == 'scientific' and edit['current_value'] is None
    assert edit['target_context']['scales']['y']['quantity'] == 'modulus'
    assert edit['target_context']['sources'][0]['source_id'] == 'raw:A'
    assert all(shape['additionalProperties'] is False for shape in append_descriptor()['value_schema']['oneOf'])
    transformed = deepcopy(document)
    transformed['scientific']['transforms'] = [{'kind': 'normalize'}]
    assert append_targets(transformed) == {}
    spec = figure_spec(document)
    spec['scales'][0]['transform'] = 'symlog'
    assert append_targets(store_spec(document, spec)) == {}


def test_append_resolve_refuses_source_change_after_preparation(tmp_path):
    document = bound_document(tmp_path)
    request = append_request(document, tmp_path)
    candidate, _, _, _ = prepare_update(document, request)
    source = Path(request['changes'][0]['value']['source']['path'])
    source.write_text(source.read_text().replace('8,7,', '8,6,'))
    with pytest.raises(EngineError) as error:
        resolve_science(tmp_path / 'store', candidate)
    assert error.value.reason_code == 'managed_inputs_changed'


def test_append_keeps_original_revision_guard(tmp_path):
    document = bound_document(tmp_path)
    request = append_request(document, tmp_path)
    document['revision'] += 1
    document = seal_document(document)
    with pytest.raises(EngineError) as error:
        prepare_update(document, request)
    assert error.value.reason_code == 'document_revision_conflict'


def test_source_facts_clarification_allocates_no_transaction_and_same_key_can_continue(tmp_path, monkeypatch):
    from sciplot_core.project_lifecycle import application as service_module
    from sciplot_core.plot_engine.service import PlotService
    from sciplot_core.plot_engine.storage import transaction_path

    document = bound_document(tmp_path)
    complete = append_request(document, tmp_path)
    query = deepcopy(complete)
    query['changes'][0]['value'] = {'source': {key: complete['changes'][0]['value']['source'][key]
                                              for key in ('source_id', 'path')}}
    root = tmp_path / 'store'
    original = {str(path): file_sha256(path) for path in root.rglob('*') if path.is_file()}
    monkeypatch.setattr(service_module, 'load_head', lambda _: {'document': document, 'binding': {}})
    service = PlotService(backend=object())
    with pytest.raises(EngineError) as question:
        service._patch(root, query)
    assert question.value.reason_code == 'managed_append_source_confirmation_required'
    facts = question.value.repair
    assert facts['source_sha256'] == complete['changes'][0]['value']['source']['sha256']
    assert facts['next_step']['same_idempotency_key'] is True
    assert facts['next_step']['idempotency_key'] == complete['idempotency_key']
    assert facts['next_step']['required_fields']
    assert facts['candidates'][0]['columns'][0]['header'] == 'Frequency'
    assert 'values' not in str(facts['candidates']) and 'rows' not in facts['tables'][0]
    assert not transaction_path(root, complete['idempotency_key']).exists()
    assert {str(path): file_sha256(path) for path in root.rglob('*') if path.is_file()} == original
    candidate, diff, risk, execute = prepare_update(document, complete)
    assert diff and execute and risk == 'review' and candidate['plot_id'] == document['plot_id']
    bad = deepcopy(query)
    bad['changes'][0]['value']['source']['normalize'] = True
    with pytest.raises(ValueError) as error:
        prepare_update(document, bad)
    assert error.value.reason_code == 'managed_append_invalid_value'


@pytest.mark.parametrize('negative', [False, True])
def test_log_append_uses_existing_full_domain_validator_without_dropping_observations(tmp_path, negative):
    document = bound_document(tmp_path)
    spec = figure_spec(document)
    spec['scales'][1].update(transform='log', domain=[1, 20])
    spec['views'][0]['axes'][1]['ticks'] = [1, 10]
    document = store_spec(document, spec)
    assert 'view:A' in append_targets(document)
    original = deepcopy(document)
    request = append_request(document, tmp_path)
    if negative:
        source = Path(request['changes'][0]['value']['source']['path'])
        source.write_text(source.read_text().replace('8,7,', '8,-7,'))
        request['changes'][0]['value']['source']['sha256'] = file_sha256(source)
    candidate, _, _, _ = prepare_update(document, request)
    candidate, _ = resolve_science(tmp_path / 'store', candidate)
    if negative:
        with pytest.raises(ValueError) as error:
            resolved_ir(tmp_path / 'store', candidate)
        assert error.value.reason_code == 'figure_log_data_domain'
    else:
        ir = resolved_ir(tmp_path / 'store', candidate)
        assert ir['datasets']['raw:B']['columns']['column:1']['values'] == [7, None, 3, 9]
        assert ir['scales'][1]['transform'] == 'log'
    assert document == original
