"""Continue exact independently parsed Tests in the same original Managed plot."""

from copy import deepcopy
import csv
import io
import struct

import pytest
from test_figure_document import request_for_figure
from test_instrument_source_regions import instrument

from sciplot_core.foundation.file_hashing import file_sha256
from sciplot_core.plot_engine.managed_resolution import resolve_science, resolved_metadata
from sciplot_core.plot_engine.managed_state import resolved_ir
from sciplot_core.plot_engine.managed_updates import prepare_update
from sciplot_core.plot_ir import create_managed_document
from sciplot_core.plot_ir.figure_document import figure_spec
from sciplot_core.plot_transforms import builtin_executor
from sciplot_core.source_inspection.semantic_evidence import inspect_semantic_tables


def bound_tests(tmp_path, *, two_storage_columns=False):
    path = tmp_path / 'independent-tests.csv'
    rows, facts = instrument(path, (4, 3, 5, 2), missing_tail=True)
    if two_storage_columns:
        for fact in facts:
            rows[fact['header_row']][5] = 'Storage Modulus'
        stream = io.StringIO()
        csv.writer(stream, delimiter='\t', lineterminator='\n').writerows(rows)
        path.write_text(stream.getvalue(), encoding='utf-16')
    observed = inspect_semantic_tables(path)
    blocks = observed['candidates'][0]['blocks']
    request = request_for_figure(tmp_path)
    spec = request['template_definition']['figure_spec']
    # The four-entry legend needs 21.24 mm including its guard margin; the
    # inherited 35 mm cell has only 18.5 mm of plot height. Keep layout policy
    # fixed during append by establishing a 45 mm cell (28.5 mm plot) up front.
    spec['layout']['panel_min_height_mm'] = 45
    spec['scales'][0].update(quantity='temperature', unit='°C', domain=[270, 285])
    spec['scales'][1].update(quantity='storage_modulus', unit='Pa', transform='log', domain=[1, 1000])
    spec['views'][0]['axes'][0].update(label='Measured temperature (°C)', ticks=[270, 275, 280, 285])
    spec['views'][0]['axes'][1].update(label='Original storage modulus (Pa)', ticks=[1, 10, 100, 1000])
    prototype = spec['views'][0]['layers'][0]
    layers, sources, slots, transforms = [], [], {}, []
    executor = builtin_executor()
    for index in (0, 1, 3):
        block = blocks[index]
        source_id, output = f'raw:test:{index}', f'original:{index}'
        sources.append({'source_id': source_id, 'path': str(path), 'sha256': observed['sha256'],
                        'table_selection': block['table_selection']})
        nodes = [('select', {'columns': ['column:3', 'column:4']}),
                 ('rename', {'columns': {'column:3': {'id': 'x', 'label': 'Temperature'},
                                        'column:4': {'id': 'y', 'label': 'Storage Modulus'}}}),
                 ('convert_unit', {'columns': ['x'], 'from_unit': '[°C]', 'to_unit': '°C'}),
                 ('convert_unit', {'columns': ['y'], 'from_unit': '[Pa]', 'to_unit': 'Pa'})]
        for position, (kind, parameters) in enumerate(nodes):
            target = f'{output}:{position}'
            transforms.append({'id': target, 'kind': kind, 'inputs': [source_id if position == 0 else f'{output}:{position-1}'],
                'output': target, 'parameters': parameters, 'executor': executor, 'determinism': 'deterministic'})
        identifier = f'layer:original:{index}'
        layer = deepcopy(prototype)
        layer.update(id=identifier, dataset_id=f'{output}:3', mappings={'x': 'x', 'y': 'y'},
                     mapping_semantics={'x': 'temperature', 'y': 'storage_modulus'}, label=block['test_name'],
                     legend={'visible': True, 'label': block['test_name']}, z_order=index)
        for position, mark in enumerate(layer['marks']):
            mark['id'] = f'{identifier}:mark:{position}'
        layer['marks'][0]['style'] = {'line_color': '#2277aa', 'line_width_pt': 1.7}
        layers.append(layer)
        slots[identifier] = {'series_id': identifier, 'sample': block['test_name'],
            'x': {'source_id': f'{output}:3', 'column': 'x'}, 'y': {'source_id': f'{output}:3', 'column': 'y'},
            'x_unit': '°C', 'y_unit': 'Pa'}
    spec['views'][0]['layers'] = layers
    spec['guides'][0].update(layer_ids=[layer['id'] for layer in layers], order=[layer['id'] for layer in layers],
                             labels={}, location='top-left')
    binding = request['data_binding']
    binding.update(data_sources=sources, slots=slots, transforms=transforms)
    document = create_managed_document(request['template_definition'], binding, plot_id='same-original-tests')
    document = resolved_metadata(document, rule_id='ordinary_xy', executors={})
    document, _ = resolve_science(tmp_path / 'store', document)
    return document, path, blocks, facts


