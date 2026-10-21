"""Append uses the same registered unit relation as existing target science."""

from copy import deepcopy
from pathlib import Path

import pytest
from test_managed_source_append import append_request, bound_document

from sciplot_core.plot_engine.managed_resolution import resolve_science
from sciplot_core.plot_engine.managed_source_append import append_targets
from sciplot_core.plot_engine.managed_state import resolved_ir
from sciplot_core.plot_engine.managed_updates import prepare_update
from sciplot_core.plot_ir.figure_document import figure_spec, store_spec
from sciplot_core.plot_transforms import builtin_executor


def test_append_charge_and_temperature_use_the_confirmed_quantity_before_numeric_projection():
    from sciplot_core.plot_engine.managed_source_append import _coordinates

    columns = {0: {'index': 0, 'header': 'Time', 'unit': 's', 'sample': 'A', 'metadata_conflicts': []},
               1: {'index': 1, 'header': 'Charge', 'unit': 'C', 'sample': 'A', 'metadata_conflicts': []}}
    curve = {'sample': 'A', 'x_column_index': 0, 'y_column_index': 1}
    scales = {'x': {'quantity': 'time', 'unit': 's'}, 'y': {'quantity': 'charge', 'unit': 'C'}}
    original = deepcopy(columns)
    relation = _coordinates(curve, columns, scales)['y']['unit_relation']
    assert relation['kind'] == 'identity' and relation['canonical_from_unit'] == relation['canonical_to_unit'] == 'C'
    scales['y']['unit'] = 'K'
    curve['y_unit'] = 'K'
    with pytest.raises(ValueError) as error:
        _coordinates(curve, columns, scales)
    assert error.value.reason_code == 'managed_append_unit_conflict' and columns == original
    columns[1]['header'] = 'Temperature'
    scales['y']['quantity'] = 'temperature'
    relation = _coordinates(curve, columns, scales)['y']['unit_relation']
    assert relation['kind'] == 'conversion' and relation['factor'] == 1 and relation['offset'] == 273.15


def test_append_lineage_uses_original_quantity_before_rename_or_display_alias():
    from sciplot_core.plot_engine.append_target_lineage import coordinate_origin

    executor = {'executor': builtin_executor(), 'determinism': 'deterministic'}
    source = {'source_id': 'raw:A', 'table_selection': {'data_start_row': 3, 'data_end_row': 6}}
    original_column = {'label': 'Charge', 'unit': 'C', 'values': [-0.0, None, 2.5]}
    document = {'scientific': {'data_sources': [source], 'provenance': {'datasets': {
        'raw:A': {'columns': {'column:1': original_column}}}}, 'transforms': [
        dict(executor, id='rename', kind='rename', inputs=['raw:A'], output='renamed',
             parameters={'columns': {'column:1': {'id': 'y', 'label': 'Temperature'}}}),
        dict(executor, id='unit', kind='convert_unit', inputs=['renamed'], output='projected',
             parameters={'columns': ['y'], 'from_unit': 'C', 'to_unit': 'K'})]}}
    original = deepcopy(document)
    with pytest.raises(ValueError) as error:
        coordinate_origin(document, 'projected', 'y', 'K', quantity='charge')
    assert error.value.reason_code == 'transform_unit_incompatible' and document == original
    original_column['label'] = 'Temperature'
    assert coordinate_origin(document, 'projected', 'y', 'K', quantity='temperature') == (source, 1, 3, 6)
    # An exact selected user fact is already frozen in the semantic binding;
    # the later rename and display text must not erase or replace that evidence.
    original_column['label'] = 'sensor_C'
    source.update(path='/bound/original.csv', sha256='a' * 64)
    proof = {'version': 1, 'quantity': 'temperature', 'observed_quantity': None,
             'source_header': 'sensor_C', 'explicit_quantity_binding': True}
    document['scientific']['provenance']['binding'] = {'semantic_task': {'resolution': {'bindings': [{
        'source_path': source['path'], 'source_sha256': source['sha256'], 'table_selection': source['table_selection'],
        'coordinates': {'y': {'column_id': 'column:1', 'source_unit': 'C', 'header': 'sensor_C',
                             'quantity': 'temperature', 'observed_quantity': None, 'unit_context': proof}}}]}}}
    assert coordinate_origin(document, 'projected', 'y', 'K', quantity='temperature') == (source, 1, 3, 6)
    proof['source_header'] = 'a presentation alias'
    with pytest.raises(ValueError) as stale:
        coordinate_origin(document, 'projected', 'y', 'K', quantity='temperature')
    assert stale.value.reason_code == 'managed_append_view_unsupported'


