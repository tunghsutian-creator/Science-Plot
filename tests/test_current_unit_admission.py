"""Generated source controls for current expert admission, independent of native QA."""

from copy import deepcopy
import json

import pytest
from test_figure_document import request_for_figure

from sciplot_core.foundation.file_hashing import file_sha256
from sciplot_core.plot_document import seal_document
from sciplot_core.plot_engine.content_store import intern_document, resolve_document_content
from sciplot_core.plot_engine.contracts import validate_create
from sciplot_core.plot_engine.current_unit_admission import admit_current_units
from sciplot_core.plot_engine.managed_resolution import resolved_metadata
from sciplot_core.plot_engine.managed_source_append import append_targets
from sciplot_core.plot_engine.managed_sources import load_sources
from sciplot_core.plot_ir import create_managed_document
from sciplot_core.plot_transforms import builtin_executor, resolve_transforms


def expert_wire(tmp_path, *, header="Temperature", quantity="temperature", unit="C", target="K", rename=False):
    wire = request_for_figure(tmp_path)
    source = wire["data_binding"]["data_sources"][0]
    path = tmp_path / "figure.csv"
    path.write_text(f"Time,{header}\ns,{unit}\n1,21\n2,\n3,-5\n")
    source["sha256"] = file_sha256(path)
    spec = wire["template_definition"]["figure_spec"]
    spec["scales"][0].update(quantity="time", unit="s")
    spec["scales"][1].update(quantity=quantity, unit=target)
    layer = spec["views"][0]["layers"][0]
    layer["mapping_semantics"].update(x="time", y=quantity)
    layer["dataset_id"] = "projected"
    layer["mappings"] = {"x": "column:0", "y": "response" if rename else "column:1"}
    slot = wire["data_binding"]["slots"]["modulus"]
    slot.update(x={"source_id": "projected", "column": "column:0"},
                y={"source_id": "projected", "column": layer["mappings"]["y"]}, x_unit="s", y_unit=target)
    common = {"executor": builtin_executor(), "determinism": "deterministic"}
    nodes = [dict(common, id="select", kind="select", inputs=["raw:A"], output="selected",
                  parameters={"columns": ["column:0", "column:1"]})]
    if rename:
        nodes.append(dict(common, id="rename", kind="rename", inputs=["selected"], output="renamed",
                          parameters={"columns": {"column:1": {"id": "response", "label": "Temperature"}}}))
    nodes.append(dict(common, id="unit", kind="convert_unit", inputs=["renamed" if rename else "selected"], output="projected",
                      parameters={"columns": [layer["mappings"]["y"]], "from_unit": unit, "to_unit": target}))
    wire["data_binding"]["transforms"] = nodes
    return validate_create(wire)


def managed(wire):
    document = create_managed_document(wire["template_definition"], wire["data_binding"], plot_id="test")
    return resolved_metadata(document, rule_id=wire["rule_id"], executors=wire.get("scientific_executors", {}))


@pytest.mark.parametrize("header", ["Temperature", "sensor_C"])
def test_real_expert_binding_projects_temperature_and_preserves_original_bytes_and_mask(tmp_path, header):
    wire = expert_wire(tmp_path, header=header, rename=True)
    document = managed(wire)
    original = deepcopy(document)
    path = tmp_path / "figure.csv"
    before = path.read_bytes()
    admit_current_units(tmp_path / "store", document)
    raw = load_sources(document, wire["rule_id"])
    result = resolve_transforms(document, raw)
    assert raw["raw:A"]["columns"]["column:1"]["values"] == [21.0, None, -5.0]
    assert result["datasets"]["projected"]["columns"]["response"]["values"] == [294.15, None, 268.15]
    assert result["datasets"]["projected"]["provenance"]["sources"][0]["rows"] == [2, 3, 4]
    assert document == original and path.read_bytes() == before


@pytest.mark.parametrize("rename", [False, True])
@pytest.mark.parametrize("header", ["Charge", "Charge_C"])
def test_charge_cannot_become_temperature_by_rename_or_scientific_scale(tmp_path, header, rename):
    document = managed(expert_wire(tmp_path, header=header, rename=rename))
    with pytest.raises(ValueError) as error:
        admit_current_units(tmp_path / "store", document)
    assert error.value.reason_code == "transform_unit_incompatible"
    assert not (tmp_path / "store").exists()


def test_scale_quantity_alone_is_not_a_bound_temperature_fact(tmp_path):
    document = managed(expert_wire(tmp_path, header="sensor_C", quantity="charge"))
    document["scientific"]["provenance"].pop("figure_spec")
    with pytest.raises(ValueError):
        # Use the original-column owner directly for the legacy template case:
        # a scale quantity string alone never asserts an exact selected fact.
        from sciplot_core.plot_engine.original_coordinate import coordinate_origins
        coordinate_origins(document, "projected", "column:1", "K", quantity="temperature",
                           datasets=load_sources(document, "uvvis_spectrum"))


