from __future__ import annotations

import base64
import copy
import json
from pathlib import Path

import pytest

from sciplot_core.foundation.file_hashing import file_sha256
from sciplot_core.foundation.source_tree import source_tree_sha256
from sciplot_core.task_contract import TaskControlError
from sciplot_core import task_groups as groups, task_group_review as review
from sciplot_core.task_group_contract import normalize_group_request
from sciplot_core.task_storage import load_task, save_task
from sciplot_core._paths import REPO_ROOT


PNG = base64.b64decode('iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+jRZkAAAAASUVORK5CYII=')


@pytest.fixture
def case(tmp_path, monkeypatch):
    requests = []
    for name in ['a', 'b']:
        source = tmp_path / (name + '.csv')
        source.write_text('Time,Force\ns,N\nA,A\n0,1\n1,2\n')
        requests.append({'id': name, 'label': name, 'request': {
            'version': 1, 'action': 'create', 'source': str(source)}})
    request = {'version': 1, 'title': 'Experiments', 'items': requests}
    calls, renders, resumes = [], [], []
    projects = {}

    def inspect(project):
        project = str(project)
        figures = []
        for index in range(2):
            path = projects[project][index]
            figures.append({'figure_id': f'f{index}', 'document': str(path),
                            'spec': str(path.with_suffix('.json')), 'document_sha256': file_sha256(path), 'spec_sha256': 'b' * 64})
        return {'project': project, 'primary_figure_id': 'f0', 'figures': figures,
                'ready_to_use': True, 'source': {}, 'qa': {}, 'delivery': {}}

    def start(task, *, task_dir):
        calls.append(copy.deepcopy(task))
        task_dir.mkdir(parents=True)
        state = {'kind': 'sciplot_task', 'version': 1, 'task_dir': str(task_dir), 'request': task,
                 'status': 'complete', 'phase': 'finished', 'source_sha256': None}
        if task['action'] == 'create':
            source = Path(task['source'])
            state['source_sha256'] = source_tree_sha256(source)
            if source.stem == 'ask':
                state.update(status='needs_input', phase='planning', question={'message': 'Choose experiment'})
            else:
                project = tmp_path / 'projects' / source.stem
                project.mkdir(parents=True)
                paths = [project / f'f{i}.vsz' for i in range(2)]
                for path in paths:
                    path.write_text('test native owner fixture')
                projects[str(project)] = paths
                state['project'] = str(project)
        else:
            state['project'] = task['project']
            if task['action'] == 'edit':
                image = task_dir / 'candidate.png'
                image.write_bytes(PNG)
                state.update(status='needs_review', phase='review', operation_id='c' * 64, preview={
                    'image': {'path': str(image), 'sha256': file_sha256(image)},
                    'review_path': str(task_dir / 'review.json'), 'changes': [], 'scientific_audit': {'status': 'passed'}})
                (task_dir / 'review.json').write_text(json.dumps({'operation_id': 'c' * 64,
                    'base_state': {'project_files': {task['figure_id'] + '.json': 'b' * 64}}}))
        save_task(task_dir, state)
        return state

    def resume(path, answer):
        resumes.append((str(path), answer))
        state = load_task(path)
        if state['status'] == 'complete':
            return state
        if answer.get('accept_preview'):
            if answer['expected_operation_id'] != state['operation_id']:
                raise TaskControlError('stale_task_preview', 'stale')
            state.update(status='complete', result={'status': 'saved'})
            index = int(state['request']['figure_id'][1:])
            projects[state['project']][index].write_text('edited by fake native owner')
        else:
            state.update(status='cancelled')
        save_task(path, state)
        return state

    def preview(project, *, figure_id, output_dir):
        renders.append((str(project), figure_id))
        output_dir.mkdir(parents=True)
        image = output_dir / 'current.png'
        image.write_bytes(PNG)
        figure = next(f for f in inspect(project)['figures'] if f['figure_id'] == figure_id)
        return {'project': str(project), 'figure_id': figure_id,
                'document': {'path': figure['document'], 'sha256': figure['document_sha256']},
                'preview': {'path': str(image), 'sha256': file_sha256(image)}}

    monkeypatch.setattr(groups, 'start_task', start)
    monkeypatch.setattr(groups, 'resume_task', resume)
    monkeypatch.setattr(groups, 'inspect_project', inspect)
    monkeypatch.setattr(review, 'inspect_project', inspect)
    monkeypatch.setattr(review, 'preview_project_document', preview)
    return request, tmp_path / 'group', calls, renders, resumes