def projected_document(tmp_path, *, axis='y', target_unit='kPa'):
    document = bound_document(tmp_path)
    source = document['scientific']['data_sources'][0]
    node = {'executor': builtin_executor(), 'determinism': 'deterministic'}
    document['scientific']['transforms'] = [
        dict(node, id='select', kind='select', inputs=[source['source_id']], output='selected',
             parameters={'columns': ['column:0', 'column:1']}),
        dict(node, id='slice', kind='row_slice', inputs=['selected'], output='sliced', parameters={'start': 0, 'end': 3}),
        dict(node, id='rename', kind='rename', inputs=['sliced'], output='renamed', parameters={'columns': {
            'column:0': {'id': 'x', 'label': 'Frequency'}, 'column:1': {'id': 'y', 'label': 'Modulus'}}}),
        dict(node, id='unit', kind='convert_unit', inputs=['renamed'], output='projected',
             parameters={'columns': [axis], 'from_unit': 'Pa' if axis == 'y' else 'Hz', 'to_unit': target_unit}),
    ]
    spec = figure_spec(document)
    spec['scales'][1 if axis == 'y' else 0]['unit'] = target_unit
    layer = spec['views'][0]['layers'][0]
    layer['dataset_id'], layer['mappings'] = 'projected', {'x': 'x', 'y': 'y'}
    mapping = document['scientific']['mappings'][layer['id']]
    mapping.update(x={'source_id': 'projected', 'column': 'x'}, y={'source_id': 'projected', 'column': 'y'})
    mapping[axis + '_unit'] = target_unit
    document = store_spec(document, spec)
    return resolve_science(tmp_path / 'store', document)[0]


def test_registered_numeric_projection_requires_explicit_target_and_keeps_raw_rows_and_existing_science(tmp_path):
    document = projected_document(tmp_path)
    original = deepcopy(document)
    before = resolved_ir(tmp_path / 'store', document)
    assert 'view:A' in append_targets(document)
    request = append_request(document, tmp_path)
    request['changes'][0]['value']['curves'][0]['y_unit'] = 'kPa'
    source = Path(request['changes'][0]['value']['source']['path'])
    raw_bytes = source.read_bytes()
    candidate, diff, _, _ = prepare_update(document, request)
    relation = diff[0]['after']['unit_relations'][0]['y']
    assert relation['kind'] == 'conversion' and relation['factor'] == .001 and relation['offset'] == 0
    assert relation['from_unit'] == 'Pa' and relation['to_unit'] == 'kPa'
    assert candidate['scientific']['transforms'][:4] == document['scientific']['transforms']
    candidate, _ = resolve_science(tmp_path / 'store', candidate)
    after = resolved_ir(tmp_path / 'store', candidate)
    for name, dataset in before['datasets'].items():
        assert after['datasets'][name] == dataset
    new = after['views'][0]['layers'][-1]
    assert after['datasets']['raw:B']['columns']['column:1']['values'] == [7, None, 3, 9]
    projected = after['datasets'][new['dataset_id']]['columns']['column:1']
    assert projected['unit'] == 'kPa' and projected['values'] == [.007, None, .003, .009000000000000001]
    assert after['datasets']['raw:B']['provenance']['sources'][0]['rows'] == [3, 4, 5, 6]
    assert source.read_bytes() == raw_bytes and document == original
    assert candidate['scientific']['provenance']['source_appends'][-1]['unit_relations'] == diff[0]['after']['unit_relations']
    assert figure_spec(candidate)['scales'] == figure_spec(document)['scales']


