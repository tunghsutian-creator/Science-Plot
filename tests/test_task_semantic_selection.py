"""Source-block selection composes with existing mapping, science and recovery."""
from copy import deepcopy
import hashlib
import math

import pytest

from sciplot_core.task_errors import TaskControlError
from sciplot_core.task_semantic_plan import prepare_plan
from test_frequency_interval_binding import instrument_source, intent


def mixed_source(tmp_path):
    foreign = instrument_source(tmp_path / "foreign.csv", temperatures=(210,))
    rows = foreign.read_text(encoding="utf-16").splitlines()[:11]
    rows[2] = "Test:\tLDPE-6UDC"
    rows[6] = "Interval and data points:\t1\t1"
    control = instrument_source(tmp_path / "control.csv")
    text = control.read_text(encoding="utf-16").replace("Anonymous material", "HDPE-Control")
    source = tmp_path / "mixed.csv"
    source.write_text("\n".join(rows) + "\n\n" + text, encoding="utf-16")
    return source


def reference(block="block:1", source="source:0", table="table:0"):
    return {"source_id": source, "table_id": table, "block_id": block}


def state(source, value, plan, tmp_path):
    return {"request": {"action": "create", "sources": [str(source)], "intent": value}, "semantic_plan": plan, "semantic_choices": {},
            "intent_revision": 1, "task_dir": str(tmp_path / "task")}


@pytest.mark.parametrize("selection", [
    {}, {"test_names": []}, {"test_names": ["HDPE-Control", "HDPE-Control"]},
    {"test_names": ["HDPE-Control"], "fuzzy": True}, {"blocks": ["block:1"]},
    {"blocks": [{"block_id": "block:1"}]}, {"blocks": [reference(), reference()]},
    {"blocks": [reference(source="source:wrong")]},
])
def test_selection_schema_is_closed_and_requires_qualified_nonempty_selectors(selection):
    from sciplot_core.task_semantic_contract import validate_intent

    with pytest.raises(TaskControlError) as rejected:
        validate_intent({**intent(), "selection": selection})
    assert rejected.value.reason_code == "invalid_semantic_intent"


def test_test_selection_keeps_four_original_results_and_formal_magnitude_units(tmp_path):
    from sciplot_core.plot_engine.contracts import validate_create
    from sciplot_core.plot_engine.managed_sources import load_sources
    from sciplot_core.plot_ir import create_managed_document
    from sciplot_core.plot_transforms import resolve_transforms
    from sciplot_core.task_semantic_creation import build_managed_request

    source = mixed_source(tmp_path)
    original = source.read_bytes()
    all_blocks = prepare_plan([source], intent())["sources"][0]["candidates"][0]["blocks"]
    value = {**intent(), "selection": {"test_names": ["HDPE-Control"]}}
    value["y"]["unit"] = "mPa s"
    plan = prepare_plan([source], value)
    assert plan["decisions"] == []
    blocks = plan["sources"][0]["candidates"][0]["blocks"]
    assert [block["block_id"] for block in blocks] == ["block:1", "block:2", "block:3", "block:4"]
    assert blocks == all_blocks[1:]
    assert [block["point_count"] for block in blocks] == [16] * 4
    assert [block["result"] for block in blocks] == [f"FS {t} °C" for t in (210, 190, 170, 150)]
    assert len({block["test_row"] for block in blocks}) == 1
    report = plan["selection"]
    assert len(report["available"]) == 5 and len(report["selected"]) == 4
    assert report["excluded"] == [{**reference("block:0"), "reasons": ["test_name_not_selected"]}]
    assert report["available"][0]["test_name"] == "LDPE-6UDC"
    assert report["available"][0]["point_count"] == 1
    assert all(block["source_sha256"] == hashlib.sha256(original).hexdigest() for block in report["available"])
    wire = validate_create(build_managed_request(state(source, value, plan, tmp_path)))
    assert wire["data_binding"]["provenance"]["semantic_task"]["selection"] == report
    document = create_managed_document(wire["template_definition"], wire["data_binding"], plot_id="selected")
    resolved = resolve_transforms(document, load_sources(document, value["rule_id"]))
    assert len(document["scientific"]["data_sources"]) == 4
    assert sum(node["kind"] == "rheology_complex_viscosity" for node in document["scientific"]["transforms"]) == 4
    layers = wire["template_definition"]["figure_spec"]["views"][0]["layers"]
    assert [layer["legend"]["label"] for layer in layers] == [f"HDPE-Control · {t} °C" for t in (210, 190, 170, 150)]
    for index, layer in enumerate(layers):
        dataset = resolved["datasets"][layer["dataset_id"]]
        assert len(dataset["columns"]["x"]["values"]) == 16
        assert dataset["columns"]["y"]["unit"] == "mPa s"
        assert dataset["columns"]["y"]["values"] == pytest.approx([
            math.hypot(500 - 100 * index + point, 30 + point) / (100 / (point + 1)) * 1000
            for point in range(16)])
    assert source.read_bytes() == original


