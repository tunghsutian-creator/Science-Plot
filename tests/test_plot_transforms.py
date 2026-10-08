"""Explicit transform execution and content identities cannot hide scientific work."""

from copy import deepcopy
from pathlib import Path
import sys

import pytest

from sciplot_core.plot_document import DocumentError, seal_document
from sciplot_core.plot_transforms import ExternalExecutor, builtin_executor, execute_node, executor_files, ordered_nodes, resolve_transforms, validate_node
from test_plot_ir import managed_example, resolved_example


def builtin(kind, parameters, *, output="output", input_id="A"):
    return {"id": kind, "kind": kind, "inputs": [input_id], "output": output, "parameters": parameters,
            "executor": builtin_executor(), "determinism": "deterministic"}


def test_select_rename_scale_preserve_original_order_missing_values_and_units():
    _, _, datasets = managed_example()
    selected, _ = execute_node(builtin("select", {"columns": ["column:1"]}), datasets)
    assert list(selected["columns"]) == ["column:1"]
    renamed, _ = execute_node(builtin("rename", {"columns": {"column:1": {"id": "signal", "label": "Measured signal"}}}, input_id="output"), {"output": selected})
    scaled, _ = execute_node(builtin("scale", {"columns": ["signal"], "factor": -2}, input_id="output"), {"output": renamed})
    assert scaled["columns"]["signal"] == {"label": "Measured signal", "unit": "V", "values": [-4, None, -8]}
    assert scaled["provenance"]["sources"] == datasets["A"]["provenance"]["sources"]
    assert [step["node_id"] for step in scaled["provenance"]["transforms"]] == ["select", "rename", "scale"]


@pytest.mark.parametrize("parameters", [
    {"columns": ["column:1"], "method": "constant", "constant": 0, "output_unit": "1"},
    {"columns": ["column:1"], "method": "max_abs", "constant": 1, "output_unit": "1"},
    {"columns": ["column:1"], "method": "first", "output_unit": "V"},
    {"columns": ["absent"], "method": "first", "output_unit": "1"},
])
def test_normalization_rejects_zero_implicit_units_and_invalid_parameter_mixtures(parameters):
    _, _, datasets = managed_example()
    with pytest.raises(DocumentError):
        execute_node(builtin("normalize", parameters), datasets)


def test_cycles_missing_inputs_and_output_overwrites_fail_before_execution():
    node = builtin("scale", {"columns": ["column:1"], "factor": 2})
    with pytest.raises(DocumentError):
        ordered_nodes([{**node, "inputs": ["output"]}], ["A"])
    with pytest.raises(DocumentError):
        ordered_nodes([{**node, "output": "A"}], ["A"])
    with pytest.raises(DocumentError):
        ordered_nodes([node, {**node, "id": "other"}], ["A"])


def test_normalization_divides_directly_without_overflowing_a_reciprocal():
    _, _, datasets = managed_example()
    datasets["A"]["columns"]["column:1"]["values"] = [1e-320, None, 1e-320]
    result, _ = execute_node(builtin("normalize", {"columns": ["column:1"], "method": "max_abs", "output_unit": "1"}), datasets)
    assert result["columns"]["column:1"]["values"] == [1, None, 1]


def test_builtin_code_identity_and_determinism_are_checked_before_work(monkeypatch):
    from sciplot_core.plot_transforms import execution

    _, _, datasets = managed_example()
    node = builtin("scale", {"columns": ["column:1"], "factor": 2})
    with pytest.raises(DocumentError) as error:
        execute_node({**node, "determinism": "non_deterministic"}, datasets)
    assert error.value.reason_code == "transform_nondeterministic_unsupported"
    monkeypatch.setattr(execution, "builtin_executor", lambda: {**node["executor"], "content_hash": "0" * 64})
    with pytest.raises(DocumentError) as error:
        execute_node(node, datasets)
    assert error.value.reason_code == "transform_executor_changed"


