"""Group manifests preserve the single-task semantic source and continuation contract."""
from copy import deepcopy
from pathlib import Path

import pytest

from sciplot_core import task_groups as groups, task_group_review as review
from sciplot_core.task_contract import TaskControlError
from sciplot_core.task_group_contract import normalize_group_request
from sciplot_core.task_storage import load_task
from test_task_semantic_delivery import _timed_semantic_backend


def semantic_group(tmp_path, monkeypatch, *, decisions=()):
    task, _, calls = _timed_semantic_backend(tmp_path, monkeypatch, decisions=list(decisions))
    second = tmp_path / 'second.csv'
    second.write_text('Time,Mass\ns,%\n0,80\n1,79\n')
    task['sources'] = ['original.csv', 'second.csv']
    task['out'] = 'figures'
    request = {'version': 1, 'title': 'Attachments', 'items': [
        {'id': 'overlay', 'label': 'Both originals', 'request': task}]}
    monkeypatch.setattr(review, 'inspect_project', lambda *_: pytest.fail('Managed plot must use its own current-result owner'))
    return request, tmp_path / 'group', calls


@pytest.mark.parametrize('needs_choice', [False, True])
def test_multisource_group_create_and_resume_keep_manifest_paths_and_all_hashes(tmp_path, monkeypatch, needs_choice):
    decisions = [{'field': 'time_boundary', 'options': ['preserve_endpoint', 'next_sample']}] if needs_choice else []
    request, root, calls = semantic_group(tmp_path, monkeypatch, decisions=decisions)
    before = deepcopy(request)
    result = groups.start_group(request, group_dir=root, base_dir=tmp_path)
    item = result['items'][0]
    child = load_task(Path(item['task_dir']))
    paths = [str(tmp_path / name) for name in ['original.csv', 'second.csv']]
    assert child['request']['sources'] == paths
    assert set(child['source_hashes']) == set(paths)
    assert item['sources'] == paths and item['source_current'] is True
    assert request == before
    if needs_choice:
        assert item['status'] == 'needs_input'
        result = groups.resume_group(root, [{'item_id': 'overlay', 'task_dir': item['task_dir'], 'response': {
            'confirm_plan': True, 'expected_question_id': item['task']['question']['question_id'],
            'choices': {'time_boundary': 'next_sample'}}}])
    assert result['status'] == 'complete', result
    assert result['items'][0]['ready_to_use'] is True
    assert result['next_step']['images'] == ['/delivery/figure.tiff']
    assert groups.resume_group(root)['status'] == 'complete'
    assert groups.start_group(request, group_dir=root, base_dir=tmp_path)['status'] == 'complete'
    assert calls['create'] == calls['delivery'] == 1


@pytest.mark.parametrize('changed', ['original.csv', 'second.csv'])
@pytest.mark.parametrize('at_question', [False, True])
def test_group_checks_every_attachment_before_resume_and_in_overview(tmp_path, monkeypatch, changed, at_question):
    decisions = [{'field': 'time_boundary', 'options': ['preserve_endpoint', 'next_sample']}] if at_question else []
    request, root, calls = semantic_group(tmp_path, monkeypatch, decisions=decisions)
    result = groups.start_group(request, group_dir=root, base_dir=tmp_path)
    item = result['items'][0]
    (tmp_path / changed).write_text('changed raw evidence')
    before = dict(calls)
    with pytest.raises(TaskControlError) as error:
        groups.resume_group(root, [{'item_id': 'overlay', 'task_dir': item['task_dir'], 'response': {'retry': True}}])
    assert error.value.reason_code == 'source_changed'
    assert calls == before
    current = groups.inspect_group(root)['items'][0]
    assert current['source_current'] is False
    assert current['status'] == 'blocked' and current['ready_to_use'] is False
    result = groups.resume_group(root)
    assert result['items'][0]['blocker']['reason_code'] == 'source_changed'
    assert calls['create'] == (0 if at_question else 1)


@pytest.mark.parametrize('destination', ['checkpoint', 'own_output', 'other_output', 'workspace'])
def test_nonfirst_attachment_is_protected_at_every_group_destination(tmp_path, monkeypatch, destination):
    request, root, calls = semantic_group(tmp_path, monkeypatch)
    task = request['items'][0]['request']
    parent = tmp_path / {'checkpoint': 'group', 'own_output': 'figures',
                        'other_output': 'other', 'workspace': '.sciplot/figures'}[destination]
    parent.mkdir(parents=True)
    source = parent / 'second.csv'
    source.write_text('Time,Mass\n0,100\n')
    task['sources'][1] = str(source)
    if destination == 'other_output':
        extra = deepcopy(request['items'][0])
        extra.update(id='other', label='Other')
        extra['request']['sources'] = ['original.csv']
        extra['request']['out'] = 'other'
        request['items'].append(extra)
    with pytest.raises(TaskControlError) as error:
        groups.start_group(request, group_dir=root, base_dir=tmp_path)
    assert error.value.reason_code in {'task_path_overlap', 'output_path_overlap', 'group_source_overlap'}
    assert not (root / 'group.json').exists() and calls['create'] == 0


def test_alias_sources_reuse_single_task_validation(tmp_path, monkeypatch):
    request, root, calls = semantic_group(tmp_path, monkeypatch)
    request['items'][0]['request']['sources'][1] = './original.csv'
    with pytest.raises(TaskControlError) as error:
        normalize_group_request(request, base_dir=tmp_path)
    assert error.value.reason_code == 'duplicate_semantic_source'
    assert not root.exists()


@pytest.mark.parametrize('option', ['presentation', 'sample_style_preset'])
def test_native_only_group_styles_fail_before_semantic_creation(tmp_path, monkeypatch, option):
    request, root, calls = semantic_group(tmp_path, monkeypatch)
    preset = {'preset': 'styles.json', 'expected_preset_sha256': 'a' * 64}
    if option == 'presentation':
        request['items'][0][option] = {'operations': [{'op': 'apply_sample_style_preset', **preset}]}
    else:
        request[option] = preset
    with pytest.raises(TaskControlError) as error:
        groups.start_group(request, group_dir=root, base_dir=tmp_path)
    assert error.value.reason_code == 'group_presentation_scope'
    assert not root.exists() and calls['create'] == 0