def append_test(document, path, block):
    return {'plot_id': document['plot_id'], 'base_revision': document['revision'], 'idempotency_key': 'append-independent-test',
        'intent_class': 'scientific', 'changes': [{'op': 'set', 'target': ['view:A'], 'property': 'source.append',
            'value': {'source': {'source_id': 'raw:new-test', 'path': str(path), 'sha256': file_sha256(path),
                                 'table_selection': deepcopy(block['table_selection'])},
                      'curves': [{'sample': block['test_name'], 'x_column_index': 3, 'y_column_index': 4,
                                  'label': 'New original Test display alias', 'color': '#009e73', 'line_width_pt': 1.5}]}}]}


def _bits(values):
    return [None if value is None else struct.pack('!d', value) for value in values]


def test_same_file_independent_test_append_exposes_all_facts_and_preserves_old_rows_units_and_presentation(tmp_path):
    document, path, blocks, facts = bound_tests(tmp_path)
    original, before_spec = deepcopy(document), figure_spec(document)
    raw_bytes = path.read_bytes()
    before = resolved_ir(tmp_path / 'store', document)
    request = append_test(document, path, blocks[2])
    query = deepcopy(request)
    query['changes'][0]['value'] = {'source': {key: request['changes'][0]['value']['source'][key] for key in ('source_id', 'path')}}
    with pytest.raises(ValueError) as question:
        prepare_update(document, query)
    assert question.value.reason_code == 'managed_append_source_confirmation_required'
    candidates = question.value.repair['candidates']
    assert [item['test_name'] for item in candidates] == [block['test_name'] for block in blocks]
    assert [item['block_id'] for item in candidates] == [block['block_id'] for block in blocks]
    assert [item['table_selection'] for item in candidates] == [block['table_selection'] for block in blocks]
    assert len({tuple(item['table_selection']['header_rows']) for item in candidates}) == 4
    assert 'values' not in str(candidates) and question.value.repair['next_step']['same_idempotency_key']
    candidate, diff, risk, execute = prepare_update(document, request)
    assert risk == 'review' and execute and candidate['plot_id'] == document['plot_id']
    proof = diff[0]['after']['physical_region']
    assert proof['block_id'] == blocks[2]['block_id'] and proof['test_name'] == blocks[2]['test_name']
    assert proof['source_sha256'] == file_sha256(path) and proof['table_selection'] == blocks[2]['table_selection']
    source = candidate['scientific']['data_sources'][-1]
    assert {item['field'] for item in source['metadata_confirmations']} == {'sample'}
    assert {item['column_index'] for item in source['metadata_confirmations']} == {3, 4}
    assert all(item['value'] == blocks[2]['test_name'] and item['evidence']['row_index'] == blocks[2]['test_row']
               and item['evidence']['kind'] == 'source_cell' for item in source['metadata_confirmations'])
    candidate, _ = resolve_science(tmp_path / 'store', candidate)
    after = resolved_ir(tmp_path / 'store', candidate)
    for name, dataset in before['datasets'].items():
        assert after['datasets'][name] == dataset
    new_layer = after['views'][0]['layers'][-1]
    measured = after['datasets'][new_layer['dataset_id']]['columns']
    assert _bits(measured['column:3']['values']) == _bits([point[0] for point in facts[2]['points']])
    assert _bits(measured['column:4']['values']) == _bits([point[1] for point in facts[2]['points']])
    assert len(measured['column:4']['values']) == 5 and measured['column:4']['values'][-1] is None
    assert after['datasets']['raw:new-test']['provenance']['sources'][0]['rows'] == list(range(facts[2]['data_start_row'], facts[2]['data_end_row']))
    final = figure_spec(candidate)
    assert final['views'][0]['layers'][:-1] == before_spec['views'][0]['layers']
    assert final['views'][0]['axes'] == before_spec['views'][0]['axes'] and final['scales'] == before_spec['scales']
    assert candidate['scientific']['provenance']['source_appends'][-1]['physical_region'] == proof
    # The existing following display transaction hides the old Test, retaining
    # its complete source-bound science and every raw/derived dataset.
    hidden, _, _, rerun = prepare_update(candidate, {'plot_id': candidate['plot_id'], 'base_revision': candidate['revision'],
        'idempotency_key': 'hide-original-test', 'intent_class': 'presentation', 'changes': [{'op': 'set',
        'target': ['layer:original:1'], 'property': 'series.visible', 'value': False}]})
    assert not rerun and hidden['scientific_hash'] == candidate['scientific_hash']
    assert resolved_ir(tmp_path / 'store', hidden)['datasets'] == after['datasets']
    assert figure_spec(hidden)['views'][0]['layers'][1]['visible'] is False
    assert document == original and path.read_bytes() == raw_bytes


