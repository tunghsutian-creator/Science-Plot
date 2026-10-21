"""Generated source-bound controls for one semantic decision and its continuation."""
from copy import deepcopy
import csv
import hashlib

import pytest

from sciplot_core.task_errors import TaskControlError
from test_frequency_interval_binding import instrument_source


def raw_intent():
    return {"x": {"quantity": "angular_frequency", "unit": "rad/s", "scale": "log", "direction": "ascending"},
            "y": {"quantity": "complex_viscosity", "unit": "Pa s", "scale": "log"},
            "selection": {"test_names": ["Anonymous material"]}}


def state(source, intent, tmp_path):
    from sciplot_core.task_semantic_plan import prepare_plan

    return {"request": {"intent": intent}, "semantic_plan": prepare_plan([source], intent),
            "semantic_choices": {}, "intent_revision": 1, "task_dir": str(tmp_path / "task")}


def resolve_wire(wire):
    from sciplot_core.plot_engine.contracts import validate_create
    from sciplot_core.plot_engine.managed_sources import load_sources
    from sciplot_core.plot_ir import create_managed_document
    from sciplot_core.plot_transforms import resolve_transforms

    request = validate_create(wire)
    document = create_managed_document(request["template_definition"], request["data_binding"], plot_id="generated-resolution")
    resolved = resolve_transforms(document, load_sources(document, request["rule_id"]))
    layers = request["template_definition"]["figure_spec"]["views"][0]["layers"]
    return [resolved["datasets"][layer["dataset_id"]] for layer in layers]


def source_coordinates(source):
    """Independent literal-cell oracle; never infer the reported response."""
    with source.open(encoding="utf-16", newline="") as stream:
        rows = list(csv.reader(stream, delimiter="\t"))
    assert rows[7][3] == "Angular Frequency" and rows[7][11] == "Complex Viscosity"
    assert rows[9][3] == "[rad/s]" and rows[9][11] == "[mPa·s]"
    return ([float(row[3]) for row in rows[10:26]], [float(row[11]) * .001 for row in rows[10:26]])


def bits(values):
    return [float(value).hex() for value in values]


def test_charge_c_identity_preserves_raw_mask_order_and_native_label(tmp_path):
    from sciplot_core.plot_backends.native_primitives import _text
    from sciplot_core.task_semantic_creation import build_managed_request

    source = tmp_path / 'charge.csv'
    source.write_text('position_s,charge_C\n3,-0.0\n1,\n1,2.5\n2,-4\n')
    original = source.read_bytes()
    intent = {'x': {'quantity': 'time', 'header': 'position_s'}, 'y': {'quantity': 'charge', 'header': 'charge_C'}}
    current = state(source, intent, tmp_path)
    coordinate = current['semantic_plan']['resolved_bindings'][0]['coordinates']['y']
    assert coordinate['observed_quantity'] == 'charge' and coordinate['source_unit'] == coordinate['unit'] == 'C'
    assert coordinate['unit_relation']['canonical_from_unit'] == coordinate['unit_relation']['canonical_to_unit'] == 'C'
    wire = build_managed_request(current)
    assert not any(node['kind'] == 'convert_unit' for node in wire['data_binding']['transforms'])
    columns = resolve_wire(wire)[0]['columns']
    assert columns['x']['values'] == [3, 1, 1, 2]
    assert columns['y']['values'][1] is None
    assert bits([value for value in columns['y']['values'] if value is not None]) == bits([-0.0, 2.5, -4])
    axes = wire['template_definition']['figure_spec']['views'][0]['axes']
    assert axes[1]['label'] == 'Charge (C)' and _text(axes[1]['label']) == 'Charge (C)'
    assert all(binding['sha256'] == hashlib.sha256(original).hexdigest() for binding in wire['data_binding']['data_sources'])
    intent['y']['unit'] = 'K'
    with pytest.raises(TaskControlError) as error:
        state(source, intent, tmp_path)
    assert error.value.reason_code == 'transform_unit_incompatible'
    assert source.read_bytes() == original


@pytest.mark.parametrize('target,expected', [('C', [21., None, -5.]), ('°C', [21., None, -5.]),
                                           ('K', [294.15, None, 268.15])])
