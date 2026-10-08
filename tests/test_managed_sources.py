"""Original sample identities remain bound through scientific transform chains."""

from copy import deepcopy
from pathlib import Path
import sys

import pytest

from sciplot_core.foundation.file_hashing import file_sha256
from sciplot_core.plot_engine.errors import EngineError
from sciplot_core.plot_engine.managed_sources import load_sources
from sciplot_core.plot_transforms import ExternalExecutor, builtin_executor, builtin_files
from sciplot_core.plot_document import apply_patch, seal_document
from test_plot_ir import resolved_example


def _node(kind, input_id, output, parameters):
    return {"id": output, "kind": kind, "inputs": [input_id], "output": output,
            "parameters": parameters, "executor": builtin_executor(), "determinism": "deterministic"}


def _document(tmp_path, *, samples=True):
    path = tmp_path / "UVvis.csv"
    metadata = "A,A,B,B\n" if samples else ""
    path.write_text("Wavelength,Absorbance,Wavelength,Absorbance\nnm,a.u.,nm,a.u.\n" + metadata +
                    "400,1,400,2\n450,2,450,3\n500,4,500,6\n")
    start = 3 if samples else 2
    selection = {"sheet": None, "header_rows": [0], "unit_row": 1, "data_start_row": start, "data_end_row": start + 3}
    if samples:
        selection["sample_row"] = 2
    mapping = {"series_id": "series:A", "sample": "A",
               "x": {"source_id": "raw", "column": "Wavelength", "column_index": 0},
               "y": {"source_id": "raw", "column": "Absorbance", "column_index": 1},
               "x_unit": "nm", "y_unit": "a.u."}
    return {"scientific": {"data_sources": [{"source_id": "raw", "path": str(path), "sha256": file_sha256(path),
                                             "table_selection": selection}],
                           "mappings": {"series:A": mapping}, "transforms": []}}


def test_explicit_mechanical_table_keeps_its_rule_and_original_metadata(tmp_path):
    from sciplot_core.data_mapping.table_choice import table_choice_snapshot

    source = tmp_path / 'tensile_summary.csv'
    source.write_text('Category,Tensile strength\n1,MPa\nE0,E0\n0,34.078\n')
    document = {'scientific': {
        'data_sources': [{'source_id': 'raw', 'path': str(source), 'sha256': file_sha256(source),
                          'table_selection': {'sheet': None, 'header_rows': [0], 'unit_row': 1,
                                              'sample_row': 2, 'data_start_row': 3, 'data_end_row': 4}}],
        'mappings': {'series:E0': {'series_id': 'series:E0', 'sample': 'E0',
            'x': {'source_id': 'raw', 'column': 'Category', 'column_index': 0},
            'y': {'source_id': 'raw', 'column': 'Tensile strength', 'column_index': 1},
            'x_unit': '1', 'y_unit': 'MPa'}}, 'transforms': []}}
    # Ordinary automatic curve discovery has not acquired a new adapter.
    assert table_choice_snapshot(source, 'tensile_curve') is None
    loaded = load_sources(document, 'tensile_curve')
    assert loaded['raw']['columns']['column:1'] == {'label': 'Tensile strength', 'unit': 'MPa', 'values': [34.078]}
    assert loaded['raw']['provenance']['sources'][0]['rows'] == [3]
    document['scientific']['mappings']['series:E0']['y_unit'] = 'Pa'
    with pytest.raises(EngineError) as error:
        load_sources(document, 'tensile_curve')
    assert error.value.reason_code == 'managed_metadata_conflict'


@pytest.mark.parametrize("kind", ["select", "rename", "scale", "normalize"])
def test_builtin_outputs_cannot_be_rebound_to_a_different_sample(tmp_path, kind):
    document = _document(tmp_path)
    parameters = {"select": {"columns": ["column:0", "column:1"]},
                  "rename": {"columns": {"column:1": {"id": "response", "label": "Renamed"}}},
                  "scale": {"columns": ["column:1"], "factor": 2},
                  "normalize": {"columns": ["column:1"], "method": "max_abs", "output_unit": "1"}}[kind]
    document["scientific"]["transforms"] = [_node(kind, "raw", "processed", parameters)]
    mapping = document["scientific"]["mappings"]["series:A"]
    for axis in ("x", "y"):
        mapping[axis]["source_id"] = "processed"
    if kind == "rename":
        mapping["y"] = {"source_id": "processed", "column": "response"}
    assert load_sources(document, "uvvis_spectrum")["raw"]["columns"]["column:1"]["values"] == [1, 2, 4]
    mapping["sample"] = "wrong"
    with pytest.raises(EngineError) as error:
        load_sources(document, "uvvis_spectrum")
    assert error.value.reason_code == "managed_sample_conflict"


