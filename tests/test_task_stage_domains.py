"""Original domains survive stage choices; finite display runs never crop science."""
from copy import deepcopy
import csv
import hashlib
import io
import json

import pytest

from sciplot_core.plot_engine.managed_sources import load_sources
from sciplot_core.plot_ir import create_managed_document
from sciplot_core.plot_transforms import resolve_transforms
from sciplot_core.task_errors import TaskControlError
from sciplot_core.task_semantic_creation import build_managed_request
from sciplot_core.task_semantic_plan import prepare_plan


def original(tmp_path, times, *, temperature=None, clock=None):
    source = tmp_path / "original.csv"
    headers = ["Time", "Mass"] + (["Temperature"] if temperature is not None else []) + (["Clock"] if clock is not None else [])
    units = ["s", "%"] + (["C"] if temperature is not None else []) + (["s"] if clock is not None else [])
    responses = [-0.0, 7.125, 6.25, 5.5, 4.25, 3.125][:len(times)]
    rows = [headers, units]
    for index, time in enumerate(times):
        rows.append([time, responses[index]] + ([temperature[index]] if temperature is not None else []) + ([clock[index]] if clock is not None else []))
    source.write_text("\n".join(",".join("" if value is None else str(value) for value in row) for row in rows) + "\n")
    return source, responses


def intent(*, stages=True, order="source_order"):
    value = {"x": {"quantity": "time", "unit": "s"}, "y": {"quantity": "mass", "unit": "%"}}
    if stages:
        value["stages"] = {"mode": "concatenate", "order": order, "boundary": "preserve_endpoint"}
    return value


def state(source, value, tmp_path):
    return {"request": {"intent": value}, "semantic_plan": prepare_plan([source], value),
            "semantic_choices": {}, "intent_revision": 1, "task_dir": str(tmp_path / "task")}


def columns(wire):
    document = create_managed_document(wire["template_definition"], wire["data_binding"], plot_id="complete-stage-domain")
    resolved = resolve_transforms(document, load_sources(document, wire["rule_id"]))
    layer, = wire["template_definition"]["figure_spec"]["views"][0]["layers"]
    return resolved["datasets"][layer["dataset_id"]]


def bits(values):
    return [None if value is None else float(value).hex() for value in values]


@pytest.mark.parametrize("times", [[None, 0, 1], [0, None, 1], [0, 1, None]])
def test_single_complete_stage_preserves_missing_time_and_response_before_and_after_json_reload(tmp_path, times):
    source, y = original(tmp_path, times)
    before = source.read_bytes()
    current = state(source, intent(), tmp_path)
    candidate, = current["semantic_plan"]["sources"][0]["candidates"]
    assert [(stage["data_start_row"], stage["data_end_row"]) for stage in candidate["stages"]] == [(2, 5)]
    first = build_managed_request(current)
    assert not any(node["kind"] == "concat_time" for node in first["data_binding"]["transforms"])
    persisted = tmp_path / "saved-semantic-state.json"
    persisted.write_text(json.dumps(current))
    reloaded = build_managed_request(json.loads(persisted.read_text()))
    assert first == reloaded
    for wire in (first, reloaded):
        data = columns(wire)
        assert bits(data["columns"]["x"]["values"]) == bits(times)
        assert bits(data["columns"]["y"]["values"]) == bits(y)
        assert data["provenance"]["sources"][0]["rows"] == [2, 3, 4]
        assert data["provenance"]["sources"][0]["sha256"] == hashlib.sha256(before).hexdigest()
    assert source.read_bytes() == before


@pytest.mark.parametrize("times", [[None, 0, 1, 0, 1], [0, None, 1, 0, 1],
                                   [0, 1, 0, None, 1], [0, 1, 0, 1, None]])
