"""Current transform wire; regular historical graphs use their original validator."""
from copy import deepcopy
from typing import Any

from sciplot_core.plot_document.errors import fail

from .versions.v1 import node_contract as historical
from .versions.v1.schema import BUILTIN_VERSION
from .versions.v1.wire import DIGEST, IDENTIFIER, closed, validate_wire

EXACT_X_MEAN = "rheology_mean_exact_x"
FREQUENCY_COMPLETE = "rheology_frequency_complete"


def _current_schema(kind: str) -> dict[str, Any]:
    params = ({"x_column": IDENTIFIER} if kind == EXACT_X_MEAN else
              {"derivations": {"type": "array", "uniqueItems": True,
                               "items": {"enum": ["complex_modulus", "complex_viscosity"]}}})
    inputs = {"type": "array", "minItems": 2, "uniqueItems": True, "items": IDENTIFIER} if kind == EXACT_X_MEAN else {
        "type": "array", "minItems": 1, "maxItems": 1, "items": IDENTIFIER}
    return closed({"id": IDENTIFIER, "kind": {"const": kind}, "inputs": inputs,
                   "output": IDENTIFIER, "parameters": closed(params),
                   "executor": closed({"kind": {"const": "builtin"}, "operator": {"const": kind},
                                       "version": {"const": "1"}, "content_hash": DIGEST}),
                   "determinism": {"const": "deterministic"}})


def transform_schema() -> dict[str, Any]:
    schema = historical.transform_schema()
    schema["oneOf"].extend(_current_schema(kind) for kind in (EXACT_X_MEAN, FREQUENCY_COMPLETE))
    return schema


def _is_current(node: Any) -> bool:
    return isinstance(node, dict) and node.get("kind") in (EXACT_X_MEAN, FREQUENCY_COMPLETE)


def validate_node(value: Any) -> dict[str, Any]:
    if not _is_current(value):
        return historical.validate_node(value)
    validate_wire(value, _current_schema(value["kind"]), code="transform_node_invalid")
    return deepcopy(value)


def ordered_nodes(nodes: list[dict[str, Any]], source_ids: list[str]) -> list[dict[str, Any]]:
    if not any(_is_current(node) for node in nodes):
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
