from __future__ import annotations

import base64
import copy
import json
from pathlib import Path

import pytest

from sciplot_core import task_comparisons as comparisons, task_comparison_review as presentation
from sciplot_core import task_comparison_contract as contract
from sciplot_core.foundation.file_hashing import file_sha256
from sciplot_core.studio_core.document_edit_state import preview_identity
from sciplot_core.task_contract import TaskControlError
from sciplot_core.task_storage import load_task, save_task


PNG = base64.b64decode('iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+jRZkAAAAASUVORK5CYII=')


@pytest.fixture
def case(tmp_path, monkeypatch):
    project = tmp_path / 'project'
    project.mkdir()
    document, spec = project / 'document.vsz', project / 'spec.json'
    document.write_text('native baseline fixture')
    spec.write_text('{"data":[1,2,3]}')
    calls, applies, renders = [], [], []

    def baseline(_):
        return {'project_files': {p.name: file_sha256(p) for p in (document, spec)}, 'delivery_files': None}

    def figure(*_):
        return {'figure_id': 'curve', 'document': str(document), 'spec': str(spec)}

    def artifact(path, contents):
        path.write_bytes(contents)
        return {'path': str(path), 'sha256': file_sha256(path)}

    def preview(_, *, figure_id, output_dir):
        renders.append(figure_id)
        output_dir.mkdir()
        return {'document': {'sha256': file_sha256(document)}, 'preview': artifact(output_dir / 'current.png', PNG)}

    def start(request, *, task_dir):
        calls.append(copy.deepcopy(request))
        task_dir.mkdir(parents=True)
        state = {'kind': 'sciplot_task', 'version': 1, 'task_dir': str(task_dir), 'request': request,
                 'project': str(project), 'status': 'running', 'phase': 'starting'}
        save_task(task_dir, state)
        if request['action'] == 'export':
            state.update(status='complete', phase='finished', result={'ready_to_use': True})
            save_task(task_dir, state)
            return state
        width = request['operations'][0]['style']['width']
        if width == '99pt':
            state.update(status='blocked', phase='previewing', blocker={'message': 'unsupported width fixture'})
            save_task(task_dir, state)
            return state
        unchanged = width == '1pt'
        review = {'kind': 'sciplot_document_edit_preview', 'version': 2, 'status': 'ready',
                  'project': str(project), 'figure_id': 'curve', 'document': str(document),
                  'document_sha256': file_sha256(document), 'base_state': baseline(project),
                  'operations': request['operations'], 'changes': [],
                  'actual_changes': [{'setting_path': '/graph/line/color', 'old_value': '#222222', 'new_value': '#222222'},
                                     {'setting_path': '/graph/line/width', 'old_value': '1pt', 'new_value': width}],
                  'candidate': artifact(task_dir / 'candidate.vsz', document.read_bytes() if unchanged else width.encode()),
                  'candidate_spec': artifact(task_dir / 'candidate.json', spec.read_bytes()),
                  'preview': artifact(task_dir / 'candidate.png', PNG + width.encode()),
                  'scientific_audit': {'status': 'passed'}}
        review['operation_id'] = preview_identity(review)
        (task_dir / 'review.json').write_text(json.dumps(review))
        state.update(status='needs_review', phase='review', operation_id=review['operation_id'],
                     preview={'image': review['preview']})
        if unchanged:
            state.update(status='complete', phase='finished', edit_outcome={'status': 'unchanged'},
                         result={'status': 'unchanged', 'document_sha256': file_sha256(document)})
        save_task(task_dir, state)
        return state

    def resume(directory, response):
        state = load_task(directory)
        assert response['accept_preview'] is True
        assert response['expected_operation_id'] == state['operation_id']
        review = json.loads((directory / 'review.json').read_text())
        assert baseline(project) == review['base_state']
        document.write_bytes(Path(review['candidate']['path']).read_bytes())
        spec.write_bytes(Path(review['candidate_spec']['path']).read_bytes())
        applies.append(directory.name)
        state.update(status='complete', phase='finished', result={'status': 'saved', 'document_sha256': file_sha256(document)})
        save_task(directory, state)
        return state

    monkeypatch.setattr(contract, 'resolve_project_path', lambda path: path)
    monkeypatch.setattr(comparisons, 'task_location', lambda request, supplied: supplied)
    monkeypatch.setattr(comparisons, 'resolve_project_figure', figure)
    monkeypatch.setattr(comparisons, 'edit_state', baseline)
    monkeypatch.setattr(presentation, 'edit_state', baseline)
    monkeypatch.setattr(presentation, 'inspect_project', lambda path: {'ready_to_use': False, 'source': {'current': True}})
    monkeypatch.setattr(comparisons, 'preview_project_document', preview)
    monkeypatch.setattr(comparisons, 'start_task', start)
    monkeypatch.setattr(comparisons, 'resume_task', resume)
    request = {'version': 1, 'title': 'Compare <script>alert(1)</script>', 'project': str(project),
               'figure_id': 'curve', 'expected_document_sha256': file_sha256(document),
               'candidates': [{'id': name, 'label': name, 'operations': [
                   {'op': 'set_sample_style', 'samples': ['E0'], 'style': {'width': width}}]}
                   for name, width in [('a', '2pt'), ('b', '3pt')]]}
    return request, tmp_path / 'comparison', document, spec, calls, applies, renders


