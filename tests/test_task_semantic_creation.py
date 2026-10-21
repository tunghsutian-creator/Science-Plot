"""The ordinary task owns semantic preparation, correction and managed recovery."""
from copy import deepcopy
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator

from sciplot_core.task_contract import TaskControlError, task_request_schema, task_response_schema, validate_task_request


def _resolved_semantic_control(tmp_path, sources, intent):
    from sciplot_core.task_semantic_plan import prepare_plan
    from sciplot_core.task_semantic_creation import build_managed_request
    from sciplot_core.plot_engine.contracts import validate_create
    from sciplot_core.plot_engine.managed_sources import load_sources
    from sciplot_core.plot_ir import create_managed_document
    from sciplot_core.plot_transforms import resolve_transforms

    plan = prepare_plan(sources, intent)
    assert plan['decisions'] == []
    state = {'request': {'intent': intent}, 'semantic_plan': plan, 'semantic_choices': {},
             'intent_revision': 1, 'task_dir': str(tmp_path / 'task')}
    wire = validate_create(build_managed_request(state))
    document = create_managed_document(wire['template_definition'], wire['data_binding'], plot_id='generated-control')
    datasets = resolve_transforms(document, load_sources(document, intent['rule_id']))['datasets']
    layers = wire['template_definition']['figure_spec']['views'][0]['layers']
    return wire, [datasets[layer['dataset_id']] for layer in layers]


def test_sample_columns_are_curves_with_independent_grids_and_registered_conversion(tmp_path):
    source = tmp_path / 'three-row.csv'
    source.write_text('Angular Frequency,Complex Viscosity,Angular Frequency,Complex Viscosity\n'
                      'Resin red,Resin red,Resin blue,Resin blue\nrad/s,mPa s,rad/s,mPa s\n'
                      '7,2100,9,3900\n3,4200,2,8100\n')
    original = source.read_bytes()
    intent = {'x': {'quantity': 'angular_frequency', 'unit': 'rad/s'},
              'y': {'quantity': 'complex_viscosity', 'unit': 'Pa s'}, 'rule_id': 'rheology_frequency_sweep'}
    wire, datasets = _resolved_semantic_control(tmp_path, [source], intent)
    assert [dataset['columns']['x']['values'] for dataset in datasets] == [[7, 3], [9, 2]]
    assert [dataset['columns']['y']['values'] for dataset in datasets] == [[2.1, 4.2], [3.9, 8.1]]
    assert {slot['sample'] for slot in wire['data_binding']['slots'].values()} == {'Resin red', 'Resin blue'}
    assert all(source['table_selection']['sample_row'] == 1 for source in wire['data_binding']['data_sources'])
    assert source.read_bytes() == original

    # Existing block selection excludes a whole sample before binding. The
    # retained block keeps its physical identity and independent original grid.
    intent['selection'] = {'blocks': [{'source_id': 'source:0', 'table_id': 'table:0', 'block_id': 'block:1'}]}
    selected, datasets = _resolved_semantic_control(tmp_path, [source], intent)
    assert len(datasets) == 1 and datasets[0]['columns']['x']['values'] == [9, 2]
    assert {slot['sample'] for slot in selected['data_binding']['slots'].values()} == {'Resin blue'}
    compiled = selected['data_binding']['data_sources'][0]
    origin = datasets[0]['provenance']['sources'][0]
    assert origin['source_id'] == compiled['source_id']
    assert origin['sha256'] == compiled['sha256'] == __import__('hashlib').sha256(original).hexdigest()
    assert origin['rows'] == [3, 4]
    assert compiled['table_selection'] == {'sheet': None, 'header_rows': [0], 'sample_row': 1,
                                           'unit_row': 2, 'data_start_row': 3, 'data_end_row': 5}
    assert selected['data_binding']['provenance']['semantic_task']['selection']['selected'] == [
        {'source_id': 'source:0', 'table_id': 'table:0', 'block_id': 'block:1'}]
    slot = next(iter(selected['data_binding']['slots'].values()))
    assert slot['x']['source_id'] == slot['y']['source_id'] == datasets[0]['id']
    assert any(node['inputs'] == [compiled['source_id']] for node in selected['data_binding']['transforms'])
    assert source.read_bytes() == original


