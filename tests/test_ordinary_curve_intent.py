"""Generated ordinary XY contracts keep scientific quantities and original grids."""
from copy import deepcopy
import csv
from io import StringIO
import json

import pytest

from sciplot_core.foundation.file_hashing import file_sha256
from sciplot_core.plot_engine.managed_resolution import resolved_metadata, resolve_science
from sciplot_core.plot_engine.managed_state import resolved_ir
from sciplot_core.plot_engine.managed_updates import prepare_update
from sciplot_core.plot_ir import create_managed_document
from sciplot_core.plot_ir.figure_document import figure_spec, store_spec
from sciplot_core.task_semantic_contract import validate_intent
from sciplot_core.task_semantic_creation import build_managed_request as build_request
from sciplot_core.task_semantic_plan import prepare_plan


def compose(tmp_path, source, intent):
    intent = validate_intent(intent)
    plan = prepare_plan([source], intent)
    assert plan['decisions'] == []
    request = build_request({'request': {'intent': intent}, 'semantic_plan': plan, 'semantic_choices': {},
                             'intent_revision': 1, 'task_dir': str(tmp_path / 'task')})
    document = create_managed_document(request['template_definition'], request['data_binding'], plot_id='ordinary')
    document = resolved_metadata(document, rule_id='ordinary_xy', executors={})
    document, _ = resolve_science(tmp_path / 'store', document)
    return request, document, resolved_ir(tmp_path / 'store', document)


def paired_quantities(tmp_path):
    source = tmp_path / 'independent-pairs.csv'
    source.write_text('Temperature,Storage Modulus,Temperature,Loss Modulus,Temperature,Storage Modulus,Temperature,Loss Modulus\n'
                      'Amber,Amber,Amber,Amber,Blue,Blue,Blue,Blue\nC,Pa,C,Pa,C,Pa,C,Pa\n'
                      '80,200,75,20,78,400,73,40\n100,150,105,18,95,350,90,35\n'
                      '100,180,125,16,,,118,31\n90,170,,,,,131,29\n')
    intent = {'x': {'quantity': 'temperature', 'scale': 'linear'},
              'y': {'quantity': 'modulus', 'quantity_members': ['storage_modulus', 'loss_modulus'], 'scale': 'log'},
              'labels': ['Amber storage', 'Amber loss', 'Blue storage', 'Blue loss'],
              'curve_bindings': [{'source_id': 'source:0', 'table_id': 'table:0', 'block_id': f'block:{sample}',
                                  'x_column_id': f'column:{sample * 4 + member * 2}',
                                  'y_column_id': f'column:{sample * 4 + member * 2 + 1}', 'y_quantity': quantity}
                                 for sample in range(2) for member, quantity in enumerate(['storage_modulus', 'loss_modulus'])]}
    return source, intent


def mass_source(tmp_path):
    source = tmp_path / 'independent-mass.csv'
    source.write_text('Molar Mass,Differential Weight Fraction,Molar Mass,Differential Weight Fraction,Molar Mass,Differential Weight Fraction\n'
                      'Amber,Amber,Blue,Blue,Coral,Coral\ng/mol,1,g/mol,1,g/mol,1\n'
                      '10,0,20,0,12,0\n100,0.3,200,0.2,120,0.4\n1000,0.1,,,120,0.35\n,,,,1100,0.1\n')
    intent = {'x': {'quantity': 'molar_mass', 'header': 'Molar Mass', 'scale': 'log'},
              'y': {'quantity': 'differential_weight_fraction', 'header': 'Differential Weight Fraction', 'scale': 'linear'},
              'selection': {'blocks': [{'source_id': 'source:0', 'table_id': 'table:0', 'block_id': f'block:{i}'} for i in (0, 1)]}}
    return source, intent


def same_file_request(document, source, *, y=5, x=4, sample='Coral', key='same-file'):
    region = deepcopy(document['scientific']['data_sources'][0]['table_selection'])
    region['data_end_row'] = 7
    return {'plot_id': document['plot_id'], 'base_revision': document['revision'], 'idempotency_key': key,
            'intent_class': 'scientific', 'changes': [{'op': 'set', 'target': ['view:main'], 'property': 'source.append',
                'value': {'source': {'source_id': 'projection:coral', 'path': str(source), 'sha256': file_sha256(source),
                                     'table_selection': region},
                          'curves': [{'sample': sample, 'x_column_index': x, 'y_column_index': y, 'label': 'Coral alias',
                                      'color': '#cc6600', 'line_width_pt': 1.7}]}}]}


