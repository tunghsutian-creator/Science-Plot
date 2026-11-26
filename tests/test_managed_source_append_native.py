"""Generated real native append acceptance through cold public CLI processes."""

from managed_plot_helpers import read_managed_head_and_ir
from socket_fixture_helpers import socket_directory

from copy import deepcopy
import json
import math
import os
from pathlib import Path
import signal
import shutil
import subprocess

import pytest
from test_figure_document import request_for_figure
from test_managed_source_append import append_request

from sciplot_core._paths import REPO_ROOT
from sciplot_core.foundation.file_hashing import file_sha256
from sciplot_core.plot_engine.service import PlotService
from sciplot_core.plot_engine.storage import load_head, transaction_path
from sciplot_core.project_lifecycle.context import repository_scope
from sciplot_core.project_lifecycle.repository_router import ComposedProjectRepository
from sciplot_core.plot_ir.figure_document import figure_spec


def _cli(tmp_path, action, plot=None, request=None, *, success=True, arguments=(), direct=True):
    command = [str(REPO_ROOT / 'skill/scripts/sciplot'), 'plot', action]
    if plot is not None:
        command.append(str(plot))
    if request is not None:
        request_file = tmp_path / f'cli-{action}.json'
        request_file.write_text(json.dumps(request))
        command.extend(['--request', str(request_file)])
    process = subprocess.run([*command, *arguments, '--json', *(['--direct'] if direct else [])], capture_output=True,
                             text=True, cwd=REPO_ROOT, timeout=180, check=False)
    if process.returncode != (0 if success else 1):
        diagnostic = REPO_ROOT / f'.tmp_verify/managed-source-append/unexpected-{action}.json'
        diagnostic.parent.mkdir(parents=True, exist_ok=True)
        diagnostic.write_text(json.dumps({'command': command, 'returncode': process.returncode,
                                         'stdout': process.stdout, 'stderr': process.stderr}, indent=2))
    assert process.returncode == (0 if success else 1), process.stdout + process.stderr
    return json.loads(process.stdout)