def test_multiple_experiments_create_once_and_reuse_current_native_previews(case):
    request, root, calls, renders, _ = case
    result = groups.start_group(request, group_dir=root)
    assert result['status'] == 'complete' and result['ready_to_use'] is None
    assert result['readiness_evaluated'] is False
    assert all(item['source_current'] for item in result['items'])
    assert len(result['previews']) == 4 and len(calls) == 2 and len(renders) == 4
    assert groups.start_group(request, group_dir=root)['status'] == 'complete'
    assert groups.resume_group(root)['status'] == 'complete'
    assert len(calls) == 2 and len(renders) == 4
    before = root.joinpath('group.json').read_bytes()
    assert groups.inspect_group(root)['status'] == 'complete'
    assert root.joinpath('group.json').read_bytes() == before
    assert len(renders) == 4


def test_question_in_one_item_does_not_stop_other_experiments(case):
    request, root, calls, _, _ = case
    source = Path(request['items'][0]['request']['source']).with_name('ask.csv')
    source.write_text('unclassified')
    request['items'][0]['request']['source'] = str(source)
    result = groups.start_group(request, group_dir=root)
    assert result['counts'] == {'needs_input': 1, 'complete': 1}
    assert len(calls) == 2 and len(result['previews']) == 2
    assert result['items'][0]['task']['question']['message'] == 'Choose experiment'
    groups.resume_group(root)
    assert len(calls) == 2


def test_lost_child_reply_recovers_receipt_without_creating_twice(case, monkeypatch):
    request, root, calls, _, _ = case
    original = groups.start_task

    def lost(task, *, task_dir):
        original(task, task_dir=task_dir)
        if task['source'].endswith('a.csv'):
            raise RuntimeError('reply lost after child saved')

    monkeypatch.setattr(groups, 'start_task', lost)
    result = groups.start_group(request, group_dir=root)
    assert result['counts'] == {'blocked': 1, 'complete': 1}
    item = result['items'][0]
    result = groups.resume_group(root, [{'item_id': 'a', 'task_dir': item['task_dir'], 'response': {'retry': True}}])
    assert result['status'] == 'complete' and len(calls) == 2


def test_shared_preset_reviews_all_figures_then_exports_each_project_once(case):
    request, root, calls, _, _ = case
    request['sample_style_preset'] = {'preset': str(root.parent / 'styles.json'), 'expected_preset_sha256': 'd' * 64}
    result = groups.start_group(request, group_dir=root)
    assert result['counts'] == {'needs_review': 2}
    assert len([p for p in result['previews'] if p['scope'] == 'candidate']) == 2
    for _ in range(2):
        answers = [{'item_id': i['id'], 'task_dir': i['task_dir'], 'response': {
            'accept_preview': True, 'expected_operation_id': i['task']['operation_id']}} for i in result['items']]
        result = groups.resume_group(root, answers)
    assert result['status'] == 'complete'
    assert [call['action'] for call in calls].count('edit') == 4
    assert [call['action'] for call in calls].count('export') == 2
    assert all(call['export'] is False for call in calls if call['action'] == 'edit')
    assert all(p['scope'] == 'saved' for p in result['previews'])


def test_changed_input_or_preview_cannot_reuse_old_readiness_or_image(case):
    request, root, calls, renders, _ = case
    result = groups.start_group(request, group_dir=root)
    Path(result['previews'][0]['preview']['path']).write_bytes(b'altered')
    assert len(groups.inspect_group(root)['previews']) == 4 and len(renders) == 5
    groups.inspect_group(root)
    assert len(renders) == 5
    Path(request['items'][0]['request']['source']).write_text('changed measurements')
    result = groups.inspect_group(root)
    assert result['ready_to_use'] is None and result['items'][0]['source_current'] is False
    assert len(calls) == 2


