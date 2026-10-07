from __future__ import annotations

from copy import deepcopy
import json
from pathlib import Path
import stat

from sciplot_core.cli.value_io import _cli_runtime_error_payload
from sciplot_core.mcp_server.errors import error_payload
from sciplot_core.task_contract import TaskControlError
from sciplot_core.task_repair import request_repair, response_repair, wire_issues
from sciplot_core.task_result_projection import compact_task_result


def _state(tmp_path):
    return {"kind": "sciplot_task", "version": 1, "status": "needs_input",
            "phase": "scientific_choice", "task_dir": str(tmp_path),
            "request": {"version": 1, "action": "create", "source": "/source.csv"},
            "question": {"field": "table_selection", "question_id": "a" * 64,
                         "mapping_candidates": [{"candidate_id": "c" * 64,
                            "mapping": {"column_mapping": {"pairs": [{"x_column": 0, "y_column": 1}]}}}],
                         "evidence": {"original_cells": ["source data"]}}}


def test_long_blocked_message_is_bounded_with_original_durable_diagnostics(tmp_path):
    state = _state(tmp_path)
    state.update(status="blocked", phase="exporting", blocker={
        "reason_code": "fixture_worker_failure", "message": "x" * 50000,
        "recovery": "Repair the export cause."},
        next_step={"action": "repair_export_then_retry", "response": {"retry": True}},
        preview={"scientific_audit": {"status": "failed", "failures": ["data changed"]}},
        current_project={"source": {"current": None, "status": "unknown"}})
    diagnostic = tmp_path / "task.json"
    diagnostic.write_text(json.dumps(state))
    before = deepcopy(state)
    compact = compact_task_result(state)
    assert len(json.dumps(compact)) < 2500
    assert json.loads(Path(compact["diagnostics"]["path"]).read_text()) == before
    assert state == before
    for field in ("question", "preview", "current_project", "next_step"):
        assert compact[field] == before[field]
    assert compact["blocker"]["reason_code"] == "fixture_worker_failure"


def test_cli_mcp_long_errors_share_private_complete_diagnostic():
    exc = TaskControlError("fixture_failure", "head " + "worker detail\n" * 4000)
    cli, mcp = _cli_runtime_error_payload(exc), error_payload(exc)
    assert len(json.dumps(cli)) < 1200 and len(json.dumps(mcp)) < 1200
    assert cli["message"] == mcp["error"]["message"]
    assert cli["diagnostics"] == mcp["diagnostics"]
    path = Path(cli["diagnostics"]["path"])
    try:
        assert json.loads(path.read_text())["message"] == str(exc)
        assert stat.S_IMODE(path.stat().st_mode) == 0o600
    finally:
        path.unlink()


def test_short_errors_do_not_write_diagnostics(monkeypatch):
    from sciplot_core import task_error_feedback
    monkeypatch.setattr(task_error_feedback.tempfile, "mkstemp", lambda **_: (_ for _ in ()).throw(AssertionError()))
    exc = TaskControlError("bad_field", "Choose an exact sample label.")
    exc.field = "operations/0/samples"
    cli, mcp = _cli_runtime_error_payload(exc), error_payload(exc)
    assert cli["field"] == mcp["error"]["field"] == "/operations/0/samples"
    assert "diagnostics" not in cli and "diagnostics" not in mcp


def test_candidate_semantic_feedback_names_only_rejected_fields(tmp_path):
    state = _state(tmp_path)
    before = deepcopy(state)
    response = {"expected_question_id": "a" * 64, "mapping_candidate_id": "d" * 64}
    repair = response_repair(state, response, TaskControlError("invalid_mapping_candidate", "Unknown candidate."))
    assert repair["issues"] == [{"path": "/mapping_candidate_id", "constraint": "advertised_candidate", "expected": ["c" * 64]}]
    assert repair["question_unchanged"] is True and "evidence" not in repair["question"]
    response.update(mapping_candidate_id="c" * 64, pair_indices=[9])
    repair = response_repair(state, response, TaskControlError("invalid_mapping_candidate", "Pair index out of range."))
    assert repair["issues"] == [{"path": "/pair_indices/0", "constraint": "maximum", "expected": 0}]
    assert state == before


def test_profile_conflict_and_explicit_owner_issues_are_actionable():
    request = {"version": 1, "action": "create", "source": "/source.csv", "profile": "/profile", "rule_id": "uvvis_spectrum"}
    repair = request_repair(request, TaskControlError("profile_selection_conflict", "Conflicting choices."))
    assert repair["issues"] == [{"path": "/profile", "constraint": "mutually_exclusive", "conflicts_with": ["rule_id"]}]
    exc = TaskControlError("bad_width", "Provide physical size.")
    exc.issues = [{"path": "/operations/0/style/width", "constraint": "positive_physical_size"}]
    assert request_repair(request, exc)["issues"] == exc.issues


