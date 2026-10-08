"""Additive Figure grammar authority shares existing Binding, storage and revisions."""
from copy import deepcopy

import pytest

from sciplot_core.foundation.file_hashing import file_sha256
from sciplot_core.plot_document import DocumentError, seal_document, build_keys
from sciplot_core.plot_engine.content_store import intern_document
from sciplot_core.plot_engine.contracts import validate_create
from sciplot_core.plot_engine.managed_updates import prepare_update
from sciplot_core.plot_ir import create_managed_document, compile_document, validate_managed
from sciplot_core.plot_transforms.graph import dependency_graph
from test_figure_grammar import example


def request_for_figure(tmp_path):
    spec, datasets = example()
    source = tmp_path / 'figure.csv'
    source.write_text('Frequency,Modulus\nHz,Pa\n0,1\n5,5\n10,15\n')
    selection = {'sheet': None, 'header_rows': [0], 'unit_row': 1, 'data_start_row': 2, 'data_end_row': 5}
    binding = {'kind': 'sciplot_binding', 'schema_version': 1, 'template_id': 'fixture',
        'data_sources': [{'source_id': 'raw:A', 'path': str(source), 'sha256': file_sha256(source), 'table_selection': selection}],
        'slots': {'modulus': {'series_id': 'layer:modulus', 'sample': 'Modulus',
            'x': {'source_id': 'raw:A', 'column': 'Frequency', 'column_index': 0},
            'y': {'source_id': 'raw:A', 'column': 'Modulus', 'column_index': 1}, 'x_unit': 'Hz', 'y_unit': 'Pa'}},
        'transforms': [], 'guards': {}, 'provenance': {}}
    return {'idempotency_key': 'figure-create', 'template_definition': {'kind': 'sciplot_figure_template',
        'schema_version': 2, 'template_id': 'fixture', 'figure_spec': spec}, 'data_binding': binding, 'rule_id': 'uvvis_spectrum'}


def test_figure_document_complete_coverage_binding_and_cas(tmp_path):
    request = validate_create(request_for_figure(tmp_path))
    doc = create_managed_document(request['template_definition'], request['data_binding'], plot_id='test')
    compact = intern_document(tmp_path / 'store', doc, minimum_bytes=2)
    assert compact['scientific']['provenance']['figure_spec'] == doc['scientific']['provenance']['figure_spec']
    validate_managed(compact)
    for field in ['layout', 'theme', 'objects']:
        bad = deepcopy(doc)
        bad['presentation'][field]['extra'] = {}
        with pytest.raises(DocumentError):
            validate_managed(seal_document(bad))
    bad = deepcopy(doc)
    bad['scientific']['mappings']['layer:modulus']['y']['column_index'] = 0
    with pytest.raises(DocumentError):
        validate_managed(seal_document(bad))


def test_scale_domain_invalidates_compile_without_reexecuting_science(tmp_path):
    request = request_for_figure(tmp_path)
    doc = create_managed_document(request['template_definition'], request['data_binding'], plot_id='test')
    _, datasets = example()
    doc['scientific']['provenance']['datasets'] = datasets
    doc = seal_document(doc)
    patch = {'plot_id': 'test', 'base_revision': 0, 'idempotency_key': 'domain', 'intent_class': 'scientific',
        'changes': [{'op': 'set', 'target': ['scale:x'], 'property': 'scale.domain', 'value': [0, 20]}]}
    updated, diff, risk, execute = prepare_update(doc, patch)
    assert risk == 'scientific' and not execute and diff
    before, after = (build_keys(dependency_graph(item, datasets)) for item in (doc, updated))
    assert {key for key in before if before[key] != after[key]} == {'compile', 'render', 'export'}
    assert compile_document(updated)['schema_version'] == 2
    patch['intent_class'] = 'presentation'
    with pytest.raises(ValueError):
        prepare_update(doc, patch)


def test_layer_consumes_existing_normalization_executor_output(tmp_path):
    from sciplot_core.plot_transforms import builtin_executor, resolve_transforms
    from sciplot_core.plot_engine.managed_sources import load_sources

    request = request_for_figure(tmp_path)
    spec = request['template_definition']['figure_spec']
    spec['views'][0]['layers'][0]['dataset_id'] = 'normalized'
    spec['scales'][1].update(unit='1', domain=[0, 1.2])
    spec['views'][0]['axes'][1]['ticks'] = [0, .5, 1]
    binding = request['data_binding']
    mapping = binding['slots']['modulus']
    for axis in ('x','y'):
        mapping[axis]['source_id'] = 'normalized'
    mapping['y_unit'] = '1'
    binding['transforms'] = [{'id':'normalize','kind':'normalize','inputs':['raw:A'],'output':'normalized',
        'parameters':{'columns':['column:1'],'method':'max_abs','output_unit':'1'},
        'executor':builtin_executor(),'determinism':'deterministic'}]
    doc = create_managed_document(request['template_definition'], binding, plot_id='test')
    resolved = resolve_transforms(doc, load_sources(doc, 'uvvis_spectrum'))
    ir = compile_document(resolved['document'])
    assert ir['views'][0]['layers'][0]['dataset_id'] == 'normalized'
    assert ir['datasets']['normalized']['columns']['column:1']['values'] == [1/15, 5/15, 1]
    assert ir['datasets']['normalized']['provenance']['transforms'][0]['node_id'] == 'normalize'
