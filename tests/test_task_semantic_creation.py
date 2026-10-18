"""The ordinary task owns semantic preparation, correction and managed recovery."""
from copy import deepcopy
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator

from sciplot_core.task_contract import TaskControlError, task_request_schema, task_response_schema, validate_task_request


def request(source: Path) -> dict:
    return {"version": 1, "action": "create", "sources": [str(source)],
            "intent": {"x": {"quantity": "time", "unit": "min"},
                       "y": {"quantity": "mass", "unit": "%", "minimum": 95},
                       "secondary_y": {"quantity": "temperature"},
                       "stages": {"mode": "concatenate"},
                       "display": {"marker_every": 20}}}


def test_public_semantic_request_keeps_scientific_intent_small_and_closed(tmp_path):
    value = request(tmp_path / "original.xlsx")
    assert validate_task_request(value) == value
    assert Draft202012Validator(task_request_schema()).is_valid(value)
    for mutation in ({"template_definition": {}}, {"intent": {"magic_smooth": True}},
                     {"source": "other.csv"}, {"sources": []}):
        rejected = {**value, **mutation}
        assert not Draft202012Validator(task_request_schema()).is_valid(rejected)
        with pytest.raises(TaskControlError):
            validate_task_request(rejected)


def test_same_task_plan_response_and_revision_contracts_are_shared():
    confirm = {"expected_question_id": "a" * 64, "confirm_plan": True,
               "choices": {"temperature_header": "Ts", "stage_order": "temperature_continuity",
                           "time_boundary": "preserve_endpoint", "temperature_source": "source:0"}}
    assert Draft202012Validator(task_response_schema()).is_valid(confirm)
    revision = {"expected_intent_revision": 1, "revise_intent": {
        "x": {"quantity": "time", "unit": "min"}, "y": {"quantity": "mass", "minimum": 95}}}
    assert Draft202012Validator(task_response_schema()).is_valid(revision)
    assert not Draft202012Validator(task_response_schema()).is_valid({**confirm, "idempotency_key": "AI-key"})


def test_semantic_plan_is_one_question_before_any_render(tmp_path, monkeypatch):
    from sciplot_core import task_control as control, task_semantic_creation as semantic
    source = tmp_path / "source.csv"
    source.write_text("t,Mass,Ts\ns,%,°C\n0,100,30\n1,99,40\n")
    calls = []
    monkeypatch.setattr(semantic, "prepare_plan", lambda paths, intent: {
        "sources": [{"source_id": "source:0", "path": str(source), "sha256": __import__("hashlib").sha256(source.read_bytes()).hexdigest()}],
        "decisions": [{"field": "temperature_header", "options": ["Ts", "Tr"]}]})
    monkeypatch.setattr(semantic, "execute_managed", lambda *args: calls.append(args) or {})
    result = control.start_task(request(source), task_dir=tmp_path / "task")
    assert result["status"] == "needs_input"
    assert result["question"]["field"] == "semantic_plan"
    assert result["next_step"]["response_template"]["confirm_plan"] is True
    assert calls == []
    before = (tmp_path / "task" / "task.json").read_bytes()
    with pytest.raises(TaskControlError) as rejected:
        control.resume_task(tmp_path / "task", {"expected_question_id": "b" * 64, "confirm_plan": True})
    assert rejected.value.reason_code == "stale_task_question"
    assert (tmp_path / "task" / "task.json").read_bytes() == before


