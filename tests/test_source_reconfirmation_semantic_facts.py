"""Independent original condition and derived-input counterfactual controls."""

from copy import deepcopy

import pytest
from test_frequency_interval_binding import instrument_source, intent
from test_managed_source_reconfirmation import fresh_value, patch

from sciplot_core.plot_engine.current_unit_admission import prepare_current_update
from sciplot_core.plot_engine.managed_resolution import resolved_metadata
from sciplot_core.plot_engine.managed_source_revision import validate_reconfirmed_contexts
from sciplot_core.plot_engine.managed_sources import load_sources
from sciplot_core.plot_engine.managed_updates import prepare_update
from sciplot_core.plot_ir import create_managed_document
from sciplot_core.plot_transforms import resolve_transforms
from sciplot_core.task_semantic_creation import build_managed_request
from sciplot_core.task_semantic_plan import prepare_plan
from sciplot_core.task_semantic_plan import _coordinate_binding


def semantic_document(path, value, tmp_path):
    plan = prepare_plan([path], value)
    assert plan["decisions"] == []
    wire = build_managed_request({"request": {"intent": value}, "semantic_plan": plan, "semantic_choices": {},
        "intent_revision": 1, "task_dir": str(tmp_path / "task")})
    document = create_managed_document(wire["template_definition"], wire["data_binding"], plot_id="facts")
    return resolved_metadata(document, rule_id=wire["rule_id"], executors={})


def prepare_and_check(document, path, tmp_path):
    target = "source:" + document["scientific"]["data_sources"][0]["source_id"]
    updated = prepare_current_update(tmp_path, document, patch(document, fresh_value(document, path), target=target))[0]
    facts, frames = {}, {}
    datasets = load_sources(updated, updated["scientific"]["provenance"]["managed"]["rule_id"],
                            column_facts=facts, source_frames=frames)
    validate_reconfirmed_contexts(updated, document, datasets=datasets, column_facts=facts, source_frames=frames)
    return updated, datasets


@pytest.mark.parametrize("magnitude", [False, True])
def test_numeric_only_refresh_revalidates_original_condition_and_all_derived_inputs(tmp_path, magnitude):
    path = instrument_source(tmp_path / "source.csv", temperatures=(190,), magnitude=magnitude)
    document = semantic_document(path, intent(), tmp_path)
    old = deepcopy(document)
    rows = path.read_text(encoding="utf-16").splitlines()
    fields = rows[10].split("\t")
    assert fields[3:6] == ["100.0", "500", "30"]
    fields[4:6] = ["300", "400"]
    if magnitude:
        fields[11] = "5000"  # Explicit observed 5000 mPa·s = 5 Pa s.
    rows[10] = "\t".join(fields)
    path.write_text("\n".join(rows), encoding="utf-16")
    updated, datasets = prepare_and_check(document, path, tmp_path)
    projected = resolve_transforms(updated, datasets)["datasets"]
    layer = updated["scientific"]["provenance"]["figure_spec"]["views"][0]["layers"][0]
    assert projected[layer["dataset_id"]]["columns"]["y"]["values"][0] == 5.0
    context = updated["scientific"]["provenance"]["binding"]["semantic_task"]["resolution"]["bindings"][0]
    assert context["condition"]["source_interval"]["nominal_temperature"] == 190.0
    assert context["condition"]["source_interval"]["point_count"] == 16
    assert document == old


@pytest.mark.parametrize("magnitude,fault", [(magnitude, fault) for magnitude in (False, True)
    for fault in ("result", "test", "frequency-quantity")] + [(False, "storage-quantity")])
def test_changed_literal_condition_or_quantity_cannot_reuse_old_source_fact(tmp_path, fault, magnitude):
    path = instrument_source(tmp_path / "source.csv", temperatures=(190,), magnitude=magnitude)
    document = semantic_document(path, intent(), tmp_path)
    text = path.read_text(encoding="utf-16")
    if fault == "result":
        text = text.replace("FS 190 °C", "FS 150 °C")
    elif fault == "test":
        text = text.replace("Anonymous material", "Different material")
    elif fault == "storage-quantity":
        text = text.replace("Storage Modulus", "Shear Stress")
    else:
        text = text.replace("Angular Frequency", "Measured Voltage")
    path.write_text(text, encoding="utf-16")
    with pytest.raises(ValueError):
        prepare_and_check(document, path, tmp_path)