def test_cache_result_bytes_are_checked_and_hooks_separate_execution_from_reuse():
    resolved, raw = resolved_example()
    events = []
    result = resolve_transforms(resolved["document"], raw,
        before_execute=lambda node, key: events.append(("before", node["id"], key)),
        on_result=lambda key, value: events.append(("saved", value["id"], key)))
    assert [event[0] for event in events] == ["before", "saved", "before", "saved"]
    events.clear()
    repeated = resolve_transforms(resolved["document"], raw, cache=result["cache"],
        before_execute=lambda *args: events.append(args), on_result=lambda *args: events.append(args))
    assert not events and repeated["executed"] == []
    key = next(iter(result["cache"]))
    corrupt = deepcopy(result["cache"])
    corrupt[key]["columns"]["column:1"]["values"][0] = 9
    with pytest.raises(DocumentError) as error:
        resolve_transforms(resolved["document"], raw, cache=corrupt)
    assert error.value.reason_code == "transform_cache_corrupt"


def _external(tmp_path, multiplier=2):
    script = tmp_path / "fixed_transform.py"
    script.write_text('''import argparse,json
p=argparse.ArgumentParser(); p.add_argument('--request'); p.add_argument('--response'); a=p.parse_args()
with open(a.request) as f: r=json.load(f)
c=r['input']['columns']
for name in r['parameters']['columns']:
    c[name]['values']=[None if v is None else v * MULTIPLIER for v in c[name]['values']]
with open(a.response,'w') as f:
    json.dump({'kind':'sciplot_transform_response','schema_version':1,'request_sha256':r['request_sha256'],'columns':c},f)
'''.replace("MULTIPLIER", str(multiplier)))
    schema = {"type": "object", "properties": {"columns": {"type": "array", "items": {"type": "string"}}},
              "required": ["columns"], "additionalProperties": False}
    executor = ExternalExecutor(Path(sys.executable), script, schema)
    node = {"id": "external-A", "kind": "external", "inputs": ["A"], "output": "external-output",
            "parameters": {"columns": ["column:1"]}, "executor": executor.descriptor("fixed"), "determinism": "deterministic"}
    return executor, node


def test_same_filename_new_script_bytes_change_executor_output_and_cache_key(tmp_path):
    _, _, datasets = managed_example()
    executor, node = _external(tmp_path)
    registered = executor.to_dict("fixed")
    loaded = ExternalExecutor.from_dict(registered)
    first, key = execute_node(node, datasets, external_executors={"fixed": loaded})
    assert first["columns"]["column:1"]["values"] == [4, None, 8]
    previous_files = executor_files([node], {"fixed": loaded})
    changed, new_node = _external(tmp_path, 3)
    with pytest.raises(DocumentError) as error:
        execute_node(node, datasets, external_executors={"fixed": changed})
    assert error.value.reason_code == "transform_executor_changed"
    with pytest.raises(DocumentError):
        ExternalExecutor.from_dict(registered)
    second, new_key = execute_node(new_node, datasets, external_executors={"fixed": changed})
    assert new_key != key and new_node["executor"]["content_hash"] != node["executor"]["content_hash"]
    assert second["columns"]["column:1"]["values"] == [6, None, 12]
    assert previous_files[str(executor.script)] != executor_files([new_node], {"fixed": changed})[str(executor.script)]


def test_external_contract_rejects_source_snippets_and_undeclared_parameters(tmp_path):
    executor, node = _external(tmp_path)
    _, _, datasets = managed_example()
    with pytest.raises(DocumentError):
        validate_node({**node, "source_code": "print('unapproved')"})
    with pytest.raises(DocumentError):
        execute_node({**node, "parameters": {"code": "print('unapproved')"}}, datasets, external_executors={"fixed": executor})


def test_external_timeout_never_returns_or_reuses_an_uncertain_result(tmp_path):
    executor, node = _external(tmp_path)
    executor.script.write_text("import time\ntime.sleep(5)\n")
    executor = ExternalExecutor(executor.executable, executor.script, executor.parameter_schema, timeout_seconds=.05)
    node["executor"] = executor.descriptor("fixed")
    _, _, datasets = managed_example()
    with pytest.raises(DocumentError) as error:
        execute_node(node, datasets, external_executors={"fixed": executor})
    assert error.value.reason_code == "transform_external_timeout"


def test_raw_snapshot_cannot_silently_drop_rows_or_change_source_identity():
    resolved, raw = resolved_example()
    altered = deepcopy(raw)
    altered["A"]["provenance"]["sources"][0]["rows"] = [2, 4]
    with pytest.raises(DocumentError):
        resolve_transforms(resolved["document"], altered)
    changed = deepcopy(resolved["document"])
    changed["scientific"]["data_sources"][0]["sha256"] = "f" * 64
    with pytest.raises(DocumentError):
        resolve_transforms(seal_document(changed), raw)