def test_task_owns_retry_key_and_scientific_rejection_can_revise(tmp_path, monkeypatch):
    from sciplot_core import task_control as control, task_semantic_creation as semantic
    source = tmp_path / "source.csv"
    source.write_text("t,Mass\ns,%\n0,100\n1,99\n")
    monkeypatch.setattr(semantic, "prepare_plan", lambda paths, intent: {"sources": [], "decisions": [{"field": "time_boundary", "options": ["preserve_endpoint", "next_sample"]}]})
    def build(state):
        return {"idempotency_key": "task-attempt-" + str(state["intent_revision"]),
                "data_binding": {"data_sources": [{"path": str(source)}]}}
    monkeypatch.setattr(semantic, "build_managed_request", build)
    keys = []
    def execute(state, wire):
        keys.append(wire["idempotency_key"])
        if len(keys) == 1:
            raise ValueError("scientific refusal before commit")
        return {"status": "complete", "ready_to_use": True, "plot": str(tmp_path / "managed"), "exports": [{"path": "/mock/export.pdf"}]}
    monkeypatch.setattr(semantic, "execute_managed", execute)
    monkeypatch.setattr(semantic, "current_result", lambda state: {**__import__("sciplot_core.task_storage", fromlist=["task_summary"]).task_summary(state), "ready_to_use": True})
    task = tmp_path / "task"
    first = control.start_task(request(source), task_dir=task)
    answer = {"expected_question_id": first["question"]["question_id"], "confirm_plan": True, "choices": {"time_boundary": "preserve_endpoint"}}
    failed = control.resume_task(task, answer)
    assert failed["status"] == "blocked"
    assert failed["intent_revision"] == 1
    revised_intent = deepcopy(request(source)["intent"])
    revised_intent["y"]["minimum"] = 94
    revised = control.resume_task(task, {"expected_intent_revision": 1, "revise_intent": revised_intent})
    assert revised["status"] == "needs_input" and revised["intent_revision"] == 2
    answer = {"expected_question_id": revised["question"]["question_id"], "confirm_plan": True, "choices": {"time_boundary": "preserve_endpoint"}}
    done = control.resume_task(task, answer)
    assert done["status"] == "complete" and keys == ["task-attempt-1", "task-attempt-2"]
    assert control.resume_task(task, {"retry": True})["status"] == "complete"
    assert len(keys) == 2


def test_changed_second_attachment_blocks_plan_confirmation(tmp_path, monkeypatch):
    from sciplot_core import task_control as control, task_semantic_creation as semantic
    first = tmp_path / "first.csv"
    second = tmp_path / "second.csv"
    first.write_text("x,y\ns,%\n0,100\n")
    second.write_text(first.read_text())
    value = request(first) | {"sources": [str(first), str(second)]}
    monkeypatch.setattr(semantic, "prepare_plan", lambda paths, intent: {"sources": [], "decisions": [{"field": "time_boundary", "options": ["preserve_endpoint", "next_sample"]}]})
    monkeypatch.setattr(semantic, "execute_managed", lambda *args: pytest.fail("changed raw executed"))
    started = control.start_task(value, task_dir=tmp_path / "task")
    second.write_text(second.read_text() + "1,99\n")
    result = control.resume_task(tmp_path / "task", {
        "expected_question_id": started["question"]["question_id"], "confirm_plan": True, "choices": {"time_boundary": "preserve_endpoint"}})
    assert result["status"] == "blocked" and result["blocker"]["reason_code"] == "source_changed"


def test_program_expands_source_metadata_units_and_house_layout(tmp_path):
    from sciplot_core.task_semantic_plan import prepare_plan
    from sciplot_core.task_semantic_figure import build_request
    from sciplot_core.plot_engine.contracts import validate_create
    from sciplot_core.plot_ir import create_managed_document
    source = tmp_path / "anonymous.csv"
    source.write_text("Time (s),Mass (%),Temperature (°C)\n0,100.011,25\n2,99.2,30\n4,98,35\n")
    value = request(source)
    plan = prepare_plan([source], value["intent"])
    assert plan["decisions"] == []
    state = {"task_dir": str(tmp_path / "task"), "request": value, "intent_revision": 1,
             "semantic_plan": plan, "semantic_choices": {}}
    wire = validate_create(build_request(state))
    document = create_managed_document(wire["template_definition"], wire["data_binding"], plot_id="test")
    spec = wire["template_definition"]["figure_spec"]
    assert len(spec["views"][0]["layers"]) == 2
    assert spec["scales"][0]["unit"] == "min"
    y = next(item for item in spec["scales"] if item["id"] == "scale:y")
    assert y["domain"][0] == 95 and y["domain"][1] > 100.011
    assert document["scientific"]["data_sources"][0]["sha256"]
    assert any(node["kind"] == "convert_unit" for node in wire["data_binding"]["transforms"])
    assert wire["data_binding"]["provenance"]["semantic_task"]["layout_selection"]["attempts"][-1]["status"] == "fit"
    assert "column_index" not in str(value) and "template_definition" not in value


