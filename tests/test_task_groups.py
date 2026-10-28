from __future__ import annotations

import base64
import copy
import json
from pathlib import Path

import pytest

from test_native_project_commands import edit as edit
from test_project_query import project as project

from sciplot_core.foundation.file_hashing import file_sha256
from sciplot_core.foundation.source_tree import source_tree_sha256
from sciplot_core.task_contract import TaskControlError
from sciplot_core import task_groups as groups, task_group_review as review
from sciplot_core.task_group_contract import normalize_group_request
from sciplot_core.task_storage import load_task, save_task
from sciplot_core.studio_core.source_update_commit import file_inventory
from sciplot_core._paths import REPO_ROOT


PNG = base64.b64decode('iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+jRZkAAAAASUVORK5CYII=')


def _sealed_group_review(edit, tmp_path, monkeypatch):
    from sciplot_core.studio_core.project_query import inspect_project

    selected, document, signed, calls = edit
    root, task = tmp_path / 'group', tmp_path / 'group/child'
    task.mkdir(parents=True)
    supplied = copy.deepcopy(signed)
    supplied['review_path'] = str(task / 'review.json')
    Path(supplied['review_path']).write_text(json.dumps(supplied))
    request = {'version': 1, 'action': 'edit', 'project': str(selected),
        'figure_id': signed['figure_id'], 'expected_document_sha256': signed['document_sha256'],
        'operations': [{'op': 'set_style', **change} for change in signed['changes']], 'export': False}
    child = {'kind': 'sciplot_task', 'version': 1, 'task_dir': str(task), 'request': request,
        'project': str(selected), 'status': 'needs_review', 'phase': 'review',
        'operation_id': signed['operation_id'], 'preview': {'image': signed['preview'],
            'review_path': supplied['review_path'], 'changes': signed['actual_changes'],
            'scientific_audit': signed['scientific_audit']}}
    save_task(task, child)
    item = {'id': 'selected', 'label': 'Selected', 'status': 'needs_review',
        'steps': [{'name': 'style_001', 'task_dir': str(task), 'request': request}]}
    state = {'request': {'title': 'Sealed review'}, 'updated_at': '2026-10-28T00:00:00+00:00', 'items': [item]}
    def current(path):
        result = inspect_project(path)
        result['figures'] = [figure for figure in result['figures'] if figure['figure_id'] == signed['figure_id']]
        return result
    monkeypatch.setattr(review, 'inspect_project', current)
    return root, state, child, document, calls


def test_group_gallery_uses_the_current_sealed_v3_candidate_without_native_or_repair(edit, tmp_path, monkeypatch):
    from sciplot_core.project_store import FileProjectStore

    root, state, child, document, calls = _sealed_group_review(edit, tmp_path, monkeypatch)
    head = (document.parents[1] / '.sciplot_store/head.json').read_bytes()
    before = document.read_bytes()
    monkeypatch.setattr(FileProjectStore, 'recover', lambda *_args: pytest.fail('Gallery cannot repair a project'))
    result = review.group_overview(root, state)
    assert result['counts'] == {'needs_review': 1}, result
    assert len(result['previews']) == 1 and result['previews'][0]['scope'] == 'candidate'
    projected = result['previews'][0]['preview']
    assert Path(projected['path']).is_relative_to(root)
    assert {key: value for key, value in projected.items() if key != 'path'} == {
        key: value for key, value in child['preview']['image'].items() if key != 'path'}
    assert Path(projected['path']).read_bytes() == Path(child['preview']['image']['path']).read_bytes()
    assert result['next_step']['responses_template'] == [{'item_id': 'selected', 'task_dir': child['task_dir'],
        'response': {'accept_preview': True, 'expected_operation_id': child['operation_id']}}]
    assert document.read_bytes() == before and len(calls) == 1
    assert (document.parents[1] / '.sciplot_store/head.json').read_bytes() == head


