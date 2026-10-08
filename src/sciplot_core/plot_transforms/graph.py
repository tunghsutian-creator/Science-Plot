"""Per-source and per-transform dependencies, without renderer metadata."""

from typing import Any

from sciplot_core.plot_document.dependency import validate_dependency_graph

from .datasets import dataset_hash
from .schema import ordered_nodes


def dependency_graph(document: dict[str, Any], datasets: dict[str, dict[str, Any]]) -> dict[str, Any]:
    sources = document["scientific"]["data_sources"]
    owners = {source["source_id"]: "source:" + source["source_id"] for source in sources}
    nodes = [{"id": owners[source["source_id"]], "kind": "source", "dependencies": [],
              "parameters": {"source_sha256": source["sha256"], "table_selection": source["table_selection"]},
              "version": "source-snapshot-1", "content_hash": dataset_hash(datasets[source["source_id"]])}
             for source in sources]
    for node in ordered_nodes(document["scientific"]["transforms"], list(owners)):
        identifier = "transform:" + node["id"]
        nodes.append({"id": identifier, "kind": "transform", "dependencies": [owners[name] for name in node["inputs"]],
                      "parameters": node, "version": "typed-transform-1", "content_hash": dataset_hash(datasets[node["output"]])})
        owners[node["output"]] = identifier
    mappings = []
    for identifier, mapping in document["scientific"]["mappings"].items():
        name = "mapping:" + identifier
        nodes.append({"id": name, "kind": "mapping", "dependencies": list(dict.fromkeys(owners[mapping[axis]["source_id"]] for axis in ("x", "y"))),
                      "parameters": mapping, "version": "xy-mapping-1"})
        mappings.append(name)
    compile_parameters = {"presentation_hash": document["presentation_hash"]}
    if "figure_spec" in document["scientific"]["provenance"]:
        compile_parameters["scientific_hash"] = document["scientific_hash"]
    nodes.append({"id": "compile", "kind": "compile", "dependencies": mappings,
                  "parameters": compile_parameters, "version": "semantic-compiler-1"})
    nodes.append({"id": "render", "kind": "render", "dependencies": ["compile"], "parameters": {}, "version": "render-input-1"})
    nodes.append({"id": "export", "kind": "export", "dependencies": ["render"],
                  "parameters": document["presentation"]["export_configuration"], "version": "export-input-1"})
    return validate_dependency_graph({"kind": "sciplot_dependency_graph", "schema_version": 1, "nodes": nodes})