def test_different_segment_shape_keeps_all_raw_points_and_explicit_boundary(tmp_path):
    from sciplot_core.task_semantic_plan import prepare_plan
    from sciplot_core.task_semantic_figure import build_request
    from sciplot_core.plot_engine.managed_resolution import resolve_science, resolved_metadata
    from sciplot_core.plot_ir import create_managed_document
    source = tmp_path / "unknown-instrument.csv"
    source.write_text("t,Mass,Ts,,t,Mass,Ts\ns,%,°C,,s,%,°C\n"
                      "0,100,10,,0,99.7,25\n2,99.9,15,,2,99.6,25\n4,99.8,20,,4,99.5,25\n"
                      "6,99.7,25,,6,99.4,25\n0,99.3,25,,8,99.3,25\n2,99.2,30,,,,\n4,99.1,35,,,,\n")
    value = request(source)
    value["intent"]["stages"].update(order="temperature_continuity", boundary="preserve_endpoint")
    plan = prepare_plan([source], value["intent"])
    assert [stage["point_count"] for stage in plan["sources"][0]["candidates"][0]["stages"]] == [4, 3, 5]
    wire = build_request({"task_dir": str(tmp_path / "task"), "request": value, "intent_revision": 1,
                          "semantic_plan": plan, "semantic_choices": {}})
    document = create_managed_document(wire["template_definition"], wire["data_binding"], plot_id="test")
    document = resolved_metadata(document, rule_id=wire["rule_id"], executors={})
    resolved, _evidence = resolve_science(tmp_path / "science", document)
    from sciplot_core.plot_engine.content_store import resolve_document_content
    resolved = resolve_document_content(tmp_path / "science", resolved)
    dataset_id = wire["data_binding"]["slots"]["layer:response:0"]["x"]["source_id"]
    dataset = resolved["scientific"]["provenance"]["datasets"][dataset_id]
    xs = dataset["columns"]["x"]["values"]
    assert len(xs) == 12 and xs[-1] == pytest.approx(18 / 60)
    assert xs[3] == xs[4] and xs[8] == xs[9]
    assert dataset["columns"]["y"]["values"] == [100,99.9,99.8,99.7,99.7,99.6,99.5,99.4,99.3,99.3,99.2,99.1]
    concat = dataset["provenance"]["transforms"][-1]
    assert concat["parameters"]["boundary"] == "preserve_endpoint"


def test_semantic_directory_error_is_not_an_experiment_question(tmp_path):
    from sciplot_core.task_control import start_task
    from sciplot_core.foundation.file_hashing import file_sha256
    child = tmp_path / "original.csv"
    child.write_text("Time,Mass\ns,%\n0,100\n")
    digest = file_sha256(child)
    with pytest.raises(TaskControlError) as rejected:
        start_task(request(tmp_path), task_dir=tmp_path / "task")
    assert rejected.value.reason_code == "source_is_directory"
    assert rejected.value.repair["files"] == [str(child)]
    assert file_sha256(child) == digest and not (tmp_path / "task").exists()


def test_explicit_unambiguous_intent_does_not_add_a_confirmation_round(tmp_path, monkeypatch):
    from sciplot_core import task_control as control, task_semantic_creation as semantic
    source = tmp_path / "data.csv"
    source.write_text("Time,Mass\ns,%\n0,100\n1,99\n")
    monkeypatch.setattr(semantic, "prepare_plan", lambda paths, intent: {"sources": [], "decisions": []})
    monkeypatch.setattr(semantic, "build_managed_request", lambda state: {"idempotency_key": "locally-owned"})
    calls = []
    monkeypatch.setattr(semantic, "execute_managed", lambda state, wire: calls.append(wire) or {"status": "complete", "ready_to_use": True, "plot": "/mock/managed", "exports": [{"path": "/mock/export.pdf"}]})
    monkeypatch.setattr(semantic, "current_result", lambda state: __import__("sciplot_core.task_storage", fromlist=["task_summary"]).task_summary(state))
    result = control.start_task(request(source), task_dir=tmp_path / "task")
    assert result["status"] == "complete" and len(calls) == 1
    assert "question" not in result


def test_unadvertised_choice_cannot_override_explicit_or_unambiguous_facts(tmp_path, monkeypatch):
    from sciplot_core import task_control as control, task_semantic_creation as semantic
    source = tmp_path / "data.csv"
    source.write_text("Time,Mass\ns,%\n0,100\n1,99\n")
    monkeypatch.setattr(semantic, "prepare_plan", lambda paths, intent: {"sources": [], "decisions": [
        {"field": "time_boundary", "options": ["preserve_endpoint", "next_sample"]}]})
    monkeypatch.setattr(semantic, "execute_managed", lambda *args: pytest.fail("extra choice executed"))
    task = tmp_path / "task"
    result = control.start_task(request(source), task_dir=task)
    before = (task / "task.json").read_bytes()
    with pytest.raises(TaskControlError) as rejected:
        control.resume_task(task, {"expected_question_id": result["question"]["question_id"], "confirm_plan": True,
                                  "choices": {"time_boundary": "preserve_endpoint", "temperature_header": "Tr"}})
    assert rejected.value.reason_code == "invalid_task_response"
    assert (task / "task.json").read_bytes() == before


