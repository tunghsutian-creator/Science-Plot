"""A source mismatch identifies its original column and safe correction boundary."""
from copy import deepcopy

import pytest

from sciplot_core.foundation.file_hashing import file_sha256
from sciplot_core.plot_engine.errors import EngineError
from sciplot_core.plot_engine.managed_sources import load_sources


def document(tmp_path):
    source = tmp_path / 'measured.csv'
    source.write_text('Time,Mass\ns,%\n0,100\n1,99.5\n')
    return {'scientific': {'data_sources': [{'source_id': 'raw', 'path': str(source),
        'sha256': file_sha256(source), 'table_selection': {'sheet': None, 'header_rows': [0],
         'unit_row': 1, 'data_start_row': 2, 'data_end_row': 4}}],
        'mappings': {'trace': {'series_id': 'trace', 'sample': 'sample',
         'x': {'source_id': 'raw', 'column': 'Time', 'column_index': 0},
         'y': {'source_id': 'raw', 'column': 'Mass', 'column_index': 1}, 'x_unit': 's', 'y_unit': '%'}},
        'transforms': []}}


@pytest.mark.parametrize(('coordinate', 'field', 'bad', 'expected'), [('x', 'unit', 'min', 's'),
    ('y', 'column', 'Changed mass', 'Mass'), ('y', 'column_index', 7, [0, 1])])
def test_conflict_gives_exact_original_expected_actual_and_repair(tmp_path, coordinate, field, bad, expected):
    data = document(tmp_path)
    original = deepcopy(data)
    mapping = data['scientific']['mappings']['trace']
    if field == 'unit':
        mapping[coordinate + '_unit'] = bad
    else:
        mapping[coordinate][field] = bad
    with pytest.raises(EngineError) as caught:
        load_sources(data, 'tga_curve')
    error = caught.value
    assert error.reason_code == 'managed_metadata_conflict'
    issue, = error.issues
    assert issue['source_id'] == 'raw'
    assert issue['source'] == data['scientific']['data_sources'][0]['path']
    assert issue['sheet'] is None
    assert issue['field'] == field
    assert issue['expected'] == expected and issue['actual'] == bad
    assert issue['mapping_id'] == 'trace' and issue['coordinate'] == coordinate
    assert issue['column_index'] == mapping[coordinate]['column_index']
    assert error.repair['action'] == 'correct_binding'
    assert 'raw_cells' not in error.repair['allowed_changes']
    assert 'conversion' in error.repair['message'].lower()
    assert original['scientific']['data_sources'] == data['scientific']['data_sources']


def test_literal_unit_and_header_are_accepted_without_relabelling(tmp_path):
    data = document(tmp_path)
    loaded = load_sources(data, 'tga_curve')
    assert loaded['raw']['columns']['column:0'] == {'label': 'Time', 'unit': 's', 'values': [0., 1.]}
    assert loaded['raw']['columns']['column:1']['values'] == [100., 99.5]


@pytest.mark.parametrize('derived', [False, True])
def test_rejected_unit_declaration_cannot_hide_behind_matching_raw_binding(tmp_path, derived):
    data = document(tmp_path)
    source = data['scientific']['data_sources'][0]
    source['metadata_confirmations'] = [{'source_sha256': source['sha256'], 'sheet': None,
        'column_index': 0, 'field': 'unit', 'value': 'min', 'evidence': {'kind': 'user_statement',
        'asserted_by': 'test data owner', 'statement': 'Please call this time in minutes.'}}]
    if derived:
        from sciplot_core.plot_transforms import builtin_executor
        data['scientific']['transforms'] = [{'id': 'select', 'kind': 'select', 'inputs': ['raw'],
            'output': 'processed', 'parameters': {'columns': ['column:0', 'column:1']},
            'executor': builtin_executor(), 'determinism': 'deterministic'}]
        for axis in ('x', 'y'):
            data['scientific']['mappings']['trace'][axis]['source_id'] = 'processed'
    with pytest.raises(EngineError) as caught:
        load_sources(data, 'tga_curve')
    issue, = caught.value.issues
    assert issue['field'] == 'unit'
    assert issue['expected'] == 's' and issue['actual'] == 'min'
    assert source['metadata_confirmations'][0]['value'] == 'min'


@pytest.mark.parametrize('later_sample', ['A', 'B'])
def test_concat_sample_identity_includes_later_inputs(monkeypatch, later_sample):
    from sciplot_core.plot_engine import managed_sources
    # Node validation/execution belongs to plot_transforms. This unit boundary
    # exercises the original-sample audit for an already ordered concat plan.
    monkeypatch.setattr(managed_sources, 'ordered_nodes', lambda nodes, sources: nodes)
    raw = {'first': {'time': set(), 'response': {'A'}},
           'middle': {'time': set(), 'response': {'A'}},
           'last': {'time': set(), 'response': {later_sample}}}
    data = {'scientific': {'transforms': [{'kind': 'concat_time',
        'inputs': ['first', 'middle', 'last'], 'output': 'joined'}],
        'mappings': {'trace': {'sample': 'A', 'x': {'source_id': 'joined', 'column': 'time'},
                               'y': {'source_id': 'joined', 'column': 'response'}}}}}
    if later_sample == 'A':
        managed_sources._require_sample_lineage(data, raw)
    else:
        with pytest.raises(EngineError) as caught:
            managed_sources._require_sample_lineage(data, raw)
        assert caught.value.reason_code == 'managed_sample_conflict'


def test_concat_refuses_a_later_input_with_missing_original_column(monkeypatch):
    from sciplot_core.plot_engine import managed_sources
    monkeypatch.setattr(managed_sources, 'ordered_nodes', lambda nodes, sources: nodes)
    data = {'scientific': {'transforms': [{'kind': 'concat_time', 'inputs': ['first', 'last'],
                                          'output': 'joined'}], 'mappings': {}}}
    raw = {'first': {'time': set(), 'response': {'A'}}, 'last': {'time': set()}}
    with pytest.raises(EngineError) as caught:
        managed_sources._require_sample_lineage(data, raw)
    assert caught.value.reason_code == 'managed_column_lineage_missing'
