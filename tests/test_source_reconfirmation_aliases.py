"""Public generated aliases share physical evidence, never equal-content files."""

from copy import deepcopy
import json

import pytest
from test_managed_source_reconfirmation import fresh_value, patch
from test_source_reconfirmation_semantic_facts import semantic_document

from sciplot_core.foundation.file_hashing import file_sha256
from sciplot_core.plot_document import seal_document
from sciplot_core.plot_engine.content_store import intern_document
from sciplot_core.plot_engine.current_unit_admission import admit_current_units
from sciplot_core.plot_engine.managed_source_revision import source_value, validate_reconfirmed_contexts
from sciplot_core.plot_engine.managed_sources import load_sources
from sciplot_core.plot_engine.managed_updates import prepare_update
from sciplot_core.plot_transforms import resolve_transforms


def saved_alias_document(tmp_path, *, aliases):
    path = tmp_path / "original.csv"
    path.write_text("Time,sensor\ns,C\n1,21\n2,\n3,-5\n")
    intent = {"x": {"quantity": "time", "header": "Time", "unit": "s"},
              "y": {"quantity": "temperature", "header": "sensor", "unit": "K"}}
    document = semantic_document(path, intent, tmp_path)
    sources = document["scientific"]["data_sources"]
    original = deepcopy(sources[0])
    for index in range(aliases):
        alias = tmp_path / ("alias-" + str(index) + ".csv")
        alias.symlink_to(path)
        if index == 0:
            sources[0]["path"] = str(alias)
        else:
            sources.append({**deepcopy(original), "source_id": "alias:" + str(index), "path": str(alias)})
    # Expert creation retains the actual builder's original realpath proof.
    document = seal_document(document)
    admit_current_units(tmp_path / "store", document)
    return json.loads(json.dumps(document)), path


def check_fresh(document, previous, tmp_path):
    admit_current_units(tmp_path / "store", document, previous=previous)
    facts, frames = {}, {}
    datasets = load_sources(document, "ordinary_xy", column_facts=facts, source_frames=frames)
    validate_reconfirmed_contexts(document, previous, datasets=datasets, column_facts=facts, source_frames=frames)
    return datasets


@pytest.mark.parametrize("aliases", [1, 2])
def test_realpath_context_reconfirms_saved_alias_source_group_once(tmp_path, aliases):
    document, path = saved_alias_document(tmp_path, aliases=aliases)
    previous = deepcopy(document)
    context = document["scientific"]["provenance"]["binding"]["semantic_task"]["resolution"]["bindings"][0]
    assert context["source_path"] == str(path.resolve())
    assert all(source["path"] != context["source_path"] for source in document["scientific"]["data_sources"])
    path.write_text(path.read_text().replace("1,21", "1,22"))
    target = "source:" + document["scientific"]["data_sources"][0]["source_id"]
    value = fresh_value(document, path)
    assert len(value["unit_context_bindings"]) == 1
    updated = prepare_update(document, patch(document, value, target=target))[0]
    datasets = check_fresh(updated, previous, tmp_path)
    assert all(dataset["columns"]["column:1"]["values"] == [22, None, -5] for dataset in datasets.values())
    result = resolve_transforms(updated, datasets)["datasets"]
    layer = updated["scientific"]["provenance"]["figure_spec"]["views"][0]["layers"][0]
    assert result[layer["dataset_id"]]["columns"]["y"]["values"] == [295.15, None, 268.15]
    assert result[layer["dataset_id"]]["provenance"]["sources"][0]["rows"] == [2, 3, 4]
    assert previous == document


def test_reconfirmation_can_name_an_existing_alias_without_duplicating_group_context(tmp_path):
    document, path = saved_alias_document(tmp_path, aliases=2)
    path.write_text(path.read_text().replace("1,21", "1,22"))
    target = "source:" + document["scientific"]["data_sources"][0]["source_id"]
    value = fresh_value(document, path)
    alias = document["scientific"]["data_sources"][1]["path"]
    value["unit_context_bindings"][0]["source_path"] = alias
    updated = prepare_update(document, patch(document, value, target=target))[0]
    reopened = json.loads(json.dumps(updated))
    datasets = check_fresh(reopened, document, tmp_path)
    assert len(reopened["scientific"]["provenance"]["binding"]["semantic_task"]["resolution"]["bindings"]) == 1
    assert all(item["columns"]["column:1"]["values"] == [22, None, -5] for item in datasets.values())


def test_alias_only_context_edit_is_true_noop_and_preserves_cas_representation(tmp_path):
    document, _path = saved_alias_document(tmp_path, aliases=2)
    root = tmp_path / "store"
    compact = intern_document(root, document, minimum_bytes=2)
    original = deepcopy(compact)
    target = "source:" + document["scientific"]["data_sources"][0]["source_id"]
    value = source_value(compact, target, root=root)
    value["unit_context_bindings"][0]["source_path"] = document["scientific"]["data_sources"][1]["path"]
    updated, diff, _risk, _scientific = prepare_update(compact, patch(compact, value, target=target), root=root)
    assert diff == [] and updated == original and compact == original
    assert updated["scientific"]["provenance"]["binding"]["kind"] == "sciplot_content_reference"


def test_equal_content_different_file_cannot_supply_same_group_or_unit_proof(tmp_path):
    document, path = saved_alias_document(tmp_path, aliases=1)
    path.write_text(path.read_text().replace("1,21", "1,22"))
    separate = tmp_path / "separate.csv"
    separate.write_bytes(path.read_bytes())
    assert file_sha256(path) == file_sha256(separate) and path.resolve() != separate.resolve()
    target = "source:" + document["scientific"]["data_sources"][0]["source_id"]
    value = fresh_value(document, path)
    value["unit_context_bindings"][0]["source_path"] = str(separate)
    with pytest.raises(ValueError):
        prepare_update(document, patch(document, value, target=target))
    # Independently exercise the original-column owner, without the edit guard.
    forged = deepcopy(document)
    forged["scientific"]["data_sources"][0]["sha256"] = file_sha256(path)
    forged["scientific"]["provenance"]["binding"]["semantic_task"]["resolution"]["bindings"] = value["unit_context_bindings"]
    with pytest.raises(ValueError):
        admit_current_units(tmp_path / "store", seal_document(forged), previous=document)


@pytest.mark.parametrize("fault", ["sha", "region", "column"])
def test_alias_identity_preserves_exact_sha_region_and_column_requirements(tmp_path, fault):
    document, path = saved_alias_document(tmp_path, aliases=2)
    path.write_text(path.read_text().replace("1,21", "1,22"))
    target = "source:" + document["scientific"]["data_sources"][0]["source_id"]
    updated = prepare_update(document, patch(document, fresh_value(document, path), target=target))[0]
    context = updated["scientific"]["provenance"]["binding"]["semantic_task"]["resolution"]["bindings"][0]
    if fault == "sha":
        context["source_sha256"] = "0" * 64
    elif fault == "region":
        context["table_selection"]["data_end_row"] = 4
    else:
        context["coordinates"]["y"].update(column_id="column:0", column_index=0)
    with pytest.raises(ValueError):
        admit_current_units(tmp_path / "store", seal_document(updated), previous=document)