def test_multiple_responses_return_one_repairable_header_choice(tmp_path):
    from sciplot_core.task_semantic_plan import prepare_plan
    from sciplot_core.task_semantic_figure import build_request
    source = tmp_path / "responses.csv"
    source.write_text("Time,Mass,Weight\ns,%,%\n0,100,98\n1,99,97\n")
    value = request(source)
    value["intent"].pop("secondary_y")
    plan = prepare_plan([source], value["intent"])
    decision = next(item for item in plan["decisions"] if item["field"] == "y_header")
    assert decision["options"] == ["Mass", "Weight"]
    wire = build_request({"task_dir": str(tmp_path / "task"), "request": value, "intent_revision": 1,
                          "semantic_plan": plan, "semantic_choices": {"y_header": "Weight"}})
    selected = next(node for node in wire["data_binding"]["transforms"] if node["kind"] == "select")
    assert selected["parameters"]["columns"] == ["column:0", "column:2"]
    invalid = deepcopy(value)
    invalid["intent"]["y"]["header"] = "not an original header"
    with pytest.raises(TaskControlError) as rejected:
        prepare_plan([source], invalid["intent"])
    assert rejected.value.reason_code == "semantic_coordinate_mapping_required"
    assert rejected.value.repair["existing_mapping_route"]


def test_secondary_quantity_is_closed_to_implemented_temperature(tmp_path):
    value = request(tmp_path / "data.csv")
    value["intent"]["secondary_y"]["quantity"] = "pressure"
    assert not Draft202012Validator(task_request_schema()).is_valid(value)
    with pytest.raises(TaskControlError):
        validate_task_request(value)


@pytest.mark.parametrize("action", ["inspect_diagnostic", "correct_layout", "refresh_scientific_binding"])
def test_managed_failure_owner_action_is_not_converted_to_blind_retry(action):
    from sciplot_core.task_semantic_creation import blocked_next_step
    state = {"task_dir": "/task", "project": "/managed", "status": "blocked", "phase": "exporting",
             "request": {"action": "create", "intent": {}}, "intent_revision": 1,
             "blocker": {"reason_code": "native_failure", "recovery_action": action,
                         "owner_next_step": {"action": action}, "diagnostic": {"path": "/diagnostic.json"}}}
    step = blocked_next_step(state)
    assert step["action"] == action and step["diagnostic"]["path"] == "/diagnostic.json"
    assert "response_template" not in step and "cli_argv" not in step


def test_lost_creation_reply_cannot_replace_an_already_committed_attempt(tmp_path, monkeypatch):
    from sciplot_core import task_control as control, task_semantic_creation as semantic
    from sciplot_core.plot_engine.storage import digest
    source = tmp_path / "original.csv"
    source.write_text("Time,Mass\ns,%\n0,100\n1,99\n")
    original = source.read_bytes()
    monkeypatch.setattr(semantic, "prepare_plan", lambda paths, intent: {"sources": [], "decisions": []})
    wire = {"idempotency_key": "frozen-attempt", "data_binding": {"data_sources": [{"path": str(source)}]}}
    monkeypatch.setattr(semantic, "build_managed_request", lambda state: deepcopy(wire))
    calls = []
    def commit_without_reply(state, request):
        calls.append(request)
        owner = source.parent / ".sciplot_documents" / "managed" / digest(request["idempotency_key"])
        owner.mkdir(parents=True)
        (owner / "head.json").write_text("{}")
        raise OSError("lost reply after commit")
    monkeypatch.setattr(semantic, "execute_managed", commit_without_reply)
    task = tmp_path / "task"
    result = control.start_task(request(source), task_dir=task)
    assert result["status"] == "blocked" and len(calls) == 1
    changed = deepcopy(request(source)["intent"])
    changed["y"]["minimum"] = 90
    before = (task / "task.json").read_bytes()
    with pytest.raises(TaskControlError) as rejected:
        control.resume_task(task, {"expected_intent_revision": 1, "revise_intent": changed})
    assert rejected.value.reason_code == "task_not_revisable"
    assert (task / "task.json").read_bytes() == before and source.read_bytes() == original
    assert len(calls) == 1
