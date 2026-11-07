"""Content-addressed dependency planning; this module never executes transforms."""

from copy import deepcopy
from typing import Any

from sciplot_core.foundation.json_hashing import canonical_json_sha256

from .errors import fail
from .schema import DIGEST, IDENTIFIER, closed
from .validation import validate_wire


def dependency_schema() -> dict[str, Any]:
    node = closed({
        "id": IDENTIFIER,
        "kind": {"enum": ["source", "transform", "fit", "mapping", "compile", "render", "export"]},
        "dependencies": {"type": "array", "uniqueItems": True, "items": IDENTIFIER},
        "parameters": {"type": "object"}, "version": {"type": "string", "minLength": 1},
        "content_hash": DIGEST,
    }, ["id", "kind", "dependencies", "parameters", "version"])
    return closed({"kind": {"const": "sciplot_dependency_graph"}, "schema_version": {"const": 1},
                   "nodes": {"type": "array", "maxItems": 1000, "items": node}})


def _ordered(graph: dict[str, Any]) -> list[dict[str, Any]]:
    nodes = {node["id"]: node for node in graph["nodes"]}
    if len(nodes) != len(graph["nodes"]):
        fail("document_dependency_duplicate", "Dependency node IDs must be unique.", "/nodes", "unique_ids")
    for index, node in enumerate(graph["nodes"]):
        unknown = [name for name in node["dependencies"] if name not in nodes]
        if unknown:
            fail("document_dependency_missing", "Every dependency must reference an existing node.",
                 f"/nodes/{index}/dependencies", "node_reference", unknown=unknown)
        if node["kind"] == "source" and ("content_hash" not in node or node["dependencies"]):
            fail("document_dependency_source", "A source needs a content hash and cannot have upstream nodes.",
                 f"/nodes/{index}", "source_hash")
    ordered: list[dict[str, Any]] = []
    done: set[str] = set()
    while len(done) < len(nodes):
        ready = [node for name, node in nodes.items() if name not in done
                 and all(dep in done for dep in node["dependencies"])]
        if not ready:
            fail("document_dependency_cycle", "A dependency graph must be acyclic.", "/nodes", "acyclic",
                 blocked=[name for name in nodes if name not in done])
        ordered.extend(ready)
        done.update(node["id"] for node in ready)
    return ordered


def validate_dependency_graph(graph: Any) -> dict[str, Any]:
    validate_wire(graph, dependency_schema(), code="document_invalid_dependency_graph")
    assert isinstance(graph, dict)
    _ordered(graph)
    return deepcopy(graph)


def build_keys(graph: Any) -> dict[str, str]:
    """Bind parameters, implementation versions and every ordered upstream content key."""
    checked = validate_dependency_graph(graph)
    keys: dict[str, str] = {}
    for node in _ordered(checked):
        projection = {key: value for key, value in node.items() if key not in {"id", "dependencies"}}
        projection["upstream"] = [{"id": dep, "key": keys[dep]} for dep in node["dependencies"]]
        keys[node["id"]] = canonical_json_sha256(projection, allow_nan=False)
    return keys


def invalidated_nodes(graph: Any, changed_ids: list[str]) -> list[str]:
    """Return changed nodes and their descendants, in execution order."""
    checked = validate_dependency_graph(graph)
    names = {node["id"] for node in checked["nodes"]}
    if any(name not in names for name in changed_ids):
        fail("document_dependency_missing", "An invalidation must name existing nodes.", "/changed_ids", "node_reference")
    dirty = set(changed_ids)
    result: list[str] = []
    for node in _ordered(checked):
        if node["id"] in dirty or any(dep in dirty for dep in node["dependencies"]):
            dirty.add(node["id"])
            result.append(node["id"])
    return result


def artifact_build_key(*, scientific_hash: str, presentation_hash: str,
                       backend_versions: dict[str, str], export_configuration: dict[str, Any],
                       fonts: dict[str, str]) -> str:
    """A reproducibility/cache key, deliberately distinct from output byte hashes."""
    value = {"scientific_hash": scientific_hash, "presentation_hash": presentation_hash,
             "backend_versions": backend_versions, "export_configuration": export_configuration, "fonts": fonts}
    validate_wire(value, closed({
        "scientific_hash": DIGEST, "presentation_hash": DIGEST,
        "backend_versions": {"type": "object", "minProperties": 1,
                             "additionalProperties": {"type": "string", "minLength": 1}},
        "export_configuration": {"type": "object"},
        "fonts": {"type": "object", "additionalProperties": {"type": "string", "minLength": 1}},
    }), code="document_invalid_build_key")
    return canonical_json_sha256(value, allow_nan=False)
