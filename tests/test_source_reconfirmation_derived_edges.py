"""A frozen literal derivation input must be the typed graph's actual input."""

from copy import deepcopy

import pytest
from test_frequency_interval_binding import instrument_source, intent
from test_managed_source_reconfirmation import fresh_value, patch
from test_source_reconfirmation_semantic_facts import semantic_document

from sciplot_core.plot_document import seal_document
from sciplot_core.plot_engine.managed_source_revision import validate_reconfirmed_contexts
from sciplot_core.plot_engine.managed_sources import load_sources
from sciplot_core.plot_engine.managed_updates import prepare_update
from sciplot_core.plot_transforms import builtin_executor, resolve_transforms
from sciplot_core.plot_transforms.unit_relations import resolve_unit_relation


def prepared_rebind(tmp_path, *, fresh_source=True, swap=False):
    path = instrument_source(tmp_path / "source.csv", temperatures=(190,), magnitude=False)
    rows = path.read_text(encoding="utf-16").splitlines()
    first = rows[10].split("\t")
    first[3:6], first[8] = ["100", "300", "400"], "0"
    rows[10] = "\t".join(first)
    path.write_text("\n".join(rows), encoding="utf-16")
    document = semantic_document(path, intent(), tmp_path)
    layer = document["scientific"]["provenance"]["figure_spec"]["views"][0]["layers"][0]
    initial = resolve_transforms(document, load_sources(document, "rheology_frequency_sweep"))["datasets"]
    assert initial[layer["dataset_id"]]["columns"]["y"]["values"][0] == 5.0
    # A real changed source version, without changing any frozen coordinate.
    if fresh_source:
        first[9] = "0.4"
        rows[10] = "\t".join(first)
        path.write_text("\n".join(rows), encoding="utf-16")
    source_id = document["scientific"]["data_sources"][0]["source_id"]
    request = patch(document, fresh_value(document, path), target="source:" + source_id)
    selector = next(node for node in document["scientific"]["transforms"] if node["kind"] == "select" and node["inputs"] == [source_id])
    derived = next(node for node in document["scientific"]["transforms"] if node["kind"] == "rheology_complex_viscosity")
    request["changes"].extend([
        {"op": "set", "target": ["transform:" + selector["id"]], "property": "transform.parameters",
         "value": {"columns": [*selector["parameters"]["columns"], "column:8"]}},
        {"op": "set", "target": ["transform:" + derived["id"]], "property": "transform.parameters",
         "value": {**deepcopy(derived["parameters"]),
                   **({"storage_column": "column:5", "loss_column": "column:4"} if swap else {"storage_column": "column:8"})}},
    ])
    updated = prepare_update(document, request)[0]
    facts, frames = {}, {}
    datasets = load_sources(updated, "rheology_frequency_sweep", column_facts=facts, source_frames=frames)
    return document, updated, datasets, facts, frames, layer


@pytest.mark.parametrize("fresh_source", [False, True])
@pytest.mark.parametrize("swap", [False, True])
def test_typed_storage_edge_cannot_use_another_physical_quantity(tmp_path, fresh_source, swap):
    document, updated, datasets, facts, frames, layer = prepared_rebind(tmp_path, fresh_source=fresh_source, swap=swap)
    binding = updated["scientific"]["provenance"]["binding"]["semantic_task"]["resolution"]["bindings"][0]
    assert binding["coordinates"]["y"]["derivation"]["inputs"]["storage_modulus"]["column_id"] == "column:4"
    # The stress substitution computes 4 instead of 5. Swapping storage and loss
    # still computes 5, but violates the same independently fixed physical roles.
    counterfactual = resolve_transforms(updated, datasets)["datasets"]
    assert counterfactual[layer["dataset_id"]]["columns"]["y"]["values"][0] == (5.0 if swap else 4.0)
    with pytest.raises(ValueError):
        validate_reconfirmed_contexts(updated, document, datasets=datasets, column_facts=facts, source_frames=frames)