@pytest.mark.comprehensive
def test_public_source_replacement_reviews_same_curve_without_overwriting_either_original(tmp_path):
    source = tmp_path / 'acquisition-A-v1.csv'
    unaffected = tmp_path / 'acquisition-B.csv'
    revised = tmp_path / 'acquisition-A-v2.csv'
    wrong_unit = tmp_path / 'acquisition-A-wrong-unit.csv'
    source.write_text('Time,Mass\ns,%\nA,A\n0,100\n10,98\n20,95\n')
    unaffected.write_text('Time,Mass\ns,%\nB,B\n1,99\n8,97\n15,96\n23,94\n')
    revised.write_text('Time,Mass\ns,%\nA,A\n0,100\n9,97\n20,95\n')
    wrong_unit.write_text(revised.read_text().replace('s,%', 's,mg'))
    originals = {path: path.read_bytes() for path in (source, unaffected, revised, wrong_unit)}
    request = tmp_path / 'create.json'
    request.write_text(json.dumps({'version': 1, 'action': 'create', 'sources': [str(source), str(unaffected)],
        'intent': {'x': {'quantity': 'time', 'unit': 's'}, 'y': {'quantity': 'mass', 'unit': '%'},
                   'labels': ['Cooling A', 'Cooling B']}, 'formats': ['pdf']}))
    created = subprocess.run([str(REPO_ROOT / 'skill/scripts/sciplot'), 'task', 'start', '--request', str(request),
        '--task-dir', str(tmp_path / 'task'), '--json'], cwd=REPO_ROOT, capture_output=True, text=True, timeout=180, check=False)
    assert created.returncode == 0, created.stdout + created.stderr
    plot = Path(json.loads(created.stdout)['project'])
    before, before_ir = read_managed_head_and_ir(plot)
    original, untouched = before['document']['scientific']['data_sources']
    assert original['path'] == str(source) and untouched['path'] == str(unaffected)
    target = 'source:' + original['source_id']
    contract = _cli(tmp_path, 'describe', plot,
                    arguments=('--scope', 'edit', '--target-id', target, '--property', 'source.sha256'))
    descriptor = contract['figure_edit_contract'][target]['source.sha256']
    assert any('replacement_path' in shape.get('required', []) for shape in descriptor['value_schema']['oneOf'])

    def replace(path, key, revision=0):
        value = deepcopy(contract['current_value'])
        assert value['unit_context_bindings']
        value.update(replacement_path=str(path), sha256=file_sha256(path))
        for member in value['unit_context_bindings']:
            member.update(source_path=str(path), source_sha256=value['sha256'])
        return {'plot_id': before['document']['plot_id'], 'base_revision': revision, 'idempotency_key': key,
                'intent_class': 'scientific',
                'changes': [{'op': 'set', 'target': [target], 'property': 'source.sha256', 'value': value}]}

    incompatible = _cli(tmp_path, 'patch', plot, replace(wrong_unit, 'wrong-unit'), success=False)
    assert incompatible['reason_code'] == 'managed_unit_lineage_unsupported'
    assert load_head(plot)['document'] == before['document'] and not transaction_path(plot, 'wrong-unit').exists()
    pending = _cli(tmp_path, 'patch', plot, replace(revised, 'rejected'))
    assert pending['status'] == 'needs_review' and pending['plot_id'] == before['document']['plot_id']
    assert all(Path(pending[name]['path']).is_file() for name in ('before_preview', 'preview'))
    assert load_head(plot)['document'] == before['document']
    rejected = _cli(tmp_path, 'decide', plot, {**pending['next_step']['request'], 'accept': False})
    assert rejected['status'] == 'rejected' and load_head(plot)['document'] == before['document']

    pending = _cli(tmp_path, 'patch', plot, replace(revised, 'accepted'))
    accepted = _cli(tmp_path, 'decide', plot, pending['next_step']['request'])
    assert accepted['ready_to_use'] and accepted['revision'] == 1 and accepted['plot_id'] == before['document']['plot_id']
    head, ir = read_managed_head_and_ir(plot)
    assert head['document']['scientific']['data_sources'] == [
        {**original, 'path': str(revised), 'sha256': file_sha256(revised)}, untouched]
    assert ir['datasets'][untouched['source_id']] == before_ir['datasets'][untouched['source_id']]
    replacement = ir['datasets'][original['source_id']]['columns']
    assert replacement['column:0']['values'] == [0, 9, 20] and replacement['column:0']['unit'] == 's'
    assert replacement['column:1']['values'] == [100, 97, 95] and replacement['column:1']['unit'] == '%'
    original_layers = figure_spec(before['document'])['views'][0]['layers']
    assert figure_spec(head['document'])['views'][0]['layers'] == original_layers
    assert {path: path.read_bytes() for path in originals} == originals
    cold = _cli(tmp_path, 'open', plot, arguments=('--scope', 'summary'))
    assert cold['status'] == 'current' and (cold['plot_id'], cold['revision']) == (accepted['plot_id'], 1)
    stale = _cli(tmp_path, 'patch', plot, replace(revised, 'stale'), success=False)
    assert stale['reason_code'] == 'document_revision_conflict' and load_head(plot)['document'] == head['document']


