"""Structural parsing never silently assigns experiment or replicate identities."""
import pandas as pd
import pytest
from openpyxl import Workbook

from sciplot_core.foundation.file_hashing import file_sha256
from sciplot_core.source_inspection import inspect_input_file
from sciplot_core.source_tables import load_replicate_table_from_frame


def mixed_workbook(path):
    book = Workbook()
    sheet = book.active
    sheet.title = 'Measured'
    for row in [
        ['Index', 't', 'Ts', 'Tr', 'Value', None, 'Index', 't', 'Ts', 'Tr', 'Value'],
        [None, '[s]', '[°C]', '[°C]', '[%]', None, None, '[s]', '[°C]', '[°C]', '[%]'],
        [0, 0, 30, 30, 100, None, 0, 0, 200, 200, 99],
        [1, 1, 40, 40, 99.8, None, 1, 1, 200, 200, 98.9],
        [0, 0, 200, 200, 99.5, None, 2, 2, 200, 200, 98.8],
        [1, 1, 210, 210, 99.4, None, 3, 3, 200, 200, 98.7],
        [None, None, None, None, None, None, 4, 4, 200, 200, 98.6],
    ]:
        sheet.append(row)
    book.save(path)
    return path


def test_mixed_instrument_blocks_are_not_confident_replicates(tmp_path):
    source = mixed_workbook(tmp_path / 'not-a-material-name.xlsx')
    inspection = inspect_input_file(source)
    assert inspection.model == 'unbound_table'
    assert inspection.recommendations == ()
    assert inspection.recommendation_confidence == 0
    assert any('scientific' in item.lower() for item in inspection.warnings)


@pytest.mark.parametrize('suffix', ['.csv', '.xlsx'])
@pytest.mark.parametrize('shared', [True, False])
def test_real_replicate_layouts_remain_recognized(tmp_path, suffix, shared):
    rows = ([['Strength', None], ['Control', 'Foam'], ['MPa', 'MPa']] if shared else
            [['Strength', 'Strength'], ['MPa', 'MPa'], ['Control', 'Foam']])
    frame = pd.DataFrame([*rows, [10, 8], [11, 7]])
    source = tmp_path / ('replicates' + suffix)
    if suffix == '.csv':
        frame.to_csv(source, index=False, header=False)
    else:
        frame.to_excel(source, index=False, header=False)
    inspection = inspect_input_file(source)
    assert inspection.model == 'replicate_table'
    assert inspection.recommendations[0].template_id == 'box'
    assert [group.group for group in load_replicate_table_from_frame(frame)] == ['Control', 'Foam']


def test_semantic_candidates_preserve_cells_and_report_resets_and_roles(tmp_path):
    from sciplot_core.source_inspection.semantic_evidence import inspect_semantic_tables
    source = mixed_workbook(tmp_path / 'ordinary.xlsx')
    before = file_sha256(source)
    result = inspect_semantic_tables(source)
    candidate, = result['candidates']
    assert result['sha256'] == before == file_sha256(source)
    assert candidate['table_selection'] == {'sheet': 'Measured', 'header_rows': [0], 'unit_row': 1,
                                           'data_start_row': 2, 'data_end_row': 7}
    assert candidate['columns'][1]['column_id'] == 'column:1'
    assert candidate['columns'][1]['header'] == 't'
    assert candidate['columns'][1]['unit'] == '[s]'
    assert candidate['columns'][1]['quantity'] == 'time'
    assert candidate['columns'][4]['quantity'] is None
    assert candidate['columns'][4]['quantity_candidates'] == []  # percent is not a mass identity
    left, right = candidate['blocks']
    assert left['time_column'] == 'column:1'
    assert left['temperature_columns'] == ['column:2', 'column:3']
    assert left['response_columns'] == ['column:4']
    assert [(s['data_start_row'], s['data_end_row'], s['point_count']) for s in left['segments']] == [(2, 4, 2), (4, 6, 2)]
    assert [(s['data_start_row'], s['data_end_row'], s['time_start'], s['time_end']) for s in right['segments']] == [(2, 7, 0., 4.)]
    assert result['scientific_identity']['confirmed'] is False
    assert result['scientific_identity']['rule_candidates'] == []
    assert {'quantity_unconfirmed', 'temperature_role'} <= {a['code'] for a in candidate['ambiguities']}


