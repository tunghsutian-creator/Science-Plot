"""Additive Figure grammar authority shares existing Binding, storage and revisions."""
from copy import deepcopy
from pathlib import Path

import pytest
from test_figure_grammar import example

from sciplot_core.foundation.file_hashing import file_sha256
from sciplot_core.plot_document import DocumentError, build_keys, seal_document
from sciplot_core.plot_engine.content_store import intern_document
from sciplot_core.plot_engine.contracts import validate_create
from sciplot_core.plot_engine.errors import EngineError
from sciplot_core.plot_engine.managed_updates import prepare_update
from sciplot_core.plot_engine.service import PlotService
from sciplot_core.plot_engine.storage import load_head, read
from sciplot_core.plot_ir import (
    compile_document,
    create_managed_document,
    validate_managed,
)
from sciplot_core.plot_transforms.graph import dependency_graph


def request_for_figure(tmp_path):
    spec, _datasets = example()
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


def test_v2_source_revision_recompiles_explicit_changed_values_and_units(tmp_path):
    from sciplot_core.plot_engine.managed_resolution import (
        resolve_science,
        resolved_metadata,
    )
    from sciplot_core.plot_engine.managed_state import resolved_ir

    request = request_for_figure(tmp_path)
    source = tmp_path / 'figure.csv'
    document = create_managed_document(request['template_definition'], request['data_binding'], plot_id='test')
    document = resolved_metadata(document, rule_id=request['rule_id'], executors={})
    document, _ = resolve_science(tmp_path, document)
    before = resolved_ir(tmp_path, document)
    assert before['datasets']['raw:A']['columns']['column:1']['values'] == [1, 5, 15]

    source.write_text(source.read_text().replace('5,5\n', '5,7\n'))
    revised_bytes = source.read_bytes()
    patch = {'plot_id': 'test', 'base_revision': 0, 'idempotency_key': 'v2-source-revision',
        'intent_class': 'scientific', 'changes': [{'op': 'set', 'target': ['source:raw:A'],
            'property': 'source.sha256', 'value': file_sha256(source)}]}
    updated, diff, risk, execute = prepare_update(document, patch)
    assert diff and risk == 'scientific' and execute
    updated, _ = resolve_science(tmp_path, updated)
    after = resolved_ir(tmp_path, updated)
    assert after['schema_version'] == 2 and after['ir_hash'] != before['ir_hash']
    assert after['scientific_hash'] != before['scientific_hash']
    assert after['presentation_hash'] == before['presentation_hash']
    assert after['datasets']['raw:A']['columns']['column:0'] == before['datasets']['raw:A']['columns']['column:0']
    values = after['datasets']['raw:A']['columns']['column:1']
    assert values['values'] == [1, 7, 15] and values['unit'] == 'Pa'
    repeated, repeated_diff, _, _ = prepare_update(updated, patch)
    assert repeated == updated and repeated_diff == []
    assert resolved_ir(tmp_path, repeated)['ir_hash'] == after['ir_hash']
    assert source.read_bytes() == revised_bytes


def test_layer_consumes_existing_normalization_executor_output(tmp_path):
    from sciplot_core.plot_engine.managed_sources import load_sources
    from sciplot_core.plot_transforms import builtin_executor, resolve_transforms

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


@pytest.mark.comprehensive
def test_figure_service_patch_and_source_refresh_keep_scientific_authority(tmp_path):
    """Synthetic v2 data: edit display, then explicitly accept changed source bytes."""
    request = request_for_figure(tmp_path)
    source = tmp_path / 'figure.csv'
    service = PlotService()
    try:
        created = service.create(request)
        assert created['ready_to_use'], created
        root = Path(created['plot'])
        initial = load_head(root)
        initial_ir = read(Path(initial['binding']['ir_path']))
        assert initial_ir['datasets']['raw:A']['columns']['column:1']['values'] == [1, 5, 15]

        def change(description, key, prop, value, target, intent='presentation'):
            return {'plot_id': description['plot_id'], 'base_revision': description['revision'],
                'idempotency_key': key, 'intent_class': intent,
                'changes': [{'op': 'set', 'target': [target], 'property': prop, 'value': value}]}

        label = change(created, 'axis-label', 'axis.label', 'Frequency, Hz', 'axis:xb')
        edited = service.patch(root, label)
        assert edited['ready_to_use'] and edited['revision'] == 1, edited
        assert edited['scientific_hash'] == created['scientific_hash']
        assert edited['presentation_hash'] != created['presentation_hash']
        edited_head = load_head(root)
        edited_ir = read(Path(edited_head['binding']['ir_path']))
        assert edited_head['binding']['ir_hash'] != initial['binding']['ir_hash']
        assert edited_ir['datasets'] == initial_ir['datasets']

        no_op = service.patch(root, change(edited, 'same-axis-label', 'axis.label',
                                           'Frequency, Hz', 'axis:xb'))
        assert no_op['ready_to_use'] and no_op['changed'] is False and no_op['revision'] == 1
        assert no_op['scientific_hash'] == edited['scientific_hash']
        assert no_op['presentation_hash'] == edited['presentation_hash']
        assert load_head(root)['binding'] == edited_head['binding']

        source.write_text(source.read_text().replace('5,5\n', '5,7\n'))
        revised_bytes = source.read_bytes()
        assert service.describe(root)['status'] == 'stale'
        with pytest.raises(EngineError) as stale:
            service.patch(root, change(edited, 'stale-axis-label', 'axis.label',
                                       'Revised frequency', 'axis:xb'))
        assert stale.value.reason_code == 'document_inputs_changed'
        assert load_head(root)['document']['revision'] == 1

        refreshed = service.patch(root, change(edited, 'source-revision', 'source.sha256',
                                               file_sha256(source), 'source:raw:A', 'scientific'))
        assert refreshed['ready_to_use'] and refreshed['revision'] == 2, refreshed
        assert refreshed['scientific_hash'] != edited['scientific_hash']
        assert refreshed['presentation_hash'] == edited['presentation_hash']
        final = load_head(root)
        current_ir = read(Path(final['binding']['ir_path']))
        assert current_ir['schema_version'] == 2
        columns = current_ir['datasets']['raw:A']['columns']
        assert columns['column:0']['values'] == [0, 5, 10]
        assert columns['column:0']['unit'] == 'Hz'
        assert columns['column:1']['values'] == [1, 7, 15]
        assert columns['column:1']['unit'] == 'Pa'
        assert final['document']['scientific']['data_sources'][0]['sha256'] == file_sha256(source)
        assert read(Path(refreshed['evidence']))['export']['scientific_audit']['status'] == 'passed'
        assert current_ir['views'] == edited_ir['views']
        assert source.read_bytes() == revised_bytes
        assert service.describe(root)['status'] == 'current'
    finally:
        service.close()
