"""Frozen v1 dataset admission, cache keys and execution provenance."""
from collections.abc import Callable
from copy import deepcopy
from typing import Any

from .datasets import dataset_hash, numeric_hash, validate_dataset
from .hashing import canonical_json_sha256
from .node_contract import validate_node


def execute(node: dict[str, Any], inputs: list[dict[str, Any]], operation: Callable[..., Any], *,
            multiple_inputs: bool) -> tuple[dict[str, Any], str]:
    node = validate_node(node)
    sources = [validate_dataset(value) for value in inputs]
    input_hashes = [dataset_hash(value) for value in sources]
    key = canonical_json_sha256({"node": node, "inputs": input_hashes}, allow_nan=False)
    result, details = operation(node, sources if multiple_inputs else sources[0])
    return record_result(node, result, details, input_hashes, key), key


def record_result(node: dict[str, Any], result: dict[str, Any], details: dict[str, Any],
                  input_hashes: list[str], key: str) -> dict[str, Any]:
    result["provenance"] = deepcopy(result["provenance"])
    result["provenance"]["transforms"].append({"node_id": node["id"], "cache_key": key,
        "executor_hash": canonical_json_sha256(node["executor"], allow_nan=False), "input_hashes": input_hashes,
        "output_hash": numeric_hash(result), "parameters": deepcopy(node["parameters"]), "details": details})
    return validate_dataset(result)