def test_concat_uses_complete_stages_and_refuses_missing_time_without_dropping_rows(tmp_path, times):
    source, _ = original(tmp_path, times)
    before = source.read_bytes()
    current = state(source, intent(), tmp_path)
    candidate, = current["semantic_plan"]["sources"][0]["candidates"]
    ranges = sorted((stage["data_start_row"], stage["data_end_row"]) for stage in candidate["stages"])
    assert [row for start, end in ranges for row in range(start, end)] == [2, 3, 4, 5, 6]
    assert sum(stage["point_count"] for stage in candidate["stages"]) == 5
    snapshot = json.loads(json.dumps(current))
    for draft in (current, snapshot):
        with pytest.raises(TaskControlError) as rejected:
            build_managed_request(draft)
        assert rejected.value.reason_code == "semantic_stage_time_invalid"
        evidence = rejected.value.issues[0]
        assert evidence["constraint"] == "transform_stage_time_invalid"
        assert sum(stage["point_count"] for stage in evidence["complete_stages"]) == 5
        assert evidence["source_sha256"] == hashlib.sha256(before).hexdigest()
    assert current == snapshot and source.read_bytes() == before


def test_time_decrease_across_missing_time_does_not_invent_an_acquisition_boundary(tmp_path):
    source, _ = original(tmp_path, [0, 2, None, 0, 1])
    before = source.read_bytes()
    with pytest.raises(TaskControlError) as rejected:
        prepare_plan([source], intent())
    assert rejected.value.reason_code == "semantic_stage_boundary_ambiguous"
    evidence = rejected.value.issues[0]
    reset, = evidence["unresolved_resets"]
    assert (reset["previous_time_row"], reset["next_time_row"]) == (3, 5)
    assert reset["source_sha256"] == hashlib.sha256(before).hexdigest()
    stage, = evidence["stages"]
    assert (stage["data_start_row"], stage["data_end_row"], stage["point_count"]) == (2, 7, 5)
    # The exact same original is supported as unshifted XY; its gap is retained.
    raw = columns(build_managed_request(state(source, intent(stages=False), tmp_path)))
    assert bits(raw["columns"]["x"]["values"]) == bits([0, 2, None, 0, 1])
    assert source.read_bytes() == before


def test_stage_reset_observation_uses_the_resolved_x_column_and_keeps_original_row_order(tmp_path):
    source, y = original(tmp_path, [0, 1, 2, 3], clock=[10, 11, 0, 1])
    value = intent()
    value["x"]["header"] = "Clock"
    current = state(source, value, tmp_path)
    stages = current["semantic_plan"]["resolved_views"][0]["stages"]
    assert [(stage["data_start_row"], stage["data_end_row"], stage["time_column_id"]) for stage in stages] == [
        (2, 4, "column:2"), (4, 6, "column:2")]
    data = columns(build_managed_request(current))
    assert data["columns"]["x"]["values"] == [10, 11, 11, 12]
    assert bits(data["columns"]["y"]["values"]) == bits(y)
    assert [origin[0]["row"] for origin in data["provenance"]["transforms"][-1]["details"]["row_origins"]] == [2, 3, 4, 5]
    for stages in (current["semantic_plan"]["sources"][0]["candidates"][0]["stages"],
                   current["semantic_plan"]["resolved_views"][0]["stages"]):
        for stage in stages:
            stage.pop("time_column_id")
    with pytest.raises(TaskControlError) as old:
        build_managed_request(json.loads(json.dumps(current)))
    assert old.value.reason_code == "semantic_stage_domain_confirmation_required"


def test_source_supported_temperature_order_and_serialized_reopen_keep_the_same_stage_science(tmp_path):
    source, y = original(tmp_path, [0, 1, 0, 1], temperature=[20, 30, 10, 20])
    current = state(source, intent(order="temperature_continuity"), tmp_path)
    first = build_managed_request(current)
    saved = tmp_path / "confirmed-plan.json"
    saved.write_text(json.dumps(current))
    second = build_managed_request(json.loads(saved.read_text()))
    assert first == second
    data = columns(second)
    assert bits(data["columns"]["x"]["values"]) == bits([0, 1, 1, 2])
    assert bits(data["columns"]["y"]["values"]) == bits([*y[2:], *y[:2]])
    assert [origin[0]["row"] for origin in data["provenance"]["transforms"][-1]["details"]["row_origins"]] == [4, 5, 2, 3]
    sources = {item["source_id"]: item for item in second["data_binding"]["data_sources"]}
    for stage in second["data_binding"]["provenance"]["semantic_task"]["stages"]["source:0"]:
        assert stage["source_id"] in sources