@pytest.mark.comprehensive
def test_cold_cli_append_review_tamper_reject_accept_repeat_and_export(tmp_path):
    created = _cli(tmp_path, 'create', request=request_for_figure(tmp_path))
    assert created['ready_to_use'], created
    plot = Path(created['plot'])
    initial = load_head(plot)
    source_a = Path(initial['document']['scientific']['data_sources'][0]['path'])
    bytes_a = source_a.read_bytes()
    style = {'plot_id': created['plot_id'], 'base_revision': 0, 'idempotency_key': 'original-custom-style',
        'intent_class': 'presentation', 'changes': [
            {'op': 'set', 'target': ['mark:line'], 'property': 'style', 'value': {'line_color': '#2277aa', 'line_width_pt': 1.8}},
            {'op': 'set', 'target': ['axis:xb'], 'property': 'axis.label', 'value': 'Custom frequency display'},
            {'op': 'set', 'target': ['guide:legend'], 'property': 'legend.location', 'value': 'bottom-left'}]}
    styled = _cli(tmp_path, 'patch', plot, style)
    assert styled['ready_to_use'] and styled['revision'] == 1, styled
    before = load_head(plot)
    _, before_ir = read_managed_head_and_ir(plot)
    before_spec = figure_spec(before['document'])
    contract = _cli(tmp_path, 'describe', plot, arguments=('--scope', 'edit', '--target-id', 'view:A', '--property', 'source.append'))
    assert contract['next_step']['intent_class'] == 'scientific'

    request = append_request(before['document'], tmp_path)
    source_b = Path(request['changes'][0]['value']['source']['path'])
    bytes_b = source_b.read_bytes()
    query = deepcopy(request)
    query['changes'][0]['value'] = {'source': {key: request['changes'][0]['value']['source'][key]
                                              for key in ('source_id', 'path')}}
    before_files = {str(path): file_sha256(path) for path in Path(before['binding']['output']).rglob('*') if path.is_file()}
    transactions = list((plot / 'transactions').glob('*.json'))
    source_facts = _cli(tmp_path, 'patch', plot, query, success=False)
    assert source_facts['reason_code'] == 'managed_append_source_confirmation_required'
    assert source_facts['repair']['next_step']['idempotency_key'] == request['idempotency_key']
    assert not transaction_path(plot, request['idempotency_key']).exists()
    assert load_head(plot) == before and list((plot / 'transactions').glob('*.json')) == transactions
    assert {str(path): file_sha256(path) for path in Path(before['binding']['output']).rglob('*') if path.is_file()} == before_files
    pending = _cli(tmp_path, 'patch', plot, request)
    assert pending['status'] == 'needs_review' and pending['revision'] == 2, pending
    assert load_head(plot) == before
    selected = ComposedProjectRepository()
    with repository_scope(selected), selected.query_scope(plot):
        review = selected.read(Path(pending['evidence']))['review']
    assert pending['before_preview'] == review['before_preview']
    assert pending['source_append_evidence'] == {'path': pending['evidence'], 'json_pointer': '/review/source_append'}
    assert review['scientific_audit']['status'] == review['source_append']['before_scientific_audit']['status'] == 'passed'
    assert len(review['source_append']['before_layer_ids']) == 1
    assert len(review['source_append']['candidate_layer_ids']) == 2
    for image in (review['before_preview'], review['preview']):
        assert file_sha256(Path(image['path'])) == image['sha256']
    repeated_pending = _cli(tmp_path, 'patch', plot, request)
    assert repeated_pending['decision_id'] == pending['decision_id']
    assert repeated_pending['preview'] == pending['preview']
    assert load_head(plot) == before

    source_b.write_text(source_b.read_text().replace('8,7,', '8,6,'))
    blocked = _cli(tmp_path, 'decide', plot, pending['next_step']['request'], success=False)
    assert blocked['reason_code'] == 'document_inputs_changed'
    assert load_head(plot) == before
    source_b.write_bytes(bytes_b)
    rejected = _cli(tmp_path, 'decide', plot, {**pending['next_step']['request'], 'accept': False})
    assert rejected['status'] == 'rejected' and load_head(plot) == before
    assert _cli(tmp_path, 'patch', plot, request)['status'] == 'rejected'

    accepted_request = deepcopy(request)
    accepted_request['idempotency_key'] = 'append-B-accepted'
    accepted_preview = _cli(tmp_path, 'patch', plot, accepted_request)
    accepted = _cli(tmp_path, 'decide', plot, accepted_preview['next_step']['request'])
    assert accepted['ready_to_use'] and accepted['revision'] == 2, accepted
    assert accepted['plot_id'] == created['plot_id']
    replay = _cli(tmp_path, 'patch', plot, accepted_request)
    assert replay['replayed'] and replay['ready_to_use'] and replay['revision'] == 2
    current, ir = read_managed_head_and_ir(plot)
    spec = figure_spec(current['document'])
    assert spec['views'][0]['layers'][0] == before_spec['views'][0]['layers'][0]
    assert spec['views'][0]['axes'] == before_spec['views'][0]['axes']
    assert spec['scales'] == before_spec['scales']
    assert spec['guides'][0]['location'] == 'bottom-left'
    for identifier, dataset in before_ir['datasets'].items():
        assert ir['datasets'][identifier] == dataset
    assert ir['datasets']['raw:B']['columns']['column:1']['values'] == [7, None, 3, 9]
    assert ir['datasets']['raw:B']['provenance']['sources'][0]['rows'] == [3, 4, 5, 6]

    next_request = append_request(current['document'], tmp_path, 'C')
    next_preview = _cli(tmp_path, 'patch', plot, next_request)
    final = _cli(tmp_path, 'decide', plot, next_preview['next_step']['request'])
    assert final['ready_to_use'] and final['revision'] == 3 and final['plot_id'] == created['plot_id'], final
    rollback = _cli(tmp_path, 'rollback', plot, {'base_revision': 3, 'target_revision': 1,
                    'idempotency_key': 'explicit-scientific-history-boundary'}, success=False)
    assert rollback['reason_code'] == 'document_scientific_rollback_unsupported'
    assert load_head(plot)['document']['revision'] == 3
    exported = _cli(tmp_path, 'export', plot)
    assert exported['ready_to_use'] and exported['revision'] == 3
    assert {item['format'] for item in exported['exports']} >= {'pdf', 'tiff_300', 'vsz'}
    assert source_a.read_bytes() == bytes_a and source_b.read_bytes() == bytes_b
    final_head = load_head(plot)
    assert len(final_head['document']['scientific']['data_sources']) == 3
    assert len(final_head['document']['scientific']['provenance']['source_appends']) == 2
    report = REPO_ROOT / '.tmp_verify/managed-source-append/native-cli.json'
    report.parent.mkdir(parents=True, exist_ok=True)
    report.write_text(json.dumps({'scope': 'generated tables; cold CLI --direct; real native compiler and scientific audits',
        'plot_id': created['plot_id'], 'plot': str(plot), 'contract': contract,
        'pending': pending, 'review': review, 'rejected': rejected, 'accepted': accepted, 'replay': replay,
        'sequential_append': final, 'rollback_boundary': rollback, 'exported': exported}, indent=2))