def test_different_structure_inline_headers_keeps_mass_time_and_temp_separate(tmp_path):
    from sciplot_core.source_inspection.semantic_evidence import inspect_semantic_tables
    source = tmp_path / 'unrelated.csv'
    source.write_text('Time (min),Mass (%),Temperature (°C)\n0,100,20\n1,99,30\n2,98,40\n')
    candidate, = inspect_semantic_tables(source)['candidates']
    assert candidate['table_selection'] == {'sheet': None, 'header_rows': [0],
                                           'data_start_row': 1, 'data_end_row': 4}
    assert [column['quantity'] for column in candidate['columns']] == ['time', 'mass', 'temperature']
    assert [column['unit'] for column in candidate['columns']] == ['min', '%', '°C']
    assert candidate['blocks'][0]['time_column'] == 'column:0'
    assert candidate['blocks'][0]['response_columns'] == ['column:1']


def test_directory_error_is_not_experiment_ambiguity(tmp_path):
    from sciplot_core.source_inspection import SourceInputError
    (tmp_path / 'a.csv').write_text('x,y\n1,2\n')
    with pytest.raises(SourceInputError) as caught:
        inspect_input_file(tmp_path)
    assert caught.value.reason_code == 'source_is_directory'
    assert caught.value.repair['action'] == 'select_source_files'
    assert caught.value.repair['files'] == [str(tmp_path / 'a.csv')]


def test_three_row_quantity_sample_units_bind_distinct_literal_blocks(tmp_path):
    from sciplot_core.source_inspection.semantic_evidence import inspect_semantic_tables

    source = tmp_path / 'separate-grids.csv'
    source.write_text('Angular Frequency,Complex Viscosity,Angular Frequency,Complex Viscosity\n'
                      'Resin red,Resin red,Resin blue,Resin blue\n'
                      'rad/s,mPa s,rad/s,mPa s\n7,2100,9,3900\n3,4200,2,8100\n')
    original = source.read_bytes()
    candidate, = inspect_semantic_tables(source)['candidates']
    assert candidate['table_selection'] == {'sheet': None, 'header_rows': [0], 'sample_row': 1,
                                           'unit_row': 2, 'data_start_row': 3, 'data_end_row': 5}
    assert [column['quantity'] for column in candidate['columns']] == ['angular_frequency', 'complex_viscosity'] * 2
    assert [block['sample'] for block in candidate['blocks']] == ['Resin red', 'Resin blue']
    assert [block['column_indices'] for block in candidate['blocks']] == [[0, 1], [2, 3]]
    assert all(block['segments'] == [] for block in candidate['blocks'])
    assert source.read_bytes() == original


def test_closed_machine_suffix_units_do_not_infer_unknown_quantity(tmp_path):
    from sciplot_core.source_inspection.semantic_evidence import inspect_semantic_tables
    from sciplot_core.semantic_sources.paired_curve_table_metadata import explicit_header_unit

    source = tmp_path / 'signed-response.csv'
    source.write_text('row_index,time_min,temperature_C,heat_flow_W_g\n8,1.5,31,-0.007\n9,1.6,32,0.002\n')
    candidate, = inspect_semantic_tables(source)['candidates']
    assert [column['quantity'] for column in candidate['columns']] == [None, 'time', 'temperature', 'heat_flow']
    assert [column['unit'] for column in candidate['columns']] == ['', 'min', 'C', 'W/g']
    assert explicit_header_unit('unknown_W_g') == 'W/g'
    assert explicit_header_unit('heat_flow_arbitrary_suffix') == ''
