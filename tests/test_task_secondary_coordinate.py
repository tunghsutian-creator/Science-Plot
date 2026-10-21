"""Secondary coordinate declarations bind the observed column they name."""
from copy import deepcopy

import pytest

from sciplot_core.task_errors import TaskControlError
from sciplot_core.task_semantic_contract import validate_intent
from sciplot_core.task_semantic_plan import prepare_plan


def original(tmp_path):
    source = tmp_path / "temperature.csv"
    source.write_text("Time,Mass,Ts,Tr\ns,%,C,C\n0,100,10,80\n1,99,20,90\n")
    return source


def intent(**secondary):
    return {"x": {"quantity": "time", "unit": "s"}, "y": {"quantity": "mass", "unit": "%"},
            "secondary_y": {"quantity": "temperature", **secondary}}


def values(source, value, tmp_path, choices=None):
    from sciplot_core.plot_engine.managed_sources import load_sources
    from sciplot_core.plot_ir import create_managed_document
    from sciplot_core.plot_transforms import resolve_transforms
    from sciplot_core.task_semantic_creation import build_managed_request

    plan = prepare_plan([source], validate_intent(value))
    if not choices:
        assert not plan["decisions"]
    wire = build_managed_request({"request": {"intent": value}, "semantic_plan": plan, "semantic_choices": choices or {},
                                  "task_dir": str(tmp_path / "task"), "intent_revision": 1})
    document = create_managed_document(wire["template_definition"], wire["data_binding"], plot_id="temperature")
    resolved = resolve_transforms(document, load_sources(document, "tga_curve"))
    slot = wire["data_binding"]["slots"]["layer:temperature"]
    column = resolved["datasets"][slot["y"]["source_id"]]["columns"][slot["y"]["column"]]
    return column, wire


@pytest.mark.parametrize("selector", [{"header": "Tr"}, {"column_id": "column:3"},
                                      {"header": "Tr", "column_id": "column:3"}])
def test_exact_secondary_selector_determines_numbers_without_redundant_question(tmp_path, selector):
    source = original(tmp_path)
    raw = source.read_bytes()
    column, wire = values(source, intent(**selector), tmp_path)
    assert column["values"] == [80, 90]
    assert column["unit"] == "C"
    assert wire["data_binding"]["provenance"]["semantic_task"]["intent"]["secondary_y"] == intent(**selector)["secondary_y"]
    assert source.read_bytes() == raw


@pytest.mark.parametrize("secondary,legacy", [({"header": "Tr"}, "Ts"),
                                           ({"header": "Ts", "column_id": "column:3"}, None),
                                           ({"column_id": "column:3"}, "Ts")])
def test_contradictory_explicit_temperature_selectors_fail_closed(tmp_path, secondary, legacy):
    source = original(tmp_path)
    value = intent(**secondary)
    if legacy:
        value["temperature_header"] = legacy
    with pytest.raises(TaskControlError) as rejected:
        prepare_plan([source], value)
    assert rejected.value.reason_code in {"semantic_temperature_selector_conflict", "semantic_temperature_mapping_required"}


@pytest.mark.parametrize("selector", [{"header": "missing"}, {"column_id": "column:0"}])
def test_unmatched_secondary_selector_cannot_fall_back_to_another_temperature(tmp_path, selector):
    with pytest.raises(TaskControlError) as rejected:
        prepare_plan([original(tmp_path)], intent(**selector))
    assert rejected.value.reason_code == "semantic_temperature_mapping_required"
    assert rejected.value.repair["action"] == "revise_intent"


def test_legacy_temperature_header_and_equal_new_header_remain_compatible(tmp_path):
    source = original(tmp_path)
    value = intent()
    value["temperature_header"] = "Ts"
    column, _wire = values(source, value, tmp_path)
    assert column["values"] == [10, 20]
    value["secondary_y"]["header"] = "Ts"
    column, _wire = values(source, value, tmp_path)
    assert column["values"] == [10, 20]


def test_secondary_unit_conversion_uses_same_selected_column_and_formal_operator(tmp_path):
    column, wire = values(original(tmp_path), intent(header="Tr", unit="K"), tmp_path)
    assert column["values"] == pytest.approx([353.15, 363.15])
    assert column["unit"] == "K"
    assert any(node["kind"] == "convert_unit" and node["parameters"] == {
        "columns": ["temperature"], "from_unit": "C", "to_unit": "K"} for node in wire["data_binding"]["transforms"])


