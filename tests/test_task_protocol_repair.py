from __future__ import annotations

import asyncio
import json

import pytest

from sciplot_core import task_control as control, task_execution as execution
from sciplot_core.cli.value_io import _cli_runtime_error_payload
from sciplot_core.mcp_server.errors import error_payload
from sciplot_core.mcp_server.server import Adapter
from sciplot_core.task_contract import TaskControlError
from sciplot_core.task_repair import wire_issues
from sciplot_core.task_storage import load_task
from sciplot_core.foundation.file_hashing import file_sha256
from sciplot_core.output_contract import resolve_user_output_layout


def _source(tmp_path):
    path = tmp_path / 'UVvis.csv'
    path.write_text('Wavelength,Absorbance\nnm,a.u.\nE3,E3\n400,1\n450,4\n500,1\n')
    return path


@pytest.fixture
def creates(tmp_path, monkeypatch):
    calls = []
    def create(*args, **kwargs):
        calls.append(kwargs)
        return {'project_dir': str(tmp_path / 'project'), 'studio_run': {'ready_to_use': True}}
    monkeypatch.setattr(execution, 'create_project', create)
    monkeypatch.setattr(control, 'inspect_project', lambda _: {})
    return calls


def test_misplaced_task_dir_is_relocated_without_losing_out_or_recreating(tmp_path, creates):
    source = _source(tmp_path)
    request = {'version': 1, 'action': 'create', 'source': str(source),
               'task_dir': str(tmp_path / 'task'), 'out': str(tmp_path / 'delivery')}
    original = json.dumps(request)
    result = control.start_task(request)
    assert result['status'] == 'complete'
    assert result['automatic_corrections'][0]['action'] == 'moved_to_transport_option'
    assert creates[0]['output_dir'] == tmp_path / 'delivery'
    saved = load_task(tmp_path / 'task')
    assert 'task_dir' not in saved['request'] and saved['request']['out'] == request['out']
    assert json.dumps(request) == original
    assert control.start_task(request, task_dir=tmp_path / 'task')['status'] == 'complete'
    assert len(creates) == 1


def test_conflicting_task_locations_do_not_allocate_or_guess(tmp_path, creates):
    source = _source(tmp_path)
    with pytest.raises(TaskControlError) as exc:
        control.start_task({'version': 1, 'action': 'create', 'source': str(source),
                            'task_dir': str(tmp_path / 'a')}, task_dir=tmp_path / 'b')
    assert exc.value.reason_code == 'task_location_conflict'
    assert not (tmp_path / 'a').exists() and not (tmp_path / 'b').exists() and not creates
    assert exc.value.repair['action'] == 'correct_request'


def test_invalid_wire_fields_return_batched_paths_without_echoing_data(tmp_path):
    invalid = {'version': 1, 'action': 'create', 'source': '', 'extra': list(range(10000))}
    with pytest.raises(TaskControlError) as exc:
        control.start_task(invalid, task_dir=tmp_path / 'task')
    repair = _cli_runtime_error_payload(exc.value)['repair']
    assert repair == error_payload(exc.value)['repair']
    assert any(i.get('unsupported') == ['extra'] for i in repair['issues'])
    assert any(i['path'] == '/source' and i['constraint'] == 'minLength' for i in repair['issues'])
    assert len(json.dumps(repair)) < 1200 and not (tmp_path / 'task').exists()


def test_nested_mapping_type_feedback_names_exact_original_column_field():
    issues = wire_issues({'expected_question_id': 'a'*64, 'mapping': {
        'source_sha256': 'b'*64,
        'table_selection': {'sheet': None, 'header_rows': [0], 'unit_row': 1, 'sample_row': 2,
                            'data_start_row': 3, 'data_end_row': 6},
        'column_mapping': {'pairs': [{'x_column': True, 'y_column': 1}]} }}, section='response')
    assert any(i['path'] == '/mapping/column_mapping/pairs/0/x_column' and i['constraint'] == 'type' for i in issues)