def test_suffix_unit_overlay_preserves_signed_values_and_original_order(tmp_path):
    first, second = tmp_path / 'one.csv', tmp_path / 'two.csv'
    first.write_text('row_index,time_min,temperature_C,heat_flow_W_g\n8,1.5,33,-0.007\n9,1.6,31,0.002\n')
    second.write_text('row_index,time_min,temperature_C,heat_flow_W_g\n20,4,32,0.003\n21,5,30,-0.009\n')
    intent = {'x': {'quantity': 'temperature', 'header': 'temperature_C'},
              'y': {'quantity': 'heat_flow', 'header': 'heat_flow_W_g'}, 'rule_id': 'dsc_curve'}
    wire, datasets = _resolved_semantic_control(tmp_path, [first, second], intent)
    assert [dataset['columns']['x']['values'] for dataset in datasets] == [[33, 31], [32, 30]]
    assert [dataset['columns']['y']['values'] for dataset in datasets] == [[-0.007, 0.002], [0.003, -0.009]]
    assert all(dataset['columns']['y']['unit'] == 'W/g' for dataset in datasets)
    assert not any(node['kind'] == 'rheology_complex_viscosity' for node in wire['data_binding']['transforms'])


def test_unknown_sample_fields_need_exact_binding_and_separate_original_unit(tmp_path):
    from sciplot_core.task_semantic_plan import prepare_plan
    from sciplot_core.data_mapping.curve_support import supports_table_mapping
    from sciplot_core.materials_rules import get_rule

    source = tmp_path / 'unknown-fields.csv'
    source.write_text('speed_red,response_red,speed_blue,response_blue\nrad/s,,rad/s,\n'
                      'Resin red,Resin red,Resin blue,Resin blue\n7,2100,9,3900\n3,4200,2,8100\n')
    original = source.read_bytes()
    intent = {'x': {'quantity': 'angular_frequency', 'unit': 'rad/s'},
              'y': {'quantity': 'viscosity', 'unit': 'Pa s'}, 'rule_id': 'rheology_frequency_sweep'}
    with pytest.raises(TaskControlError) as unbound:
        prepare_plan([source], intent)
    assert unbound.value.reason_code == 'semantic_coordinate_mapping_required'
    assert 'existing_mapping_route' not in unbound.value.repair
    assert unbound.value.repair['draft_correction']['action'] == 'revise_intent'
    assert not supports_table_mapping(get_rule(intent['rule_id']))
    intent['x']['headers'] = ['speed_red', 'speed_blue']
    intent['y']['headers'] = ['response_red', 'response_blue']
    with pytest.raises(TaskControlError) as missing:
        prepare_plan([source], intent)
    assert missing.value.reason_code == 'semantic_source_unit_required'
    intent['y']['source_unit'] = 'mPa s'  # explicit clarified original unit, distinct from display Pa s
    wire, datasets = _resolved_semantic_control(tmp_path, [source], intent)
    assert [dataset['columns']['y']['values'] for dataset in datasets] == [[2.1, 4.2], [3.9, 8.1]]
    confirmations = [item for source in wire['data_binding']['data_sources'] for item in source['metadata_confirmations']]
    assert [(item['column_index'], item['value']) for item in confirmations] == [(1, 'mPa s'), (3, 'mPa s')]
    assert all(item['evidence']['kind'] == 'user_statement' for item in confirmations)
    assert not any(node['kind'] == 'rheology_complex_viscosity' for node in wire['data_binding']['transforms'])
    assert source.read_bytes() == original