def test_unsupported_secondary_unit_cannot_be_relabelled_as_a_valid_temperature(tmp_path):
    source = original(tmp_path)
    raw = source.read_bytes()
    # The same incompatibility is refused while resolving the task plan,
    # before the Managed lowerer or its registered operator can execute it.
    with pytest.raises(TaskControlError) as rejected:
        values(source, intent(header="Tr", unit="kg"), tmp_path)
    assert rejected.value.reason_code == "transform_unit_incompatible"
    assert rejected.value.issues == [{"path": "/intent/secondary_y/unit", "column_id": "column:3",
                                      "source_unit": "C", "unit": "kg", "constraint": "registered_unit_relation"}]
    assert rejected.value.repair["action"] == "revise_intent"
    assert source.read_bytes() == raw


def test_duplicate_temperature_header_needs_the_intersecting_column_identity(tmp_path):
    source = tmp_path / "duplicate-roles.csv"
    source.write_text("Time,Mass,Ts,Ts\ns,%,C,C\n0,100,10,80\n1,99,20,90\n")
    with pytest.raises(TaskControlError) as rejected:
        prepare_plan([source], intent(header="Ts"))
    assert rejected.value.reason_code == "semantic_temperature_mapping_required"
    column, _wire = values(source, intent(header="Ts", column_id="column:3"), tmp_path)
    assert column["values"] == [80, 90]


def test_column_identity_also_chooses_the_temperature_continuity_role(tmp_path):
    source = tmp_path / "reset-temperature-roles.csv"
    source.write_text("Time,Mass,Ts,Tr\ns,%,C,C\n0,100,10,80\n1,99,20,90\n0,98,19,20\n1,97,30,79\n")
    value = intent(column_id="column:3")
    value["stages"] = {"mode": "concatenate", "order": "temperature_continuity", "boundary": "preserve_endpoint"}
    column, _wire = values(source, value, tmp_path)
    assert column["values"] == [20, 79, 80, 90]


def test_unselected_block_temperature_does_not_create_a_false_choice(tmp_path):
    source = tmp_path / "two-blocks.csv"
    source.write_text("Time,Mass,Ts,Tr,,Time,Mass,Ts,Tr\ns,%,C,C,,s,%,C,C\n"
                      "0,100,1,2,,0,80,10,80\n1,99,2,3,,1,79,20,90\n")
    value = intent(column_id="column:8")
    value["selection"] = {"blocks": [{"source_id": "source:0", "table_id": "table:0", "block_id": "block:1"}]}
    column, _wire = values(source, value, tmp_path)
    assert column["values"] == [80, 90]


def test_unselected_temperature_choice_remains_explicit_and_cannot_override_new_selector(tmp_path):
    source = original(tmp_path)
    plan = prepare_plan([source], intent())
    assert next(item for item in plan["decisions"] if item["field"] == "temperature_header")["options"] == ["Tr", "Ts"]
    column, _wire = values(source, intent(), tmp_path, choices={"temperature_header": "Tr"})
    assert column["values"] == [80, 90]
    value = intent(header="Tr")
    with pytest.raises(TaskControlError) as rejected:
        values(source, deepcopy(value), tmp_path, choices={"temperature_header": "Ts"})
    assert rejected.value.reason_code == "semantic_temperature_selector_conflict"


def partial_temperature_source(tmp_path):
    source = tmp_path / "optional-temperature.csv"
    source.write_text("Time,Mass,Temperature,,Time,Mass\ns,%,C,,s,%\n0,100,10,,0,80\n1,99,20,,1,79\n")
    return source


def stage_intent(order=None):
    value = {"x": {"quantity": "time", "unit": "s"}, "y": {"quantity": "mass", "unit": "%"},
             "stages": {"mode": "concatenate", "boundary": "preserve_endpoint"}}
    if order is not None:
        value["stages"]["order"] = order
    return value


def test_source_order_never_requires_an_unconsumed_auxiliary_temperature(tmp_path):
    from sciplot_core.plot_engine.managed_sources import load_sources
    from sciplot_core.plot_ir import create_managed_document
    from sciplot_core.plot_transforms import resolve_transforms
    from sciplot_core.task_semantic_figure import build_request

    source = partial_temperature_source(tmp_path)
    raw = source.read_bytes()
    value = stage_intent("source_order")
    plan = prepare_plan([source], value)
    assert plan["decisions"] == []
    wire = build_request({"request": {"intent": value}, "semantic_plan": plan, "semantic_choices": {},
                          "task_dir": str(tmp_path / "task"), "intent_revision": 1})
    document = create_managed_document(wire["template_definition"], wire["data_binding"], plot_id="source-order")
    resolved = resolve_transforms(document, load_sources(document, "tga_curve"))
    dataset_id = wire["data_binding"]["slots"]["layer:response:0"]["x"]["source_id"]
    assert resolved["datasets"][dataset_id]["columns"]["x"]["values"] == [0, 1, 1, 2]
    assert resolved["datasets"][dataset_id]["columns"]["y"]["values"] == [100, 99, 80, 79]
    assert not any("temperature" in str(node["parameters"]) for node in wire["data_binding"]["transforms"])
    assert source.read_bytes() == raw