def test_matching_question_errors_send_only_delta_but_stale_answers_get_current_evidence(tmp_path, creates):
    source = _source(tmp_path)
    state = control.start_task({'version': 1, 'action': 'create', 'source': str(source),
                               'rule_id': 'uvvis_spectrum', 'choose_columns': True}, task_dir=tmp_path / 'task')
    question = state['question']
    before = (tmp_path / 'task/task.json').read_bytes()
    for qid, unchanged in [(question['question_id'], True), ('0'*64, False)]:
        with pytest.raises(TaskControlError) as exc:
            control.resume_task(tmp_path / 'task', {'expected_question_id': qid,
                                                   'column_mapping': {'x_column': True, 'y_column': 1}})
        repair = exc.value.repair
        assert repair['question_unchanged'] is unchanged
        assert ('evidence' in repair['question']) is not unchanged
        assert repair['question']['question_id'] == question['question_id']
    assert (tmp_path / 'task/task.json').read_bytes() == before and not creates


def test_output_conflict_is_detected_before_planning_and_resumes_same_task(tmp_path, creates, monkeypatch):
    source = _source(tmp_path)
    old = tmp_path / 'old'
    old.mkdir()
    (old / 'keep').write_bytes(b'original')
    task = tmp_path / 'task'
    original_plan = execution.plan_task
    monkeypatch.setattr(execution, 'plan_task', lambda *args: pytest.fail('planning must not run for occupied output'))
    state = control.start_task({'version': 1, 'action': 'create', 'source': str(source), 'out': str(old)}, task_dir=task)
    assert state['status'] == 'needs_input' and state['question']['field'] == 'out'
    assert not creates and (old / 'keep').read_bytes() == b'original'
    before = (task / 'task.json').read_bytes()
    for answer in ({'retry': True}, {'expected_question_id': '0'*64, 'out': str(tmp_path / 'fresh')},
                   {'expected_question_id': state['question']['question_id'], 'out': str(task)}):
        with pytest.raises(TaskControlError) as exc:
            control.resume_task(task, answer)
        assert exc.value.repair['question']['question_id'] == state['question']['question_id']
        assert (task / 'task.json').read_bytes() == before
    monkeypatch.setattr(execution, 'plan_task', original_plan)
    done = control.resume_task(task, {**state['next_step']['response_template'], 'out': str(tmp_path / 'fresh')})
    assert done['status'] == 'complete' and len(creates) == 1
    assert creates[0]['output_dir'] == tmp_path / 'fresh'
    assert load_task(task)['request']['out'] == str(old)
    assert (old / 'keep').read_bytes() == b'original'


def test_output_choice_rechecks_changed_source_without_native_creation(tmp_path, creates):
    source = _source(tmp_path)
    out = tmp_path / 'old'
    out.mkdir()
    state = control.start_task({'version': 1, 'action': 'create', 'source': str(source), 'out': str(out)}, task_dir=tmp_path / 'task')
    source.write_text(source.read_text().replace('450,4', '450,9'))
    result = control.resume_task(tmp_path / 'task', {**state['next_step']['response_template'], 'out': str(tmp_path / 'fresh')})
    assert result['status'] == 'blocked' and result['blocker']['reason_code'] == 'source_changed'
    assert not creates and not (tmp_path / 'fresh').exists()


def test_bad_numeric_cell_reports_original_row_then_accepts_explicit_region(tmp_path, creates):
    source = tmp_path / 'UVvis.csv'
    source.write_text('Wavelength,Absorbance\nnm,a.u.\nE3,E3\n400,1\n450,bad\n500,2\n550,3\n600,4\n')
    original = source.read_bytes()
    mapping = {'source_sha256': file_sha256(source), 'table_selection': {
        'sheet': None, 'header_rows': [0], 'unit_row': 1, 'sample_row': 2,
        'data_start_row': 3, 'data_end_row': 8}, 'column_mapping': {'pairs': [{'x_column': 0, 'y_column': 1}]}}
    state = control.start_task({'version': 1, 'action': 'create', 'source': str(source),
                               'rule_id': 'uvvis_spectrum', 'mapping': mapping}, task_dir=tmp_path / 'task')
    assert state['status'] == 'needs_input' and not creates
    y = state['question']['evidence']['columns'][1]
    assert y['numeric']['invalid_row_indices'] == [4] and not y['y_eligible']
    assert state['mapping_error']['reason_code'] == 'invalid_mapping_selection'
    mapping['table_selection']['data_start_row'] = 5  # Explicit caller choice; never a local deletion/repair.
    done = control.resume_task(tmp_path / 'task', {'expected_question_id': state['question']['question_id'], 'mapping': mapping})
    assert done['status'] == 'complete' and len(creates) == 1
    assert source.read_bytes() == original