def test_wire_issues_follow_nested_operation_discriminator():
    request = {"version": 1, "action": "edit", "project": "/project", "expected_document_sha256": "a" * 64,
               "operations": [{"op": "add_annotation", "id": "title", "parent_path": "/page1/graph1", "text": "Title",
                               "position": {"mode": "relative", "x": "far", "y": 0.5}}]}
    assert wire_issues(request, section="request") == [
        {"path": "/operations/0/position/x", "constraint": "type", "expected": "number"}]


def test_stale_preview_feedback_contains_current_image_and_audit_to_review(tmp_path):
    state = _state(tmp_path)
    state.pop("question")
    state.update(status="needs_review", phase="review", operation_id="b" * 64,
                 preview={"image": {"path": "/current.png"}, "scientific_audit": {"status": "passed"}})
    state["request"] = {"version": 1, "action": "edit", "project": "/project", "expected_document_sha256": "c" * 64,
                        "operations": [{"op": "set_sample_style", "samples": ["A"], "style": {"width": "0.7pt"}}]}
    before = deepcopy(state)
    repair = response_repair(state, {"accept_preview": True, "expected_operation_id": "d" * 64},
                             TaskControlError("stale_task_preview", "Review the current preview."))
    assert repair["preview"] == state["preview"]
    assert repair["operation_id"] == "b" * 64
    assert repair["next_step"]["action"] == "view_preview_then_decide"
    assert repair["issues"] == [{"path": "/expected_operation_id", "constraint": "current_review_binding", "expected": "b" * 64}]
    assert state == before


def test_semantic_candidate_error_corrects_in_one_resume_without_inspect(tmp_path, monkeypatch):
    import pytest
    from sciplot_core import task_control as control, task_execution as execution
    from sciplot_core.foundation.file_hashing import file_sha256
    from sciplot_core.foundation.json_hashing import canonical_json_sha256
    from sciplot_core.task_storage import load_task, save_task

    source = tmp_path / 'UVvis.csv'
    source.write_text('Wavelength,Absorbance\nnm,a.u.\nE3,E3\n400,1\n450,4\n500,1\n')
    original = source.read_bytes()
    task = tmp_path / 'task'
    control.start_task({'version': 1, 'action': 'create', 'source': str(source),
                        'rule_id': 'uvvis_spectrum', 'choose_columns': True}, task_dir=task)
    state = load_task(task)
    question = state['question']
    question['mapping_candidates'] = [{'candidate_id': 'c' * 64, 'mapping': {
        'source_sha256': file_sha256(source), 'table_selection': {
            'sheet': None, 'header_rows': [0], 'unit_row': 1, 'sample_row': 2,
            'data_start_row': 3, 'data_end_row': 6},
        'column_mapping': {'pairs': [{'x_column': 0, 'y_column': 1}]}}}]
    question['question_id'] = canonical_json_sha256({k: v for k, v in question.items() if k != 'question_id'})
    save_task(task, state)
    before = (task / 'task.json').read_bytes()
    calls = []
    def create(*args, **kwargs):
        calls.append(kwargs)
        return {'project_dir': str(tmp_path / 'project'), 'studio_run': {'ready_to_use': True}}
    monkeypatch.setattr(execution, 'create_project', create)
    monkeypatch.setattr(control, 'inspect_project', lambda _: {})
    monkeypatch.setattr(control, 'inspect_task', lambda _: pytest.fail('repair must not need an inspect'))
    response = {'expected_question_id': question['question_id'], 'mapping_candidate_id': 'd' * 64}
    with pytest.raises(TaskControlError) as caught:
        control.resume_task(task, response)
    repair = caught.value.repair
    assert (task / 'task.json').read_bytes() == before
    assert source.read_bytes() == original and not calls
    response['mapping_candidate_id'] = repair['issues'][0]['expected'][0]
    result = control.resume_task(task, response)
    assert result['status'] == 'complete' and len(calls) == 1
    assert source.read_bytes() == original


def test_diagnostic_write_failure_preserves_original_error_without_masking(monkeypatch):
    from sciplot_core import task_error_feedback
    def unavailable(**kwargs):
        raise OSError('diagnostic disk unavailable')
    monkeypatch.setattr(task_error_feedback.tempfile, 'mkstemp', unavailable)
    exc = TaskControlError('original_failure', 'original ' + 'x' * 50000)
    cli, mcp = _cli_runtime_error_payload(exc), error_payload(exc)
    assert cli['reason_code'] == mcp['error']['code'] == 'original_failure'
    assert cli['message'] == mcp['error']['message'] == str(exc)
    assert cli['diagnostics_unavailable'] == mcp['diagnostics_unavailable'] == 'diagnostic disk unavailable'