def test_unresolved_stage_order_retains_source_order_without_requiring_temperature(tmp_path):
    plan = prepare_plan([partial_temperature_source(tmp_path)], stage_intent())
    assert plan["decisions"] == [{"field": "stage_order", "options": ["source_order"],
                                  "message": "Confirm stage order from source evidence. Temperature continuity is an explicit proposal, never an automatic experiment interpretation."}]


def test_explicit_temperature_continuity_still_requires_every_consumed_temperature(tmp_path):
    with pytest.raises(TaskControlError) as rejected:
        prepare_plan([partial_temperature_source(tmp_path)], stage_intent("temperature_continuity"))
    assert rejected.value.reason_code == "semantic_temperature_mapping_required"


def test_tables_then_source_order_answers_do_not_invent_a_temperature_question(tmp_path, monkeypatch):
    from openpyxl import Workbook
    from sciplot_core import task_control, task_semantic_creation as creation

    source = partial_temperature_source(tmp_path)
    book = tmp_path / "stages.xlsx"
    workbook = Workbook()
    for row in source.read_text().splitlines():
        workbook.active.append(row.split(","))
    other = workbook.create_sheet("Other")
    for row in [["Time", "Mass"], ["s", "%"], [0, 1], [1, 2]]:
        other.append(row)
    workbook.save(book)
    calls = []
    monkeypatch.setattr(creation, "execute_managed", lambda current, wire: calls.append(wire) or {
        "status": "blocked", "ready_to_use": False, "next_step": {"action": "retry_same_request"}})
    task = tmp_path / "task"
    result = task_control.start_task({"version": 1, "action": "create", "sources": [str(book)], "intent": stage_intent()}, task_dir=task)
    result = task_control.resume_task(task, {"expected_question_id": result["question"]["question_id"], "confirm_plan": True,
                                          "choices": {"tables": {"source:0": "table:0"}}})
    assert result["status"] == "needs_input" and not calls
    assert [decision["field"] for decision in result["question"]["plan"]["decisions"]] == ["stage_order"]
    result = task_control.resume_task(task, {"expected_question_id": result["question"]["question_id"], "confirm_plan": True,
                                          "choices": {"stage_order": "source_order"}})
    assert len(calls) == 1 and "question" not in result
    assert calls[0]["data_binding"]["provenance"]["semantic_task"]["choices"] == {
        "tables": {"source:0": "table:0"}, "stage_order": "source_order"}


def test_answered_continuity_requires_its_temperature_role_before_creation(tmp_path, monkeypatch):
    from sciplot_core import task_control, task_semantic_creation as creation
    from sciplot_core.plot_engine.managed_sources import load_sources
    from sciplot_core.plot_ir import create_managed_document
    from sciplot_core.plot_transforms import resolve_transforms

    source = tmp_path / "two-continuity-roles.csv"
    source.write_text("Time,Mass,Ts,Tr\ns,%,C,C\n0,100,10,80\n1,99,20,90\n0,98,19,20\n1,97,30,79\n")
    raw = source.read_bytes()
    calls = []
    monkeypatch.setattr(creation, "execute_managed", lambda current, wire: calls.append(wire) or {
        "status": "blocked", "ready_to_use": False, "next_step": {"action": "retry_same_request"}})
    task = tmp_path / "task"
    result = task_control.start_task({"version": 1, "action": "create", "sources": [str(source)], "intent": stage_intent()}, task_dir=task)
    assert [item["field"] for item in result["question"]["plan"]["decisions"]] == ["stage_order"]
    result = task_control.resume_task(task, {"expected_question_id": result["question"]["question_id"], "confirm_plan": True,
                                          "choices": {"stage_order": "temperature_continuity"}})
    assert not calls and result["status"] == "needs_input"
    assert [item["field"] for item in result["question"]["plan"]["decisions"]] == ["temperature_header"]
    task_control.resume_task(task, {"expected_question_id": result["question"]["question_id"], "confirm_plan": True,
                                    "choices": {"temperature_header": "Tr"}})
    assert len(calls) == 1
    wire = calls[0]
    assert wire["data_binding"]["provenance"]["semantic_task"]["choices"] == {
        "stage_order": "temperature_continuity", "temperature_header": "Tr"}
    document = create_managed_document(wire["template_definition"], wire["data_binding"], plot_id="continuity")
    resolved = resolve_transforms(document, load_sources(document, "tga_curve"))
    slot = wire["data_binding"]["slots"]["layer:response:0"]["y"]
    assert resolved["datasets"][slot["source_id"]]["columns"][slot["column"]]["values"] == [98, 97, 100, 99]
    assert source.read_bytes() == raw
