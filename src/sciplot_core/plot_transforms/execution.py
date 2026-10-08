"""Typed content-addressed transforms with explicit executor and output evidence."""

from copy import deepcopy
from collections.abc import Callable
from typing import Any

from sciplot_core.foundation.json_hashing import canonical_json_sha256
from sciplot_core.plot_document import seal_document, validate_document
from sciplot_core.plot_document.errors import fail

from .builtins import run_builtin
from .datasets import dataset_hash, numeric_hash, validate_dataset
from .external import ExternalExecutor, executor_files, run_external
from .schema import ordered_nodes, validate_node
from .identity import builtin_executor, require_builtin_runtime_current


def digest(value: Any) -> str:
    return canonical_json_sha256(value, allow_nan=False)


def execute_node(node: Any, inputs: dict[str, dict[str, Any]], *,
                 external_executors: dict[str, ExternalExecutor] | None = None) -> tuple[dict[str, Any], str]:
    node = validate_node(node)
    if node["determinism"] != "deterministic":
        fail("transform_nondeterministic_unsupported", "Non-deterministic execution requires durable output adoption; automatic scientific recomputation is disabled.", "/determinism", "deterministic_execution")
    if node["kind"] != "external" and node["executor"] != builtin_executor():
        fail("transform_executor_changed", "Builtin executor bytes changed; bind the current registered implementation.", "/executor", "exact_executor_identity")
    if node["kind"] != "external":
        require_builtin_runtime_current()
    if node["inputs"][0] not in inputs:
        fail("transform_input_missing", "The named input dataset has not been resolved.", "/inputs", "existing_dataset")
    source = validate_dataset(inputs[node["inputs"][0]])
    input_hashes = [dataset_hash(source)]
    key = digest({"node": node, "inputs": input_hashes})
    if node["kind"] == "external":
        result, details = run_external(node, source, external_executors or {})
    else:
        result, details = run_builtin(node, source)
    result["provenance"] = deepcopy(source["provenance"])
    result["provenance"]["transforms"].append({"node_id": node["id"], "cache_key": key,
        "executor_hash": digest(node["executor"]), "input_hashes": input_hashes,
        "output_hash": numeric_hash(result), "parameters": deepcopy(node["parameters"]), "details": details})
    return validate_dataset(result), key


def resolve_transforms(document: Any, datasets: dict[str, dict[str, Any]], *,
                       cache: dict[str, dict[str, Any]] | None = None,
                       external_executors: dict[str, ExternalExecutor] | None = None,
                       before_execute: Callable[[dict[str, Any], str], None] | None = None,
                       on_result: Callable[[str, dict[str, Any]], None] | None = None) -> dict[str, Any]:
    document = validate_document(document)
    sources = document["scientific"]["data_sources"]
    source_ids = [source["source_id"] for source in sources]
    if set(datasets) != set(source_ids):
        fail("transform_source_binding", "Supply exactly the bound original table snapshots.", "/datasets", "source_membership")
    values = {name: validate_dataset(value) for name, value in datasets.items()}
    for source in sources:
        dataset = values[source["source_id"]]
        evidence = dataset["provenance"]["sources"]
        if (dataset["id"] != source["source_id"] or dataset["provenance"]["transforms"] or len(evidence) != 1
                or evidence[0]["source_id"] != source["source_id"] or evidence[0]["sha256"] != source["sha256"]
                or evidence[0]["table_selection"] != source["table_selection"]):
            fail("transform_source_binding", "Snapshot provenance does not match its exact raw source binding.", "/datasets", "exact_source_identity")
        selection = source["table_selection"]
        rows = list(range(selection["data_start_row"], selection["data_end_row"]))
        if (evidence[0]["rows"] != rows or set(evidence[0]["column_indices"]) != set(dataset["columns"])
                or any(len(column["values"]) != len(rows) for column in dataset["columns"].values())
                or any(name != "column:" + str(index) for name, index in evidence[0]["column_indices"].items())):
            fail("transform_source_region", "Snapshot columns and rows must preserve the explicit original table region.", "/datasets", "original_region")
    nodes = ordered_nodes(document["scientific"]["transforms"], source_ids)
    executor_files(nodes, external_executors or {})
    saved, executed, reused = deepcopy(cache or {}), [], []
    records = []
    for node in nodes:
        if node["determinism"] != "deterministic" or node["kind"] != "external" and node["executor"] != builtin_executor():
            fail("transform_executor_changed", "Transform determinism or registered implementation cannot be reused.", "/transforms", "current_deterministic_executor")
        key = digest({"node": node, "inputs": [dataset_hash(values[name]) for name in node["inputs"]]})
        candidate = saved.get(key)
        if candidate is not None:
            candidate = validate_dataset(candidate)
            history = candidate["provenance"]["transforms"]
            if (candidate["id"] != node["output"] or not history or history[-1]["cache_key"] != key
                    or history[-1]["output_hash"] != numeric_hash(candidate)):
                fail("transform_cache_corrupt", "Cached transform bytes do not match their execution seal.", "/cache", "content_hash")
            reused.append(node["id"])
        else:
            if before_execute is not None:
                before_execute(deepcopy(node), key)
            candidate, actual = execute_node(node, values, external_executors=external_executors)
            assert actual == key
            saved[key] = candidate
            if on_result is not None:
                on_result(key, deepcopy(candidate))
            executed.append(node["id"])
        values[node["output"]] = candidate
        records.append({"node_id": node["id"], "status": "complete", "determinism": node["determinism"],
                        "cache_key": key, "output_dataset": node["output"], "content_hash": dataset_hash(candidate),
                        "executor": deepcopy(node["executor"]), "input_hashes": [dataset_hash(values[name]) for name in node["inputs"]]})
    document["scientific"]["provenance"]["datasets"] = deepcopy(values)
    document["scientific"]["provenance"]["transform_execution"] = records
    document = seal_document(document)
    from .graph import dependency_graph

    return {"document": document, "datasets": values, "cache": saved, "executed": executed,
            "reused": reused, "graph": dependency_graph(document, values)}