def test_historical_complete_stage_draft_with_the_same_observed_time_column_remains_supported(tmp_path):
    source, y = original(tmp_path, [0, 1, 0, 1])
    current = state(source, intent(), tmp_path)
    for stages in (current["semantic_plan"]["sources"][0]["candidates"][0]["stages"],
                   current["semantic_plan"]["resolved_views"][0]["stages"]):
        for stage in stages:
            stage.pop("time_column_id")
    data = columns(build_managed_request(json.loads(json.dumps(current))))
    assert bits(data["columns"]["x"]["values"]) == bits([0, 1, 1, 2])
    assert bits(data["columns"]["y"]["values"]) == bits(y)


def test_duplicate_time_in_complete_stages_is_not_deduplicated_to_make_concat_legal(tmp_path):
    source, _ = original(tmp_path, [0, 0, 1, 0, 1])
    current = state(source, intent(), tmp_path)
    with pytest.raises(TaskControlError) as rejected:
        build_managed_request(current)
    assert rejected.value.reason_code == "semantic_stage_time_invalid"
    assert sum(stage["point_count"] for stage in rejected.value.issues[0]["complete_stages"]) == 5


def test_explicit_worksheet_scope_keeps_missing_positions_without_observing_excluded_cells(tmp_path, monkeypatch):
    from openpyxl import Workbook
    from sciplot_core.data_mapping import raw_tables

    generated, y = original(tmp_path, [0, None, 1])
    source = tmp_path / "selected.xlsx"
    book = Workbook()
    book.active.title = "Summary"
    for row in [["Time", "Mass"], ["s", "%"], [0, 9], [], [1, 8]]:
        book.active.append(row)
    sheet = book.create_sheet("Measured")
    for row in csv.reader(generated.read_text().splitlines()):
        sheet.append(row)
    book.save(source)
    before = source.read_bytes()
    loader = raw_tables._read_original_cells
    calls = []
    def selected(reference, path, *, preserve_cells=False):
        assert reference.sheet == "Measured"
        calls.append(reference.sheet)
        return loader(reference, path, preserve_cells=preserve_cells)
    monkeypatch.setattr(raw_tables, "_read_original_cells", selected)
    value = intent()
    value["selection"] = {"blocks": [{"source_id": "source:0", "table_id": "table:1", "block_id": "block:0"}]}
    current = state(source, value, tmp_path)
    data = columns(build_managed_request(current))
    assert current["semantic_plan"]["resolved_views"][0]["table_id"] == "table:1"
    assert bits(data["columns"]["x"]["values"]) == bits([0, None, 1])
    assert bits(data["columns"]["y"]["values"]) == bits(y)
    assert calls and set(calls) == {"Measured"} and source.read_bytes() == before
    # A table-choice draft has no bindings for unselected candidates. Resolving
    # it must narrow the original scope before observing the chosen time role.
    from sciplot_core.task_semantic_plan import selected_table_plan

    monkeypatch.setattr(raw_tables, "_read_original_cells", loader)
    choice_source = tmp_path / "two-valid-candidates.xlsx"
    book["Summary"].delete_rows(4)  # Separate generated control; leave the original workbook intact.
    book.save(choice_source)
    ambiguous = prepare_plan([choice_source], intent())
    assert [decision["field"] for decision in ambiguous["decisions"]] == ["tables"]
    choices = {"tables": {"source:0": "table:1"}}
    chosen = selected_table_plan(ambiguous, intent(), choices)
    assert [candidate["sheet"] for candidate in chosen["sources"][0]["candidates"]] == ["Measured"]
    assert chosen["decisions"] == []
    reloaded = {**current, "request": {"intent": intent()}, "semantic_plan": json.loads(json.dumps(chosen)), "semantic_choices": choices}
    assert bits(columns(build_managed_request(reloaded))["columns"]["x"]["values"]) == bits([0, None, 1])