def choose(result, name='b'):
    return {'candidate_id': name, 'expected_comparison_id': result['comparison_id']}


def test_compare_same_baseline_once_then_apply_only_chosen_candidate(case):
    request, root, document, spec, calls, applies, renders = case
    before = (document.read_bytes(), spec.read_bytes())
    result = comparisons.start_comparison(request, comparison_dir=root)
    assert result['status'] == 'needs_selection' and result['baseline_current'] is True
    assert len(result['previews']) == 3 and len(calls) == 2 and len(renders) == 1
    assert all(c['selectable'] and c['scientific_audit_status'] == 'passed' for c in result['candidates'])
    assert all(c['change_count'] == 1 for c in result['candidates'])
    assert (document.read_bytes(), spec.read_bytes()) == before and not applies
    receipt = (root / 'comparison.json').read_bytes()
    for query in (lambda: comparisons.start_comparison(request, comparison_dir=root),
                  lambda: comparisons.inspect_comparison(root), lambda: comparisons.resume_comparison(root)):
        assert query()['comparison_id'] == result['comparison_id']
    assert len(calls) == 2 and len(renders) == 1 and not applies
    assert comparisons.inspect_comparison(root)['ready_to_use'] is None
    assert b'<script>' not in (root / 'overview.html').read_bytes() and receipt
    selection = choose(result)
    final = comparisons.select_comparison(root, selection)
    assert final['status'] == 'complete' and final['can_select'] is False
    assert document.read_text() == '3pt' and spec.read_bytes() == before[1]
    assert applies == ['b'] and load_task(root / 'candidates/a')['status'] == 'needs_review'
    assert comparisons.select_comparison(root, selection)['status'] == 'complete'
    assert comparisons.resume_comparison(root)['status'] == 'complete' and applies == ['b']
    with pytest.raises(TaskControlError, match='第二个候选'):
        comparisons.select_comparison(root, choose(result, 'a'))


@pytest.mark.parametrize('candidate', ['baseline', 'a'])
def test_keep_original_or_unchanged_candidate_has_no_write(case, candidate):
    request, root, document, spec, _, applies, _ = case
    request['candidates'][0]['operations'][0]['style']['width'] = '1pt'
    before = (document.read_bytes(), spec.read_bytes())
    result = comparisons.start_comparison(request, comparison_dir=root)
    assert result['candidates'][0]['status'] == 'unchanged'
    assert result['candidates'][0]['change_count'] == 0
    assert comparisons.select_comparison(root, choose(result, candidate))['status'] == 'complete'
    assert (document.read_bytes(), spec.read_bytes()) == before and not applies


@pytest.mark.parametrize('changed', ['document', 'spec', 'preview', 'candidate', 'review'])
def test_changed_baseline_or_candidate_never_applies(case, changed):
    request, root, document, spec, _, applies, _ = case
    result = comparisons.start_comparison(request, comparison_dir=root)
    paths = {'document': document, 'spec': spec, 'preview': root / 'candidates/b/candidate.png',
             'candidate': root / 'candidates/b/candidate.vsz', 'review': root / 'candidates/b/review.json'}
    paths[changed].write_text('changed')
    before = document.read_bytes()
    with pytest.raises(TaskControlError):
        comparisons.select_comparison(root, choose(result))
    assert not applies and document.read_bytes() == before
    if changed in {'document', 'spec'}:
        refreshed = comparisons.resume_comparison(root)
        assert refreshed['status'] == 'blocked' and refreshed['baseline_current'] is False


def test_failed_candidate_does_not_block_other_alternative(case):
    request, root, _, _, _, applies, _ = case
    request['candidates'][0]['operations'][0]['style']['width'] = '99pt'
    result = comparisons.start_comparison(request, comparison_dir=root)
    assert not result['candidates'][0]['selectable'] and result['candidates'][1]['selectable']
    assert comparisons.select_comparison(root, choose(result))['status'] == 'complete' and applies == ['b']


def test_lost_candidate_reply_recovers_existing_preview(case, monkeypatch):
    request, root, _, _, calls, _, _ = case
    original = comparisons.start_task

    def lost(request, *, task_dir):
        original(request, task_dir=task_dir)
        if task_dir.name == 'a':
            raise RuntimeError('lost reply')

    monkeypatch.setattr(comparisons, 'start_task', lost)
    first = comparisons.start_comparison(request, comparison_dir=root)
    assert not first['candidates'][0]['selectable']
    resumed = comparisons.resume_comparison(root)
    assert all(c['selectable'] for c in resumed['candidates']) and len(calls) == 2
    with pytest.raises(TaskControlError, match='重新查询'):
        comparisons.select_comparison(root, choose(first))