def test_mcp_alias_and_bad_response_return_current_context_without_an_inspect(tmp_path, creates):
    source = _source(tmp_path)
    out = tmp_path / 'old'
    out.mkdir()
    async def run():
        adapter = Adapter()
        started = await adapter.call('sciplot_task_start', {'request': {
            'version': 1, 'action': 'create', 'source': str(source), 'out': str(out),
            'task_dir': str(tmp_path / 'task')}})
        state = json.loads(started.content[0].text)
        assert state['status'] == 'needs_input' and not creates
        before = (tmp_path / 'task' / 'task.json').read_bytes()
        invalid = await adapter.call('sciplot_task_resume', {'task': state['task_dir'], 'response': {'out': 7}})
        payload = json.loads(invalid.content[0].text)
        assert invalid.is_error and payload['repair']['question'] == state['question']
        assert payload['repair']['next_step']['response_template']['expected_question_id'] == state['question']['question_id']
        assert (tmp_path / 'task' / 'task.json').read_bytes() == before
        corrected = await adapter.call('sciplot_task_resume', {'task': state['task_dir'], 'response': {
            **payload['repair']['next_step']['response_template'], 'out': str(tmp_path / 'fresh')}})
        assert json.loads(corrected.content[0].text)['status'] == 'complete'
    asyncio.run(run())
    assert len(creates) == 1


def test_uncertain_native_creation_cannot_be_redirected_or_created_again(tmp_path, monkeypatch):
    source = _source(tmp_path)
    out = tmp_path / 'delivery'
    workspace = resolve_user_output_layout(source, requested_delivery_root=out).workspace_root
    calls = []
    def interrupted(*args, **kwargs):
        calls.append(kwargs)
        workspace.mkdir(parents=True)
        (workspace / 'partial-native').write_bytes(b'preserve')
        raise RuntimeError('worker interrupted before prepared checkpoint')
    monkeypatch.setattr(execution, 'create_project', interrupted)
    task = tmp_path / 'task'
    state = control.start_task({'version': 1, 'action': 'create', 'source': str(source), 'out': str(out)}, task_dir=task)
    assert state['status'] == 'blocked' and state['phase'] == 'creating'
    before = (task / 'task.json').read_bytes()
    with pytest.raises(TaskControlError):
        control.resume_task(task, {'expected_question_id': '0'*64, 'out': str(tmp_path / 'another')})
    assert (task / 'task.json').read_bytes() == before
    retry = control.resume_task(task, {'retry': True})
    assert retry['blocker']['reason_code'] == 'creation_outcome_uncertain'
    assert len(calls) == 1 and (workspace / 'partial-native').read_bytes() == b'preserve'


def test_interrupted_output_choice_checkpoint_resumes_with_selected_output(tmp_path, creates, monkeypatch):
    source = _source(tmp_path)
    old = tmp_path / 'old'
    old.mkdir()
    task = tmp_path / 'task'
    state = control.start_task({'version': 1, 'action': 'create', 'source': str(source), 'out': str(old)}, task_dir=task)
    original = control.run_creation
    def interrupted(*args):
        raise KeyboardInterrupt('after output choice checkpoint, before creation')
    monkeypatch.setattr(control, 'run_creation', interrupted)
    with pytest.raises(KeyboardInterrupt):
        control.resume_task(task, {**state['next_step']['response_template'], 'out': str(tmp_path / 'fresh')})
    assert load_task(task)['phase'] == 'starting' and not creates
    monkeypatch.setattr(control, 'run_creation', original)
    assert control.resume_task(task, {'retry': True})['status'] == 'complete'
    assert len(creates) == 1 and creates[0]['output_dir'] == tmp_path / 'fresh'