def test_independent_sample_blocks_never_align_or_crop_their_missing_time_positions(tmp_path):
    source = tmp_path / "independent.csv"
    source.write_text("Time,Mass,Time,Mass\ns,%,s,%\nA,A,B,B\n0,10,0,20\n1,9,,19\n,8,2,18\n")
    before = source.read_bytes()
    wire = build_managed_request(state(source, intent(), tmp_path))
    assert not any(node["kind"] == "concat_time" for node in wire["data_binding"]["transforms"])
    document = create_managed_document(wire["template_definition"], wire["data_binding"], plot_id="independent-originals")
    resolved = resolve_transforms(document, load_sources(document, wire["rule_id"]))
    layers = wire["template_definition"]["figure_spec"]["views"][0]["layers"]
    assert len(layers) == 2
    for layer, x, y in zip(layers, ([0, 1, None], [0, None, 2]), ([10, 9, 8], [20, 19, 18]), strict=True):
        data = resolved["datasets"][layer["dataset_id"]]
        assert bits(data["columns"]["x"]["values"]) == bits(x)
        assert bits(data["columns"]["y"]["values"]) == bits(y)
        assert data["provenance"]["sources"][0]["rows"] == [3, 4, 5]
    assert source.read_bytes() == before


def test_instrument_marker_regions_use_each_original_header_and_temperature_for_stage_order(tmp_path):
    from test_instrument_source_regions import instrument

    source = tmp_path / "instrument.csv"
    rows, facts = instrument(source, (3, 3))
    for index, fact in enumerate(facts):
        rows[fact["test_row"]][1] = "One measured sample"
        for row, temperature in zip(range(fact["data_start_row"], fact["data_end_row"]), ([20, 30, 40], [10, 15, 20])[index], strict=True):
            rows[row][3] = str(temperature)
        if index:
            for row in [fact["header_row"], fact["unit_row"], *range(fact["data_start_row"], fact["data_end_row"])]:
                rows[row][2], rows[row][3] = rows[row][3], rows[row][2]
    stream = io.StringIO()
    csv.writer(stream, delimiter="\t", lineterminator="\n").writerows(rows)
    source.write_text(stream.getvalue(), encoding="utf-16")
    before = source.read_bytes()
    value = intent(order="temperature_continuity")
    value["y"] = {"quantity": "storage_modulus", "unit": "Pa"}
    current = state(source, value, tmp_path)
    wire = build_managed_request(current)
    data = columns(wire)
    assert data["columns"]["x"]["values"] == [0, 2, 4, 4, 6, 8]
    assert data["columns"]["y"]["values"] == [200, 201, 202, 100, 101, 102]
    assert [origin[0]["row"] for origin in data["provenance"]["transforms"][-1]["details"]["row_origins"]] == [
        *range(facts[1]["data_start_row"], facts[1]["data_end_row"]), *range(facts[0]["data_start_row"], facts[0]["data_end_row"])]
    sources = {item["source_id"]: item for item in wire["data_binding"]["data_sources"]}
    for stage in wire["data_binding"]["provenance"]["semantic_task"]["stages"]["source:0"]:
        bound = sources[stage["source_id"]]
        assert [bound["table_selection"][key] for key in ("data_start_row", "data_end_row")] == [stage[key] for key in ("data_start_row", "data_end_row")]
        assert bound["sha256"] == hashlib.sha256(before).hexdigest()
    assert source.read_bytes() == before


def test_unexecuted_old_finite_run_draft_requires_confirmation_without_rebuilding_its_science(tmp_path):
    source, _ = original(tmp_path, [0, 1, None, 0, 1])
    current = state(source, intent(stages=False), tmp_path)
    assert len(columns(build_managed_request(current))["columns"]["x"]["values"]) == 5
    current["request"]["intent"] = intent()
    plan = current["semantic_plan"]
    plan["intent"] = deepcopy(current["request"]["intent"])
    candidate = plan["sources"][0]["candidates"][0]
    old_stages = [{**segment, "stage_id": f"block:0:segment:{index}", "block_id": "block:0", "temperature_endpoints": {}}
                  for index, segment in enumerate(candidate["blocks"][0]["segments"])]
    candidate["stages"] = deepcopy(old_stages)
    plan["resolved_views"][0]["stages"] = deepcopy(old_stages)
    persisted = tmp_path / "old-unexecuted-draft.json"
    persisted.write_text(json.dumps(current))
    reloaded = json.loads(persisted.read_text())
    before = deepcopy(reloaded)
    with pytest.raises(TaskControlError) as rejected:
        build_managed_request(reloaded)
    assert rejected.value.reason_code == "semantic_stage_domain_confirmation_required"
    assert rejected.value.issues[0]["table_selection"]["data_start_row"] == 2
    assert rejected.value.issues[0]["table_selection"]["data_end_row"] == 7
    assert reloaded == before