def test_plain_headers_allow_explicit_units_but_observed_units_cannot_be_overwritten(tmp_path):
    from sciplot_core.task_semantic_plan import prepare_plan

    source = tmp_path / 'plain.csv'
    source.write_text('sensor_position,response_signal\n33,-0.007\n31,0.002\n')
    intent = {'x': {'quantity': 'temperature', 'header': 'sensor_position', 'source_unit': 'C'},
              'y': {'quantity': 'heat_flow', 'header': 'response_signal', 'source_unit': 'W/g'}, 'rule_id': 'dsc_curve'}
    _wire, datasets = _resolved_semantic_control(tmp_path, [source], intent)
    assert datasets[0]['columns']['y']['values'] == [-0.007, 0.002]
    source.write_text('Temperature (C),Heat Flow (W/g)\n33,-0.007\n31,0.002\n')
    intent['x'].update(header='Temperature (C)', source_unit='K')
    intent['y']['header'] = 'Heat Flow (W/g)'
    with pytest.raises(TaskControlError) as conflict:
        prepare_plan([source], intent)
    assert conflict.value.reason_code == 'semantic_source_unit_conflict'


def _single_table_spectral_control(tmp_path):
    source = tmp_path / 'mixed-order-spectra.csv'
    source.write_text('Wavenumber,Transmittance,Wavenumber,Transmittance,Wavenumber,Transmittance\n'
                      'cm^-1,%,cm^-1,%,cm^-1,%\n'
                      'Resin blue,Resin blue,Resin red,Resin red,Excluded resin,Excluded resin\n'
                      '700,84,650,89,800,51\n2600,62,2500,73,2700,43\n3900,79,3800,91,4000,55\n')
    intent = {'x': {'quantity': 'wavenumber', 'direction': 'descending'},
              'y': {'quantity': 'transmittance'}, 'rule_id': 'ftir_spectrum',
              'labels': ['Blue label', 'Red label'],
              'selection': {'blocks': [{'source_id': 'source:0', 'table_id': 'table:0', 'block_id': f'block:{i}'} for i in (0, 1)]}}
    return source, intent


def test_single_table_sample_blocks_keep_raw_spectra_grids_labels_and_exclusions(tmp_path):
    source, intent = _single_table_spectral_control(tmp_path)
    before = source.read_bytes()
    wire, datasets = _resolved_semantic_control(tmp_path, [source], intent)
    assert [dataset['columns']['x']['values'] for dataset in datasets] == [[700, 2600, 3900], [650, 2500, 3800]]
    assert [dataset['columns']['y']['values'] for dataset in datasets] == [[84, 62, 79], [89, 73, 91]]
    assert {slot['sample'] for slot in wire['data_binding']['slots'].values()} == {'Resin blue', 'Resin red'}
    layers = wire['template_definition']['figure_spec']['views'][0]['layers']
    assert [layer['legend']['label'] for layer in layers] == ['Blue label', 'Red label']
    selection = wire['data_binding']['provenance']['semantic_task']['selection']
    assert len(selection['selected']) == 2 and len(selection['available']) == 3
    assert selection['excluded'][0]['block_id'] == 'block:2'
    assert not any(node['kind'] == 'concat_time' for node in wire['data_binding']['transforms'])
    assert source.read_bytes() == before


def test_non_time_sample_curves_reject_an_explicit_stage_request(tmp_path):
    from sciplot_core.task_semantic_plan import prepare_plan

    source, intent = _single_table_spectral_control(tmp_path)
    intent['stages'] = {'mode': 'concatenate', 'order': 'source_order', 'boundary': 'preserve_endpoint'}
    with pytest.raises(TaskControlError) as unsupported:
        prepare_plan([source], intent)
    assert unsupported.value.reason_code == 'semantic_sample_stage_intent_unsupported'