@pytest.mark.parametrize('change', ['native', 'spec', 'decision', 'intent', 'version', 'downgrade', 'legacy_hint', 'different_image', 'accepted', 'rejected', 'complete'])
def test_group_gallery_never_offers_a_stale_or_decided_v3_candidate(edit, tmp_path, monkeypatch, change):
    from sciplot_core.project_commands import ProjectCommand, ProjectCommands
    from sciplot_core.project_store import FileProjectStore
    from sciplot_core.studio_core.project_command_scope import project_store

    root, state, child, document, calls = _sealed_group_review(edit, tmp_path, monkeypatch)
    supplied = json.loads(Path(child['preview']['review_path']).read_text())
    if change in {'accepted', 'rejected', 'complete'}:
        store = project_store(document.parents[1])
        record = store.query(supplied['operation_id'])
        if change == 'accepted':
            store.decide(record['command_id'], record['command_digest'], decision_id=record['decision_id'], accept=True)
        else:
            ProjectCommands(store).decide(ProjectCommand.from_payload(record['metadata']),
                decision_id=record['decision_id'], accept=change == 'complete')
    elif change == 'native':
        document.write_bytes(document.read_bytes() + b'outside native save')
    elif change == 'spec':
        spec = document.with_name('spec.json')
        value = json.loads(spec.read_text())
        value['outside_change'] = True
        spec.write_text(json.dumps(value))
    elif change == 'different_image':
        image = root / 'different.png'
        image.write_bytes(Path(child['preview']['image']['path']).read_bytes())
        child['preview']['image'] = {**child['preview']['image'], 'path': str(image)}
        save_task(Path(child['task_dir']), child)
    else:
        if change == 'decision':
            supplied['decision_id'] = 'f' * 64
        elif change in {'version', 'downgrade'}:
            supplied['version'] = 3.0 if change == 'version' else 2
            supplied['base_state'] = {'project_files': {'studio/spec.json': file_sha256(document.with_name('spec.json'))}}
            if change == 'downgrade':
                supplied.pop('decision_id')
        elif change == 'legacy_hint':
            supplied['base_state'] = 'invalid v3 legacy hint'
        else:
            supplied['actual_changes'][0]['value'] = '99pt'
        Path(child['preview']['review_path']).write_text(json.dumps(supplied))
    before = document.read_bytes()
    head = (document.parents[1] / '.sciplot_store/head.json').read_bytes()
    monkeypatch.setattr(FileProjectStore, 'recover', lambda *_args: pytest.fail('Gallery cannot repair a project'))
    result = review.group_overview(root, state)
    assert result['previews'] == [] and result['next_step']['responses_template'] == []
    assert result['items'][0]['task']['next_step']['action'] == 'resolve_preview_evidence'
    assert document.read_bytes() == before and len(calls) == 1
    assert (document.parents[1] / '.sciplot_store/head.json').read_bytes() == head


@pytest.mark.parametrize('change', ['symlink', 'parent_replaced'])
def test_group_candidate_asset_projection_refuses_alias_or_replaced_parent(edit, tmp_path, monkeypatch, change):
    root, state, _child, document, calls = _sealed_group_review(edit, tmp_path, monkeypatch)
    foreign = tmp_path / 'foreign-assets'
    foreign.mkdir()
    (foreign / 'keep').write_bytes(b'foreign unchanged')
    if change == 'symlink':
        (root / 'previews').symlink_to(foreign, target_is_directory=True)
    else:
        opened = review.os.open
        def replace_parent(name, flags, *args, **kwargs):
            if flags & review.os.O_WRONLY and str(name).endswith('.png') and 'dir_fd' in kwargs:
                (root / 'previews').rename(root / 'preserved-assets')
                (root / 'previews').mkdir()
            return opened(name, flags, *args, **kwargs)
        monkeypatch.setattr(review.os, 'open', replace_parent)
    before = document.read_bytes()
    result = review.group_overview(root, state)
    assert result['previews'] == [] and result['next_step']['responses_template'] == []
    assert {path.name: path.read_bytes() for path in foreign.iterdir()} == {'keep': b'foreign unchanged'}
    if change == 'parent_replaced':
        assert list((root / 'previews').iterdir()) == []
    assert document.read_bytes() == before and len(calls) == 1


def test_group_candidate_projection_preserves_corrupt_display_copy_and_sealed_source(edit, tmp_path, monkeypatch):
    root, state, child, document, calls = _sealed_group_review(edit, tmp_path, monkeypatch)
    before = document.read_bytes()
    first = review.group_overview(root, state)
    cached = Path(first['previews'][0]['preview']['path'])
    sealed = Path(child['preview']['image']['path'])
    original = sealed.read_bytes()
    cached.unlink()
    cached.write_bytes(b'altered disposable gallery copy')
    second = review.group_overview(root, state)
    current = Path(second['previews'][0]['preview']['path'])
    assert current != cached and current.is_relative_to(root)
    assert current.read_bytes() == original == sealed.read_bytes()
    assert cached.read_bytes() == b'altered disposable gallery copy'
    assert current.stat().st_mode & 0o777 == 0o400
    assert child['preview']['image']['path'] == str(sealed) and len(calls) == 1
    assert document.read_bytes() == before


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

    def start(task, *, task_dir, defer_creation_export=False):
        calls.append(copy.deepcopy(task))
        task_dir.mkdir(parents=True)
        state = {'kind': 'sciplot_task', 'version': 1, 'task_dir': str(task_dir), 'request': task,
                 'status': 'complete', 'phase': 'finished', 'source_sha256': None}
        if task['action'] == 'create':
            source = Path(task['source'])
            state['source_sha256'] = source_tree_sha256(source)
            if source.stem == 'ask':
                state.update(status='needs_input', phase='planning', question={'field': 'rule_id', 'message': 'Choose experiment'})
            else:
                project = tmp_path / 'projects' / source.stem
                project.mkdir(parents=True)
                paths = [project / f'f{i}.vsz' for i in range(2)]
                for path in paths:
                    path.write_text('test native owner fixture')
                projects[str(project)] = paths
                state['project'] = str(project)
                if defer_creation_export:
                    state.update(phase='prepared', defer_creation_export=True,
                                 prepared_creation={'project': str(project), 'source_sha256': state['source_sha256'],
                                                    'files': file_inventory(project)},
                                 result={'status': 'prepared', 'export_performed': False, 'ready_to_use': False})
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