def test_auxiliary_temperature_sorting_fact_is_valid_without_a_visible_temperature_axis(tmp_path):
    path = tmp_path / "continuity.csv"
    path.write_text("Time,Mass,Temperature\ns,%,C\n0,10,20\n1,9,30\n0,8,10\n1,7,20\n")
    value = {"x": {"quantity": "time", "header": "Time", "unit": "s"},
             "y": {"quantity": "mass", "header": "Mass", "unit": "%"},
             "stages": {"mode": "concatenate", "order": "temperature_continuity", "boundary": "preserve_endpoint"}}
    document = semantic_document(path, value, tmp_path)
    path.write_text(path.read_text().replace("0,10,20", "0,11,20"))
    updated, datasets = prepare_and_check(document, path, tmp_path)
    resolved = resolve_transforms(updated, datasets)["datasets"]
    layer = updated["scientific"]["provenance"]["figure_spec"]["views"][0]["layers"][0]
    assert resolved[layer["dataset_id"]]["columns"]["y"]["values"] == [8, 7, 11, 9]


def test_unselected_storage_header_does_not_replace_observed_magnitude_binding(tmp_path):
    path = instrument_source(tmp_path / "source.csv", temperatures=(190,), magnitude=True)
    rows = path.read_text(encoding="utf-16").splitlines()
    fields = rows[10].split("\t")
    fields[11] = "5000"
    rows[10] = "\t".join(fields)
    path.write_text("\n".join(rows), encoding="utf-16")
    document = semantic_document(path, intent(), tmp_path)
    path.write_text(path.read_text(encoding="utf-16").replace("Storage Modulus", "Shear Stress"), encoding="utf-16")
    updated, datasets = prepare_and_check(document, path, tmp_path)
    resolved = resolve_transforms(updated, datasets)["datasets"]
    layer = updated["scientific"]["provenance"]["figure_spec"]["views"][0]["layers"][0]
    assert resolved[layer["dataset_id"]]["columns"]["y"]["values"][0] == 5.0
    assert all("column:4" not in dataset["columns"] for dataset in datasets.values())


@pytest.mark.parametrize("removal", ["all-contexts", "coordinate", "derived-input"])
def test_complete_source_semantic_facts_cannot_be_deleted_to_bypass_fresh_observation(tmp_path, removal):
    path = instrument_source(tmp_path / "source.csv", temperatures=(190,), magnitude=False)
    document = semantic_document(path, intent(), tmp_path)
    path.write_text(path.read_text(encoding="utf-16").replace("FS 190 °C", "FS 150 °C"), encoding="utf-16")
    value = fresh_value(document, path)
    if removal == "all-contexts":
        value["unit_context_bindings"] = []
    elif removal == "coordinate":
        value["unit_context_bindings"][0]["coordinates"].pop("y")
    else:
        value["unit_context_bindings"][0]["coordinates"]["y"]["derivation"]["inputs"].pop("storage_modulus")
    with pytest.raises(ValueError):
        prepare_update(document, patch(document, value, target="source:" + document["scientific"]["data_sources"][0]["source_id"]))


def test_physical_frequency_unit_spelling_change_requires_explicit_new_proof_and_transform(tmp_path):
    path = instrument_source(tmp_path / "source.csv", temperatures=(190,), magnitude=False)
    document = semantic_document(path, intent(), tmp_path)
    before = resolve_transforms(document, load_sources(document, "rheology_frequency_sweep"))["datasets"]
    path.write_text(path.read_text(encoding="utf-16").replace("[rad/s]", "rad/s"), encoding="utf-16")
    value = fresh_value(document, path)
    context = value["unit_context_bindings"][0]
    for coordinate in (context["coordinates"]["x"], context["coordinates"]["y"]["derivation"]["inputs"]["angular_frequency"]):
        refreshed = _coordinate_binding({"column_id": coordinate["column_id"], "column_index": coordinate["column_index"],
            "header": coordinate["header"], "quantity": "angular_frequency", "unit": "rad/s"},
            {"quantity": "angular_frequency", "column_id": coordinate["column_id"], "unit": "rad/s"}, "x")
        coordinate.clear()
        coordinate.update(refreshed)
    target = "source:" + document["scientific"]["data_sources"][0]["source_id"]
    request = patch(document, value, target=target)
    for node in document["scientific"]["transforms"]:
        if node["kind"] == "convert_unit" and node["parameters"]["from_unit"] == "[rad/s]":
            request["changes"].append({"op": "set", "target": ["transform:" + node["id"]], "property": "transform.parameters",
                "value": {**node["parameters"], "from_unit": "rad/s"}})
    updated = prepare_update(document, request)[0]
    facts, frames = {}, {}
    datasets = load_sources(updated, "rheology_frequency_sweep", column_facts=facts, source_frames=frames)
    validate_reconfirmed_contexts(updated, document, datasets=datasets, column_facts=facts, source_frames=frames)
    after = resolve_transforms(updated, datasets)["datasets"]
    layer = updated["scientific"]["provenance"]["figure_spec"]["views"][0]["layers"][0]
    for key in ("x", "y"):
        assert after[layer["dataset_id"]]["columns"][key]["values"] == before[layer["dataset_id"]]["columns"][key]["values"]
    assert after[layer["dataset_id"]]["provenance"]["sources"][0]["rows"] == list(range(10, 26))