def test_transform_only_scale_remains_an_explicit_valid_scientific_change(tmp_path):
    document, *_unused = prepared_rebind(tmp_path, fresh_source=False)
    final = document["scientific"]["transforms"][-1]
    output = final["output"]
    final["output"] = "before-scale"
    document["scientific"]["transforms"].append({"id": "control-scale", "kind": "scale", "inputs": ["before-scale"],
        "output": output, "parameters": {"columns": ["y"], "factor": 1},
        "executor": builtin_executor("scale"), "determinism": "deterministic"})
    document = seal_document(document)
    original = deepcopy(document)
    request = {"plot_id": document["plot_id"], "base_revision": document["revision"], "idempotency_key": "valid-scale",
        "intent_class": "scientific", "changes": [{"op": "set", "target": ["transform:control-scale"],
            "property": "transform.parameters", "value": {"columns": ["y"], "factor": 2}}]}
    updated = prepare_update(document, request)[0]
    facts, frames = {}, {}
    datasets = load_sources(updated, "rheology_frequency_sweep", column_facts=facts, source_frames=frames)
    validate_reconfirmed_contexts(updated, document, datasets=datasets, column_facts=facts, source_frames=frames)
    result = resolve_transforms(updated, datasets)["datasets"]
    assert result[output]["columns"]["y"]["values"][0] == 10.0
    assert updated["scientific"]["data_sources"] == original["scientific"]["data_sources"] and document == original


def test_same_source_registered_input_unit_conversion_preserves_role_and_values(tmp_path):
    document, *_unused = prepared_rebind(tmp_path, fresh_source=False)
    derived = next(node for node in document["scientific"]["transforms"] if node["kind"] == "rheology_complex_viscosity")
    original_input = derived["inputs"][0]
    derived["inputs"] = ["unit-projected"]
    document["scientific"]["transforms"].append({"id": "control-unit", "kind": "convert_unit", "inputs": [original_input],
        "output": "unit-projected", "parameters": {"columns": ["column:4"], "from_unit": "[Pa]", "to_unit": "[Pa]"},
        "executor": builtin_executor("convert_unit"), "determinism": "deterministic"})
    document = seal_document(document)
    source = document["scientific"]["data_sources"][0]
    value = fresh_value(document, tmp_path / "source.csv")
    leaf = value["unit_context_bindings"][0]["coordinates"]["y"]["derivation"]["inputs"]["storage_modulus"]
    leaf["unit"] = "kPa"
    leaf["unit_relation"] = resolve_unit_relation("[Pa]", "kPa", quantity="storage_modulus", observed_quantity="storage_modulus")
    request = patch(document, value, target="source:" + source["source_id"])
    request["changes"].append({"op": "set", "target": ["transform:control-unit"], "property": "transform.parameters",
        "value": {"columns": ["column:4"], "from_unit": "[Pa]", "to_unit": "kPa"}})
    updated = prepare_update(document, request)[0]
    facts, frames = {}, {}
    datasets = load_sources(updated, "rheology_frequency_sweep", column_facts=facts, source_frames=frames)
    validate_reconfirmed_contexts(updated, document, datasets=datasets, column_facts=facts, source_frames=frames)
    result = resolve_transforms(updated, datasets)["datasets"]
    layer = document["scientific"]["provenance"]["figure_spec"]["views"][0]["layers"][0]
    assert result[layer["dataset_id"]]["columns"]["y"]["values"][0] == 5.0
    assert updated["scientific"]["data_sources"] == document["scientific"]["data_sources"]


def test_same_file_multiple_original_intervals_match_each_frozen_derivation_region(tmp_path):
    path = instrument_source(tmp_path / "source.csv", temperatures=(190, 150), magnitude=False)
    document = semantic_document(path, intent(), tmp_path)
    original = resolve_transforms(document, load_sources(document, "rheology_frequency_sweep"))["datasets"]
    path.write_text(path.read_text(encoding="utf-16").replace("0.2\tTruStrain", "0.4\tTruStrain", 1), encoding="utf-16")
    source = document["scientific"]["data_sources"][0]
    request = patch(document, fresh_value(document, path), target="source:" + source["source_id"])
    assert len(request["changes"][0]["value"]["unit_context_bindings"]) == 2
    updated = prepare_update(document, request)[0]
    facts, frames = {}, {}
    datasets = load_sources(updated, "rheology_frequency_sweep", column_facts=facts, source_frames=frames)
    validate_reconfirmed_contexts(updated, document, datasets=datasets, column_facts=facts, source_frames=frames)
    result = resolve_transforms(updated, datasets)["datasets"]
    for layer in document["scientific"]["provenance"]["figure_spec"]["views"][0]["layers"]:
        assert result[layer["dataset_id"]]["columns"]["y"]["values"] == original[layer["dataset_id"]]["columns"]["y"]["values"]