def test_explicit_shared_quantity_axis_preserves_each_original_grid_and_scientific_identity(tmp_path):
    source, intent = paired_quantities(tmp_path)
    original = source.read_bytes()
    request, document, ir = compose(tmp_path, source, intent)
    spec = figure_spec(document)
    layers = spec['views'][0]['layers']
    assert [layer['mapping_semantics']['y'] for layer in layers] == ['storage_modulus', 'loss_modulus'] * 2
    assert {layer['y_scale'] for layer in layers} == {'scale:y'}
    assert spec['scales'][1]['quantity_members'] == intent['y']['quantity_members']
    assert spec['scales'][1]['transform'] == 'log' and spec['scales'][0]['transform'] == 'linear'
    # Both declared sample blocks have four original records. Another pair's
    # missing tail occupies those rows; it does not redefine the source region.
    cells = list(csv.reader(StringIO(original.decode())))
    original_rows = list(range(3, len(cells)))
    finite_pairs = []
    for index, layer in enumerate(layers):
        dataset = ir['datasets'][layer['dataset_id']]
        expected_pair = []
        for role, column in (('x', index * 2), ('y', index * 2 + 1)):
            expected = [float(cells[row][column]) if cells[row][column] else None for row in original_rows]
            actual = dataset['columns'][role]['values']
            assert len(actual) == len(original_rows)
            assert [value is None for value in actual] == [value is None for value in expected]
            assert [None if value is None else float(value).hex() for value in actual] == [
                None if value is None else value.hex() for value in expected]
            expected_pair.append(expected)
        assert dataset['provenance']['sources'][0]['rows'] == original_rows
        finite_pairs.append(sum(x is not None and y is not None for x, y in zip(*expected_pair, strict=True)))
    assert finite_pairs == [4, 3, 2, 4]
    assert [slot['sample'] for slot in request['data_binding']['slots'].values()] == ['Amber', 'Amber', 'Blue', 'Blue']
    assert all(item['sha256'] == file_sha256(source) for item in request['data_binding']['data_sources'])
    assert document['scientific']['provenance']['figure_spec']['scales'][1]['quantity_members'] == intent['y']['quantity_members']
    assert source.read_bytes() == original


@pytest.mark.parametrize('problem', ['missing_pair', 'foreign_ref', 'relabel', 'same_column', 'missing_x', 'global_x', 'magnitude', 'missing_members', 'missing_bindings', 'duplicate_members', 'empty_members', 'stage'])
def test_shared_quantities_require_complete_exact_source_bound_contract(tmp_path, problem):
    source, intent = paired_quantities(tmp_path)
    if problem == 'missing_pair':
        intent['curve_bindings'].pop()
    elif problem == 'foreign_ref':
        intent['curve_bindings'][0]['source_id'] = 'source:9'
    elif problem == 'relabel':
        intent['curve_bindings'][0]['y_column_id'] = 'column:3'
    elif problem == 'same_column':
        intent['curve_bindings'][0]['x_column_id'] = 'column:1'
    elif problem == 'missing_x':
        intent['curve_bindings'][1].pop('x_column_id')
    elif problem == 'global_x':
        intent['x']['column_id'] = 'column:0'
    elif problem == 'magnitude':
        intent['y']['quantity'] = 'complex_viscosity'
    elif problem == 'missing_members':
        intent['y'].pop('quantity_members')
    elif problem == 'missing_bindings':
        intent.pop('curve_bindings')
    elif problem == 'duplicate_members':
        intent['y']['quantity_members'].append('storage_modulus')
    elif problem == 'empty_members':
        intent['y']['quantity_members'] = []
    else:
        intent['stages'] = {'mode': 'source_order'}
    with pytest.raises(ValueError):
        compose(tmp_path, source, intent)


@pytest.mark.parametrize('value', [0, -2])
@pytest.mark.parametrize('role', ['x', 'y'])
def test_explicit_log_rejects_nonpositive_without_discarding_or_shifting(tmp_path, value, role):
    source = tmp_path / 'log-domain.csv'
    xs = [80, value if role == 'x' else 90, 100]
    ys = [100, value if role == 'y' else 40, 20]
    source.write_text('Temperature,Storage Modulus\nC,Pa\n' + ''.join(f'{x},{y}\n' for x, y in zip(xs, ys, strict=True)))
    original = source.read_bytes()
    intent = {'x': {'quantity': 'temperature'}, 'y': {'quantity': 'storage_modulus'}}
    intent[role]['scale'] = 'log'
    with pytest.raises(ValueError) as rejected:
        compose(tmp_path, source, intent)
    assert rejected.value.reason_code == 'semantic_log_domain'
    intent[role]['scale'] = 'linear'
    _, _, ir = compose(tmp_path, source, intent)
    layer = ir['views'][0]['layers'][0]
    assert ir['datasets'][layer['dataset_id']]['columns']['x']['values'] == xs
    assert ir['datasets'][layer['dataset_id']]['columns']['y']['values'] == ys
    assert source.read_bytes() == original


