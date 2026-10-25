"""Generated literal controls for whole-file source revision and exact evidence."""

from copy import deepcopy
import json

import pytest
from test_current_unit_admission import expert_wire, managed
from test_figure_document import request_for_figure

from sciplot_core.foundation.file_hashing import file_sha256
from sciplot_core.plot_document import seal_document
from sciplot_core.plot_engine.content_store import intern_document, resolve_document_content
from sciplot_core.plot_engine.current_unit_admission import admit_current_units
from sciplot_core.plot_engine.managed_source_revision import source_value, validate_reconfirmed_contexts
from sciplot_core.plot_engine.managed_sources import load_sources
from sciplot_core.plot_engine.managed_state import input_files
from sciplot_core.plot_engine.managed_updates import prepare_update
from sciplot_core.plot_engine.managed_resolution import resolved_metadata
from sciplot_core.plot_ir import create_managed_document
from sciplot_core.plot_transforms import resolve_transforms
from sciplot_core.task_semantic_plan import _coordinate_binding


def basic(tmp_path):
    wire = request_for_figure(tmp_path)
    return resolved_metadata(create_managed_document(wire["template_definition"], wire["data_binding"], plot_id="test"),
                             rule_id=wire["rule_id"], executors={})


def patch(document, value, *, target="source:raw:A", key="source-refresh"):
    return {"plot_id": document["plot_id"], "base_revision": document["revision"],
        "idempotency_key": key, "intent_class": "scientific", "changes": [
            {"op": "set", "target": [target], "property": "source.sha256", "value": value}]}


def confirm(source, *, value="Modulus", sheet=None):
    return {"source_sha256": source["sha256"], "sheet": sheet, "column_index": 1,
            "field": "sample", "value": value,
            "evidence": {"kind": "user_statement", "asserted_by": "generated-control", "statement": "Explicit sample " + value}}


def fresh_value(document, path, *, root=None):
    value = source_value(document, "source:" + document["scientific"]["data_sources"][0]["source_id"], root=root)
    value["sha256"] = file_sha256(path)
    for entry in value["bindings"].values():
        for declaration in entry["metadata_confirmations"]:
            declaration["source_sha256"] = value["sha256"]  # Explicit caller action, never implementation repinning.
    for binding in value["unit_context_bindings"]:
        binding["source_sha256"] = value["sha256"]
    return value


def test_changed_values_keep_literal_masks_rows_and_json_reopen_equivalent(tmp_path):
    document = basic(tmp_path)
    source = document["scientific"]["data_sources"][0]
    source["metadata_confirmations"] = [confirm(source)]
    document["scientific"]["provenance"]["binding"]["source_appends"] = [{"historical_sha": source["sha256"]}]
    document = seal_document(document)
    path = tmp_path / "figure.csv"
    path.write_text("Frequency,Modulus\nHz,Pa\n0,7\n5,\n10,-3\n")
    request = patch(document, fresh_value(document, path))
    old = deepcopy(document)
    updated, diff, risk, scientific = prepare_update(document, request)
    admit_current_units(tmp_path / "store", updated, previous=document)
    raw = load_sources(updated, "uvvis_spectrum")
    assert raw["raw:A"]["columns"]["column:1"]["values"] == [7.0, None, -3.0]
    assert raw["raw:A"]["provenance"]["sources"][0]["rows"] == [2, 3, 4]
    assert updated["scientific"]["provenance"]["binding"]["source_appends"] == old["scientific"]["provenance"]["binding"]["source_appends"]
    assert json.loads(json.dumps(updated)) == updated
    assert load_sources(json.loads(json.dumps(updated)), "uvvis_spectrum") == raw
    assert scientific and risk == "scientific" and len(diff) == 1 and document == old
    repeated, empty, _, _ = prepare_update(updated, patch(updated, fresh_value(updated, path)))
    assert repeated == updated and empty == [] and path.read_text().endswith("10,-3\n")


def test_old_scalar_safe_single_source_compatibility_and_noop(tmp_path):
    document = basic(tmp_path)
    path = tmp_path / "figure.csv"
    original = deepcopy(document)
    assert prepare_update(document, patch(document, document["scientific"]["data_sources"][0]["sha256"]))[1] == []
    path.write_text(path.read_text().replace("5,5", "5,9"))
    updated = prepare_update(document, patch(document, file_sha256(path)))[0]
    admit_current_units(tmp_path, updated, previous=document)
    assert load_sources(updated, "uvvis_spectrum")["raw:A"]["columns"]["column:1"]["values"] == [1, 9, 15]
    assert original == document