@pytest.mark.parametrize('problem,code', [('sample', 'managed_append_sample_conflict'), ('partial', 'managed_append_region_conflict'),
    ('start', 'managed_append_region_conflict'), ('header', 'managed_append_region_conflict'),
    ('cross_test', 'managed_append_region_conflict'), ('hash', 'managed_append_source_changed'),
    ('sample_confirmation', 'managed_append_metadata_conflict')])
def test_unconfirmed_or_misidentified_test_regions_cannot_replace_same_file_guards(tmp_path, problem, code):
    document, path, blocks, _facts = bound_tests(tmp_path)
    request = append_test(document, path, blocks[2])
    value = request['changes'][0]['value']
    if problem == 'sample':
        value['curves'][0]['sample'] = 'Invented identity'
    elif problem == 'partial':
        value['source']['table_selection']['data_end_row'] -= 1
    elif problem == 'start':
        value['source']['table_selection']['data_start_row'] += 1
    elif problem == 'header':
        value['source']['table_selection']['header_rows'] = blocks[0]['table_selection']['header_rows']
    elif problem == 'cross_test':
        value['source']['table_selection']['data_end_row'] = blocks[3]['data_end_row']
    elif problem == 'hash':
        value['source']['sha256'] = '0' * 64
    else:
        value['source']['metadata_confirmations'] = [{'source_sha256': file_sha256(path), 'sheet': None,
            'column_index': 4, 'field': 'sample', 'value': 'Other sample',
            'evidence': {'kind': 'user_statement', 'asserted_by': 'control', 'statement': 'Contradict the original Test'}}]
    original = deepcopy(document)
    with pytest.raises(ValueError) as error:
        prepare_update(document, request)
    assert error.value.reason_code == code
    assert document == original


def test_previously_bound_response_is_still_duplicate_after_hiding_and_unit_rename_lineage(tmp_path):
    document, path, blocks, _facts = bound_tests(tmp_path)
    document, _, _, _ = prepare_update(document, {'plot_id': document['plot_id'], 'base_revision': document['revision'],
        'idempotency_key': 'hide-before-duplicate', 'intent_class': 'presentation', 'changes': [{'op': 'set',
        'target': ['layer:original:1'], 'property': 'series.visible', 'value': False}]})
    request = append_test(document, path, blocks[1])
    with pytest.raises(ValueError) as error:
        prepare_update(document, request)
    assert error.value.reason_code == 'managed_append_duplicate_measurement'


def test_ambiguous_shared_block_proof_never_grants_new_same_file_permission(tmp_path, monkeypatch):
    from sciplot_core.plot_engine import append_source_regions

    document, path, blocks, _facts = bound_tests(tmp_path)
    observer = append_source_regions._physical_candidates

    def ambiguous(snapshot, sheet):
        candidates = observer(snapshot, sheet)
        candidates[0]['blocks'].append(deepcopy(candidates[0]['blocks'][2]))
        return candidates

    monkeypatch.setattr(append_source_regions, '_physical_candidates', ambiguous)
    with pytest.raises(ValueError) as error:
        prepare_update(document, append_test(document, path, blocks[2]))
    assert error.value.reason_code == 'managed_append_region_conflict'


def test_explicit_ordinary_same_region_unused_response_survives_unrelated_discovery_ambiguity(tmp_path):
    from sciplot_core.source_inspection.input_errors import SourceInputError

    request = request_for_figure(tmp_path)
    source = request['data_binding']['data_sources'][0]
    path = tmp_path / 'two-explicit-tables.csv'
    path.write_text('Frequency,Modulus,Modulus\nHz,Pa,Pa\n1,2,3\n2,4,5\n3,6,7\n\nFrequency,Modulus,Modulus\nHz,Pa,Pa\n4,8,9\n')
    source.update(path=str(path), sha256=file_sha256(path))
    document = create_managed_document(request['template_definition'], request['data_binding'], plot_id='ordinary-explicit')
    document = resolved_metadata(document, rule_id='ordinary_xy', executors={})
    document, _ = resolve_science(tmp_path / 'store', document)
    with pytest.raises(SourceInputError) as question:
        inspect_semantic_tables(path)
    assert question.value.reason_code == 'semantic_table_region_ambiguous'
    append = {'plot_id': document['plot_id'], 'base_revision': document['revision'], 'idempotency_key': 'old-explicit-route',
        'intent_class': 'scientific', 'changes': [{'op': 'set', 'target': ['view:A'], 'property': 'source.append',
        'value': {'source': {**source, 'source_id': 'raw:unused-response'}, 'curves': [
            {'sample': 'Declared independent response', 'x_column_index': 0, 'y_column_index': 2}]}}]}
    candidate, diff, _, _ = prepare_update(document, append)
    assert 'physical_region' not in diff[0]['after']
    candidate, _ = resolve_science(tmp_path / 'store', candidate)
    ir = resolved_ir(tmp_path / 'store', candidate)
    assert ir['datasets']['raw:unused-response']['columns']['column:2']['values'] == [3, 5, 7]