def test_same_original_file_append_binds_unused_pair_and_preserves_prior_science_and_style(tmp_path):
    source, intent = mass_source(tmp_path)
    _, document, before = compose(tmp_path, source, intent)
    spec = figure_spec(document)
    spec['views'][0]['layers'][0]['label'] = 'Amber custom alias'
    spec['views'][0]['layers'][0]['marks'][0]['style'] = {'line_color': '#225599', 'line_width_pt': 1.9}
    spec['views'][0]['layers'][1]['visible'] = False
    spec['guides'][0].update(columns=2, location='top-right')
    spec['layout']['width_mm'] = 180
    document = store_spec(document, spec)
    original = deepcopy(document)
    request = same_file_request(document, source)
    candidate, diff, _, execute = prepare_update(document, request)
    assert execute and diff[0]['risk'] == 'scientific' and document == original
    candidate, _ = resolve_science(tmp_path / 'store', candidate)
    after = resolved_ir(tmp_path / 'store', candidate)
    final = figure_spec(candidate)
    assert final['views'][0]['layers'][:2] == spec['views'][0]['layers']
    assert final['guides'] == spec['guides']
    for previous, current in zip(spec['scales'], final['scales'], strict=True):
        assert {key: value for key, value in previous.items() if key != 'domain'} == {
            key: value for key, value in current.items() if key != 'domain'}
    # Auto windows include the new physical maxima, rather than preserving the
    # earlier projection. Current rules, units, direction and hidden membership
    # stay exact. The response window is the literal [0,.4] plus 5% padding.
    assert final['scales'][0]['domain'][0] <= 10 < 1100 <= final['scales'][0]['domain'][1]
    assert final['scales'][1]['domain'] == [-.020000000000000004, .42000000000000004]
    assert final['scales'][1]['domain'][1] > spec['scales'][1]['domain'][1]
    layer = final['views'][0]['layers'][-1]
    assert after['datasets'][layer['dataset_id']]['columns']['column:4']['values'] == [12, 120, 120, 1100]
    assert after['datasets'][layer['dataset_id']]['columns']['column:5']['values'] == [0, .4, .35, .1]
    assert all(after['datasets'][key] == value for key, value in before['datasets'].items())
    assert candidate['plot_id'] == document['plot_id'] and candidate['scientific_hash'] != document['scientific_hash']
    reopened, _ = resolve_science(tmp_path / 'store', json.loads(json.dumps(candidate)))
    assert figure_spec(reopened) == final
    assert resolved_ir(tmp_path / 'store', reopened) == after


@pytest.mark.parametrize('problem,code', [('hidden_duplicate', 'managed_append_duplicate_measurement'),
    ('relabel_duplicate', 'managed_append_sample_conflict'), ('sha_drift', 'managed_append_source_changed'),
    ('unit', 'managed_append_unit_conflict'), ('intent', 'managed_append_scientific_intent_required'),
    ('region', 'managed_append_region_conflict')])
def test_same_file_append_rejects_duplicate_observations_and_changed_facts(tmp_path, problem, code):
    source, intent = mass_source(tmp_path)
    if problem == 'unit':
        source.write_text(source.read_text().replace('g/mol,1,g/mol,1,g/mol,1', 'g/mol,1,g/mol,1,g/mol,%'))
    _, document, _ = compose(tmp_path, source, intent)
    spec = figure_spec(document)
    spec['views'][0]['layers'][1]['visible'] = False
    document = store_spec(document, spec)
    request = same_file_request(document, source)
    value = request['changes'][0]['value']
    if problem in {'hidden_duplicate', 'relabel_duplicate'}:
        value['curves'][0].update(x_column_index=2, y_column_index=3, sample='Blue' if problem == 'hidden_duplicate' else 'Fake')
    elif problem == 'sha_drift':
        source.write_text(source.read_text().replace('12,0', '13,0'))
        value['source']['sha256'] = file_sha256(source)
    elif problem == 'unit':
        pass
    elif problem == 'intent':
        request['intent_class'] = 'presentation'
    else:
        value['source']['table_selection']['data_start_row'] = 4
    original = deepcopy(document)
    with pytest.raises(ValueError) as rejected:
        prepare_update(document, request)
    assert rejected.value.reason_code == code
    assert document == original


def test_public_cli_scale_flags_compile_to_the_small_semantic_intent():
    from sciplot_core.cli.parsers.builder import build_parser
    from sciplot_core.cli.dispatch.tasks import _semantic_intent

    args = build_parser().parse_args(['task', 'create', '--source', '/generated.csv', '--x', 'molar_mass',
                                     '--y', 'differential_weight_fraction', '--x-scale', 'log', '--y-scale', 'linear'])
    intent = _semantic_intent(args)
    assert intent['x']['scale'] == 'log' and intent['y']['scale'] == 'linear'


