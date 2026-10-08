"""Closed typed transform nodes; executable source text is never a wire field."""

from copy import deepcopy
from typing import Any

from sciplot_core.plot_document.errors import fail
from sciplot_core.plot_document.schema import DIGEST, IDENTIFIER, closed
from sciplot_core.plot_document.validation import validate_wire

BUILTIN_VERSION = "sciplot-column-transforms-1"


def transform_schema() -> dict[str, Any]:
    columns = {"type": "array", "minItems": 1, "uniqueItems": True, "items": IDENTIFIER}
    parameters = {
        "select": closed({"columns": columns}),
        "rename": closed({"columns": {"type": "object", "minProperties": 1, "propertyNames": IDENTIFIER,
            "additionalProperties": closed({"id": IDENTIFIER, "label": {"type": "string"}})}}),
        "scale": closed({"columns": columns, "factor": {"type": "number"}}),
        "normalize": closed({"columns": columns, "method": {"enum": ["max_abs", "first", "constant"]},
                             "constant": {"type": "number"}, "output_unit": {"const": "1"}},
                            ["columns", "method", "output_unit"]),
        "external": {"type": "object"},
    }
    variants = []
    for kind, params in parameters.items():
        executor = (closed({"kind": {"const": "external"}, "id": IDENTIFIER,
                            "version": {"type": "string", "minLength": 1}, "content_hash": DIGEST,
                            "side_effect_free": {"const": True},
                            "executable_sha256": DIGEST, "script_sha256": DIGEST,
                            "parameter_schema_sha256": DIGEST,
                            "protocol_version": {"const": 1}}) if kind == "external" else
                    closed({"kind": {"const": "builtin"}, "version": {"const": BUILTIN_VERSION}, "content_hash": DIGEST}))
        variants.append(closed({"id": IDENTIFIER, "kind": {"const": kind},
            "inputs": {"type": "array", "minItems": 1, "maxItems": 1, "items": IDENTIFIER},
            "output": IDENTIFIER, "parameters": params, "executor": executor,
            "determinism": {"enum": ["deterministic", "non_deterministic"]}}))
    return {"oneOf": variants}


def validate_node(value: Any) -> dict[str, Any]:
    validate_wire(value, transform_schema(), code="transform_node_invalid")
    assert isinstance(value, dict)
    if value["kind"] == "normalize":
        if (value["parameters"]["method"] == "constant") != ("constant" in value["parameters"]):
            fail("transform_parameter_conflict", "Only constant normalization requires an explicit constant.",
                 "/parameters", "method_parameters")
    return deepcopy(value)


def ordered_nodes(nodes: list[dict[str, Any]], source_ids: list[str]) -> list[dict[str, Any]]:
    checked = [validate_node(node) for node in nodes]
    ids, outputs = [node["id"] for node in checked], [node["output"] for node in checked]
    if len(ids) != len(set(ids)) or len(outputs) != len(set(outputs)) or set(outputs) & set(source_ids):
        fail("transform_duplicate_identity", "Transform IDs and output dataset IDs must be unique and cannot overwrite sources.", "/transforms", "unique_ids")
    known = set(source_ids)
    ordered = []
    remaining = checked.copy()
    while remaining:
        ready = [node for node in remaining if set(node["inputs"]) <= known]
        if not ready:
            fail("transform_dependency_invalid", "Transform inputs must exist in an acyclic dependency graph.", "/transforms", "acyclic_existing_inputs")
        for node in ready:
            ordered.append(node)
            known.add(node["output"])
            remaining.remove(node)
    return ordered