def test_public_single_csv_task_binds_labels_to_curves_and_revises_count_without_native_work(tmp_path, monkeypatch):
    from sciplot_core import task_control as control, task_semantic_creation as semantic

    source, intent = _single_table_spectral_control(tmp_path)
    original = source.read_bytes()
    calls = []

    def stopped_native(state, wire):
        calls.append(wire)
        return {'status': 'blocked', 'ready_to_use': False,
                'error': {'reason_code': 'generated_native_boundary', 'message': 'Public generated boundary control.'}}

    monkeypatch.setattr(semantic, 'execute_managed', stopped_native)
    value = {'version': 1, 'action': 'create', 'sources': [str(source)], 'intent': intent}
    first = control.start_task(value, task_dir=tmp_path / 'valid-task')
    assert first['blocker']['reason_code'] == 'generated_native_boundary'
    assert len(calls) == 1
    assert {slot['sample'] for slot in calls[0]['data_binding']['slots'].values()} == {'Resin blue', 'Resin red'}
    invalid = deepcopy(value)
    invalid['intent']['labels'] = ['Only one label']
    blocked = control.start_task(invalid, task_dir=tmp_path / 'correctable-task')
    assert blocked['blocker']['reason_code'] == 'semantic_label_count_mismatch'
    assert len(calls) == 1
    corrected = control.resume_task(tmp_path / 'correctable-task', {
        'expected_intent_revision': 1, 'revise_intent': intent})
    assert corrected['blocker']['reason_code'] == 'generated_native_boundary'
    assert len(calls) == 2 and source.read_bytes() == original


@pytest.mark.comprehensive
def test_native_single_table_ftir_raw_overlay_preserves_sample_membership_and_descending_display(tmp_path):
    from sciplot_core.plot_backends.figure_marks import graph_path, scale_name
    from sciplot_core.plot_backends.native_primitives import dataset_name
    from sciplot_core.plot_backends.managed_audit import scientific_audit
    from sciplot_core.plot_engine.service import PlotService
    from sciplot_core.plot_engine.storage import load_head, read
    from sciplot_core.veusz_worker.document_edit import loaded_native_document

    source, intent = _single_table_spectral_control(tmp_path)
    before = source.read_bytes()
    wire, datasets = _resolved_semantic_control(tmp_path, [source], intent)
    service = PlotService()
    try:
        created = service.create(wire)
        assert created['ready_to_use'], created
        head = load_head(Path(created['plot']))
        ir = read(Path(head['binding']['ir_path']))
        with loaded_native_document(Path(service.describe(Path(created['plot']))['artifact'])) as loaded:
            assert scientific_audit(ir, loaded)['status'] == 'passed'
            axis = loaded.resolveWidgetPath(None, graph_path('view:main')).getChild(scale_name('scale:x'))
            assert axis.settings.get('min').get() > axis.settings.get('max').get()
            for layer, dataset in zip(ir['views'][0]['layers'], datasets, strict=True):
                for role in ('x', 'y'):
                    assert loaded.data[dataset_name(layer['dataset_id'], role)].data.tolist() == dataset['columns'][role]['values']
        assert source.read_bytes() == before
    finally:
        service.close()


