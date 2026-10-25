"""Only executor wire identity changes around the exact original v1 validator."""
from copy import deepcopy
from typing import Any

from . import schema as original
from .schema import BUILTIN_VERSION
from .wire import DIGEST, closed, validate_wire


def transform_schema() -> dict[str, Any]:
    schema = original.transform_schema()
    for variant in schema["oneOf"]:
        properties = variant["properties"]
        kind = properties["kind"]["const"]
        if kind != "external":
            properties["executor"] = {"oneOf": [properties["executor"], closed({
                "kind": {"const": "builtin"}, "operator": {"const": kind},
                "version": {"type": "string", "minLength": 1}, "content_hash": DIGEST})]}
    return schema


def _original_wire(node: dict[str, Any]) -> dict[str, Any]:
    projected = deepcopy(node)
    if node["kind"] != "external":
        projected["executor"] = {"kind": "builtin", "version": BUILTIN_VERSION,
                                 "content_hash": node["executor"]["content_hash"]}
    return projected


def validate_node(value: Any) -> dict[str, Any]:
    validate_wire(value, transform_schema(), code="transform_node_invalid")
    assert isinstance(value, dict)
    checked = original.validate_node(_original_wire(value))
    checked["executor"] = deepcopy(value["executor"])
    return checked


def ordered_nodes(nodes: list[dict[str, Any]], source_ids: list[str]) -> list[dict[str, Any]]:
    checked = [validate_node(node) for node in nodes]
    ordered = original.ordered_nodes([_original_wire(node) for node in checked], source_ids)
    by_id = {node["id"]: node for node in checked}
    return [by_id[node["id"]] for node in ordered]