def test_source_temperature_context_keeps_celsius_and_registered_offset(tmp_path, target, expected):
    from sciplot_core.task_semantic_creation import build_managed_request

    source = tmp_path / 'temperature.csv'
    source.write_text('Time_s,Temperature_C\n3,21\n1,\n2,-5\n')
    original = source.read_bytes()
    current = state(source, {'x': {'quantity': 'time'}, 'y': {'quantity': 'temperature', 'unit': target}}, tmp_path)
    wire = build_managed_request(current)
    columns = resolve_wire(wire)[0]['columns']
    assert columns['y']['unit'] == target and columns['y']['values'] == expected
    assert columns['x']['values'] == [3, 1, 2]
    label = wire['template_definition']['figure_spec']['views'][0]['axes'][1]['label']
    assert label == ('Temperature (K)' if target == 'K' else 'Temperature (°C)')
    assert source.read_bytes() == original


def test_charge_c_and_unique_secondary_temperature_keep_distinct_unit_contexts(tmp_path):
    from sciplot_core.task_semantic_creation import build_managed_request

    source = tmp_path / 'charge-temperature.csv'
    source.write_text('Time_s,Charge_C,Temperature_C\n3,1,21\n1,2,\n2,3,-5\n')
    original = source.read_bytes()
    current = state(source, {'x': {'quantity': 'time'}, 'y': {'quantity': 'charge', 'header': 'Charge_C'},
                            'secondary_y': {'quantity': 'temperature', 'unit': 'K'}}, tmp_path)
    wire = build_managed_request(current)
    columns = resolve_wire(wire)[0]['columns']
    assert columns['y']['unit'] == 'C' and columns['y']['values'] == [1, 2, 3]
    assert columns['temperature']['unit'] == 'K' and columns['temperature']['values'] == [294.15, None, 268.15]
    assert [axis['label'] for axis in wire['template_definition']['figure_spec']['views'][0]['axes']] == [
        'Time (s)', 'Charge (C)', 'Temperature (K)']
    # Missing observations break the temperature line. Its two isolated finite
    # measurements must remain actual marks, rather than an empty native line.
    from sciplot_core.plot_grammar.mark_geometry import layer_geometry
    layer = wire['template_definition']['figure_spec']['views'][0]['layers'][-1]
    geometry = layer_geometry(layer, {layer['dataset_id']: resolve_wire(wire)[-1]})
    assert [item.points for item in geometry] == [((3., 294.15),), ((2., 268.15),)]
    assert source.read_bytes() == original


def test_unexecuted_old_charge_conversion_requires_reconfirmation_without_replanning(tmp_path):
    from sciplot_core.task_semantic_creation import build_managed_request

    source = tmp_path / 'old-charge.csv'
    source.write_text('Time_s,Charge_C\n3,-0.0\n1,\n2,2.5\n')
    original = source.read_bytes()
    current = state(source, {'x': {'quantity': 'time'}, 'y': {'quantity': 'charge', 'header': 'Charge_C'}}, tmp_path)
    coordinate = current['semantic_plan']['resolved_bindings'][0]['coordinates']['y']
    coordinate.pop('unit_context')
    coordinate['unit'] = 'K'
    coordinate['unit_relation'].update(to_unit='K', canonical_to_unit='K', factor=1., offset=273.15, kind='conversion')
    current['request']['intent']['y']['unit'] = 'K'
    current['semantic_plan']['intent']['y']['unit'] = 'K'
    current['semantic_plan']['resolved_axes']['y']['unit'] = 'K'
    before = deepcopy(current)
    with pytest.raises(TaskControlError) as error:
        build_managed_request(current)
    assert error.value.reason_code == 'semantic_unit_context_confirmation_required'
    assert current == before and source.read_bytes() == original


def test_unexecuted_old_unambiguous_unit_plan_remains_compatible(tmp_path):
    from sciplot_core.task_semantic_creation import build_managed_request

    source = instrument_source(tmp_path / 'old-frequency.csv', temperatures=(190,), magnitude=True)
    current = state(source, raw_intent(), tmp_path)
    for binding in current['semantic_plan']['resolved_bindings']:
        for coordinate in binding['coordinates'].values():
            coordinate.pop('unit_context', None)
    columns = resolve_wire(build_managed_request(current))[0]['columns']
    original_x, original_y = source_coordinates(source)
    assert bits(columns['x']['values']) == bits(original_x)
    assert bits(columns['y']['values']) == bits(original_y)