def test_charge_identity_and_non_temperature_compound_support_are_honest(tmp_path):
    document = managed(expert_wire(tmp_path, header="Charge", quantity="charge", target="C"))
    admit_current_units(tmp_path, document)
    assert load_sources(document, "uvvis_spectrum")["raw:A"]["columns"]["column:1"]["unit"] == "C"
    document = managed(expert_wire(tmp_path, header="Charge", quantity="charge", unit="C/s", target="C/s"))
    with pytest.raises(ValueError) as error:
        admit_current_units(tmp_path, document)
    assert error.value.reason_code == "transform_unit_context_unsupported"


def test_source_sha_refresh_does_not_repin_old_expert_unknown_quantity(tmp_path):
    document = managed(expert_wire(tmp_path, header="sensor_C"))
    old = deepcopy(document)
    source = document["scientific"]["data_sources"][0]
    path = tmp_path / "figure.csv"
    path.write_text(path.read_text().replace("1,21", "1,22"))
    source["sha256"] = file_sha256(path)
    document = seal_document(document)
    with pytest.raises(ValueError) as error:
        admit_current_units(tmp_path, document, previous=old)
    assert error.value.reason_code == "transform_unit_incompatible"
    document = managed(expert_wire(tmp_path, header="Temperature"))
    previous = deepcopy(document)
    path.write_text(path.read_text().replace("1,21", "1,22"))
    document["scientific"]["data_sources"][0]["sha256"] = file_sha256(path)
    admit_current_units(tmp_path, seal_document(document), previous=previous)


@pytest.mark.parametrize("direct", [False, True])
@pytest.mark.parametrize("header,allowed", [("Charge_C", False), ("Temperature_C", True), ("sensor_C", True)])
def test_metadata_unit_confirmation_cannot_hide_the_original_c_cell(tmp_path, header, allowed, direct):
    wire = expert_wire(tmp_path, header=header, unit="C", target="°C")
    source = wire["data_binding"]["data_sources"][0]
    source["metadata_confirmations"] = [{"source_sha256": source["sha256"], "sheet": None,
        "column_index": 1, "field": "unit", "value": "°C",
        "evidence": {"kind": "user_statement", "asserted_by": "control", "statement": "Spell the observed unit as °C"}}]
    wire["data_binding"]["transforms"][-1]["parameters"]["from_unit"] = "°C"
    if direct:
        wire["data_binding"]["transforms"] = []
        wire["template_definition"]["figure_spec"]["views"][0]["layers"][0]["dataset_id"] = "raw:A"
        slot = wire["data_binding"]["slots"]["modulus"]
        slot.update(x={"source_id": "raw:A", "column": "Time", "column_index": 0},
                    y={"source_id": "raw:A", "column": header, "column_index": 1})
    document = managed(validate_create(wire))
    facts = {}
    raw = load_sources(document, wire["rule_id"], column_facts=facts)
    assert raw["raw:A"]["columns"]["column:1"]["unit"] == "°C"
    assert facts["raw:A"]["column:1"]["raw_metadata"]["unit"] == "C"
    if allowed:
        admit_current_units(tmp_path, document)
    else:
        with pytest.raises(ValueError) as error:
            admit_current_units(tmp_path, document)
        assert error.value.reason_code == "transform_unit_incompatible"


def test_unmapped_but_executed_charge_column_is_admitted_too(tmp_path):
    wire = expert_wire(tmp_path, header="Temperature")
    path = tmp_path / "figure.csv"
    path.write_text("Time,Temperature,Charge_C\ns,C,C\n1,21,2\n2,,3\n3,-5,4\n")
    wire["data_binding"]["data_sources"][0]["sha256"] = file_sha256(path)
    wire["data_binding"]["transforms"][0]["parameters"]["columns"].append("column:2")
    wire["data_binding"]["transforms"][-1]["parameters"]["columns"].append("column:2")
    with pytest.raises(ValueError) as error:
        admit_current_units(tmp_path, managed(validate_create(wire)))
    assert error.value.reason_code == "transform_unit_incompatible"


