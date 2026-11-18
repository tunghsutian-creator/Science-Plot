"""Current transform wire; regular historical graphs use their original validator."""
from copy import deepcopy
from typing import Any

from sciplot_core.plot_document.errors import fail

from .versions.v1 import node_contract as historical
from .versions.v1.schema import BUILTIN_VERSION
from .versions.v1.wire import DIGEST, IDENTIFIER, closed, validate_wire

EXACT_X_MEAN = "rheology_mean_exact_x"


def _mean_schema() -> dict[str, Any]:
    return closed({"id": IDENTIFIER, "kind": {"const": EXACT_X_MEAN},
                   "inputs": {"type": "array", "minItems": 2, "uniqueItems": True, "items": IDENTIFIER},
                   "output": IDENTIFIER, "parameters": closed({"x_column": IDENTIFIER}),
                   "executor": closed({"kind": {"const": "builtin"}, "operator": {"const": EXACT_X_MEAN},
                                       "version": {"const": "1"}, "content_hash": DIGEST}),
                   "determinism": {"const": "deterministic"}})


def transform_schema() -> dict[str, Any]:
    schema = historical.transform_schema()
    schema["oneOf"].append(_mean_schema())
    return schema


def _is_mean(node: Any) -> bool:
    return isinstance(node, dict) and node.get("kind") == EXACT_X_MEAN


def validate_node(value: Any) -> dict[str, Any]:
    if not _is_mean(value):
        return historical.validate_node(value)
    validate_wire(value, _mean_schema(), code="transform_node_invalid")
    return deepcopy(value)


def ordered_nodes(nodes: list[dict[str, Any]], source_ids: list[str]) -> list[dict[str, Any]]:
    if not any(_is_mean(node) for node in nodes):
        return historical.ordered_nodes(nodes, source_ids)
    remaining = [validate_node(node) for node in nodes]
    known = set(source_ids)
    for field in ("id", "output"):
        identities = [node[field] for node in remaining]
        if len(set(identities)) != len(identities) or (field == "output" and known.intersection(identities)):
            fail("transform_duplicate_identity", "Transform identities cannot repeat or overwrite a source.",
                 "/transforms", "unique_ids")
    ordered = []
    while remaining:
        ready = [node for node in remaining if set(node["inputs"]) <= known]
        if not ready:
            fail("transform_dependency_invalid", "Transform inputs must exist in an acyclic dependency graph.",
                 "/transforms", "acyclic_existing_inputs")
        ordered.extend(ready)
        known.update(node["output"] for node in ready)
        remaining = [node for node in remaining if node["output"] not in known]
    return ordered


__all__ = ["BUILTIN_VERSION", "ordered_nodes", "transform_schema", "validate_node"]