def test_explicit_instrument_stages_keep_missing_first_and_last_times_in_complete_marker_regions(tmp_path):
    from test_instrument_source_regions import instrument

    source = tmp_path / "marker-gaps.csv"
    rows, facts = instrument(source, (3, 3))
    rows[facts[0]["data_start_row"]][2] = ""
    rows[facts[1]["data_end_row"] - 1][2] = ""
    stream = io.StringIO()
    csv.writer(stream, delimiter="\t", lineterminator="\n").writerows(rows)
    source.write_text(stream.getvalue(), encoding="utf-16")
    before = source.read_bytes()
    value = intent()
    value["y"] = {"quantity": "storage_modulus", "unit": "Pa"}
    current = state(source, value, tmp_path)
    with pytest.raises(TaskControlError) as rejected:
        build_managed_request(current)
    assert rejected.value.reason_code == "semantic_stage_time_invalid"
    stages = rejected.value.issues[0]["complete_stages"]
    assert [(stage["data_start_row"], stage["data_end_row"]) for stage in stages] == [
        (fact["data_start_row"], fact["data_end_row"]) for fact in facts]
    assert stages[0]["time_start"] is None and stages[1]["time_end"] is None
    assert sum(stage["point_count"] for stage in stages) == 6 and source.read_bytes() == before


def test_public_stage_refusal_keeps_complete_draft_and_recovers_only_through_explicit_raw_intent(tmp_path, monkeypatch):
    from sciplot_core import task_control, task_semantic_creation as creation

    source, y = original(tmp_path, [None, 0, 1, 0, 1])
    before = source.read_bytes()
    calls = []
    monkeypatch.setattr(creation, "execute_managed", lambda current, wire: calls.append(deepcopy(wire)) or {"status": "blocked"})
    task = tmp_path / "public-task"
    result = task_control.start_task({"version": 1, "action": "create", "sources": [str(source)], "intent": intent()}, task_dir=task)
    assert result["status"] == "blocked" and result["blocker"]["reason_code"] == "semantic_stage_time_invalid"
    blocked = json.loads((task / "task.json").read_text())
    assert not calls and "managed_request" not in blocked and "creation_attempts" not in blocked
    stages = blocked["semantic_plan"]["resolved_views"][0]["stages"]
    assert sum(stage["point_count"] for stage in stages) == 5
    task_control.resume_task(task, {"expected_intent_revision": 1, "revise_intent": intent(stages=False)})
    wire, = calls
    raw = columns(wire)
    assert bits(raw["columns"]["x"]["values"]) == bits([None, 0, 1, 0, 1])
    assert bits(raw["columns"]["y"]["values"]) == bits(y)
    assert source.read_bytes() == before


def test_saved_creation_request_replay_does_not_enter_new_stage_resolution(tmp_path, monkeypatch):
    from sciplot_core import task_control, task_semantic_creation as creation

    source, _ = original(tmp_path, [0, 1, 0, 1])
    calls = []
    monkeypatch.setattr(creation, "execute_managed", lambda current, wire: calls.append(deepcopy(wire)) or {"status": "blocked"})
    task = tmp_path / "public-task"
    task_control.start_task({"version": 1, "action": "create", "sources": [str(source)], "intent": intent()}, task_dir=task)
    saved = json.loads((task / "task.json").read_text())
    frozen = deepcopy(saved["managed_request"])
    def forbidden(*args, **kwargs):
        raise AssertionError("A saved creation key must not re-enter stage planning or lowering")
    monkeypatch.setattr(creation, "build_managed_request", forbidden)
    monkeypatch.setattr(creation, "prepare_plan", forbidden)
    creation.run_creation(task, saved)
    assert calls == [frozen, frozen]
    assert json.loads((task / "task.json").read_text())["managed_request"] == frozen