@pytest.mark.parametrize("relabel", [False, True])
def test_charge_normalization_is_allowed_but_celsius_metadata_cannot_hide_behind_it(tmp_path, relabel):
    wire = expert_wire(tmp_path, header="Charge_C", quantity="charge", target="1")
    node = wire["data_binding"]["transforms"][-1]
    node.update(kind="normalize", parameters={"columns": ["column:1"], "method": "max_abs", "output_unit": "1"})
    if relabel:
        source = wire["data_binding"]["data_sources"][0]
        source["metadata_confirmations"] = [{"source_sha256": source["sha256"], "sheet": None,
            "column_index": 1, "field": "unit", "value": "°C",
            "evidence": {"kind": "user_statement", "asserted_by": "control", "statement": "Rename the unit cell"}}]
    document = managed(validate_create(wire))
    if relabel:
        with pytest.raises(ValueError) as error:
            admit_current_units(tmp_path, document)
        assert error.value.reason_code == "transform_unit_incompatible"
    else:
        admit_current_units(tmp_path, document)
        result = resolve_transforms(document, load_sources(document, wire["rule_id"]))
        assert result["datasets"]["projected"]["columns"]["column:1"]["values"] == [1.0, None, -5 / 21]


def test_external_c_output_has_no_implicit_column_evidence(tmp_path):
    from test_plot_transforms import _external
    executor, node = _external(tmp_path)
    wire = expert_wire(tmp_path, header="Temperature", target="C")
    node.update(inputs=["raw:A"], output="projected")
    wire["data_binding"]["transforms"] = [node]
    wire["scientific_executors"] = {"fixed": executor.to_dict("fixed")}
    document = managed(validate_create(wire))
    with pytest.raises(ValueError) as error:
        admit_current_units(tmp_path, document)
    assert error.value.reason_code == "managed_unit_lineage_unsupported"
    assert not list(tmp_path.rglob("*.started.json"))


def test_real_builder_creation_round_trip_retains_exact_selected_context_for_append(tmp_path):
    from test_task_semantic_resolution import state
    from sciplot_core.task_semantic_creation import build_managed_request

    path = tmp_path / "sensor.csv"
    path.write_text("Time_s,sensor_C\n1,21\n2,-5\n")
    task = state(path, {"x": {"quantity": "time"}, "y": {"quantity": "temperature", "header": "sensor_C", "unit": "K"}}, tmp_path)
    document = managed(validate_create(build_managed_request(task)))
    assert "unit_context" in document["scientific"]["provenance"]["binding"]["semantic_task"]["resolution"]["bindings"][0]["coordinates"]["y"]
    admit_current_units(tmp_path, document)
    result = resolve_transforms(document, load_sources(document, "ordinary_xy"))["document"]
    compact = intern_document(tmp_path / "store", result, minimum_bytes=2)
    saved = tmp_path / "saved.json"
    saved.write_text(json.dumps(compact))
    reopened = json.loads(saved.read_text())
    appended_source = tmp_path / "additional-temperature.csv"
    appended_source.write_text("Time_s,Temperature_C\n1,5\n2,\n3,-2\n")
    additional_bytes = appended_source.read_bytes()
    original_view = build_managed_request(task)["template_definition"]["figure_spec"]["views"][0]
    append_request = {"plot_id": reopened["plot_id"], "base_revision": reopened["revision"],
        "idempotency_key": "append-temperature", "intent_class": "scientific", "changes": [{"op": "set",
        "target": [original_view["id"]], "property": "source.append", "value": {
            "source": {"source_id": "raw:additional", "path": str(appended_source), "sha256": file_sha256(appended_source),
                       "table_selection": {"sheet": None, "header_rows": [0], "data_start_row": 1, "data_end_row": 4}},
            "curves": [{"sample": "additional", "x_column_index": 0, "y_column_index": 1, "y_unit": "K"}]}}]}
    from sciplot_core.plot_engine.current_unit_admission import prepare_current_update
    candidate, diff, _risk, scientific = prepare_current_update(tmp_path / "store", reopened, append_request)
    assert diff and scientific and reopened == compact
    after = resolve_transforms(candidate, load_sources(candidate, "ordinary_xy"))
    appended_layer = next(layer for view in candidate["scientific"]["provenance"]["figure_spec"]["views"]
                          for layer in view["layers"] if layer["id"] != original_view["layers"][0]["id"])
    assert after["datasets"][appended_layer["dataset_id"]]["columns"][appended_layer["mappings"]["y"]]["values"] == [278.15, None, 271.15]
    assert appended_source.read_bytes() == additional_bytes
    datasets_ref = reopened["scientific"]["provenance"]["datasets"]
    # Prove compact description never opens the unrelated array blob.
    (tmp_path / "store" / "content" / (datasets_ref["sha256"] + ".json")).unlink()
    assert append_targets(reopened, root=tmp_path / "store")
    assert reopened == compact
    with pytest.raises(ValueError) as missing:
        resolve_document_content(tmp_path / "store", reopened)
    assert missing.value.reason_code == "document_content_unavailable"