def test_unknown_temperature_header_requires_exact_selected_user_fact(tmp_path):
    from sciplot_core.task_semantic_creation import build_managed_request

    source = tmp_path / 'sensor.csv'
    source.write_text('Time_s,sensor_C\n1,21\n2,-5\n')
    intent = {'x': {'quantity': 'time'}, 'y': {'quantity': 'temperature'}}
    with pytest.raises(TaskControlError) as error:
        state(source, intent, tmp_path)
    assert error.value.reason_code == 'transform_unit_incompatible'
    intent['y'].update(header='sensor_C', unit='K')
    current = state(source, intent, tmp_path)
    assert resolve_wire(build_managed_request(current))[0]['columns']['y']['values'] == [294.15, 268.15]
    coordinate = current['semantic_plan']['resolved_bindings'][0]['coordinates']['y']
    coordinate.pop('unit_context')
    with pytest.raises(TaskControlError) as legacy:
        build_managed_request(current)
    assert legacy.value.reason_code == 'semantic_unit_context_confirmation_required'


def test_frozen_managed_request_replay_does_not_enter_new_draft_admission(tmp_path, monkeypatch):
    from sciplot_core import task_semantic_creation as semantic

    source = tmp_path / 'already-requested.csv'
    source.write_text('Time_s,Charge_C\n1,2\n')
    frozen = {'idempotency_key': 'original-executed-key', 'data_binding': {'historical_request': 'retained'}}
    current = {'request': {'intent': {'x': {'quantity': 'time'}, 'y': {'quantity': 'charge'}}},
               'source_hashes': {str(source): hashlib.sha256(source.read_bytes()).hexdigest()},
               'semantic_plan': {'resolution_version': 1}, 'semantic_plan_confirmed': True,
               'managed_request': deepcopy(frozen)}
    calls = []
    def forbidden(*args, **kwargs):
        raise AssertionError('a frozen creation key must not re-enter unit admission or preparation')
    monkeypatch.setattr(semantic, 'build_managed_request', forbidden)
    monkeypatch.setattr(semantic, 'prepare_plan', forbidden)
    monkeypatch.setattr(semantic, 'save_task', lambda *args: None)
    monkeypatch.setattr(semantic, 'execute_managed', lambda current, wire: calls.append(deepcopy(wire)) or {'status': 'blocked'})
    semantic.run_creation(tmp_path / 'task', current)
    assert calls == [frozen] and current['managed_request'] == frozen


@pytest.mark.parametrize("context", [None, "ordinary_xy"])
@pytest.mark.parametrize("layout", [None, "instrument_intervals", "rheology_frequency_intervals"])
def test_physical_layout_cannot_replace_ordinary_science_or_explicit_axes(tmp_path, monkeypatch, context, layout):
    from sciplot_core.source_inspection import semantic_evidence
    from sciplot_core.task_semantic_creation import build_managed_request

    source = instrument_source(tmp_path / "original.csv", temperatures=(190,), magnitude=True)
    original = source.read_bytes()
    evidence = semantic_evidence.inspect_semantic_tables(source)
    evidence["candidates"][0]["format"] = layout
    monkeypatch.setattr(semantic_evidence, "inspect_semantic_tables", lambda *args, **kwargs: deepcopy(evidence))
    intent = raw_intent()
    if context:
        intent["rule_id"] = context
    current = state(source, intent, tmp_path)
    assert current["semantic_plan"]["decisions"] == []
    wire = build_managed_request(current)
    coordinate = current["semantic_plan"]["resolved_bindings"][0]["coordinates"]["y"]
    assert coordinate["header"] == "Complex Viscosity" and coordinate["column_id"] == "column:11"
    assert coordinate["source_unit"] == "[mPa·s]" and coordinate["unit"] == "Pa s"
    assert coordinate["unit_relation"]["factor"] == .001
    assert wire["rule_id"] == "ordinary_xy"
    assert [scale["transform"] for scale in wire["template_definition"]["figure_spec"]["scales"]] == ["log", "log"]
    assert not any(node["kind"] == "rheology_complex_viscosity" for node in wire["data_binding"]["transforms"])
    datasets = resolve_wire(wire)
    assert len(datasets) == 1
    values = datasets[0]["columns"]
    original_x, original_y = source_coordinates(source)
    assert len(original_x) == len(original_y) == 16
    assert bits(values["x"]["values"]) == bits(original_x)
    assert bits(values["y"]["values"]) == bits(original_y)
    assert datasets[0]["provenance"]["sources"][0]["rows"] == list(range(10, 26))
    assert all(binding["sha256"] == hashlib.sha256(original).hexdigest() for binding in wire["data_binding"]["data_sources"])
    assert source.read_bytes() == original