def test_omitted_selection_retains_all_original_blocks_for_old_requests(tmp_path):
    plan = prepare_plan([mixed_source(tmp_path)], intent())
    blocks = plan["sources"][0]["candidates"][0]["blocks"]
    assert [block["point_count"] for block in blocks] == [1, 16, 16, 16, 16]
    assert plan["selection"]["mode"] == "all_original_blocks" and not plan["selection"]["excluded"]


def test_qualified_blocks_keep_original_order_and_intersect_test_names(tmp_path):
    source = mixed_source(tmp_path)
    value = {**intent(), "selection": {"test_names": ["HDPE-Control"],
                                        "blocks": [reference("block:4"), reference("block:1")]}}
    plan = prepare_plan([source], value)
    assert plan["selection"]["selected"] == [reference("block:1"), reference("block:4")]
    assert plan["sources"][0]["candidates"][0]["blocks"][0]["result"] == "FS 210 °C"
    assert plan["selection"]["excluded"][0]["reasons"] == ["test_name_not_selected", "block_not_selected"]


@pytest.mark.parametrize("selection,reason", [
    ({"test_names": ["HDPE control"]}, "semantic_source_selection_unmatched"),
    ({"test_names": ["HDPE-Control", "missing"]}, "semantic_source_selection_unmatched"),
    ({"blocks": [reference("block:99")]}, "semantic_source_selection_unmatched"),
    ({"test_names": ["HDPE-Control"], "blocks": [reference("block:0")]}, "semantic_source_selection_empty"),
])
def test_invalid_selection_never_falls_back_to_whole_source(tmp_path, selection, reason):
    source = mixed_source(tmp_path)
    original = source.read_bytes()
    with pytest.raises(TaskControlError) as rejected:
        prepare_plan([source], {**intent(), "selection": selection})
    error = rejected.value
    assert error.reason_code == reason and error.repair["action"] == "revise_intent"
    assert len(error.repair["available_blocks"]) == 5
    assert error.issues[0]["path"] == "/intent/selection"
    assert source.read_bytes() == original


def test_unknown_test_name_cannot_use_filename_or_inferred_sample(tmp_path):
    source = tmp_path / "HDPE-Control.csv"
    source.write_text("Time,Mass\ns,%\n0,100\n1,99\n")
    value = {"x": {"quantity": "time"}, "y": {"quantity": "mass"},
             "selection": {"test_names": ["HDPE-Control"]}}
    with pytest.raises(TaskControlError) as rejected:
        prepare_plan([source], value)
    assert rejected.value.reason_code == "semantic_test_selection_unavailable"


def test_qualified_blocks_are_scoped_to_attachment_and_preserve_source_id(tmp_path):
    first = instrument_source(tmp_path / "first.csv", temperatures=(210,))
    second = instrument_source(tmp_path / "second.csv", temperatures=(150,))
    plan = prepare_plan([first, second], {**intent(), "selection": {"blocks": [reference("block:0", "source:1")]}})
    assert [source["source_id"] for source in plan["sources"]] == ["source:1"]
    assert plan["selection"]["selected"] == [reference("block:0", "source:1")]
    assert plan["selection"]["excluded"][0] == {**reference("block:0"), "reasons": ["block_not_selected"]}


def test_qualified_selection_composes_with_existing_nonfrequency_stages(tmp_path):
    from sciplot_core.task_semantic_figure import build_request

    source = tmp_path / "parallel.csv"
    source.write_text("Time,Mass,,Time,Mass\ns,%,,s,%\n0,100,,0,80\n1,99,,1,79\n")
    value = {"x": {"quantity": "time", "unit": "s"}, "y": {"quantity": "mass", "unit": "%"},
             "selection": {"blocks": [reference("block:1")]}}
    plan = prepare_plan([source], value)
    assert not plan["decisions"]
    assert len(plan["sources"][0]["candidates"][0]["stages"]) == 1
    wire = build_request(state(source, value, plan, tmp_path))
    selected = next(node for node in wire["data_binding"]["transforms"] if node["kind"] == "select")
    assert selected["parameters"]["columns"] == ["column:3", "column:4"]
    assert not any(node["kind"] == "concat_time" for node in wire["data_binding"]["transforms"])