def test_absent_sample_row_accepts_explicit_binding_identity_for_raw_and_derived(tmp_path):
    document = _document(tmp_path, samples=False)
    document["scientific"]["mappings"]["series:A"]["sample"] = "Explicit author label"
    assert load_sources(document, "uvvis_spectrum")
    document["scientific"]["transforms"] = [_node("scale", "raw", "processed", {"columns": ["column:1"], "factor": 2})]
    for axis in ("x", "y"):
        document["scientific"]["mappings"]["series:A"][axis]["source_id"] = "processed"
    assert load_sources(document, "uvvis_spectrum")


def test_external_mixed_sample_inputs_need_explicit_lineage_or_prior_selection(tmp_path):
    document = _document(tmp_path)
    script = tmp_path / "fixed.py"
    script.write_text("raise AssertionError('sample lineage must be checked before execution')\n")
    executor = ExternalExecutor(Path(sys.executable), script, {"type": "object", "properties": {}, "additionalProperties": False})
    node = {"id": "external", "kind": "external", "inputs": ["raw"], "output": "processed", "parameters": {},
            "executor": executor.descriptor("fixed"), "determinism": "deterministic"}
    document["scientific"]["transforms"] = [node]
    for axis in ("x", "y"):
        document["scientific"]["mappings"]["series:A"][axis]["source_id"] = "processed"
    with pytest.raises(EngineError) as error:
        load_sources(document, "uvvis_spectrum")
    assert error.value.reason_code == "managed_sample_lineage_unknown"
    selected = _node("select", "raw", "only-A", {"columns": ["column:0", "column:1"]})
    document["scientific"]["transforms"] = [selected, {**node, "inputs": ["only-A"]}]
    assert load_sources(document, "uvvis_spectrum")
    changed = deepcopy(document)
    changed["scientific"]["mappings"]["series:A"]["sample"] = "B"
    with pytest.raises(EngineError) as error:
        load_sources(changed, "uvvis_spectrum")
    assert error.value.reason_code == "managed_sample_conflict"


def test_builtin_identity_exposes_every_bound_implementation_file():
    files = builtin_files()
    assert {Path(name).name for name in files} == {"builtins.py", "datasets.py", "execution.py", "schema.py", "identity.py"}
    assert all(Path(name).is_absolute() and file_sha256(Path(name)) == value for name, value in files.items())


def _request(document, prop, value, target="figure:main", intent="presentation"):
    return {"plot_id": document["plot_id"], "base_revision": document["revision"], "idempotency_key": "test-update",
            "intent_class": intent, "changes": [{"op": "set", "target": [target], "property": prop, "value": value}]}


def test_theme_same_definition_is_noop_until_a_manual_override_needs_reset():
    from sciplot_core.plot_engine.managed_updates import prepare_update

    resolved, _ = resolved_example()
    document = resolved["document"]
    theme = {"kind": "sciplot_theme", "schema_version": 1, "theme_id": "paper", "rules": [
        {"target": ["series:A"], "property": "style.line.width", "value": "1pt"}]}
    themed, diff, _, _ = prepare_update(document, _request(document, "theme", theme))
    assert diff
    same, diff, _, _ = prepare_update(themed, _request(themed, "theme", theme))
    assert not diff and same["scientific_hash"] == themed["scientific_hash"] and same["presentation_hash"] == themed["presentation_hash"]
    edited, _, _ = apply_patch(themed, _request(themed, "style.line.width", "2pt", "series:A"))
    restored, diff, _, _ = prepare_update(edited, _request(edited, "theme", theme))
    assert diff and restored["presentation"]["objects"]["series:A"]["properties"]["style.line.width"] == "1pt"
    assert restored["scientific_hash"] == edited["scientific_hash"]


def test_numeric_type_changes_cannot_be_reported_as_hash_preserving_noops():
    from sciplot_core.plot_engine.managed_updates import prepare_update

    resolved, _ = resolved_example()
    document = deepcopy(resolved["document"])
    parameters = {"columns": ["column:1"], "method": "constant", "constant": 8, "output_unit": "1"}
    document["scientific"]["transforms"][0]["parameters"] = parameters
    document = seal_document(document)
    changed, diff, risk, science = prepare_update(document,
        _request(document, "transform.parameters", {**parameters, "constant": 8.0}, "transform:normalize-A", "scientific"))
    assert diff and risk == "scientific" and science
    assert changed["scientific_hash"] != document["scientific_hash"]


