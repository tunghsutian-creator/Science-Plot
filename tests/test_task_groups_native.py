from __future__ import annotations

import json
import os
from pathlib import Path
import subprocess
import sys

import anyio
import pytest

from sciplot_core._paths import REPO_ROOT
from sciplot_core.foundation.file_hashing import file_sha256


def cli(*arguments):
    result = subprocess.run([str(REPO_ROOT / 'skill/scripts/sciplot'), *map(str, arguments), '--json'],
                            cwd=REPO_ROOT, capture_output=True, text=True, timeout=240)
    assert result.returncode == 0, result.stdout + result.stderr
    return json.loads(result.stdout)


def write(path, value):
    path.write_text(json.dumps(value, ensure_ascii=False))
    return path


@pytest.mark.comprehensive
@pytest.mark.parametrize('transport', ['cli', 'mcp'])
def test_experiment_group_native_creation_style_review_and_resume(tmp_path, transport):
    origin, uvvis, ftir = [tmp_path / name for name in ('origin_UVvis.csv', 'UVvis.csv', 'FTIR.csv')]
    uv = ('Wavelength,Absorbance,Wavelength,Absorbance\nnm,a.u.,nm,a.u.\nE0,E0,E2,E2\n'
          '400,1,400,2\n450,3,450,4\n500,2,500,3\n')
    origin.write_text(uv)
    uvvis.write_text(uv)
    ftir.write_text('Wavenumber,Absorbance,Wavenumber,Absorbance\ncm-1,a.u.,cm-1,a.u.\nE2,E2,E0,E0\n'
                    '1000,2,1000,1\n1250,3,1250,2\n1500,2,1500,1\n')
    raw = {p: p.read_bytes() for p in (origin, uvvis, ftir)}
    prepared = cli('task', 'start', '--request', write(tmp_path / 'origin.json', {
        'version': 1, 'action': 'create', 'source': str(origin)}), '--task-dir', tmp_path / 'origin')
    figure = cli('task', 'inspect', prepared['task_dir'])['current_project']['figures'][0]
    edit = cli('task', 'start', '--request', write(tmp_path / 'edit.json', {
        'version': 1, 'action': 'edit', 'project': prepared['project'],
        'expected_document_sha256': figure['document_sha256'], 'export': False,
        'operations': [{'op': 'set_sample_style', 'samples': ['E0','E2'], 'style': {'width': '2pt', 'color': '#7B61A8'}}]}),
        '--task-dir', tmp_path / 'edit')
    cli('task', 'resume', edit['task_dir'], '--response', write(tmp_path / 'accept.json', {
        'accept_preview': True, 'expected_operation_id': edit['operation_id']}))
    preset = cli('project', 'style-capture', prepared['project'], '--out', tmp_path / 'preset')
    request = {'version': 1, 'title': 'Two experiments', 'sample_style_preset': {
        'preset': preset['preset'], 'expected_preset_sha256': preset['preset_sha256']}, 'items': [
        {'id': 'uvvis', 'label': 'UV–vis', 'request': {'version': 1, 'action': 'create', 'source': str(uvvis)}},
        {'id': 'ftir', 'label': 'FTIR', 'request': {'version': 1, 'action': 'create', 'source': str(ftir)}}]}
    group = tmp_path / 'group'

    def validate_pending(result):
        assert result['counts'] == {'needs_review': 2} and len(result['previews']) == 2
        assert all(image['scope'] == 'candidate' for image in result['previews'])
        for item in result['items']:
            assert item['task']['scientific_audit_status'] == 'passed'
            assert item['task']['changes']
        return [{'item_id': item['id'], 'task_dir': item['task_dir'], 'response': {
            'accept_preview': True, 'expected_operation_id': item['task']['operation_id']}} for item in result['items']]

    if transport == 'cli':
        pending = cli('task', 'group', 'start', '--request', write(tmp_path / 'experiments.json', request), '--group-dir', group)
        answers = validate_pending(pending)
        result = cli('task', 'group', 'resume', group, '--responses', write(tmp_path / 'responses.json', answers))
        again = cli('task', 'group', 'resume', group)
    else:
        from mcp import Client
        from mcp.client.stdio import StdioServerParameters

        async def scenario():
            parameters = StdioServerParameters(command=sys.executable, args=['-m', 'sciplot_core.mcp_server'],
                cwd=REPO_ROOT, env={**os.environ, 'PYTHONPATH': str(REPO_ROOT / 'src')})
            async with Client(parameters, read_timeout_seconds=240) as client:
                response = await client.call_tool('sciplot_group_start', {'request': request, 'group_dir': str(group)})
                assert not response.is_error, response.content
                pending = response.structured_content
                answers = validate_pending(pending)
                assert len(pending['preview_resources']) == 2
                for preview in pending['preview_resources']:
                    image = await client.call_tool('sciplot_read_result', {'uri': preview['uri']})
                    assert image.content[1].type == 'image'
                response = await client.call_tool('sciplot_group_resume', {'group': str(group), 'responses': answers})
                assert not response.is_error, response.content
                result = response.structured_content
            # New connection recovers group context without relying on resource URIs or chat.
            async with Client(parameters, read_timeout_seconds=240) as client:
                response = await client.call_tool('sciplot_group_inspect', {'group': str(group)})
                assert not response.is_error, response.content
                return result, response.structured_content
        result, again = anyio.run(scenario)

    assert result['status'] == again['status'] == 'complete'
    assert all(p['scope'] == 'saved' for p in result['previews'])
    assert Path(result['overview']).is_file() and result['model_calls_by_sciplot'] == 0
    assert all(path.read_bytes() == contents for path, contents in raw.items())
    for item in result['items']:
        assert item['source_current'] is True
        assert all(item['current_evidence'][key]['current'] for key in ('source','qa','delivery'))
        project = cli('project', 'inspect', item['project'], '--figure', item['figures'][0]['figure_id'])['selected_figure']
        for sample in project['sample_styles']:
            path = sample['object_paths'][0]
            fields = {f['setting_path']: f['current_value'] for f in project['objects'][path]['editable_fields']}
            assert fields[path + '/PlotLine/width'] == '2pt'
            assert fields[path + '/PlotLine/color'] == '#7B61A8'
        later = next(i for i in again['items'] if i['id'] == item['id'])
        assert item['figures'][0]['document_sha256'] == later['figures'][0]['document_sha256']
        assert file_sha256(Path(item['figures'][0]['document'])) == item['figures'][0]['document_sha256']
