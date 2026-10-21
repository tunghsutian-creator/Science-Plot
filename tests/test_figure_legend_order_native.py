"""One generated native continuity proof for the existing guide-order projection."""

from copy import deepcopy
from pathlib import Path

import pytest
from test_figure_legend_order import LAYERS, legend_request, order_patch
from test_managed_source_append_native import _cli

from sciplot_core.foundation.file_hashing import file_sha256
from sciplot_core.plot_engine.storage import load_head, read
from sciplot_core.plot_ir.figure_document import figure_spec


@pytest.mark.comprehensive
def test_cold_public_legend_order_review_reject_replay_and_native_entries_preserve_all_science(tmp_path):
    from sciplot_core.plot_backends.figure_audit import scientific_audit
    from sciplot_core.plot_backends.figure_marks import graph_path
    from sciplot_core.plot_backends.native_primitives import dataset_name, native_name
    from sciplot_core.veusz_worker.document_edit import loaded_native_document

    request = legend_request(tmp_path)
    source = Path(request['data_binding']['data_sources'][0]['path'])
    source_bytes = source.read_bytes()
    created = _cli(tmp_path, 'create', request=request)
    assert created['ready_to_use'], created
    root = Path(created['plot'])
    before = load_head(root)
    before_ir = read(Path(before['binding']['ir_path']))
    edit = _cli(tmp_path, 'describe', root, arguments=('--scope', 'edit', '--target-id', 'guide:legend', '--property', 'legend.order'))
    assert edit['current_value'] == [] and edit['figure_edit_contract']['guide:legend']['legend.order']['risk'] == 'review'
    rejected_request = order_patch(before['document'], [LAYERS[2], LAYERS[0], LAYERS[1]], key='reject-legend-order')
    pending = _cli(tmp_path, 'patch', root, rejected_request)
    assert pending['status'] == 'needs_review' and load_head(root) == before
    rejected = _cli(tmp_path, 'decide', root, {**pending['next_step']['request'], 'accept': False})
    assert rejected['status'] == 'rejected' and load_head(root) == before
    accepted_request = deepcopy(rejected_request)
    accepted_request['idempotency_key'] = 'accept-legend-order'
    accepted_request['changes'].append({'op': 'set', 'target': [LAYERS[1]], 'property': 'series.visible', 'value': False})
    review = _cli(tmp_path, 'patch', root, accepted_request)
    assert review['status'] == 'needs_review' and load_head(root) == before
    accepted = _cli(tmp_path, 'decide', root, review['next_step']['request'])
    assert accepted['ready_to_use'] and accepted['revision'] == 1
    assert _cli(tmp_path, 'patch', root, accepted_request)['replayed']
    cold = _cli(tmp_path, 'open', root, arguments=('--scope', 'summary'))
    assert cold['revision'] == 1 and cold['scientific_hash'] == before['document']['scientific_hash']
    current = load_head(root)
    third = figure_spec(current['document'])['views'][0]['layers'][2]
    late = {'plot_id': current['document']['plot_id'], 'base_revision': current['document']['revision'],
        'idempotency_key': 'late-curve-width', 'intent_class': 'presentation', 'changes': [{'op': 'set',
        'target': [third['marks'][0]['id']], 'property': 'style',
        'value': {**third['marks'][0]['style'], 'line_width_pt': 2.0}}]}
    edited = _cli(tmp_path, 'patch', root, late)
    assert edited['ready_to_use'] and edited['revision'] == 2
    exported = _cli(tmp_path, 'export', root)
    assert exported['ready_to_use'] and exported['revision'] == 2
    final = load_head(root)
    ir = read(Path(final['binding']['ir_path']))
    assert ir['datasets'] == before_ir['datasets'] and ir['scales'] == before_ir['scales']
    assert final['document']['scientific_hash'] == before['document']['scientific_hash']
    assert figure_spec(final['document'])['guides'][0]['order'] == [LAYERS[2], LAYERS[0], LAYERS[1]]
    assert [entry['layer_id'] for entry in ir['guides'][0]['entries']] == [LAYERS[2], LAYERS[0]]
    with loaded_native_document(Path(final['binding']['document'])) as loaded:
        assert scientific_audit(ir, loaded)['status'] == 'passed'
        graph = loaded.resolveWidgetPath(None, graph_path('view:A'))
        key = graph.getChild(native_name('legend', 'guide:legend'))
        providers = key.settings.get('order').get().split(',')
        assert [graph.getChild(name).settings.get('key').get() for name in providers] == ['Curve 3', 'Curve 1']
        assert loaded.data[dataset_name('raw:A', 'column:0')].data.tolist() == [1., 2., 3.]
        for index, values in enumerate(([2., 4., 6.], [3., 5., 7.], [4., 6., 8.]), 1):
            assert loaded.data[dataset_name('raw:A', f'column:{index}')].data.tolist() == values
    assert source.read_bytes() == source_bytes and file_sha256(source) == request['data_binding']['data_sources'][0]['sha256']
