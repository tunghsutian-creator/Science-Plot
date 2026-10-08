"""Managed authority guards use the public lifecycle and never bypass pending work."""

from copy import deepcopy
from pathlib import Path

import pytest

from managed_plot_helpers import patch, request_for_source
from sciplot_core.plot_engine.errors import EngineError
from sciplot_core.plot_engine.service import PlotService
from sciplot_core.plot_engine.storage import load_head, transaction_path


@pytest.mark.comprehensive
def test_managed_noop_pending_creation_replay_and_simultaneous_input_drift(tmp_path):
    request = request_for_source(tmp_path)
    service = PlotService()
    try:
        created = service.create(request)
        assert created['ready_to_use'], created
        root = Path(created['plot'])
        initial = service.describe(root)
        before = load_head(root)
        noop = service.patch(root, patch(initial, 'same-theme', 'theme', request['theme'], 'figure:main'))
        assert noop['changed'] is False and noop['revision'] == 0
        assert load_head(root) == before

        mixed = patch(initial, 'mixed', 'theme', request['theme'], 'figure:main', scientific=True)
        mixed['changes'].append({'op': 'set', 'target': ['transform:normalize-A'],
            'property': 'transform.parameters', 'value': {'columns': ['column:1'], 'method': 'first', 'output_unit': '1'}})
        with pytest.raises(EngineError) as error:
            service.patch(root, mixed)
        assert error.value.reason_code == 'managed_mixed_update'
        assert not transaction_path(root, 'mixed').exists() and load_head(root) == before

        review = service.patch(root, patch(initial, 'legend-review', 'legend.position', [.6, .8], 'legend:main'))
        assert review['status'] == 'needs_review', review
        with pytest.raises(EngineError) as pending:
            service.create(request)
        assert pending.value.reason_code == 'document_transaction_pending'
        assert load_head(root) == before
        service.decide(root, {**review['next_step']['request'], 'accept': False})
        assert service.create(request)['ready_to_use']

        source = Path(request['data_binding']['data_sources'][0]['path'])
        source.write_text(source.read_text().replace('2,8', '2,6'))
        native = Path(before['binding']['document'])
        native.write_text(native.read_text() + '\n# external save\n')
        description = service.describe(root)
        assert description['status'] == 'stale'
        assert {str(source), str(native)} <= set(description['changed_inputs'])
        assert {'source:A', 'transform:normalize-A', 'compile', 'render', 'export'} <= set(description['dependencies']['invalidated'])
        assert description['next_step']['automatic_adoption'] is False
        assert load_head(root) == before
    finally:
        service.close()


def test_unused_external_executor_is_rejected_before_creation_side_effects(tmp_path):
    from sciplot_core.plot_engine.managed_resolution import resolved_metadata
    from sciplot_core.plot_ir import create_managed_document

    request = request_for_source(tmp_path)
    document = create_managed_document(request['template_definition'], request['data_binding'], plot_id='test')
    before = deepcopy(document)
    with pytest.raises(EngineError) as error:
        resolved_metadata(document, rule_id=request['rule_id'], executors={'unused': {}})
    assert error.value.reason_code == 'managed_executor_membership'
    assert document == before