def with_presentations(request):
    for item in request['items']:
        item['presentation'] = {'figure_id': 'f0', 'operations': [{
            'op': 'add_annotation', 'id': 'sample_display', 'parent_path': '/page1/graph1',
            'text': item['label'], 'position': {'mode': 'relative', 'x': 0.1, 'y': 0.86}}]}
    return request


def test_create_presentations_prepare_once_review_together_and_export_only_after_acceptance(case):
    request, root, calls, _, _ = case
    with_presentations(request)
    result = groups.start_group(request, group_dir=root)
    assert result['counts'] == {'needs_review': 2}
    assert [call['action'] for call in calls] == ['create', 'edit', 'create', 'edit']
    assert all(call['export'] is False for call in calls if call['action'] == 'edit')
    for identifier in ('a', 'b'):
        prepared = load_task(root / 'tasks' / identifier / 'initial')
        assert prepared['phase'] == 'prepared' and prepared['result']['export_performed'] is False
    answers = result['next_step']['responses_template']
    assert len(answers) == 2
    assert all(answer['response'] == {'accept_preview': True, 'expected_operation_id': 'c' * 64}
               for answer in answers)
    result = groups.resume_group(root, answers)
    assert result['status'] == 'complete' and result['ready_to_use'] is None
    assert [call['action'] for call in calls].count('create') == 2
    assert [call['action'] for call in calls].count('export') == 2
    assert [(f['item_id'], f['figure_id']) for f in result['ordered_figures']] == [
        ('a', 'f0'), ('a', 'f1'), ('b', 'f0'), ('b', 'f1')]
    assert result['next_step']['paper_cli_argv_template'][4:6] == ['--group', str(root)]
    groups.start_group(request, group_dir=root)
    groups.resume_group(root)
    assert len(calls) == 6


def test_shared_preset_and_explicit_presentation_use_one_batch_for_the_selected_figure(case):
    request, root, calls, _, _ = case
    with_presentations(request)
    request['sample_style_preset'] = {'preset': '/styles.json', 'expected_preset_sha256': 'd' * 64}
    groups.start_group(request, group_dir=root)
    edits = [call for call in calls if call['action'] == 'edit']
    assert len(edits) == 2
    assert [op['op'] for op in edits[0]['operations']] == ['apply_sample_style_preset', 'add_annotation']
    assert edits[0]['figure_id'] == 'f0' and edits[0]['export'] is False


@pytest.mark.parametrize('selected', [None, 'missing'])
def test_unknown_or_ambiguous_presentation_figure_preserves_prepared_project(case, selected):
    request, root, calls, _, _ = case
    with_presentations(request)
    for item in request['items']:
        if selected is None:
            del item['presentation']['figure_id']
        else:
            item['presentation']['figure_id'] = selected
    result = groups.start_group(request, group_dir=root)
    assert result['counts'] == {'blocked': 2}
    assert all(item['blocker']['reason_code'] == (
        'group_figure_required' if selected is None else 'group_figure_not_found') for item in result['items'])
    assert [call['action'] for call in calls] == ['create', 'create']
    assert load_task(root / 'tasks/a/initial')['result']['export_performed'] is False


@pytest.mark.parametrize('changed', ['source', 'native'])
def test_changed_preparation_blocks_presentation_without_recreating_or_hiding_other_items(case, monkeypatch, changed):
    request, root, calls, _, _ = case
    with_presentations(request)
    original = groups.start_task

    def changed_after_checkpoint(task, **kwargs):
        result = original(task, **kwargs)
        if task['action'] == 'create' and Path(task['source']).stem == 'a':
            path = Path(task['source']) if changed == 'source' else Path(result['project']) / 'f0.vsz'
            path.write_text('external change after native checkpoint')
        return result

    monkeypatch.setattr(groups, 'start_task', changed_after_checkpoint)
    result = groups.start_group(request, group_dir=root)
    assert result['counts'] == {'blocked': 1, 'needs_review': 1}
    assert result['items'][0]['blocker']['reason_code'] == (
        'source_changed' if changed == 'source' else 'prepared_project_changed')
    assert [call['action'] for call in calls] == ['create', 'create', 'edit']


