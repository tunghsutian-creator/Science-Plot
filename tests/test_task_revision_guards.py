from __future__ import annotations

import copy

import pytest
from jsonschema import Draft202012Validator

from sciplot_core.task_contract import TaskControlError, task_response_schema
from sciplot_core.task_editing import begin_preview_revision


def state():
    return {"request": {"version": 1, "action": "edit", "project": "/p", "export": False,
                        "expected_document_sha256": "b" * 64, "operations": [operation()]},
            "status": "blocked", "phase": "previewing", "operation_id": "a" * 64,
            "blocker": {"message": "Native preview failed"}, "preview_attempt": 1}


def operation():
    return {"op": "set_style", "object_path": "/page1/graph1/series_1",
            "setting_path": "/page1/graph1/series_1/PlotLine/width", "expected_value": "1pt", "value": "2pt"}


@pytest.mark.parametrize("patch", [{"status": "running"}, {"phase": "applying"},
    {"phase": "exporting"}, {"status": "complete"}, {"status": "cancelled"},
    {"preview_accepted": True}, {"applied_operation": {"status": "pending"}},
    {"request": {"action": "export"}},
])
def test_failed_revision_never_replaces_uncertain_or_completed_work(patch):
    value = {**state(), **patch}
    before = copy.deepcopy(value)
    with pytest.raises(TaskControlError) as error:
        begin_preview_revision(value, {"expected_preview_revision": 1, "revise_operations": [operation()]})
    assert error.value.reason_code == "task_not_revisable" and value == before


@pytest.mark.parametrize("binding", [True, 0, -1, 1.0, "1", None])
def test_failed_revision_requires_an_actual_positive_integer(binding):
    value = state()
    before = copy.deepcopy(value)
    with pytest.raises(TaskControlError) as error:
        begin_preview_revision(value, {"expected_preview_revision": binding, "revise_operations": [operation()]})
    assert error.value.reason_code == "invalid_task_response" and value == before


@pytest.mark.parametrize("response,status", [
    ({"expected_preview_revision": 2}, "blocked"),
    ({"expected_operation_id": "a" * 64}, "blocked"),
    ({"expected_preview_revision": 1}, "needs_review"),
])
def test_stale_or_wrong_binding_cannot_replace_current_intent(response, status):
    value = {**state(), "status": status}
    before = copy.deepcopy(value)
    with pytest.raises(TaskControlError) as error:
        begin_preview_revision(value, {**response, "revise_operations": [operation()]})
    assert error.value.reason_code == "stale_task_preview" and value == before


def test_mixed_version_keys_and_bad_replacements_leave_failure_evidence_unchanged():
    value = state()
    for response in [
        {"expected_preview_revision": 1, "expected_operation_id": "a" * 64, "revise_operations": [operation()]},
        {"expected_preview_revision": 1, "revise_operations": [{"op": "set_style"}]},
    ]:
        before = copy.deepcopy(value)
        with pytest.raises(TaskControlError):
            begin_preview_revision(value, response)
        assert value == before


def test_response_schema_exposes_exclusive_correction_and_review_bindings():
    validator = Draft202012Validator(task_response_schema())
    replacement = {"revise_operations": [operation()]}
    validator.validate({**replacement, "expected_preview_revision": 1})
    validator.validate({**replacement, "expected_operation_id": "a" * 64})
    assert not validator.is_valid({**replacement, "expected_preview_revision": True})
    assert not validator.is_valid({**replacement, "expected_preview_revision": 1, "expected_operation_id": "a" * 64})
