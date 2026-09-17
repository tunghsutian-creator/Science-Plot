"""Factor repeated JSON Schema nodes into local definitions without loosening them."""

from collections import Counter
from copy import deepcopy
import json
from typing import Any

from sciplot_core.foundation.json_hashing import canonical_json_sha256


def compact_schema(schema: dict[str, Any]) -> dict[str, Any]:
    """Return a standalone schema; references resolve at this returned root."""
    counts: Counter[str] = Counter()
    nodes: dict[str, dict[str, Any]] = {}

    def children(node: dict[str, Any], visit: Any) -> dict[str, Any]:
        result = deepcopy(node)
        for key in ("properties", "patternProperties", "dependentSchemas", "$defs"):
            if isinstance(node.get(key), dict):
                result[key] = {name: visit(value) if isinstance(value, dict) else value
                               for name, value in node[key].items()}
        for key in ("oneOf", "anyOf", "allOf", "prefixItems"):
            if isinstance(node.get(key), list):
                result[key] = [visit(value) if isinstance(value, dict) else value for value in node[key]]
        for key in ("items", "additionalProperties", "contains", "not", "if", "then", "else", "propertyNames"):
            if isinstance(node.get(key), dict):
                result[key] = visit(node[key])
        return result

    def count(node: dict[str, Any]) -> dict[str, Any]:
        digest = canonical_json_sha256(node)
        counts[digest] += 1
        nodes[digest] = node
        children(node, count)
        return node

    count(schema)
    definitions: dict[str, Any] = {}
    names: dict[str, str] = {}
    reserved = set(schema.get("$defs", {}))

    def definition_name(digest: str) -> str:
        if digest not in names:
            index = len(names)
            while f"s{index}" in reserved:
                index += 1
            names[digest] = f"s{index}"
            reserved.add(names[digest])
        return names[digest]

    def render(node: dict[str, Any]) -> dict[str, Any]:
        digest = canonical_json_sha256(node)
        # Small nodes cost less in place than a reference and its definition.
        if counts[digest] > 1 and len(str(nodes[digest])) >= 128:
            # These names are local references, not scientific identities.
            # Keep complete digests internally, but do not repeat them on wire.
            name = definition_name(digest)
            if name not in definitions:
                definitions[name] = children(node, render)
            return {"$ref": f"#/$defs/{name}"}
        return children(node, render)

    result = children(schema, render)
    if definitions:
        result["$defs"] = {**result.get("$defs", {}), **definitions}
    if len(json.dumps(result, ensure_ascii=False)) >= len(json.dumps(schema, ensure_ascii=False)):
        return deepcopy(schema)
    return result