def test_missing_current_candidate_evidence_does_not_offer_a_batch_acceptance(case):
    request, root, _, _, _ = case
    with_presentations(request)
    pending = groups.start_group(request, group_dir=root)
    image = next(p for p in pending['previews'] if p['item_id'] == 'a' and p['scope'] == 'candidate')
    Path(image['preview']['path']).write_bytes(b'altered image')
    current = groups.inspect_group(root)
    assert current['items'][0]['task']['next_step']['action'] == 'resolve_preview_evidence'
    assert [answer['item_id'] for answer in current['next_step']['responses_template']] == ['b']


def test_changed_original_source_removes_preview_acceptance_guidance(case):
    request, root, _, _, _ = case
    with_presentations(request)
    groups.start_group(request, group_dir=root)
    Path(request['items'][0]['request']['source']).write_text('changed original measurements')
    current = groups.inspect_group(root)
    assert current['items'][0]['source_current'] is False
    assert current['items'][0]['task']['next_step']['action'] == 'resolve_source_change'
    assert [answer['item_id'] for answer in current['next_step']['responses_template']] == ['b']


@pytest.mark.parametrize('change', ['unknown_operation', 'edit_scope', 'combined_batch_overflow'])
def test_invalid_create_presentation_is_rejected_before_any_creation(case, change):
    request, root, calls, _, _ = case
    with_presentations(request)
    if change == 'unknown_operation':
        request['items'][0]['presentation']['operations'][0]['op'] = 'invent_science'
    elif change == 'edit_scope':
        request['items'][0]['request'] = {'version': 1, 'action': 'export', 'project': '/saved-project'}
    else:
        request['sample_style_preset'] = {'preset': '/styles.json', 'expected_preset_sha256': 'd' * 64}
        request['items'][0]['presentation']['operations'] *= 100
    with pytest.raises(ValueError):
        groups.start_group(request, group_dir=root)
    assert calls == [] and not root.exists()


def test_presentation_preset_paths_resolve_against_original_group_request(case):
    request, root, _, _, _ = case
    with_presentations(request)
    request['items'][0]['presentation']['operations'] = [{
        'op': 'apply_sample_style_preset', 'preset': 'known-style.json', 'expected_preset_sha256': 'd' * 64}]
    normalized = normalize_group_request(request, base_dir=root.parent)
    assert normalized['items'][0]['presentation']['operations'][0]['preset'] == str(root.parent / 'known-style.json')
    assert request['items'][0]['presentation']['operations'][0]['preset'] == 'known-style.json'


def test_old_group_answers_recheck_every_original_before_any_mutation_and_resume_when_restored(case):
    request, root, calls, _, resumes = case
    with_presentations(request)
    pending = groups.start_group(request, group_dir=root)
    answers = pending['next_step']['responses_template']
    source = Path(request['items'][1]['request']['source'])
    original = source.read_bytes()
    native = {f['document']: Path(f['document']).read_bytes()
              for item in pending['items'] for f in item['figures']}
    source.write_text('actual raw CSV changed after all previews')
    with pytest.raises(TaskControlError) as error:
        groups.resume_group(root, answers)
    assert error.value.reason_code == 'source_changed'
    assert resumes == []
    assert [call['action'] for call in calls].count('export') == 0
    assert all(Path(path).read_bytes() == contents for path, contents in native.items())
    source.write_bytes(original)
    assert groups.resume_group(root, answers)['status'] == 'complete'
    assert [call['action'] for call in calls].count('create') == 2
    assert [call['action'] for call in calls].count('export') == 2


@pytest.mark.parametrize('retry', [False, True])
def test_raw_drift_blocks_group_continuation_or_explicit_retry_before_running_child(case, retry):
    request, root, calls, _, resumes = case
    with_presentations(request)
    pending = groups.start_group(request, group_dir=root)
    task = Path(pending['items'][0]['task_dir'])
    interrupted = load_task(task)
    interrupted.update(status='running', phase='previewing')
    save_task(task, interrupted)
    Path(request['items'][0]['request']['source']).write_text('changed raw file before continuation')
    if retry:
        with pytest.raises(TaskControlError) as error:
            groups.resume_group(root, [{'item_id': 'a', 'task_dir': str(task), 'response': {'retry': True}}])
        assert error.value.reason_code == 'source_changed'
    else:
        current = groups.resume_group(root)
        assert current['items'][0]['status'] == 'blocked'
        assert current['items'][0]['blocker']['reason_code'] == 'source_changed'
    assert resumes == [] and [call['action'] for call in calls].count('create') == 2
    assert [call['action'] for call in calls].count('export') == 0