def test_recognized_unsupported_instrument_never_uses_the_ordinary_explicit_fallback(tmp_path):
    from sciplot_core.source_inspection.input_errors import SourceInputError

    request = request_for_figure(tmp_path)
    source = request['data_binding']['data_sources'][0]
    path = tmp_path / 'unsupported-instrument.csv'
    path.write_text('Frequency,Modulus,Modulus\nHz,Pa,Pa\n1,2,3\n2,4,5\n3,6,7\n\nTest:,Literal Test\nUnsupported interval:,1\n')
    source.update(path=str(path), sha256=file_sha256(path))
    document = create_managed_document(request['template_definition'], request['data_binding'], plot_id='explicit-refusal')
    document = resolved_metadata(document, rule_id='ordinary_xy', executors={})
    document, _ = resolve_science(tmp_path / 'store', document)
    append = {'plot_id': document['plot_id'], 'base_revision': document['revision'], 'idempotency_key': 'unsupported-layout',
        'intent_class': 'scientific', 'changes': [{'op': 'set', 'target': ['view:A'], 'property': 'source.append',
        'value': {'source': {**source, 'source_id': 'raw:unused-response'}, 'curves': [
            {'sample': 'Declared response', 'x_column_index': 0, 'y_column_index': 2}]}}]}
    with pytest.raises(SourceInputError) as error:
        prepare_update(document, append)
    assert error.value.reason_code == 'instrument_layout_unsupported'


def test_shortened_existing_test_unused_response_cannot_bypass_literal_test_identity(tmp_path):
    document, path, blocks, _facts = bound_tests(tmp_path, two_storage_columns=True)
    request = append_test(document, path, blocks[0])
    value = request['changes'][0]['value']
    value['source']['table_selection']['data_end_row'] -= 1
    value['curves'][0].update(sample='Invented Test', y_column_index=5)
    # This is an unused original response, so the duplicate-Y guard cannot
    # conceal whether the original literal Test identity is actually checked.
    with pytest.raises(ValueError) as error:
        prepare_update(document, request)
    assert error.value.reason_code == 'managed_append_sample_conflict'


def test_existing_test_prefix_retains_its_old_unused_response_route_with_true_identity(tmp_path):
    document, path, blocks, _facts = bound_tests(tmp_path, two_storage_columns=True)
    request = append_test(document, path, blocks[0])
    value = request['changes'][0]['value']
    value['source']['table_selection']['data_end_row'] -= 1
    value['curves'][0]['y_column_index'] = 5
    candidate, diff, _, _ = prepare_update(document, request)
    assert 'physical_region' not in diff[0]['after']
    assert all(item['value'] == blocks[0]['test_name'] for item in candidate['scientific']['data_sources'][-1]['metadata_confirmations'])
    candidate, _ = resolve_science(tmp_path / 'store', candidate)
    ir = resolved_ir(tmp_path / 'store', candidate)
    assert ir['datasets']['raw:new-test']['columns']['column:5']['values'] == [10., 10.1, 10.2]


@pytest.mark.parametrize('problem', ['cross_test', 'ambiguous_start'])
def test_existing_test_prefix_never_uses_an_unbounded_or_ambiguous_test_identity(tmp_path, monkeypatch, problem):
    from sciplot_core.plot_engine import append_source_regions

    document, path, blocks, _facts = bound_tests(tmp_path, two_storage_columns=True)
    request = append_test(document, path, blocks[0])
    value = request['changes'][0]['value']
    value['source']['table_selection']['data_end_row'] -= 1
    value['curves'][0]['y_column_index'] = 5
    if problem == 'cross_test':
        value['source']['table_selection']['data_end_row'] = blocks[1]['data_end_row']
    else:
        observer = append_source_regions._physical_candidates

        def ambiguous(snapshot, sheet):
            candidates = observer(snapshot, sheet)
            candidates[0]['blocks'].append(deepcopy(candidates[0]['blocks'][0]))
            return candidates

        monkeypatch.setattr(append_source_regions, '_physical_candidates', ambiguous)
    with pytest.raises(ValueError) as error:
        prepare_update(document, request)
    assert error.value.reason_code == 'managed_append_region_conflict'