@pytest.mark.parametrize('target', [None, 'Pa', '[kPa]', 'MPa'])
def test_numeric_projection_cannot_infer_or_change_the_axis_target(tmp_path, target):
    document = projected_document(tmp_path)
    request = append_request(document, tmp_path)
    if target is not None:
        request['changes'][0]['value']['curves'][0]['y_unit'] = target
    original = deepcopy(document)
    with pytest.raises(ValueError) as error:
        prepare_update(document, request)
    assert error.value.reason_code == 'managed_append_unit_conflict'
    assert document == original


def test_registered_identity_spelling_uses_existing_axis_without_new_conversion_permission(tmp_path):
    document = projected_document(tmp_path, axis='x', target_unit='[Hz]')
    request = append_request(document, tmp_path)
    candidate, diff, _, _ = prepare_update(document, request)
    assert diff[0]['after']['unit_relations'][0]['x']['kind'] == 'identity'
    candidate, _ = resolve_science(tmp_path / 'store', candidate)
    ir = resolved_ir(tmp_path / 'store', candidate)
    layer = ir['views'][0]['layers'][-1]
    column = ir['datasets'][layer['dataset_id']]['columns']['column:0']
    assert column['unit'] == '[Hz]' and column['values'] == [8, 5, 5, 2]
    assert candidate['scientific']['mappings'][layer['id']]['x_unit'] == '[Hz]'


@pytest.mark.parametrize('problem', ['derived', 'incompatible', 'stale_executor'])
def test_capability_refuses_unsupported_target_lineage(tmp_path, problem):
    document = projected_document(tmp_path)
    node = document['scientific']['transforms'][-1]
    if problem == 'derived':
        node.update(kind='normalize', parameters={'columns': ['y'], 'method': 'max_abs', 'output_unit': '1'})
    elif problem == 'incompatible':
        node['parameters'].update(from_unit='C', to_unit='kPa')
    else:
        node['executor']['content_hash'] = '0' * 64
    assert append_targets(document) == {}


def test_separate_registered_source_branches_continue_without_replacing_existing_science(tmp_path):
    document = projected_document(tmp_path)
    first = append_request(document, tmp_path)
    first['changes'][0]['value']['curves'][0]['y_unit'] = 'kPa'
    document, _, _, _ = prepare_update(document, first)
    document, _ = resolve_science(tmp_path / 'store', document)
    original = deepcopy(document)
    before = resolved_ir(tmp_path / 'store', document)
    before_spec = figure_spec(document)
    assert 'view:A' in append_targets(document)
    request = append_request(document, tmp_path, 'C')
    request['changes'][0]['value']['curves'][0]['y_unit'] = 'kPa'
    candidate, _, _, _ = prepare_update(document, request)
    candidate, _ = resolve_science(tmp_path / 'store', candidate)
    after = resolved_ir(tmp_path / 'store', candidate)
    after_spec = figure_spec(candidate)
    for name, dataset in before['datasets'].items():
        assert after['datasets'][name] == dataset
    assert after_spec['scales'] == before_spec['scales']
    assert after_spec['views'][0]['axes'] == before_spec['views'][0]['axes']
    assert after_spec['views'][0]['layers'][:-1] == before_spec['views'][0]['layers']
    for old, new in zip(before_spec['guides'], after_spec['guides'], strict=True):
        assert {key: value for key, value in new.items() if key not in {'layer_ids', 'order'}} == {
            key: value for key, value in old.items() if key not in {'layer_ids', 'order'}}
        assert new['order'][:-1] == old['order']
    assert document == original


def test_same_response_cannot_be_duplicated_through_registered_unit_rename_and_row_lineage(tmp_path):
    document = projected_document(tmp_path)
    spec = figure_spec(document)
    spec['views'][0]['layers'][0]['legend']['visible'] = False
    spec['guides'] = []
    document = store_spec(document, spec)
    request = append_request(document, tmp_path)
    value = request['changes'][0]['value']
    source = document['scientific']['data_sources'][0]
    value['source'] = {**deepcopy(source), 'source_id': 'raw:duplicate'}
    value['curves'][0].update(sample='New display alias', y_unit='kPa')
    original = deepcopy(document)
    with pytest.raises(ValueError) as error:
        prepare_update(document, request)
    assert error.value.reason_code == 'managed_append_duplicate_measurement'
    assert document == original
