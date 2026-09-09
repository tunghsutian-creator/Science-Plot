from __future__ import annotations

import json
import os
from pathlib import Path
import sys

import anyio
import pytest

from sciplot_core._paths import REPO_ROOT
from sciplot_core.foundation.file_hashing import file_sha256
from sciplot_core.studio_core.document_edit_state import edit_state
from sciplot_core.task_storage import load_task
from test_sample_style_presets_native import cli, task


@pytest.mark.comprehensive
@pytest.mark.parametrize('transport', ['cli', 'mcp'])
def test_compare_native_alternatives_from_one_baseline_then_select_only_one(tmp_path, transport):
    source = tmp_path / 'UVvis.csv'
    source.write_text('Wavelength,Absorbance,Wavelength,Absorbance\nnm,a.u.,nm,a.u.\n'
                      'E0,E0,E2,E2\n400,1,400,2\n450,3,450,4\n500,2,500,3\n')
    original = source.read_bytes()
    created = task(tmp_path, 'create', {'version': 1, 'action': 'create', 'source': str(source)})
    project = Path(created['project'])
    figure = cli('task', 'inspect', created['task_dir'])['current_project']['figures'][0]
    spec_before = json.loads(Path(figure['spec']).read_text())
    before = edit_state(project)
    request = {'version': 1, 'title': 'Native alternatives', 'project': str(project),
               'figure_id': figure['figure_id'], 'expected_document_sha256': figure['document_sha256'],
               'export': True, 'candidates': [
                   {'id': name, 'label': name, 'operations': [{'op': 'set_sample_style', 'samples': ['E0', 'E2'],
                     'style': {'width': width, 'color': color}}]}
                   for name, width, color in [('a', '0.7pt', '#777777'), ('b', '2pt', '#3568C0'), ('c', '3pt', '#C43F50')]]}
    root = tmp_path / 'comparison'

    def pending_checks(result):
        assert result['status'] == 'needs_selection' and result['baseline_current'] and len(result['previews']) == 4
        assert all(c['selectable'] and c['change_count'] > 0 for c in result['candidates'])
        assert all(c['scientific_audit_status'] == 'passed' for c in result['candidates'])
        assert edit_state(project) == before
        for candidate in result['candidates']:
            review = json.loads(Path(candidate['review_path']).read_text())
            assert review['base_state'] == before and review['document_sha256'] == figure['document_sha256']
        return {'candidate_id': 'b', 'expected_comparison_id': result['comparison_id']}

    if transport == 'cli':
        manifest = tmp_path / 'alternatives.json'
        manifest.write_text(json.dumps(request))
        result = cli('task', 'compare', 'start', '--request', manifest, '--comparison-dir', root)
        selection = pending_checks(result)
        assert cli('task', 'compare', 'inspect', root)['comparison_id'] == result['comparison_id']
        assert cli('task', 'compare', 'resume', root)['comparison_id'] == result['comparison_id']
        path = tmp_path / 'selection.json'
        path.write_text(json.dumps(selection))
        final = cli('task', 'compare', 'select', root, '--selection', path)
        after = edit_state(project)
        assert cli('task', 'compare', 'select', root, '--selection', path)['status'] == 'complete'
        assert edit_state(project) == after
    else:
        from mcp import Client
        from mcp.client.stdio import StdioServerParameters

        async def scenario():
            parameters = StdioServerParameters(command=sys.executable, args=['-m', 'sciplot_core.mcp_server'],
                cwd=REPO_ROOT, env={**os.environ, 'PYTHONPATH': str(REPO_ROOT / 'src')})
            async with Client(parameters, read_timeout_seconds=240) as client:
                response = await client.call_tool('sciplot_comparison_start', {'request': request, 'comparison_dir': str(root)})
                assert not response.is_error, response.content
                result = response.structured_content
                selection = pending_checks(result)
                assert {p['candidate_id'] for p in result['preview_resources']} == {'baseline', 'a', 'b', 'c'}
                for preview in result['preview_resources']:
                    image = await client.call_tool('sciplot_read_result', {'uri': preview['uri']})
                    assert image.content[1].type == 'image'
            async with Client(parameters, read_timeout_seconds=240) as client:
                response = await client.call_tool('sciplot_comparison_inspect', {'comparison': str(root)})
                assert response.structured_content['comparison_id'] == result['comparison_id']
                response = await client.call_tool('sciplot_comparison_select', {'comparison': str(root), 'selection': selection})
                assert not response.is_error, response.content
                final = response.structured_content
                after = edit_state(project)
                again = await client.call_tool('sciplot_comparison_resume', {'comparison': str(root)})
                assert again.structured_content['status'] == 'complete' and edit_state(project) == after
                return final
        final = anyio.run(scenario)

    assert final['status'] == 'complete' and final['selection']['candidate_id'] == 'b'
    assert all(final['current_evidence'][key]['current'] for key in ('source', 'qa', 'delivery'))
    assert source.read_bytes() == original
    assert load_task(root / 'candidates/a')['status'] == load_task(root / 'candidates/c')['status'] == 'needs_review'
    selected = cli('project', 'inspect', project, '--figure', figure['figure_id'])['selected_figure']
    for sample in selected['sample_styles']:
        path = sample['object_paths'][0]
        fields = {f['setting_path']: f['current_value'] for f in selected['objects'][path]['editable_fields']}
        assert fields[path + '/PlotLine/width'] == '2pt' and fields[path + '/PlotLine/color'] == '#3568C0'
    spec_after = json.loads(Path(figure['spec']).read_text())
    for old, new in zip(spec_before['series'], spec_after['series'], strict=True):
        for field in ('label', 'x_values', 'y_values'):
            assert new[field] == old[field]
    assert file_sha256(Path(figure['document'])) == final['selection_outcome']['document_sha256']