def test_lowerer_uses_frozen_bindings_without_any_scientific_selector(tmp_path, monkeypatch):
    from sciplot_core import task_semantic_coordinates as coordinates, task_semantic_figure as figure
    from sciplot_core.task_semantic_creation import build_managed_request

    source = instrument_source(tmp_path / "source.csv", temperatures=(190,), magnitude=True)
    current = state(source, raw_intent(), tmp_path)
    def forbidden(*args, **kwargs):
        raise AssertionError("lowering resolved science must not select coordinates or views again")
    monkeypatch.setattr(coordinates, "coordinate_columns", forbidden)
    monkeypatch.setattr(coordinates, "source_unit", forbidden)
    monkeypatch.setattr(figure, "_source_views", forbidden)
    assert len(resolve_wire(build_managed_request(current))[0]["columns"]["x"]["values"]) == 16


@pytest.mark.parametrize("drift", ["column", "region", "relation"])
def test_lowerer_rejects_literal_binding_and_execution_relation_drift(tmp_path, drift):
    from sciplot_core.task_semantic_creation import build_managed_request

    source = instrument_source(tmp_path / "source.csv", temperatures=(190,), magnitude=True)
    current = state(source, raw_intent(), tmp_path)
    plan = current["semantic_plan"]
    block = plan["sources"][0]["candidates"][0]["blocks"][0]
    if drift == "column":
        block["columns"][11]["header"] = "Different original identity"
    elif drift == "region":
        block["table_selection"]["data_end_row"] -= 1
    else:
        plan["resolved_bindings"][0]["coordinates"]["y"]["unit_relation"]["factor"] = 1
    with pytest.raises(TaskControlError) as rejected:
        build_managed_request(current)
    assert rejected.value.reason_code == "semantic_resolved_binding_changed"


def test_explicit_ordinary_context_preserves_time_reversals_without_stage_inference(tmp_path):
    from sciplot_core.task_semantic_creation import build_managed_request

    source = tmp_path / "time.csv"
    source.write_text("Time,Heat Flow\ns,W/g\n4,-2\n1,3\n2,-1\n")
    for context in (None, "ordinary_xy"):
        intent = {"x": {"quantity": "time"}, "y": {"quantity": "heat_flow"}}
        if context:
            intent["rule_id"] = context
        current = state(source, intent, tmp_path)
        assert current["semantic_plan"]["decisions"] == []
        wire = build_managed_request(current)
        dataset = resolve_wire(wire)[0]
        assert dataset["columns"]["x"]["values"] == [4, 1, 2]
        assert dataset["columns"]["y"]["values"] == [-2, 3, -1]
        assert not any(node["kind"] == "concat_time" for node in wire["data_binding"]["transforms"])


def test_same_task_revision_reaches_measured_xy_and_frozen_retry_does_not_resolve(tmp_path, monkeypatch):
    from sciplot_core import task_control, task_semantic_creation, task_semantic_plan

    source = instrument_source(tmp_path / "source.csv", temperatures=(190,), magnitude=True)
    original = source.read_bytes()
    wires = []
    def execution_boundary(current, wire):
        resolve_wire(wire)
        wires.append(deepcopy(wire))
        return {"status": "blocked", "ready_to_use": False,
                "error": {"reason_code": "generated_execution_boundary", "message": "No native body in this contract control."},
                "next_step": {"action": "retry_same_request"}}
    monkeypatch.setattr(task_semantic_creation, "execute_managed", execution_boundary)
    invalid = raw_intent()
    invalid["y"]["header"] = "Storage Modulus"
    task_dir = tmp_path / "same-task"
    first = task_control.start_task({"version": 1, "action": "create", "sources": [str(source)], "intent": invalid}, task_dir=task_dir)
    assert first["blocker"]["reason_code"] == "semantic_coordinate_mapping_required"
    assert first["next_step"]["action"] == "revise_intent" and wires == []
    second = task_control.resume_task(task_dir, {"expected_intent_revision": 1, "revise_intent": raw_intent()})
    assert second["intent_revision"] == 2 and len(wires) == 1
    assert second["blocker"]["reason_code"] == "generated_execution_boundary"
    from sciplot_core.task_storage import load_task, save_task

    frozen = load_task(task_dir)
    frozen["semantic_plan"].pop("resolution_version")
    frozen["semantic_plan"].pop("resolved_bindings")
    save_task(task_dir, frozen)
    def forbidden(*args, **kwargs):
        raise AssertionError("a frozen request retry must not resolve science")
    monkeypatch.setattr(task_semantic_plan, "selected_table_plan", forbidden)
    monkeypatch.setattr(task_semantic_creation, "prepare_plan", forbidden)
    monkeypatch.setattr(task_semantic_creation, "build_managed_request", forbidden)
    task_control.resume_task(task_dir, {"retry": True})
    assert len(wires) == 2 and wires[0] == wires[1]
    assert source.read_bytes() == original