@pytest.mark.comprehensive
def test_native_ftir_raw_overlay_descending_scale_preserves_each_unshifted_array(tmp_path):
    from sciplot_core.plot_backends.figure_marks import graph_path, scale_name
    from sciplot_core.plot_backends.native_primitives import dataset_name
    from sciplot_core.plot_backends.managed_audit import scientific_audit
    from sciplot_core.plot_engine.service import PlotService
    from sciplot_core.plot_engine.storage import load_head, read
    from sciplot_core.veusz_worker.document_edit import loaded_native_document

    sources = [tmp_path / 'spectrum_red.csv', tmp_path / 'spectrum_blue.csv']
    sources[0].write_text('Wavenumber (cm⁻¹),Transmittance (%)\n3900,79\n2600,62\n700,84\n')
    sources[1].write_text('Wavenumber (cm⁻¹),Transmittance (%)\n3800,91\n2500,73\n650,89\n')
    before = [path.read_bytes() for path in sources]
    intent = {'x': {'quantity': 'wavenumber', 'header': 'Wavenumber (cm⁻¹)', 'direction': 'descending'},
              'y': {'quantity': 'transmittance'}, 'rule_id': 'ftir_spectrum'}
    wire, datasets = _resolved_semantic_control(tmp_path, sources, intent)
    spec = wire['template_definition']['figure_spec']
    assert spec['scales'][0]['direction'] == 'descending'
    assert spec['scales'][0]['domain'][0] < spec['scales'][0]['domain'][1]
    expected = [([3900, 2600, 700], [79, 62, 84]), ([3800, 2500, 650], [91, 73, 89])]
    service = PlotService()
    try:
        created = service.create(wire)
        assert created['ready_to_use'], created
        head = load_head(Path(created['plot']))
        ir = read(Path(head['binding']['ir_path']))
        description = service.describe(Path(created['plot']))
        with loaded_native_document(Path(description['artifact'])) as loaded:
            assert scientific_audit(ir, loaded)['status'] == 'passed'
            graph = loaded.resolveWidgetPath(None, graph_path('view:main'))
            axis = graph.getChild(scale_name('scale:x'))
            assert axis.settings.get('min').get() > axis.settings.get('max').get()
            for layer, dataset, (x, y) in zip(ir['views'][0]['layers'], datasets, expected, strict=True):
                assert dataset['columns']['x']['values'] == x
                assert dataset['columns']['y']['values'] == y
                assert loaded.data[dataset_name(layer['dataset_id'], 'x')].data.tolist() == x
                assert loaded.data[dataset_name(layer['dataset_id'], 'y')].data.tolist() == y
        assert [path.read_bytes() for path in sources] == before
    finally:
        service.close()


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
    from sciplot_core import task_semantic_delivery
    monkeypatch.setattr(task_semantic_delivery, "execute_delivery", lambda wire: {"status": "complete", "ready_to_use": True, "delivery": {"native_launcher": "/mock/launcher"}})
    from sciplot_core import task_control as control, task_semantic_creation as semantic
    source = tmp_path / "source.csv"
    source.write_text("t,Mass\ns,%\n0,100\n1,99\n")
    monkeypatch.setattr(semantic, "prepare_plan", lambda paths, intent: {"resolution_version": 1, "sources": [], "decisions": [{"field": "time_boundary", "options": ["preserve_endpoint", "next_sample"]}]})
    from sciplot_core import task_semantic_plan
    monkeypatch.setattr(task_semantic_plan, "selected_table_plan", lambda plan, intent, choices: {**plan, "decisions": []})
    def build(state):
        return {"idempotency_key": "task-attempt-" + str(state["intent_revision"]),
                "data_binding": {"data_sources": [{"path": str(source)}]}}
    monkeypatch.setattr(semantic, "build_managed_request", build)
    keys = []
    def execute(state, wire):
        keys.append(wire["idempotency_key"])
        if len(keys) == 1:
            raise ValueError("scientific refusal before commit")
        return {"status": "complete", "ready_to_use": True, "plot": str(tmp_path / "managed"), "plot_id": "plot:test", "revision": 0, "exports": [{"path": "/mock/export.pdf"}]}
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
    from sciplot_core.plot_engine.managed_sources import load_sources
    from sciplot_core.plot_ir import create_managed_document
    from sciplot_core.plot_transforms import resolve_transforms
    source = tmp_path / "unknown-instrument.csv"
    source.write_text("t,Mass,Ts,,t,Mass,Ts\ns,%,°C,,s,%,°C\n"
                      "0,100,10,,0,99.7,25\n2,99.9,15,,2,99.6,25\n4,99.8,20,,4,99.5,25\n"
                      "6,99.7,25,,6,99.4,25\n0,99.3,25,,8,99.3,25\n2,99.2,30,,,,\n4,99.1,35,,,,\n")
    value = request(source)
    value["intent"]["stages"].update(order="temperature_continuity", boundary="preserve_endpoint")
    original = source.read_bytes()
    # The confirmed second block has seven physical positions, not just its
    # first five finite times. Its missing temperature endpoint cannot prove
    # continuity, and dropping those rows cannot authorize concatenation.
    with pytest.raises(TaskControlError) as continuity:
        prepare_plan([source], value["intent"])
    assert continuity.value.reason_code == "semantic_stage_order_ambiguous"
    value["intent"]["stages"]["order"] = "source_order"
    plan = prepare_plan([source], value["intent"])
    candidate = plan["sources"][0]["candidates"][0]
    assert candidate["blocks"][1]["segments"][0]["point_count"] == 5
    assert [stage["point_count"] for stage in candidate["stages"]] == [4, 3, 7]
    with pytest.raises(TaskControlError) as time:
        build_request({"task_dir": str(tmp_path / "task"), "request": value, "intent_revision": 1,
                       "semantic_plan": plan, "semantic_choices": {}})
    assert time.value.reason_code == "semantic_stage_time_invalid"
    assert sum(stage["point_count"] for stage in time.value.issues[0]["complete_stages"]) == 14
    # An explicitly selected raw block remains supported, including its time
    # reversals. This does not claim the original cumulative goal passed.
    raw = {key: item for key, item in value["intent"].items() if key not in {"stages", "secondary_y"}}
    raw["selection"] = {"blocks": [{"source_id": "source:0", "table_id": "table:0", "block_id": "block:0"}]}
    wire = build_request({"task_dir": str(tmp_path / "raw-task"), "request": {"intent": raw}, "intent_revision": 1,
                          "semantic_plan": prepare_plan([source], raw), "semantic_choices": {}})
    document = create_managed_document(wire["template_definition"], wire["data_binding"], plot_id="test")
    resolved = resolve_transforms(document, load_sources(document, wire["rule_id"]))
    dataset_id = wire["data_binding"]["slots"]["layer:response:0"]["x"]["source_id"]
    dataset = resolved["datasets"][dataset_id]
    assert dataset["columns"]["x"]["values"] == [value / 60 for value in [0, 2, 4, 6, 0, 2, 4]]
    assert dataset["columns"]["y"]["values"] == [100, 99.9, 99.8, 99.7, 99.3, 99.2, 99.1]
    assert dataset["provenance"]["sources"][0]["rows"] == list(range(2, 9))
    assert not any(node["kind"] == "concat_time" for node in wire["data_binding"]["transforms"])
    assert source.read_bytes() == original


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
    from sciplot_core import task_semantic_delivery
    monkeypatch.setattr(task_semantic_delivery, "execute_delivery", lambda wire: {"status": "complete", "ready_to_use": True, "delivery": {"native_launcher": "/mock/launcher"}})
    from sciplot_core import task_control as control, task_semantic_creation as semantic
    source = tmp_path / "data.csv"
    source.write_text("Time,Mass\ns,%\n0,100\n1,99\n")
    monkeypatch.setattr(semantic, "prepare_plan", lambda paths, intent: {"sources": [], "decisions": []})
    monkeypatch.setattr(semantic, "build_managed_request", lambda state: {"idempotency_key": "locally-owned"})
    calls = []
    monkeypatch.setattr(semantic, "execute_managed", lambda state, wire: calls.append(wire) or {"status": "complete", "ready_to_use": True, "plot": "/mock/managed", "plot_id": "plot:test", "revision": 0, "exports": [{"path": "/mock/export.pdf"}]})
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
    from sciplot_core.task_semantic_creation import build_managed_request as build_request
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
    assert rejected.value.repair["draft_correction"]["action"] == "revise_intent"


def test_secondary_quantity_is_closed_to_implemented_temperature(tmp_path):
    value = request(tmp_path / "data.csv")
    value["intent"]["secondary_y"]["quantity"] = "pressure"
    assert not Draft202012Validator(task_request_schema()).is_valid(value)
    with pytest.raises(TaskControlError):
        validate_task_request(value)
    for field, declaration in (("headers", ["Ts"]), ("source_unit", "C")):
        unsupported = request(tmp_path / "data.csv")
        unsupported["intent"]["secondary_y"][field] = declaration
        assert not Draft202012Validator(task_request_schema()).is_valid(unsupported)


@pytest.mark.parametrize("action", ["inspect_diagnostic", "correct_layout", "refresh_scientific_binding"])
def test_managed_failure_owner_action_is_not_converted_to_blind_retry(action):
    from sciplot_core.task_semantic_next_step import blocked_next_step
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