def test_selection_report_is_compactly_visible_without_coordinates(tmp_path):
    from sciplot_core.task_semantic_selection import selection_summary
    from sciplot_core.task_storage import task_summary

    source = mixed_source(tmp_path)
    value = {**intent(), "selection": {"test_names": ["HDPE-Control"]}}
    plan = prepare_plan([source], value)
    current = state(source, value, plan, tmp_path) | {"status": "running", "phase": "planning"}
    result = task_summary(current)["source_plan"]["selection"]
    assert result == selection_summary(plan["selection"])
    assert result["available_block_count"] == 5 and result["selected_block_count"] == 4
    assert result["selected_point_count"] == 64
    assert result["excluded"][0]["test_name"] == "LDPE-6UDC"
    assert "columns" not in str(result) and "values" not in str(result)


def test_rejected_selection_revises_same_task_and_keeps_idempotent_attempt(tmp_path, monkeypatch):
    from sciplot_core import task_control, task_semantic_creation as creation

    source = mixed_source(tmp_path)
    original = source.read_bytes()
    request = {"version": 1, "action": "create", "sources": [str(source)],
               "intent": {**intent(), "selection": {"test_names": ["wrong"]}}}
    calls = []
    monkeypatch.setattr(creation, "execute_managed", lambda current, wire: calls.append(wire) or {
        "status": "blocked", "ready_to_use": False, "next_step": {"action": "retry_same_request"}})
    task = tmp_path / "draft"
    blocked = task_control.start_task(request, task_dir=task)
    assert blocked["status"] == "blocked" and not calls
    assert blocked["blocker"]["reason_code"] == "semantic_source_selection_unmatched"
    correction = {**intent(), "selection": {"test_names": ["HDPE-Control"]}}
    continued = task_control.resume_task(task, {"expected_intent_revision": 1, "revise_intent": correction})
    assert continued["intent_revision"] == 2 and len(calls) == 1
    assert continued["source_plan"]["selection"]["selected_point_count"] == 64
    task_control.resume_task(task, {"retry": True})
    assert len(calls) == 2 and calls[0] == calls[1]
    assert calls[0]["idempotency_key"] == calls[1]["idempotency_key"]
    with pytest.raises(TaskControlError) as stale:
        task_control.resume_task(task, {"expected_intent_revision": 1, "revise_intent": correction})
    assert stale.value.reason_code == "stale_task_question"
    assert source.read_bytes() == original
    source.write_bytes(original + b"\x00")
    changed = task_control.resume_task(task, {"retry": True})
    assert changed["status"] == "blocked" and changed["blocker"]["reason_code"] == "source_changed"
    assert len(calls) == 2


def test_duplicate_evidence_references_fail_closed_without_mutating_source_facts():
    from sciplot_core.task_semantic_selection import select_source_blocks

    block = {"block_id": "block:0", "order": 0, "data_start_row": 2, "data_end_row": 3, "point_count": 1}
    sources = [{"source_id": "source:0", "sha256": "a" * 64,
                "candidates": [{"candidate_id": "table:0", "blocks": [block, deepcopy(block)]}]}]
    before = deepcopy(sources)
    with pytest.raises(TaskControlError) as rejected:
        select_source_blocks(sources, {"blocks": [reference("block:0")]})
    assert rejected.value.reason_code == "semantic_source_selection_ambiguous"
    assert sources == before


def test_confirmed_table_choice_is_retained_in_summary_and_scientific_provenance(tmp_path):
    from sciplot_core.task_semantic_selection import select_source_blocks, selection_for_choices, selection_summary
    from sciplot_core.task_semantic_creation import build_managed_request

    source = mixed_source(tmp_path)
    plan = prepare_plan([source], intent())
    second = deepcopy(plan["sources"][0]["candidates"][0])
    second["candidate_id"] = "table:1"
    sources = deepcopy(plan["sources"])
    sources[0]["candidates"].append(second)
    plan["sources"], plan["selection"] = select_source_blocks(sources, None)
    choices = {"tables": {"source:0": "table:1"}}
    current = state(source, intent(), plan, tmp_path) | {"semantic_choices": choices}
    report = selection_for_choices(plan["selection"], choices)
    assert len(report["selected"]) == 5 and len(report["excluded"]) == 5
    assert all(block["table_id"] == "table:1" for block in report["selected"])
    assert all(block["reasons"] == ["table_not_selected"] for block in report["excluded"])
    assert selection_summary(plan["selection"], choices)["selected_block_count"] == 5
    wire = build_managed_request(current)
    assert wire["data_binding"]["provenance"]["semantic_task"]["selection"] == report
    assert len(plan["selection"]["selected"]) == 10  # original draft evidence retained