def test_builtin_refresh_requires_explicit_current_descriptor_and_scientific_intent():
    from sciplot_core.plot_engine.managed_updates import prepare_update

    resolved, _ = resolved_example()
    document = deepcopy(resolved["document"])
    document["scientific"]["transforms"][0]["executor"]["content_hash"] = "0" * 64
    document = seal_document(document)
    value = builtin_executor()
    with pytest.raises(ValueError):
        prepare_update(document, _request(document, "transform.executor", value, "transform:normalize-A"))
    with pytest.raises(ValueError):
        prepare_update(document, _request(document, "transform.executor", {**value, "content_hash": "1" * 64}, "transform:normalize-A", "scientific"))
    changed, diff, _, science = prepare_update(document,
        _request(document, "transform.executor", value, "transform:normalize-A", "scientific"))
    assert diff and science and changed["scientific"]["transforms"][0]["executor"] == value


def test_large_managed_control_metadata_stays_inline_while_dataset_payload_is_interned(tmp_path):
    from sciplot_core.plot_engine.content_store import intern_document, resolve_document_content

    resolved, _ = resolved_example()
    document = deepcopy(resolved["document"])
    marker = document["scientific"]["provenance"]["managed"]
    marker["executors"] = {"large-fixed": {"parameter_schema": {"description": "x" * 70000}}}
    document = seal_document(document)
    canonical = intern_document(tmp_path, document, minimum_bytes=1024)
    assert canonical["scientific"]["provenance"]["managed"] == marker
    assert canonical["scientific"]["provenance"]["datasets"]["kind"] == "sciplot_content_reference"
    assert resolve_document_content(tmp_path, canonical)["scientific_hash"] == document["scientific_hash"]


def test_existing_binding_observes_builtin_byte_drift_and_description_remains_usable(tmp_path, monkeypatch):
    from sciplot_core.plot_engine import managed_state
    from sciplot_core.plot_engine.managed_description import describe_managed
    from sciplot_core.plot_engine.managed_backend import ManagedBackend
    from sciplot_core.plot_engine.current import changed_inputs

    resolved, _ = resolved_example()
    document = deepcopy(resolved["document"])
    for source in document["scientific"]["data_sources"]:
        path = tmp_path / (source["source_id"] + ".csv")
        path.write_text("original source")
        source.update(path=str(path), sha256=file_sha256(path))
    document = seal_document(document)
    implementation = tmp_path / "builtin.py"
    implementation.write_text("version = 1")
    monkeypatch.setattr(managed_state, "builtin_files", lambda: {str(implementation): file_sha256(implementation)})
    files = managed_state.input_files(document)
    native = tmp_path / "deleted-document.vsz"
    binding = {"document": str(native), "ir_hash": "d" * 64, "ir_path": str(tmp_path / "deleted-ir.json"),
               "fingerprint": {"files": files, "artifacts": {str(native): "d" * 64}}, "graph": resolved["graph"]}
    implementation.write_text("version = 2")
    backend = ManagedBackend()
    try:
        changed = changed_inputs(backend, binding)
        assert changed == [str(implementation)]
        result = describe_managed(tmp_path, {"document": document, "binding": binding},
                                  {"changed_inputs": changed, "status": "dirty"}, backend)
        assert "transform:normalize-A" in result["dependencies"]["invalidated"]
        assert "transform:normalize-B" in result["dependencies"]["invalidated"]
        assert "source:A" not in result["dependencies"]["invalidated"]
        assert result["next_step"]["action"] == "refresh_builtin_executor"
        current = builtin_executor()
        monkeypatch.setattr(managed_state, "builtin_executor", lambda: {**current, "content_hash": "e" * 64})
        with pytest.raises(EngineError) as error:
            managed_state.require_inputs(document)
        assert error.value.reason_code == "managed_builtin_executor_changed"
    finally:
        backend.close()


def test_loaded_builtin_code_cannot_execute_under_a_new_file_identity(monkeypatch):
    from sciplot_core.plot_transforms import identity, execute_node

    resolved, raw = resolved_example()
    monkeypatch.setattr(identity, "_LOADED_FILES", {"old-runtime": "0" * 64})
    with pytest.raises(ValueError) as error:
        execute_node(resolved["document"]["scientific"]["transforms"][0], raw)
    assert error.value.reason_code == "transform_runtime_changed"
