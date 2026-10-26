"""Comparison consumers of actual sealed v3 native command candidates."""

from __future__ import annotations

import base64
import copy
import json
from pathlib import Path

import pytest

from test_project_query import project as project
from sciplot_core import task_comparisons as comparisons
from sciplot_core.foundation.file_hashing import file_sha256
from sciplot_core.project_commands import ProjectCommand, ProjectCommands, ProjectMutation
from sciplot_core.studio_core.document_edit_commands import preview_native_edit
from sciplot_core.studio_core.document_edit_state import edit_state
from sciplot_core.studio_core.project_command_scope import project_store
from sciplot_core.task_storage import load_task, save_task
from sciplot_core.task_comparison_storage import candidate_review, load_comparison
from sciplot_core.task_comparison_gallery import write_comparison_gallery


PNG = base64.b64decode('iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+jRZkAAAAASUVORK5CYII=')


@pytest.fixture
def stored_comparison(project, tmp_path, monkeypatch):
    document = project / 'studio/document.vsz'
    spec = project / 'studio/spec.json'
    original = {path: path.read_bytes() for path in (document, spec, project / 'source/data.csv')}
    calls, applies = [], []

    def artifact(path, data):
        path.write_bytes(data)
        return {'path': str(path), 'sha256': file_sha256(path)}

    def candidate(document, spec, changes, output, *, operations, figure_id):
        calls.append(operations)
        change = operations[0]
        saved = artifact(output / 'candidate.vsz', document.read_bytes() + change['value'].encode())
        companion = artifact(output / 'candidate.json', spec.read_bytes())
        return {'candidate': saved, 'candidate_spec': companion,
                'preview': artifact(output / 'candidate.png', PNG),
                'changes': [{'setting_path': change['setting_path'], 'old_value': change['expected_value'],
                             'new_value': change['value']}],
                'scientific_audit': {'status': 'passed', 'document_sha256': saved['sha256'],
                                     'spec_sha256': companion['sha256']}}

    def preview(_project, *, figure_id, output_dir):
        output_dir.mkdir()
        return {'document': {'sha256': file_sha256(document)},
                'preview': artifact(output_dir / 'current.png', PNG)}

    def start(request, *, task_dir):
        task_dir.mkdir(parents=True)
        review = preview_native_edit(project, [], output_dir=task_dir / 'native', figure_id='first',
            expected_document_sha256=request['expected_document_sha256'], operations=request['operations'],
            expected_spec_sha256=file_sha256(spec), candidate_builder=candidate,
            audit_document=lambda *_args: {'status': 'passed'})
        (task_dir / 'review.json').write_text(json.dumps(review))
        child = {'kind': 'sciplot_task', 'version': 1, 'task_dir': str(task_dir), 'request': request,
                 'project': str(project), 'status': 'needs_review', 'phase': 'review',
                 'operation_id': review['operation_id'], 'preview': {'image': review['preview']}}
        save_task(task_dir, child)
        return child

    def resume(directory, response):
        child = load_task(directory)
        review = json.loads((directory / 'review.json').read_text())
        assert response == {'accept_preview': True, 'expected_operation_id': child['operation_id']}
        app = ProjectCommands(project_store(project))
        record = app.query(child['operation_id'])
        completed = app.decide(ProjectCommand.from_payload(record['metadata']),
                               decision_id=review['decision_id'], accept=True)
        applies.append(child['operation_id'])
        child.update(status='complete', phase='finished',
                     result={'document_sha256': completed['result']['result_sha256']})
        save_task(directory, child)
        return child

    monkeypatch.setattr(comparisons, 'preview_project_document', preview)
    monkeypatch.setattr(comparisons, 'start_task', start)
    monkeypatch.setattr(comparisons, 'resume_task', resume)
    request = {'version': 1, 'title': 'Sealed alternatives', 'project': str(project), 'figure_id': 'first',
               'expected_document_sha256': file_sha256(document), 'export': False,
               'candidates': [{'id': name, 'label': name, 'operations': [{'op': 'set_style',
                   'object_path': '/page1/graph1/x', 'setting_path': '/page1/graph1/x/Label/size',
                   'expected_value': '8pt', 'value': value}]} for name, value in [('a', '9pt'), ('b', '10pt')]]}
    return request, tmp_path / 'comparison', original, calls, applies


def test_sealed_v3_candidates_compare_then_commit_only_the_exact_selection(stored_comparison):
    request, root, original, calls, applies = stored_comparison
    before = edit_state(Path(request['project']))
    result = comparisons.start_comparison(request, comparison_dir=root)
    assert result['status'] == 'needs_selection', result
    assert result['baseline_current'] and len(result['previews']) == 3
    assert all(item['selectable'] and item['scientific_audit_status'] == 'passed' for item in result['candidates'])
    assert all(path.read_bytes() == data for path, data in original.items())
    assert len(calls) == 2 and not applies
    assert comparisons.inspect_comparison(root)['comparison_id'] == result['comparison_id']
    assert comparisons.resume_comparison(root)['comparison_id'] == result['comparison_id']
    html = (root / 'overview.html').read_text()
    assert 'data:image/png;base64,' + base64.b64encode(PNG).decode() in html
    assert '.sciplot_store' not in html
    assert 'baseline-' in html and 'current.png' in html
    assert edit_state(Path(request['project'])) == before
    selected = {'candidate_id': 'b', 'expected_comparison_id': result['comparison_id']}
    final = comparisons.select_comparison(root, selected)
    assert final['status'] == 'complete', final
    assert len(applies) == 1 and len(calls) == 2
    assert comparisons.select_comparison(root, selected)['status'] == 'complete'
    assert comparisons.resume_comparison(root)['status'] == 'complete' and len(applies) == 1
    assert (Path(request['project']) / 'studio/document.vsz').read_bytes().endswith(b'10pt')
    assert all(path.read_bytes() == data for path, data in original.items() if path.name != 'document.vsz')
    assert load_task(root / 'candidates/a')['status'] == 'needs_review'


