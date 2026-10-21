"""Public task/plot processes retain original arrays through ordinary continuation."""

from socket_fixture_helpers import socket_directory
import csv
import json
import math
import os
from pathlib import Path
import shutil
import signal
import subprocess

import pytest
from test_managed_source_append_native import _cli
from test_ordinary_curve_intent import mass_source, paired_quantities, same_file_request
from test_series_display_native import _native_save

from sciplot_core._paths import REPO_ROOT
from sciplot_core.foundation.file_hashing import file_sha256
from sciplot_core.plot_backends.managed_audit import scientific_audit
from sciplot_core.plot_backends.native_primitives import dataset_name
from sciplot_core.plot_engine.storage import load_head, read
from sciplot_core.plot_ir.figure_document import figure_spec
from sciplot_core.plot_protocol.paths import read_owner
from sciplot_core.veusz_worker.document_edit import loaded_native_document


@pytest.mark.comprehensive
@pytest.mark.parametrize('mode', ['same_file', 'quantity_members'])
def test_public_ordinary_curve_intent_cold_continuation_native_arrays_and_replay(tmp_path, monkeypatch, mode):
    source, intent = mass_source(tmp_path) if mode == 'same_file' else paired_quantities(tmp_path)
    original = source.read_bytes()
    with socket_directory(prefix='spcurve-', dir='/tmp', endpoints=('engine.sock', 'cold.sock')) as temporary:
        socket = Path(temporary) / 'engine.sock'
        monkeypatch.setenv('SCIPLOT_ENGINE_SOCKET', str(socket))
        server_pid = None
        try:
            command = [str(REPO_ROOT / 'skill/scripts/sciplot'), 'task', 'create', '--source', str(source),
                       '--task-dir', str(tmp_path / 'task'), '--curve-display', 'raw_overlay',
                       '--summary-statistic', 'raw_only', '--out', str(tmp_path / 'delivery')]
            if mode == 'same_file':
                command += ['--x', 'molar_mass', '--x-header', 'Molar Mass', '--x-scale', 'log',
                            '--y', 'differential_weight_fraction', '--y-header', 'Differential Weight Fraction',
                            '--y-scale', 'linear', '--y-min', '0', '--y-max', '.5',
                            '--source-block', 'source:0/table:0/block:0', '--source-block', 'source:0/table:0/block:1']
            else:
                intent['display'] = {'marker_every': 2}
                intent_file = tmp_path / 'intent.json'
                intent_file.write_text(json.dumps(intent))
                command += ['--intent', str(intent_file)]
            process = subprocess.run([*command, '--json'], cwd=REPO_ROOT, capture_output=True, text=True, timeout=180)
            assert process.returncode == 0, process.stdout + process.stderr
            created = json.loads(process.stdout)
            assert created['status'] == 'complete', created
            server_pid = read_owner(socket)['pid']
            plot = Path(created['project'])
            head = load_head(plot)
            initial_ir = read(Path(head['binding']['ir_path']))
            spec = figure_spec(head['document'])
            layers = spec['views'][0]['layers']
            changes = [{'op': 'set', 'target': ['figure:main'], 'property': 'layout',
                        'value': {**spec['layout'], 'width_mm': 180}},
                       {'op': 'set', 'target': ['guide:legend'], 'property': 'legend.columns', 'value': 2},
                       {'op': 'set', 'target': ['guide:legend'], 'property': 'legend.location', 'value': 'top-right'}]
            for index, layer in enumerate(layers):
                changes += [{'op': 'set', 'target': [layer['id']], 'property': 'series.display_label',
                             'value': ('Amber' if index < (1 if mode == 'same_file' else 2) else 'Blue') +
                                      ((' Gp' if index % 2 == 0 else ' Gpp') if mode == 'quantity_members' else '')},
                            {'op': 'set', 'target': [layer['marks'][0]['id']], 'property': 'style',
                             'value': {'line_color': '#225599' if index < 2 else '#bb5500',
                                       'line_width_pt': 1.8 if index < 2 else 1.1,
                                       'line_style': 'dash' if mode == 'quantity_members' and index % 2 else 'solid'}},
                            {'op': 'set', 'target': [layer['marks'][1]['id']], 'property': 'style',
                             'value': {**layer['marks'][1]['style'], 'marker_color': '#225599' if index < 2 else '#bb5500'}}]
            if mode == 'same_file':
                changes.append({'op': 'set', 'target': [layers[1]['id']], 'property': 'series.visible', 'value': False})
            style = {'plot_id': head['document']['plot_id'], 'base_revision': 0, 'idempotency_key': 'authorized-display',
                     'intent_class': 'presentation', 'changes': changes}
            styled = _cli(tmp_path, 'patch', plot, style, direct=False)
            if styled['status'] == 'needs_review':
                assert styled['scientific_audit']['status'] == 'passed'
                styled = _cli(tmp_path, 'decide', plot, styled['next_step']['request'], direct=False)
            assert styled['ready_to_use'], styled
            before = load_head(plot)
            before_spec = figure_spec(before['document'])
            assert before['document']['scientific_hash'] == head['document']['scientific_hash']
            request = style
            accepted = styled
            if mode == 'same_file':
                request = same_file_request(before['document'], source)
                contract = _cli(tmp_path, 'describe', plot, arguments=('--scope', 'edit', '--target-id', 'view:main', '--property', 'source.append'), direct=False)
                assert contract['target_context']['sources'][0]['sha256'] == file_sha256(source)
                pending = _cli(tmp_path, 'patch', plot, request, direct=False)
                assert pending['status'] == 'needs_review' and load_head(plot) == before, pending
                recovered = _cli(tmp_path, 'patch', plot, request, direct=False)
                assert recovered['decision_id'] == pending['decision_id']
                accepted = _cli(tmp_path, 'decide', plot, recovered['next_step']['request'], direct=False)
                assert accepted['ready_to_use'], accepted
            first_pid = server_pid
            os.kill(first_pid, signal.SIGTERM)
            server_pid = None
            socket = Path(temporary) / 'cold.sock'
            monkeypatch.setenv('SCIPLOT_ENGINE_SOCKET', str(socket))
            cold = _cli(tmp_path, 'open', plot, arguments=('--scope', 'summary'), direct=False)
            server_pid = read_owner(socket)['pid']
            assert server_pid != first_pid and cold['status'] == 'current'
            assert cold['plot_id'] == head['document']['plot_id'] and cold['revision'] == accepted['revision']
            replay = _cli(tmp_path, 'patch', plot, request, direct=False)
            assert replay['replayed'] and replay['revision'] == accepted['revision']
            exported = _cli(tmp_path, 'export', plot, direct=False)
            assert exported['ready_to_use'] and exported['revision'] == accepted['revision'], exported
            current = load_head(plot)
            final = figure_spec(current['document'])
            ir = read(Path(current['binding']['ir_path']))
            assert final['views'][0]['layers'][:len(layers)] == before_spec['views'][0]['layers']
            for layer in final['views'][0]['layers']:
                assert layer['marks'][0]['style']['line_color'] == layer['marks'][1]['style']['marker_color']
            assert final['scales'] == before_spec['scales'] and final['guides'] == before_spec['guides']
            assert all(ir['datasets'][key] == dataset for key, dataset in initial_ir['datasets'].items())
            cells = list(csv.reader(original.decode().splitlines()))
            physical_rows = list(range(3, len(cells)))
            assert physical_rows == [3, 4, 5, 6]
            finite_pairs = []
            with loaded_native_document(Path(current['binding']['document'])) as native:
                audit = scientific_audit(ir, native)
                assert audit['status'] == 'passed', audit
                assert len(ir['views'][0]['layers']) == (3 if mode == 'same_file' else 4)
                for index, layer in enumerate(ir['views'][0]['layers']):
                    dataset = ir['datasets'][layer['dataset_id']]
                    provenance, = dataset['provenance']['sources']
                    assert provenance['sha256'] == file_sha256(source)
                    assert provenance['rows'] == physical_rows
                    assert provenance['column_indices'] == {f'column:{index * 2}': index * 2,
                                                            f'column:{index * 2 + 1}': index * 2 + 1}
                    expected_pair = []
                    for channel, original_column in (('x', index * 2), ('y', index * 2 + 1)):
                        column = layer['mappings'][channel]
                        expected = [float(cells[row][original_column]) if cells[row][original_column] else None
                                    for row in physical_rows]
                        resolved = dataset['columns'][column]['values']
                        actual = native.data[dataset_name(layer['dataset_id'], column)].data.tolist()
                        assert len(actual) == len(resolved) == len(expected) == len(physical_rows)
                        assert [value is None for value in resolved] == [value is None for value in expected]
                        assert [math.isnan(value) for value in actual] == [value is None for value in expected]
                        assert [None if value is None else float(value).hex() for value in resolved] == [
                            None if value is None else value.hex() for value in expected]
                        for value, original_value in zip(actual, expected, strict=True):
                            if original_value is not None:
                                assert math.isfinite(value) and value.hex() == original_value.hex()
                        expected_pair.append(expected)
                    finite_pairs.append(sum(x is not None and y is not None for x, y in zip(*expected_pair, strict=True)))
            if mode == 'quantity_members':
                assert [layer['mapping_semantics']['y'] for layer in final['views'][0]['layers']] == ['storage_modulus', 'loss_modulus'] * 2
                assert [len(ir['datasets'][layer['dataset_id']]['columns']['x']['values']) for layer in final['views'][0]['layers']] == [4, 4, 4, 4]
                assert finite_pairs == [4, 3, 2, 4]
            else:
                assert finite_pairs == [3, 2, 4]
                new_layer = final['views'][0]['layers'][-1]
                assert ir['datasets'][new_layer['dataset_id']]['columns']['column:4']['values'] == [12, 120, 120, 1100]
                assert ir['datasets'][new_layer['dataset_id']]['columns']['column:5']['values'] == [0, .4, .35, .1]
            assert source.read_bytes() == original
            native_path = Path(current['binding']['document'])
            native_bytes = native_path.read_bytes()
            _native_save(native_path)
            blocked = _cli(tmp_path, 'export', plot, direct=False, success=False)
            assert blocked.get('reason_code') and load_head(plot)['document']['revision'] == accepted['revision']
            native_path.write_bytes(native_bytes)
            source.write_bytes(original + b'\n')
            raw_blocked = _cli(tmp_path, 'export', plot, direct=False, success=False)
            assert raw_blocked.get('reason_code') and load_head(plot)['document']['revision'] == accepted['revision']
            source.write_bytes(original)
            report = REPO_ROOT / '.tmp_verify/ordinary-curve-intent' / (mode + '.json')
            report.parent.mkdir(parents=True, exist_ok=True)
            retained_exports = []
            for export in exported['exports']:
                target = report.parent / (mode + '-' + Path(export['path']).name)
                shutil.copyfile(export['path'], target)
                retained_exports.append({**export, 'retained_path': str(target)})
            (report.parent / (mode + '-ir.json')).write_text(json.dumps(ir, indent=2))
            report.write_text(json.dumps({'scope': 'generated original files; public task create; cold RPC owner; real native arrays',
                'created': created, 'styled': styled, 'accepted': accepted, 'cold': cold, 'replay': replay,
                'exported': exported, 'audit': audit, 'native_save_rejected': blocked, 'raw_drift_rejected': raw_blocked,
                'source_sha256': file_sha256(source), 'retained_exports': retained_exports}, indent=2))
        finally:
            for startup_log in Path(temporary).glob('*.log'):
                retained = REPO_ROOT / '.tmp_verify/ordinary-curve-intent' / (mode + '-' + startup_log.name)
                retained.parent.mkdir(parents=True, exist_ok=True)
                shutil.copyfile(startup_log, retained)
            if server_pid is not None:
                os.kill(server_pid, signal.SIGTERM)