@pytest.mark.parametrize("fault", ["scalar", "missing-member", "old-confirmation", "extra-field", "wrong-source"])
def test_group_payload_closed_and_explicit_without_partial_candidate_mutation(tmp_path, fault):
    document = basic(tmp_path)
    source = document["scientific"]["data_sources"][0]
    source["metadata_confirmations"] = [confirm(source)]
    document["scientific"]["data_sources"].append({**deepcopy(source), "source_id": "raw:B"})
    document = seal_document(document)
    before = deepcopy(document)
    path = tmp_path / "figure.csv"
    path.write_text(path.read_text().replace("5,5", "5,9"))
    value = fresh_value(document, path)
    if fault == "scalar":
        value = value["sha256"]
    elif fault == "missing-member":
        value["bindings"].pop("raw:B")
    elif fault == "old-confirmation":
        value["bindings"]["raw:B"]["metadata_confirmations"][0]["source_sha256"] = source["sha256"]
    elif fault == "extra-field":
        value["auto_confirm"] = True
    else:
        value["bindings"]["raw:C"] = {"metadata_confirmations": []}
    with pytest.raises(ValueError):
        prepare_update(document, patch(document, value))
    assert document == before


def test_same_physical_alias_group_batch_dedup_and_all_bindings_update(tmp_path):
    document = basic(tmp_path)
    path, alias = tmp_path / "figure.csv", tmp_path / "alias.csv"
    alias.symlink_to(path)
    document["scientific"]["data_sources"].append({**deepcopy(document["scientific"]["data_sources"][0]),
                                                 "source_id": "raw:B", "path": str(alias)})
    document = seal_document(document)
    path.write_text(path.read_text().replace("5,5", "5,11"))
    request = patch(document, fresh_value(document, path))
    updated = prepare_update(document, request)[0]
    assert {source["sha256"] for source in updated["scientific"]["data_sources"]} == {file_sha256(path)}
    assert input_files(updated) == {str(path): file_sha256(path)}
    request["changes"].append({**deepcopy(request["changes"][0]), "target": ["source:raw:B"]})
    with pytest.raises(ValueError) as error:
        prepare_update(document, request)
    assert error.value.reason_code == "document_duplicate_change"


def test_source_executable_script_and_builtin_inputs_cannot_overwrite_conflicting_hash(tmp_path, monkeypatch):
    from sciplot_core.plot_engine import managed_state
    document = basic(tmp_path)
    source = document["scientific"]["data_sources"][0]
    extra = {**deepcopy(source), "source_id": "raw:B", "sha256": "b" * 64}
    document["scientific"]["data_sources"].append(extra)
    with pytest.raises(ValueError, match="conflicting"):
        input_files(document)
    document["scientific"]["data_sources"].pop()
    for field in ("executable", "script"):
        document["scientific"]["provenance"]["managed"]["executors"] = {"external": {
            "executable": str(tmp_path / "other"), "script": str(tmp_path / "other"), field: source["path"],
            "identity": {"executable_sha256": "b" * 64, "script_sha256": "b" * 64}}}
        with pytest.raises(ValueError, match="conflicting"):
            input_files(document)
    document["scientific"]["provenance"]["managed"]["executors"] = {}
    from sciplot_core.plot_transforms import builtin_executor

    document["scientific"]["transforms"] = [{"id": "fake", "kind": "select", "inputs": [source["source_id"]],
        "output": "selected", "parameters": {"columns": ["column:0"]},
        "executor": builtin_executor("select"), "determinism": "deterministic"}]
    monkeypatch.setattr(managed_state, "builtin_files", lambda *_: {source["path"]: "b" * 64})
    with pytest.raises(ValueError, match="conflicting"):
        input_files(document)


def context_for(document, sha, *, header="sensor_C"):
    source = document["scientific"]["data_sources"][0]
    column = {"column_id": "column:1", "column_index": 1, "header": header, "quantity": None, "unit": "C"}
    coordinate = _coordinate_binding(column, {"quantity": "temperature", "column_id": "column:1", "unit": "K"}, "y")
    return {"source_path": source["path"], "source_sha256": sha, "table_id": "table:0", "block_id": "block:0",
            "table_selection": deepcopy(source["table_selection"]), "quantities": {"x": "time", "y": "temperature"},
            "condition": {}, "coordinates": {"y": coordinate}}


