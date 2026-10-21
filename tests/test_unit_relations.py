"""Registered unit projection agrees with the unchanged scientific executor."""

from copy import deepcopy

import pytest

from sciplot_core.materials_rules.unit_data import _UNIT_RULES
from sciplot_core.materials_rules.unit_formatting import format_unit_label
from sciplot_core.plot_document.errors import DocumentError
from sciplot_core.plot_transforms.unit_relations import resolve_unit_relation
from sciplot_core.plot_transforms.units import run_unit_builtin


ENDPOINTS = {endpoint for pair in _UNIT_RULES for endpoint in pair}
RELATIONS = sorted(set(_UNIT_RULES) | {(unit, unit) for unit in ENDPOINTS})


def _spellings(unit):
    label = format_unit_label(unit)
    return sorted({unit, label, '[' + label + ']', '(' + unit + ')', label.replace('·', ' ')})


def _execute(from_unit, to_unit):
    node = {'kind': 'convert_unit', 'parameters': {'columns': ['value'], 'from_unit': from_unit, 'to_unit': to_unit},
            'output': 'projected'}
    source = {'id': 'original', 'columns': {'value': {'label': 'Original quantity', 'unit': from_unit,
                                                   'values': [-2., None, 0., 3.]}}}
    original = deepcopy(source)
    result, details = run_unit_builtin(node, source)
    assert source == original
    assert result['columns']['value']['unit'] == to_unit
    assert result['columns']['value']['values'][1] is None
    return details


@pytest.mark.parametrize(('source', 'target'), RELATIONS)
def test_registered_relation_spellings_match_actual_executor_details(source, target):
    for from_unit in _spellings(source):
        for to_unit in _spellings(target):
            relation = resolve_unit_relation(from_unit, to_unit, quantity='temperature', observed_quantity='temperature')
            actual = _execute(from_unit, to_unit)
            assert {key: value for key, value in relation.items() if key != 'kind'} == {
                key: actual[key] for key in relation if key != 'kind'}
            assert relation['kind'] == ('identity' if source == target else 'conversion')


@pytest.mark.parametrize(('source', 'target'), [('Pa', 'C'), ('K', 'Pa'), ('unregistered', 'Pa'), ('W/g', 'W g^-1')])
def test_incompatible_relations_keep_actual_executor_error(source, target):
    for call in (resolve_unit_relation, _execute):
        with pytest.raises(DocumentError) as error:
            call(source, target)
        assert error.value.reason_code == 'transform_unit_incompatible'


@pytest.mark.parametrize('unit', ['unregistered', '[unknown]', ' (unknown) ', 'W/g', ' arbitrary / unit '])
def test_unregistered_exact_identity_keeps_original_literal(unit):
    relation = resolve_unit_relation(unit, unit)
    assert relation['from_unit'] == relation['to_unit'] == unit
    assert relation['canonical_from_unit'] == relation['canonical_to_unit'] == unit
    actual = _execute(unit, unit)
    # The historical executor strips wrappers in its own details. Current
    # unchanged-unit bindings emit no convert node and preserve the raw literal.
    assert actual['factor'] == 1 and actual['offset'] == 0
    assert relation['kind'] == 'identity'
    assert relation['factor'] == 1 and relation['offset'] == 0


@pytest.mark.parametrize(('source', 'target'), [('[unknown]', 'unknown'), ('unknown', '(unknown)'),
                                              ('unknown/unit', 'unknown·unit⁻¹')])
def test_unknown_formatted_equality_cannot_authorize_a_projection(source, target):
    with pytest.raises(DocumentError) as error:
        resolve_unit_relation(source, target)
    assert error.value.reason_code == 'transform_unit_incompatible'


def test_identity_is_not_confused_with_numeric_conversion_or_offset():
    assert resolve_unit_relation('C', '°C', quantity='temperature', observed_quantity='temperature')['kind'] == 'identity'
    viscosity = resolve_unit_relation('mPa·s', 'Pa·s')
    assert viscosity['kind'] == 'conversion' and viscosity['factor'] == .001 and viscosity['offset'] == 0
    temperature = resolve_unit_relation('C', 'K', quantity='temperature', observed_quantity='temperature')
    assert temperature['kind'] == 'conversion' and temperature['factor'] == 1 and temperature['offset'] == 273.15


@pytest.mark.parametrize(('source', 'target'), [('', ''), (' ', 'C'), ('C', '')])
def test_missing_units_do_not_become_unknown_identity(source, target):
    with pytest.raises(DocumentError) as error:
        resolve_unit_relation(source, target)
    assert error.value.reason_code == 'transform_unit_incompatible'


@pytest.mark.parametrize('context', [{}, {'quantity': 'charge'}, {'quantity': 'temperature'},
                                   {'quantity': 'temperature', 'observed_quantity': 'charge', 'explicit_quantity_binding': True}])
def test_celsius_conversion_requires_a_confirmed_temperature_binding(context):
    if context.get('quantity') != 'temperature':
        identity = resolve_unit_relation('C', 'C', **context)
        assert identity['canonical_from_unit'] == identity['canonical_to_unit'] == 'C'
        assert identity['kind'] == 'identity' and identity['factor'] == 1 and identity['offset'] == 0
    for source, target in [('C', 'K'), ('K', 'C'), ('C', '°C'), ('°C', 'C')]:
        with pytest.raises(DocumentError) as error:
            resolve_unit_relation(source, target, **context)
        assert error.value.reason_code == 'transform_unit_incompatible'


def test_exact_selected_user_temperature_fact_can_admit_legacy_celsius():
    relation = resolve_unit_relation('C', 'K', quantity='temperature', explicit_quantity_binding=True)
    assert relation['factor'] == 1 and relation['offset'] == 273.15 and relation['kind'] == 'conversion'
    with pytest.raises(DocumentError) as conflict:
        resolve_unit_relation('C', 'C', quantity='charge', observed_quantity='temperature')
    assert conflict.value.reason_code == 'transform_unit_incompatible'


@pytest.mark.parametrize('unit', ['C/s', 's/C', '(C/s)', 'C^2/s'])
def test_non_temperature_compounds_refuse_the_unmigrated_formatter_boundary(unit):
    with pytest.raises(DocumentError) as error:
        resolve_unit_relation(unit, unit, quantity='charge_rate', explicit_quantity_binding=True)
    assert error.value.reason_code == 'transform_unit_context_unsupported'