@pytest.mark.comprehensive
def test_append_native_preview_interruption_recovers_same_request_without_duplicate_members(tmp_path, monkeypatch):
    class ProcessInterrupted(BaseException):
        pass

    service = PlotService()
    try:
        created = service.create(request_for_figure(tmp_path))
        assert created['ready_to_use'], created
        plot = Path(created['plot'])
        before = load_head(plot)
        request = append_request(before['document'], tmp_path)
        native_preview = service.backend.managed.preview
        calls = []

        def interrupted(*args, **kwargs):
            review = native_preview(*args, **kwargs)
            calls.append(review)
            raise ProcessInterrupted('Candidate and audit finished; preview receipt was lost.')

        monkeypatch.setattr(service.backend.managed, 'preview', interrupted)
        with pytest.raises(ProcessInterrupted):
            service.patch(plot, request)
        assert load_head(plot) == before and len(calls) == 1
        monkeypatch.setattr(service.backend.managed, 'preview', native_preview)
        recovered = service.patch(plot, request)
        assert recovered['status'] == 'needs_review' and load_head(plot) == before
        accepted = service.decide(plot, recovered['next_step']['request'])
        assert accepted['ready_to_use'] and accepted['revision'] == 1, accepted
        current = load_head(plot)['document']
        assert len(current['scientific']['data_sources']) == len(figure_spec(current)['views'][0]['layers']) == 2
        assert len(current['scientific']['provenance']['source_appends']) == 1
        assert service.patch(plot, request)['replayed']
    finally:
        service.close()