def test_lost_apply_reply_recovers_selected_child_without_second_apply(case, monkeypatch):
    request, root, _, _, _, applies, _ = case
    result = comparisons.start_comparison(request, comparison_dir=root)
    original = comparisons.resume_task

    def lost(directory, response):
        original(directory, response)
        raise RuntimeError('reply lost after saved edit')

    monkeypatch.setattr(comparisons, 'resume_task', lost)
    assert comparisons.select_comparison(root, choose(result))['status'] == 'blocked'
    assert comparisons.resume_comparison(root)['status'] == 'complete' and applies == ['b']


@pytest.mark.parametrize('candidate', ['b', 'baseline'])
def test_export_lost_reply_resumes_without_reapplying(case, monkeypatch, candidate):
    request, root, _, _, calls, applies, _ = case
    request['export'] = True
    result = comparisons.start_comparison(request, comparison_dir=root)
    original = comparisons.start_task

    def lost(request, *, task_dir):
        original(request, task_dir=task_dir)
        if request['action'] == 'export':
            raise RuntimeError('reply lost after export')

    monkeypatch.setattr(comparisons, 'start_task', lost)
    assert comparisons.select_comparison(root, choose(result, candidate))['status'] == 'blocked'
    assert comparisons.resume_comparison(root)['status'] == 'complete'
    assert len([c for c in calls if c['action'] == 'export']) == 1
    assert applies == (['b'] if candidate == 'b' else [])


@pytest.mark.parametrize('mutation', ['one', 'duplicate', 'reserved', 'unknown_operation', 'extra'])
def test_invalid_manifest_is_rejected_before_comparison_creation(case, mutation):
    request, root, _, _, calls, _, _ = case
    if mutation == 'one':
        request['candidates'].pop()
    elif mutation == 'duplicate':
        request['candidates'][1]['id'] = 'a'
    elif mutation == 'reserved':
        request['candidates'][0]['id'] = 'baseline'
    elif mutation == 'unknown_operation':
        request['candidates'][0]['operations'][0]['op'] = 'exec_python'
    else:
        request['accept_all'] = True
    with pytest.raises(ValueError):
        comparisons.start_comparison(request, comparison_dir=root)
    assert not root.exists() and not calls


def test_changed_receipt_and_out_of_band_candidate_revision_fail_closed(case):
    request, root, _, _, _, applies, _ = case
    result = comparisons.start_comparison(request, comparison_dir=root)
    child = load_task(root / 'candidates/b')
    child['edit_revisions'] = [{'revise_operations': request['candidates'][0]['operations']}]
    save_task(root / 'candidates/b', child)
    with pytest.raises(TaskControlError):
        comparisons.select_comparison(root, choose(result))
    receipt = json.loads((root / 'comparison.json').read_text())
    receipt['request']['title'] = 'altered'
    (root / 'comparison.json').write_text(json.dumps(receipt))
    with pytest.raises(TaskControlError, match='记录已变化'):
        comparisons.inspect_comparison(root)
    assert not applies


def test_portable_comparison_manifest_uses_shared_contract():
    from sciplot_core._paths import REPO_ROOT
    from sciplot_core.task_group_contract import validate_shape

    value = json.loads((REPO_ROOT / 'skill/references/figure-comparison.json').read_text())
    validate_shape(value, contract.comparison_request_schema())


def test_later_edit_cannot_be_exported_as_the_comparison_selection(case, monkeypatch):
    request, root, document, _, calls, applies, _ = case
    request['export'] = True
    result = comparisons.start_comparison(request, comparison_dir=root)
    original = comparisons.resume_task

    def lost(directory, response):
        original(directory, response)
        raise RuntimeError('reply lost')

    monkeypatch.setattr(comparisons, 'resume_task', lost)
    assert comparisons.select_comparison(root, choose(result))['status'] == 'blocked'
    document.write_text('a later independent edit')
    resumed = comparisons.resume_comparison(root)
    assert resumed['status'] == 'blocked' and resumed['blocker']['reason_code'] == 'comparison_selected_figure_changed'
    assert document.read_text() == 'a later independent edit' and applies == ['b']
    assert all(c['action'] != 'export' for c in calls)


def test_manifest_paths_resolve_beside_the_manifest(case):
    request, root, _, _, _, _, _ = case
    request['project'] = 'project'
    request['candidates'][0]['operations'] = [{'op': 'apply_sample_style_preset',
        'preset': 'styles/preset.json', 'expected_preset_sha256': 'a' * 64}]
    resolved = contract.normalize_comparison_request(request, base_dir=root.parent)
    assert resolved['project'] == str(root.parent / 'project')
    assert resolved['candidates'][0]['operations'][0]['preset'] == str(root.parent / 'styles/preset.json')