def test_mcp_stale_preview_error_exposes_immutable_current_image(tmp_path, monkeypatch):
    import anyio
    import base64
    from hashlib import sha256
    from sciplot_core.mcp_server import server
    png = base64.b64decode('iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+jP1sAAAAASUVORK5CYII=')
    path = tmp_path / 'candidate.png'
    path.write_bytes(png)
    exc = TaskControlError('stale_task_preview', 'Review the current image before deciding.')
    exc.repair = {'action': 'correct_response', 'operation_id': 'b' * 64,
                  'preview': {'image': {'path': str(path), 'sha256': sha256(png).hexdigest()},
                              'scientific_audit': {'status': 'passed'}},
                  'next_step': {'action': 'view_preview_then_decide'}}
    def reject(*args):
        raise exc
    monkeypatch.setattr(server, 'invoke_owner', reject)
    async def scenario():
        adapter = server.Adapter()
        result = await adapter.call('sciplot_task_resume', {'task': '/task', 'response': {
            'accept_preview': True, 'expected_operation_id': 'a' * 64}})
        repair = result.structured_content['repair']
        assert result.is_error and repair['operation_id'] == 'b' * 64
        assert repair['next_step']['action'] == 'view_preview_then_decide'
        uri = repair['preview_resource']
        path.write_bytes(b'changed after snapshot')
        resource = await adapter.call('sciplot_read_result', {'uri': uri})
        assert base64.b64decode(resource.content[1].data) == png
        assert resource.content[1].mime_type == 'image/png'
        assert 'preview_resource' not in exc.repair
        rejected = await adapter.call('sciplot_task_resume', {'task': '/task', 'response': {
            'accept_preview': True, 'expected_operation_id': 'a' * 64}})
        assert rejected.is_error and rejected.structured_content['resource_warnings']
        assert 'preview_resource' not in rejected.structured_content['repair']
    anyio.run(scenario)


def test_short_mcp_schema_errors_do_not_write_repeated_schema_as_diagnostic(monkeypatch):
    import pytest
    from jsonschema import Draft202012Validator
    from jsonschema.exceptions import ValidationError
    from sciplot_core import task_error_feedback
    from sciplot_core.task_contract import task_request_schema
    monkeypatch.setattr(task_error_feedback.tempfile, 'mkstemp', lambda **_: pytest.fail('short field errors need no diagnostic file'))
    with pytest.raises(ValidationError) as caught:
        Draft202012Validator(task_request_schema()).validate({'version': 1, 'action': 'create', 'source': ''})
    assert len(str(caught.value)) > 1000
    result = error_payload(caught.value)
    assert result['error']['code'] == 'invalid_arguments' and 'diagnostics' not in result


def test_invalid_non_discriminator_constant_keeps_operation_branch():
    request = {'version': 1, 'action': 'edit', 'project': '/project', 'expected_document_sha256': 'a' * 64,
               'operations': [{'op': 'add_annotation', 'id': 'title', 'parent_path': '/wrong', 'text': 'Title',
                               'position': {'mode': 'relative', 'x': 'far', 'y': 0.5}}]}
    issues = wire_issues(request, section='request')
    assert {item['path'] for item in issues} == {'/operations/0/parent_path', '/operations/0/position/x'}


def test_cli_style_bad_width_exposes_owner_issue_without_task_or_context(tmp_path):
    import subprocess
    result = subprocess.run([str(Path('skill/scripts/sciplot').resolve()), 'task', 'style', str(tmp_path / 'missing-project'),
                             '--sample', 'A', '--width', '0.7', '--json'], capture_output=True, text=True, check=False)
    payload = json.loads(result.stdout)
    assert result.returncode == 1 and payload['reason_code'] == 'invalid_sample_style'
    issue = payload['issues'][0]
    assert issue['path'] == '/operations/0/style/width'
    assert issue['constraint'] == 'positive_physical_size'
    assert issue['allowed_units'] == ['pt', 'mm', 'cm', 'in', 'inch']
    assert issue['example'] == '0.7pt'
    assert list(tmp_path.iterdir()) == []


def test_mcp_direct_annotation_error_preserves_same_precise_owner_issue(monkeypatch):
    import anyio
    from sciplot_core.mcp_server import server
    from sciplot_core.studio_core.annotation_schema import validate_operation_batch
    operation = {'op': 'set_sample_style', 'samples': ['A'], 'style': {'width': '0.7'}}
    def invalid_operation(*args):
        validate_operation_batch([operation])
    monkeypatch.setattr(server, 'invoke_owner', invalid_operation)
    async def scenario():
        adapter = server.Adapter()
        result = await adapter.call('sciplot_edit_preview', {'project': '/missing-project', 'operations': [operation],
                                                            'expected_document_sha256': 'a' * 64})
        payload = result.structured_content
        assert result.is_error and payload['error']['code'] == 'invalid_sample_style'
        assert payload['issues'][0] == {'path': '/operations/0/style/width', 'constraint': 'positive_physical_size',
                                      'allowed_units': ['pt', 'mm', 'cm', 'in', 'inch'], 'example': '0.7pt'}
    anyio.run(scenario)
