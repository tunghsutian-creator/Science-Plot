"""Lower one explicitly selected independent curve to the existing source revision."""
from pathlib import Path
from typing import Any

from sciplot_core.data_mapping.table_choice import select_table
from sciplot_core.plot_engine.append_target_lineage import coordinate_origin
from sciplot_core.plot_engine.content_store import resolve_document_content
from sciplot_core.plot_engine.managed_source_groups import source_groups
from sciplot_core.plot_engine.managed_source_revision import source_value
from sciplot_core.plot_engine.managed_sources import load_source_facts
from sciplot_core.plot_ir.figure_document import figure_spec
from sciplot_core.plot_transforms import ordered_nodes

from .errors import EngineError


def _original_pair(document: dict[str, Any], layer: dict[str, Any], mapping: dict[str, Any],
                   facts: dict[str, Any]) -> tuple[dict[str, Any], dict[str, int]]:
    origins = {}
    for axis in ("x", "y"):
        ref = mapping[axis]
        column = f"column:{ref['column_index']}" if "column_index" in ref else ref["column"]
        origins[axis] = coordinate_origin(document, ref["source_id"], column, mapping[axis + "_unit"],
            quantity=layer["mapping_semantics"][axis], column_facts=facts, explicit_quantity_binding=True)
    source = origins["x"][0]
    if origins["y"][0]["source_id"] != source["source_id"]:
        raise EngineError("project_file_series_source_shared", "The selected X and Y must share one independent original source.")
    return source, {axis: value[1] for axis, value in origins.items()}


def _require_exclusive(document: dict[str, Any], layer_id: str, source_id: str) -> None:
    science = document["scientific"]
    ancestors = {source["source_id"]: {source["source_id"]} for source in science["data_sources"]}
    for node in ordered_nodes(science["transforms"], list(ancestors)):
        ancestors[node["output"]] = set().union(*(ancestors[name] for name in node["inputs"]))
    users = [identifier for identifier, mapping in science["mappings"].items()
             if any(source_id in ancestors[mapping[axis]["source_id"]] for axis in ("x", "y"))]
    if users != [layer_id] or any(node["kind"] == "external" and source_id in ancestors[node["output"]]
                                    for node in science["transforms"]):
        raise EngineError("project_file_series_source_shared",
                          "This original source is not exclusive to the selected curve. No other curve was changed.",
                          series_ids=users)


def replacement_change(request: dict[str, Any], document: dict[str, Any], root: Path,
                       snapshot: dict[str, Any], selection: dict[str, Any]) -> dict[str, Any]:
    """Build a complete same-layout source revision; no new scientific selection is inferred."""
    document = resolve_document_content(root, document)
    identifier = request["replace_layer"]
    layers = {layer["id"]: layer for view in figure_spec(document)["views"] for layer in view["layers"]}
    if identifier not in layers:
        raise EngineError("project_file_series_layer_not_found", "Choose one exact current curve ID, not a display title.",
                          action="select_series", series_ids=list(layers))
    facts = load_source_facts(document, "ordinary_xy")
    mapping = document["scientific"]["mappings"][identifier]
    source, columns = _original_pair(document, layers[identifier], mapping, facts)
    source_id = source["source_id"]
    if any(len(group) != 1 for group in source_groups(document).values()
           if any(item["source_id"] == source_id for item in group)):
        raise EngineError("project_file_series_source_shared", "The original file supplies other bound observations in this figure.")
    _require_exclusive(document, identifier, source_id)
    if columns != {axis: request[axis + "_column"] for axis in ("x", "y")} or selection != source["table_selection"]:
        raise EngineError("project_file_series_relayout_unsupported",
                          "Choose the same exact original worksheet, physical columns and row region. A layout remap is not a source revision.",
                          expected_selection=source["table_selection"], expected_columns=columns)
    if source.get("metadata_confirmations"):
        raise EngineError("managed_source_reconfirmation_required", "The original has individually confirmed metadata; use explicit scientific source reconfirmation.")
    replacement = select_table(snapshot, selection)
    old_facts = facts[source_id]
    new_facts = {column["index"]: column for column in replacement["columns"]}
    for index in columns.values():
        observed = new_facts[index]
        if (observed["metadata_conflicts"]
                or observed["raw_metadata"] != old_facts[f"column:{index}"]["raw_metadata"]):
            raise EngineError("managed_source_reconfirmation_required",
                              "The new original column metadata differs. Explicitly reconfirm the scientific source before replacing it.",
                              column_index=index)
    target = "source:" + source_id
    value = source_value(document, target)
    value.update(replacement_path=request["source"], sha256=snapshot["file_sha256"])
    for item in value["unit_context_bindings"]:
        item.update(source_path=request["source"], source_sha256=value["sha256"])
    return {"op": "set", "target": [target], "property": "source.sha256", "value": value}
