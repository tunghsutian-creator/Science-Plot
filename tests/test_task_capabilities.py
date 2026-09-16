"""Compact discovery preserves complete validation and revision-bound guidance."""

from copy import deepcopy
import json

from jsonschema import Draft202012Validator
import pytest

from sciplot_core.task_capabilities import task_capabilities
from sciplot_core.task_contract import TaskControlError, task_request_schema, task_response_schema
from sciplot_core.task_next_step import task_next_step
from sciplot_core.task_schema_compaction import compact_schema


def expand(schema):
    def visit(value):
        if isinstance(value, list):
            return [visit(item) for item in value]
        if not isinstance(value, dict):
            return value
        if "$ref" in value:
            assert set(value) == {"$ref"}
            target = schema
            for key in value["$ref"][2:].split("/"):
                target = target[key]
            return visit(target)
        return {key: visit(item) for key, item in value.items() if key != "$defs"}
    return visit(schema)


@pytest.mark.parametrize("factory", [task_request_schema, task_response_schema])
def test_compaction_is_lossless_and_standalone(factory):
    original = factory()
    before = deepcopy(original)
    compact = compact_schema(original)
    Draft202012Validator.check_schema(compact)
    assert expand(compact) == original == before
    assert len(json.dumps(compact)) < len(json.dumps(original))


def test_index_and_each_on_demand_schema_share_contract_and_exact_validation():
    index = task_capabilities()
    assert len(json.dumps(index)) < 2500
    assert "request_schema" not in index
    for section in ("request", "response", "operations"):
        for name in index["sections"][section]:
            result = task_capabilities(section=section, name=name, expected_contract_sha256=index["contract_sha256"])
            assert result["contract_sha256"] == index["contract_sha256"]
            Draft202012Validator.check_schema(result["schema"])
    full = task_capabilities(full=True)
    assert expand(full["request_schema"]) == task_request_schema()
    assert expand(full["response_schema"]) == task_response_schema()
    create = task_capabilities(section="request", name="create")["schema"]
    assert Draft202012Validator(create).is_valid({"version": 1, "action": "create", "source": "/source.xlsx"})
    for bad in ({"version": 2, "action": "create", "source": "/source.xlsx"},
                {"version": 1, "action": "create", "source": "/source.xlsx", "python": "exec"}):
        assert not Draft202012Validator(create).is_valid(bad)
    edit = task_capabilities(section="request", name="edit")["schema"]
    good = {"version": 1, "action": "edit", "project": "/project", "expected_document_sha256": "a" * 64,
            "operations": [{"op": "set_sample_style", "samples": ["A"], "style": {"color": "#ffffff"}}]}
    assert Draft202012Validator(edit).is_valid(good)
    assert not Draft202012Validator(edit).is_valid({**good, "operations": [{"op": "run_python"}]})


@pytest.mark.parametrize("query", [
    {"expected_contract_sha256": "0" * 64}, {"section": "unknown"},
    {"section": "operations", "name": "run_python"}, {"name": "edit"},
    {"full": True, "section": "request"}, {"section": "table_region", "name": "x"},
])
def test_bad_or_stale_schema_query_fails(query):
    with pytest.raises(TaskControlError):
        task_capabilities(**query)


def test_next_steps_bind_current_question_review_and_recovery_boundaries():
    state = {"status": "needs_input", "phase": "scientific_choice", "task_dir": "/task",
             "request": {"action": "create"}, "question": {"field": "column_mapping", "question_id": "a" * 64}}
    assert task_next_step(state)["response_bindings"] == {"expected_question_id": "a" * 64}
    state.update(status="needs_review", operation_id="b" * 64)
    assert task_next_step(state)["response_bindings"] == {"expected_operation_id": "b" * 64}
    state.update(status="blocked", phase="exporting")
    assert task_next_step(state)["response"] == {"retry": True}
    state.update(phase="creating", blocker={"reason_code": "creation_outcome_uncertain"})
    assert "response" not in task_next_step(state)
    state.update(phase="previewing", request={"action": "edit"}, edit_revisions=[{}])
    assert task_next_step(state)["response_bindings"] == {"expected_preview_revision": 2}
    state.update(phase="applying", request={"action": "update_source"})
    assert "response" not in task_next_step(state)