@pytest.mark.parametrize('change', ['duplicate', 'unsafe_id', 'extra_field', 'bad_operation', 'too_many'])
def test_invalid_manifest_fails_before_any_output(case, change):
    request, root, calls, _, _ = case
    if change == 'duplicate':
        request['items'][1]['id'] = 'a'
    elif change == 'unsafe_id':
        request['items'][0]['id'] = '../a'
    elif change == 'extra_field':
        request['automatic_accept'] = True
    elif change == 'bad_operation':
        request['items'][0]['request'] = {'version': 1, 'action': 'edit', 'project': '/p',
            'expected_document_sha256': 'a' * 64, 'operations': [{'op': 'delete_data'}]}
    else:
        request['items'] = request['items'] * 17
    with pytest.raises(ValueError):
        groups.start_group(request, group_dir=root)
    assert not root.exists() and calls == []


def test_group_location_and_cross_item_outputs_cannot_overlap_inputs(case):
    request, root, calls, _, _ = case
    with pytest.raises(ValueError, match='重叠'):
        groups.start_group(request, group_dir=root.parent)
    request['items'][1]['request']['out'] = request['items'][0]['request']['source']
    with pytest.raises(ValueError, match='重叠'):
        groups.start_group(request, group_dir=root)
    assert not root.exists() and calls == []


def test_same_output_for_two_items_is_rejected_before_execution(case):
    request, root, calls, _, _ = case
    for item in request['items']:
        item['request']['out'] = str(root.parent / 'same')
    with pytest.raises(ValueError, match='独立'):
        groups.start_group(request, group_dir=root)
    assert calls == [] and not root.exists()


def test_responses_are_bound_to_current_children_and_validated_before_any_apply(case):
    request, root, _, _, resumes = case
    request['sample_style_preset'] = {'preset': '/styles.json', 'expected_preset_sha256': 'd' * 64}
    result = groups.start_group(request, group_dir=root)
    answers = [{'item_id': i['id'], 'task_dir': i['task_dir'], 'response': {
        'accept_preview': True, 'expected_operation_id': i['task']['operation_id']}} for i in result['items']]
    wrong = copy.deepcopy(answers)
    wrong[1]['task_dir'] += '_old'
    with pytest.raises(ValueError, match='子任务已变化'):
        groups.resume_group(root, wrong)
    assert resumes == []
    wrong = copy.deepcopy(answers)
    del wrong[1]['response']['expected_operation_id']
    with pytest.raises(ValueError, match='expected_operation_id'):
        groups.resume_group(root, wrong)
    assert resumes == []
    groups.resume_group(root, answers)
    with pytest.raises(ValueError, match='子任务已变化'):
        groups.resume_group(root, answers)


def test_relative_manifest_paths_are_resolved_once_without_mutating_the_request(case):
    request, root, _, _, _ = case
    request['items'][0]['request']['source'] = 'a.csv'
    before = copy.deepcopy(request)
    normalized = normalize_group_request(request, base_dir=root.parent)
    assert normalized['items'][0]['request']['source'] == str(root.parent / 'a.csv')
    assert request == before


def test_gallery_escapes_titles_and_has_only_local_image_links(case):
    request, root, _, _, _ = case
    request['title'] = '<script>alert(1)</script>'
    request['items'][0]['label'] = '<img src=x onerror=alert(1)>'
    result = groups.start_group(request, group_dir=root)
    html = Path(result['overview']).read_text()
    assert '<script>' not in html and 'onerror=alert(1)>' not in html
    assert '&lt;script&gt;' in html and 'src="previews/' in html


def test_changed_receipt_or_manifest_cannot_overwrite_an_existing_group(case):
    request, root, calls, _, _ = case
    groups.start_group(request, group_dir=root)
    request['title'] = 'another request'
    with pytest.raises(ValueError, match='另一份清单'):
        groups.start_group(request, group_dir=root)
    path = root / 'group.json'
    value = json.loads(path.read_text())
    value['request']['title'] = 'altered'
    path.write_text(json.dumps(value))
    with pytest.raises(ValueError, match='记录已变化'):
        groups.inspect_group(root)
    assert len(calls) == 2


def test_documented_manifest_uses_the_public_group_contract(tmp_path):
    path = REPO_ROOT / 'skill/references/experiment-group.json'
    value = normalize_group_request(json.loads(path.read_text()), base_dir=tmp_path)
    assert len(value['items']) == 2
    assert value['items'][0]['request']['source'] == str(tmp_path / 'inputs/FTIR')