def test_unknown_expert_quantity_requires_new_exact_selector_fact_and_fresh_projection(tmp_path):
    document = managed(expert_wire(tmp_path, header="sensor_C"))
    path = tmp_path / "figure.csv"
    path.write_text(path.read_text().replace("1,21", "1,22"))
    value = fresh_value(document, path)
    updated = prepare_update(document, patch(document, value))[0]
    with pytest.raises(ValueError):
        admit_current_units(tmp_path, updated, previous=document)
    value["unit_context_bindings"] = [context_for(document, value["sha256"])]
    updated = prepare_update(document, patch(document, value))[0]
    admit_current_units(tmp_path, updated, previous=document)
    facts = {}
    datasets = load_sources(updated, "uvvis_spectrum", column_facts=facts)
    validate_reconfirmed_contexts(updated, document, datasets=datasets, column_facts=facts)
    projected = resolve_transforms(updated, datasets)["datasets"]["projected"]
    assert projected["columns"]["column:1"]["values"] == [295.15, None, 268.15]
    assert projected["provenance"]["sources"][0]["rows"] == [2, 3, 4]


@pytest.mark.parametrize("fault", ["observed-unit", "quantity", "header", "old-sha", "region", "column", "relation"])
def test_context_cannot_assert_different_physical_or_public_mapping_facts(tmp_path, fault):
    document = managed(expert_wire(tmp_path, header="sensor_C"))
    path = tmp_path / "figure.csv"
    path.write_text(path.read_text().replace("1,21", "1,22"))
    value = fresh_value(document, path)
    context = context_for(document, value["sha256"])
    coordinate = context["coordinates"]["y"]
    if fault == "observed-unit":
        coordinate["observed_unit"] = "K"
    elif fault == "quantity":
        coordinate["quantity"] = coordinate["unit_context"]["quantity"] = "charge"
    elif fault == "header":
        coordinate["header"] = coordinate["unit_context"]["source_header"] = "Other"
    elif fault == "old-sha":
        context["source_sha256"] = document["scientific"]["data_sources"][0]["sha256"]
    elif fault == "region":
        context["table_selection"]["data_end_row"] = 4
    elif fault == "column":
        coordinate["column_index"] = 0
    else:
        coordinate["unit_relation"]["offset"] = 0
    value["unit_context_bindings"] = [context]
    with pytest.raises(ValueError):
        updated = prepare_update(document, patch(document, value))[0]
        admit_current_units(tmp_path, updated, previous=document)
        facts = {}
        datasets = load_sources(updated, "uvvis_spectrum", column_facts=facts)
        validate_reconfirmed_contexts(updated, document, datasets=datasets, column_facts=facts)


def test_cas_noop_preserves_reference_and_actual_change_expands_only_binding_leaf(tmp_path):
    document = basic(tmp_path)
    document["scientific"]["provenance"]["binding"]["large"] = list(range(100))
    document["scientific"]["provenance"]["datasets"] = {"unrelated": list(range(100))}
    document = intern_document(tmp_path, seal_document(document), minimum_bytes=2)
    original = deepcopy(document)
    value = source_value(document, "source:raw:A", root=tmp_path)
    updated, diff, _, _ = prepare_update(document, patch(document, value), root=tmp_path)
    assert updated == original and diff == []
    path = tmp_path / "figure.csv"
    path.write_text(path.read_text().replace("5,5", "5,9"))
    value = fresh_value(document, path, root=tmp_path)
    updated = prepare_update(document, patch(document, value), root=tmp_path)[0]
    assert updated["scientific"]["provenance"] == original["scientific"]["provenance"]
    assert resolve_document_content(tmp_path, updated)["scientific"]["provenance"]["binding"]["large"] == list(range(100))