def test_old_uncommitted_draft_observations_are_reprepared_without_reusing_confirmation(tmp_path, monkeypatch):
    from sciplot_core import task_semantic_creation

    source = instrument_source(tmp_path / "source.csv", temperatures=(190,), magnitude=True)
    current = state(source, raw_intent(), tmp_path)
    current["request"].update(action="create", sources=[str(source)])
    current.update(source_hashes={str(source): hashlib.sha256(source.read_bytes()).hexdigest()}, status="blocked", phase="planning",
                   semantic_plan_confirmed=True, semantic_choices={"y_header": "Stale answer"},
                   question={"question_id": "1" * 64}, plan_confirmation={"mode": "historical"})
    current["semantic_plan"].pop("resolution_version")
    old_block = current["semantic_plan"]["sources"][0]["candidates"][0]["blocks"][0]
    old_block["table_selection"]["data_end_row"] -= 1
    def execution_boundary(state, wire):
        assert len(resolve_wire(wire)[0]["columns"]["x"]["values"]) == 16
        return {"status": "blocked", "ready_to_use": False}
    monkeypatch.setattr(task_semantic_creation, "execute_managed", execution_boundary)
    task_semantic_creation.run_creation(tmp_path / "task", current)
    assert current["semantic_plan"]["resolution_version"] == 1
    assert current["semantic_choices"] == {} and "question" not in current
    assert current["plan_confirmation"]["mode"] == "explicit_intent_and_unambiguous_source_evidence"
    assert current["semantic_plan_history"][0]["confirmation"] == {"mode": "historical"}
    assert current["semantic_plan_history"][0]["choices"] == {"y_header": "Stale answer"}


@pytest.mark.parametrize("uncertainty", ["creating", "exporting", "attempt"])
def test_old_unknown_creation_cannot_refresh_its_science(tmp_path, monkeypatch, uncertainty):
    from sciplot_core import task_semantic_creation

    source = instrument_source(tmp_path / "source.csv", temperatures=(190,), magnitude=True)
    current = state(source, raw_intent(), tmp_path)
    current["request"].update(action="create", sources=[str(source)])
    current.update(source_hashes={str(source): hashlib.sha256(source.read_bytes()).hexdigest()}, status="blocked",
                   phase=uncertainty if uncertainty != "attempt" else "planning")
    current["semantic_plan"].pop("resolution_version")
    if uncertainty == "attempt":
        current["creation_attempts"] = [{"intent_revision": 1, "idempotency_key": "historical"}]
    def forbidden(*args, **kwargs):
        raise AssertionError("unknown native outcome cannot resolve a replacement request")
    monkeypatch.setattr(task_semantic_creation, "prepare_plan", forbidden)
    monkeypatch.setattr(task_semantic_creation, "execute_managed", forbidden)
    with pytest.raises(TaskControlError) as rejected:
        task_semantic_creation.run_creation(tmp_path / "task", current)
    assert rejected.value.reason_code == "creation_outcome_uncertain"
    assert "semantic_plan_history" not in current


def test_nonpositive_log_has_reachable_same_draft_correction(tmp_path):
    from sciplot_core.task_control import start_task

    source = tmp_path / "source.csv"
    source.write_text("Time,Heat Flow\ns,W/g\n0,2\n1,3\n")
    result = start_task({"version": 1, "action": "create", "sources": [str(source)],
        "intent": {"x": {"quantity": "time", "scale": "log"}, "y": {"quantity": "heat_flow"}}}, task_dir=tmp_path / "task")
    assert result["blocker"]["reason_code"] == "semantic_log_domain"
    assert result["next_step"]["action"] == "revise_intent"
    assert result["next_step"]["draft_revision_template"]["expected_intent_revision"] == 1


def test_secondary_missing_unit_repair_uses_only_supported_coordinate_fields(tmp_path):
    from sciplot_core.task_control import start_task

    source = tmp_path / "source.csv"
    source.write_text("Time,Mass,Temperature\ns,%,\n0,100,20\n1,99,21\n")
    intent = {"x": {"quantity": "time"}, "y": {"quantity": "mass"},
              "secondary_y": {"quantity": "temperature", "header": "Temperature", "unit": "C"}}
    result = start_task({"version": 1, "action": "create", "sources": [str(source)], "intent": intent}, task_dir=tmp_path / "task")
    assert result["blocker"]["reason_code"] == "semantic_source_unit_required"
    assert result["next_step"]["action"] == "revise_intent"
    assert result["blocker"]["repair"]["supported_selectors"] == ["intent.secondary_y.header", "intent.secondary_y.column_id"]