@pytest.mark.comprehensive
def test_public_ordinary_cooling_task_cold_append_keeps_source_and_native_arrays(tmp_path, monkeypatch):
    from sciplot_core.plot_backends.managed_audit import scientific_audit
    from sciplot_core.plot_backends.native_primitives import dataset_name
    from sciplot_core.plot_protocol.paths import read_owner
    from sciplot_core.veusz_worker.document_edit import loaded_native_document

    source_a = tmp_path / 'cooling-A.csv'
    source_b = tmp_path / 'cooling-B.csv'
    source_a.write_text('Temperature,Heat Flow\n°C,W/g\nSample A,Sample A\n66,-0.023\n61,0.008\n61,\n53,-0.016\n')
    source_b.write_text('Temperature,Heat Flow\n°C,W/g\nSample B,Sample B\n68,-0.02\n65,0.009\n60,\n60,-0.006\n51,-0.01\n')
    original = {str(path): file_sha256(path) for path in (source_a, source_b)}
    intent = {'x': {'quantity': 'temperature', 'unit': '°C', 'direction': 'descending', 'minimum': 50, 'maximum': 70},
              'y': {'quantity': 'heat_flow', 'unit': 'W/g', 'minimum': -.03, 'maximum': .015},
              'labels': ['Cooling A'], 'source_context': 'User states this is cooling; retain original values without correction, normalization or integration.'}
    request_file = tmp_path / 'ordinary-cooling.json'
    request_file.write_text(json.dumps({'version': 1, 'action': 'create', 'sources': [str(source_a)],
        'intent': intent, 'summary_statistic': 'raw_only', 'curve_display': 'raw_overlay'}))
    with socket_directory(prefix='spappend-', dir='/tmp', endpoints=('engine.sock', 'cold-engine.sock')) as temporary:
        socket = Path(temporary) / 'engine.sock'
        monkeypatch.setenv('SCIPLOT_ENGINE_SOCKET', str(socket))
        server_pid = None
        try:
            process = subprocess.run([str(REPO_ROOT / 'skill/scripts/sciplot'), 'task', 'start', '--request', str(request_file),
                '--task-dir', str(tmp_path / 'cooling-task'), '--json'], cwd=REPO_ROOT, capture_output=True,
                text=True, timeout=180, check=False)
            assert process.returncode == 0, process.stdout + process.stderr
            created = json.loads(process.stdout)
            assert created['status'] == 'complete', created
            assert not socket.exists(), "An ordinary task must use its invocation-local owner."
            plot = Path(created['project'])
            _cli(tmp_path, 'open', plot, arguments=('--scope', 'summary'), direct=False)
            server_pid = read_owner(socket)['pid']
            initial = load_head(plot)
            assert initial['document']['scientific']['provenance']['managed']['rule_id'] == 'ordinary_xy'
            assert initial['document']['scientific']['provenance']['binding']['semantic_task']['intent'] == intent
            old_layer = figure_spec(initial['document'])['views'][0]['layers'][0]
            style = {'plot_id': initial['document']['plot_id'], 'base_revision': 0, 'idempotency_key': 'cooling-A-style',
                'intent_class': 'presentation', 'changes': [{'op': 'set', 'target': [old_layer['marks'][0]['id']],
                    'property': 'style', 'value': {'line_color': '#2277aa', 'line_width_pt': 1.7}},
                    {'op': 'set', 'target': ['axis:x'], 'property': 'axis.label', 'value': 'Sample temperature (°C)'},
                    {'op': 'set', 'target': ['guide:legend'], 'property': 'legend.location', 'value': 'bottom-left'}]}
            styled = _cli(tmp_path, 'patch', plot, style, direct=False)
            assert styled['ready_to_use'], styled
            before, before_ir = read_managed_head_and_ir(plot)
            before_spec = figure_spec(before['document'])
            query = {'plot_id': initial['document']['plot_id'], 'base_revision': styled['revision'],
                'idempotency_key': 'cooling-add-B', 'intent_class': 'scientific', 'changes': [{'op': 'set',
                'target': ['view:main'], 'property': 'source.append', 'value': {'source': {'source_id': 'raw:B', 'path': str(source_b)}}}]}
            facts = _cli(tmp_path, 'patch', plot, query, direct=False, success=False)
            assert facts['reason_code'] == 'managed_append_source_confirmation_required', facts
            region = facts['repair']['candidates'][0]['table_selection']
            complete = deepcopy(query)
            complete['changes'][0]['value'] = {'source': {'source_id': 'raw:B', 'path': str(source_b),
                'sha256': facts['repair']['source_sha256'], 'table_selection': region},
                'curves': [{'sample': 'Sample B', 'x_column_index': 0, 'y_column_index': 1,
                           'label': 'Cooling B', 'color': '#ee6677', 'line_width_pt': 1.1}],
                'source_context': 'The user confirms B is a separate original cooling acquisition.'}
            preview = _cli(tmp_path, 'patch', plot, complete, direct=False)
            assert preview['status'] == 'needs_review', preview
            accepted = _cli(tmp_path, 'decide', plot, preview['next_step']['request'], direct=False)
            assert accepted['ready_to_use'] and accepted['plot_id'] == initial['document']['plot_id'], accepted
            first_pid = server_pid
            os.kill(first_pid, signal.SIGTERM)
            server_pid = None
            # Use a fresh owned endpoint, so a cold engine cannot race the old
            # server's asynchronous signal/connection shutdown on its socket.
            socket = Path(temporary) / 'cold-engine.sock'
            monkeypatch.setenv('SCIPLOT_ENGINE_SOCKET', str(socket))
            cold = _cli(tmp_path, 'open', plot, arguments=('--scope', 'summary'), direct=False)
            server_pid = read_owner(socket)['pid']
            assert server_pid != first_pid
            assert cold['plot_id'] == accepted['plot_id'] and cold['revision'] == 2
            assert cold['status'] == 'current'
            exported = _cli(tmp_path, 'export', plot, direct=False)
            assert exported['ready_to_use'] and exported['revision'] == 2
            current, ir = read_managed_head_and_ir(plot)
            spec = figure_spec(current['document'])
            assert spec['views'][0]['layers'][0] == before_spec['views'][0]['layers'][0]
            assert spec['views'][0]['axes'] == before_spec['views'][0]['axes'] and spec['scales'] == before_spec['scales']
            assert spec['guides'][0]['location'] == 'bottom-left'
            assert current['document']['scientific']['provenance']['managed']['rule_id'] == 'ordinary_xy'
            for identifier, dataset in before_ir['datasets'].items():
                assert ir['datasets'][identifier] == dataset
            new_layer = ir['views'][0]['layers'][-1]
            with loaded_native_document(Path(current['binding']['document'])) as loaded:
                assert scientific_audit(ir, loaded)['status'] == 'passed'
                old_data = loaded.data[dataset_name(old_layer['dataset_id'], 'x')].data.tolist()
                assert old_data == [66., 61., 61., 53.]
                assert loaded.data[dataset_name(new_layer['dataset_id'], 'column:0')].data.tolist() == [68., 65., 60., 60., 51.]
                values = loaded.data[dataset_name(new_layer['dataset_id'], 'column:1')].data.tolist()
                assert values[:2] == [-.02, .009] and math.isnan(values[2]) and values[3:] == [-.006, -.01]
            assert {str(path): file_sha256(path) for path in (source_a, source_b)} == original
            report = REPO_ROOT / '.tmp_verify/managed-source-append/ordinary-cooling-native.json'
            report.parent.mkdir(parents=True, exist_ok=True)
            report.write_text(json.dumps({'scope': 'generated original cooling tables; public task + AF_UNIX; real reopened native arrays',
                'created': created, 'facts': facts, 'preview': preview, 'accepted': accepted,
                'cold_open': cold, 'exported': exported, 'source_sha256': original}, indent=2))
        finally:
            for startup_log in Path(temporary).glob('*.log'):
                retained = REPO_ROOT / '.tmp_verify/managed-source-append' / ('ordinary-cooling-' + startup_log.name)
                retained.parent.mkdir(parents=True, exist_ok=True)
                shutil.copyfile(startup_log, retained)
            if server_pid is not None:
                os.kill(server_pid, signal.SIGTERM)