def test_same_sha_new_context_still_checks_fresh_observed_facts_and_cas_previous(tmp_path):
    document = managed(expert_wire(tmp_path, header="sensor_C"))
    previous = intern_document(tmp_path, document, minimum_bytes=2)
    value = source_value(previous, "source:raw:A", root=tmp_path)
    context = context_for(document, value["sha256"])
    context["coordinates"]["y"]["observed_unit"] = "K"
    value["unit_context_bindings"] = [context]
    updated = prepare_update(previous, patch(previous, value), root=tmp_path)[0]
    before = deepcopy(previous)
    with pytest.raises(ValueError) as entry_error:
        admit_current_units(tmp_path, updated, previous=previous)
    assert entry_error.value.reason_code == "managed_source_reconfirmation_required"
    expanded = resolve_document_content(tmp_path, updated)
    facts = {}
    datasets = load_sources(expanded, "uvvis_spectrum", column_facts=facts)
    with pytest.raises(ValueError) as error:
        validate_reconfirmed_contexts(expanded, previous, datasets=datasets, column_facts=facts, root=tmp_path)
    assert error.value.reason_code == "managed_source_reconfirmation_required"
    assert previous == before


def test_order_only_complete_group_reconfirmation_is_true_noop(tmp_path):
    document = basic(tmp_path)
    source = document["scientific"]["data_sources"][0]
    source["metadata_confirmations"] = [confirm(source), {**confirm(source), "field": "unit", "value": "Pa"}]
    document = seal_document(document)
    old = deepcopy(document)
    value = source_value(document, "source:raw:A")
    value["bindings"]["raw:A"]["metadata_confirmations"].reverse()
    updated, diff, _, _ = prepare_update(document, patch(document, value))
    assert updated == old and diff == []


def test_two_regions_same_file_keep_independent_physical_rows_and_masks(tmp_path):
    document = basic(tmp_path)
    source = document["scientific"]["data_sources"][0]
    second = {**deepcopy(source), "source_id": "raw:B"}
    second["table_selection"].update(data_start_row=3, data_end_row=5)
    document["scientific"]["data_sources"].append(second)
    document = seal_document(document)
    path = tmp_path / "figure.csv"
    path.write_text("Frequency,Modulus\nHz,Pa\n0,8\n5,\n10,-7\n")
    updated = prepare_update(document, patch(document, fresh_value(document, path)))[0]
    admit_current_units(tmp_path, updated, previous=document)
    raw = load_sources(updated, "uvvis_spectrum")
    assert raw["raw:A"]["columns"]["column:1"]["values"] == [8, None, -7]
    assert raw["raw:B"]["columns"]["column:1"]["values"] == [None, -7]
    assert raw["raw:A"]["provenance"]["sources"][0]["rows"] == [2, 3, 4]
    assert raw["raw:B"]["provenance"]["sources"][0]["rows"] == [3, 4]


def test_explicit_source_unit_change_pairs_with_existing_transform_edit(tmp_path):
    document = managed(expert_wire(tmp_path, header="sensor"))
    source = document["scientific"]["data_sources"][0]
    context = context_for(document, source["sha256"], header="sensor")
    document["scientific"]["provenance"]["binding"]["semantic_task"] = {"resolution": {"bindings": [context]}}
    document = seal_document(document)
    path = tmp_path / "figure.csv"
    path.write_text("Time,sensor\ns,K\n1,295.15\n2,\n3,268.15\n")
    value = fresh_value(document, path)
    column = {"column_id": "column:1", "column_index": 1, "header": "sensor", "quantity": None, "unit": "K"}
    value["unit_context_bindings"][0]["coordinates"]["y"] = _coordinate_binding(
        column, {"quantity": "temperature", "column_id": "column:1", "unit": "K"}, "y")
    request = patch(document, value)
    unpaired = prepare_update(document, request)[0]
    with pytest.raises(ValueError):
        admit_current_units(tmp_path, unpaired, previous=document)
    request["changes"].append({"op": "set", "target": ["transform:unit"], "property": "transform.parameters",
                              "value": {"columns": ["column:1"], "from_unit": "K", "to_unit": "K"}})
    updated = prepare_update(document, request)[0]
    admit_current_units(tmp_path, updated, previous=document)
    facts = {}
    datasets = load_sources(updated, "uvvis_spectrum", column_facts=facts)
    validate_reconfirmed_contexts(updated, document, datasets=datasets, column_facts=facts)
    projected = resolve_transforms(updated, datasets)["datasets"]["projected"]
    assert datasets["raw:A"]["columns"]["column:1"] == {"label": "sensor", "unit": "K", "values": [295.15, None, 268.15]}
    assert projected["columns"]["column:1"]["values"] == [295.15, None, 268.15]
    assert projected["provenance"]["sources"][0]["rows"] == [2, 3, 4]