def test_omitted_scale_instrument_intent_retains_registered_derived_frequency_owner(tmp_path):
    from test_frequency_interval_binding import instrument_source, intent as frequency_intent

    source = instrument_source(tmp_path / 'frequency.csv', temperatures=(173,))
    value = frequency_intent()
    value.pop('rule_id')
    # Historical route selected a scientific derivation from layout alone.
    # Ordinary intent now asks for an original binding; the registered rule
    # remains the authorization for this unchanged scientific derivation.
    plan = prepare_plan([source], value)
    assert [decision['field'] for decision in plan['decisions']] == ['y_header']
    assert 'resolved_bindings' not in plan
    value['rule_id'] = frequency_intent()['rule_id']
    wire, _, _ = compose(tmp_path, source, value)
    assert [scale['transform'] for scale in wire['template_definition']['figure_spec']['scales']] == ['log', 'log']
    assert any(node['kind'] == 'rheology_complex_viscosity' for node in wire['data_binding']['transforms'])
    value['y']['header'] = 'Im(Complex Viscosity)'
    with pytest.raises(ValueError) as rejected:
        compose(tmp_path, source, value)
    assert rejected.value.reason_code == 'semantic_coordinate_mapping_required'


@pytest.mark.parametrize('problem', ['missing', 'extra', 'duplicate', 'magnitude', 'unit'])
def test_shared_quantity_science_schema_and_ir_reject_incomplete_or_false_identity(tmp_path, problem):
    from sciplot_core.plot_grammar.ir import seal_ir_v2
    from sciplot_core.plot_grammar.validation import validate_figure_spec

    source, intent = paired_quantities(tmp_path)
    _, document, ir = compose(tmp_path, source, intent)
    spec = figure_spec(document)
    for payload in (spec, ir):
        scale = payload['scales'][1]
        if problem == 'missing':
            scale['quantity_members'] = ['storage_modulus']
        elif problem == 'extra':
            scale['quantity'] = 'response'
            scale['quantity_members'].append('imaginary_complex_viscosity')
        elif problem == 'duplicate':
            scale['quantity_members'].append('storage_modulus')
        elif problem == 'magnitude':
            scale['quantity'] = 'complex_viscosity'
        else:
            scale['unit'] = 'MPa'
    if problem != 'unit':
        with pytest.raises(ValueError):
            validate_figure_spec(spec)
    with pytest.raises(ValueError):
        seal_ir_v2(ir)


def test_shared_quantity_members_do_not_infer_equal_units(tmp_path):
    source, intent = paired_quantities(tmp_path)
    source.write_text(source.read_text().replace('C,Pa,C,Pa,C,Pa,C,Pa', 'C,Pa,C,MPa,C,Pa,C,Pa'))
    with pytest.raises(ValueError) as rejected:
        compose(tmp_path, source, intent)
    assert rejected.value.reason_code == 'semantic_unit_ambiguous'


def test_shared_quantity_append_requires_the_actual_declared_member(tmp_path):
    source, intent = paired_quantities(tmp_path)
    _, document, _ = compose(tmp_path, source, intent)
    addition = tmp_path / 'next-member.csv'
    addition.write_text('Temperature,Loss Modulus\nC,Pa\nGreen,Green\n82,25\n99,22\n')
    source_binding = {'source_id': 'new:green', 'path': str(addition), 'sha256': file_sha256(addition),
                      'table_selection': {'sheet': None, 'header_rows': [0], 'unit_row': 1, 'sample_row': 2,
                                          'data_start_row': 3, 'data_end_row': 5}}
    curve = {'sample': 'Green', 'x_column_index': 0, 'y_column_index': 1}
    request = {'plot_id': document['plot_id'], 'base_revision': 0, 'idempotency_key': 'next-member',
               'intent_class': 'scientific', 'changes': [{'op': 'set', 'target': ['view:main'], 'property': 'source.append',
                   'value': {'source': source_binding, 'curves': [curve]}}]}
    with pytest.raises(ValueError) as missing:
        prepare_update(document, request)
    assert missing.value.reason_code == 'managed_append_quantity_conflict'
    curve['y_quantity'] = 'storage_modulus'
    with pytest.raises(ValueError) as false:
        prepare_update(document, request)
    assert false.value.reason_code == 'managed_append_quantity_conflict'
    curve['y_quantity'] = 'loss_modulus'
    candidate, _, _, _ = prepare_update(document, request)
    layer = figure_spec(candidate)['views'][0]['layers'][-1]
    assert layer['mapping_semantics']['y'] == 'loss_modulus'
    assert figure_spec(candidate)['scales'] == figure_spec(document)['scales']