@pytest.mark.parametrize('changed', ['decision', 'intent', 'scientific_audit', 'artifact', 'source_baseline'])
def test_v3_comparison_refuses_changed_review_or_baseline_before_any_apply(stored_comparison, changed):
    request, root, original, calls, applies = stored_comparison
    comparisons.start_comparison(request, comparison_dir=root)
    path = root / 'candidates/b/review.json'
    review = json.loads(path.read_text())
    if changed == 'decision':
        review['decision_id'] = 'f' * 64
    elif changed == 'intent':
        review['operations'][0]['value'] = '20pt'
    elif changed == 'scientific_audit':
        review['scientific_audit']['status'] = 'failed'
    elif changed == 'artifact':
        artifact = Path(review['candidate']['path'])
        artifact.chmod(0o600)
        artifact.write_bytes(b'foreign candidate bytes')
    else:
        source = Path(request['project']) / 'source/data.csv'
        source.write_bytes(b'x,y\n1,999\n')
    path.write_text(json.dumps(review))
    result = comparisons.inspect_comparison(root)
    assert not result['candidates'][1]['selectable']
    assert not applies and len(calls) == 2
    assert all(path.read_bytes() == data for path, data in original.items()
               if changed != 'source_baseline' or path.name != 'data.csv')


def test_v3_comparison_refuses_another_valid_command_kind(stored_comparison):
    request, root, original, calls, applies = stored_comparison
    comparisons.start_comparison(request, comparison_dir=root)
    path = root / 'candidates/b/review.json'
    review = json.loads(path.read_text())
    store = project_store(Path(request['project']))
    app = ProjectCommands(store)
    prior = app.query(review['operation_id'])
    metadata = prior['metadata']
    other = ProjectCommand.create('export', 'not-a-native-edit', project_id=prior['project_id'],
        expected_generation=prior['generation'], read_set=prior['read_set'], write_set=prior['write_set'],
        request=metadata['request'])
    recorded = app.preview(other, lambda: ProjectMutation(
        {name: Path(value) for name, value in prior['staged_paths'].items()}, prior['result'],
        review=prior['review'], artifacts={name: Path(value) for name, value in prior['artifact_paths'].items()}))
    review.update(operation_id=other.key, decision_id=recorded['decision_id'])
    path.write_text(json.dumps(review))
    child = load_task(path.parent)
    child['operation_id'] = other.key
    save_task(path.parent, child)
    with pytest.raises(ValueError, match='identity|native document edit'):
        candidate_review(root, load_comparison(root), request['candidates'][1], child)
    assert not applies and len(calls) == 2
    assert all(path.read_bytes() == data for path, data in original.items())


def test_gallery_cannot_embed_an_unowned_off_root_image(stored_comparison, tmp_path, monkeypatch):
    request, root, original, calls, applies = stored_comparison
    result = comparisons.start_comparison(request, comparison_dir=root)
    forged = copy.deepcopy(result)
    foreign = tmp_path / 'private-unrelated.png'
    foreign.write_bytes(PNG + b'not a candidate')
    forged['candidates'][0]['preview'] = {'path': str(foreign), 'sha256': file_sha256(foreign)}
    original_read = Path.read_bytes

    def refuse_foreign(path):
        assert path != foreign, 'The gallery opened an unowned file before validating its sealed identity'
        return original_read(path)

    monkeypatch.setattr(Path, 'read_bytes', refuse_foreign)
    before = (root / 'overview.html').read_bytes()
    with pytest.raises(ValueError, match='exact sealed'):
        write_comparison_gallery(root, forged)
    assert (root / 'overview.html').read_bytes() == before
    assert not applies and len(calls) == 2
    assert all(path.read_bytes() == data for path, data in original.items())


def test_rejected_changed_candidate_cannot_be_selected_as_an_unchanged_one(stored_comparison):
    request, root, original, calls, applies = stored_comparison
    result = comparisons.start_comparison(request, comparison_dir=root)
    app = ProjectCommands(project_store(Path(request['project'])))
    candidate = result['candidates'][1]
    record = app.query(candidate['operation_id'])
    app.decide(ProjectCommand.from_payload(record['metadata']), decision_id=record['decision_id'], accept=False)
    inspected = comparisons.inspect_comparison(root)
    assert not inspected['candidates'][1]['selectable']
    assert not applies and len(calls) == 2
    assert all(path.read_bytes() == data for path, data in original.items())


def test_v3_comparison_uses_only_owned_artifacts_ignoring_untrusted_path_hints(stored_comparison, tmp_path):
    request, root, original, calls, applies = stored_comparison
    comparisons.start_comparison(request, comparison_dir=root)
    path = root / 'candidates/b/review.json'
    review = json.loads(path.read_text())
    original_path = review['preview']['path']
    foreign = tmp_path / 'foreign.png'
    review['preview']['path'] = str(foreign)
    path.write_text(json.dumps(review))
    child = load_task(path.parent)
    verified = candidate_review(root, load_comparison(root), request['candidates'][1], child)
    assert verified['preview']['path'] == original_path and not foreign.exists()
    assert not applies and len(calls) == 2
    assert all(path.read_bytes() == data for path, data in original.items())
