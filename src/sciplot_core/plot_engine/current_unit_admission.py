"""Admit a new scientific request using the original column's unit evidence."""

from pathlib import Path
from typing import Any

from sciplot_core.plot_ir.figure_document import figure_spec, is_figure
from sciplot_core.plot_transforms import ordered_nodes
from sciplot_core.plot_transforms.unit_relations import requires_unit_context
from sciplot_core.source_tables.read_session import with_table_reads

from .content_store import resolve_document_content, resolve_provenance_value
from .errors import EngineError
from .managed_state import require_inputs
from .managed_sources import load_sources
from .original_coordinate import coordinate_origins


@with_table_reads
def prepare_current_update(root: Path, document: dict[str, Any], request: dict[str, Any]) -> tuple[dict[str, Any], list[dict[str, Any]], str, bool]:
    """Prepare an actual current diff before admitting its scientific closure."""
    from .managed_updates import prepare_update

    before = resolve_document_content(root, document) if any(
        change["property"] == "source.append" for change in request["changes"]) else document
    datasets = None
    if is_figure(before) and any(change["property"] in {"scale.domain", "axis.ticks", "series.visible"}
                                 for change in request["changes"]):
        from sciplot_core.plot_grammar.current_view import is_current_view

        if is_current_view(figure_spec(before)):
            datasets = resolve_provenance_value(root, before, "datasets")
    result, diff, risk, scientific = prepare_update(before, request, root=root, datasets=datasets)
    if scientific and diff:
        admit_current_units(root, result, previous=document)
    return result, diff, risk, scientific


def _source_identity(source: dict[str, Any]) -> tuple[Any, ...]:
    return source.get("path"), source.get("sha256"), source.get("table_selection")


def admit_current_units(root: Path, document: dict[str, Any], *, previous: dict[str, Any] | None = None) -> None:
    """Validate before a new journal/reservation; never reinterpret saved replay.

    Figure mapping semantics plus their finite original-column binding are an
    explicit scientific user fact. An unchanged old mapping cannot reconfirm
    an unknown quantity after its original source identity changes.
    """
    document = resolve_document_content(root, document)
    require_inputs(document)
    science = document["scientific"]
    facts: dict[str, dict[str, Any]] = {}
    frames: dict[str, Any] = {}
    datasets = load_sources(document, science["provenance"]["managed"]["rule_id"], column_facts=facts, source_frames=frames)
    if previous is not None:
        from .managed_source_revision import validate_reconfirmed_contexts

        validate_reconfirmed_contexts(document, previous, datasets=datasets, column_facts=facts,
                                      source_frames=frames, root=root)
    ambiguous = {identifier for identifier, columns in facts.items()
                 if any(requires_unit_context(item["unit"], item["raw_metadata"]["unit"]) for item in columns.values())}
    ancestors = {source["source_id"]: {source["source_id"]} for source in science["data_sources"]}
    nodes = ordered_nodes(science["transforms"], list(ancestors))
    for node in nodes:
        ancestors[node["output"]] = set().union(*(ancestors[name] for name in node["inputs"]))
    old_sources = {source["source_id"]: source for source in previous["scientific"]["data_sources"]} if previous else {}
    binding_sources = {source["source_id"] for source in science["data_sources"]
                       if source["source_id"] not in old_sources
                       or _source_identity(source) == _source_identity(old_sources[source["source_id"]])}
    semantics = {layer["id"]: layer["mapping_semantics"] for view in figure_spec(document)["views"]
                 for layer in view["layers"]} if is_figure(document) else {}
    bindings: dict[tuple[str, str], str] = {}
    for identifier, mapping in science["mappings"].items():
        for axis in ("x", "y"):
            coordinate, unit = mapping[axis], mapping[axis + "_unit"]
            dataset = coordinate["source_id"]
            if not (requires_unit_context(unit, unit) or unit == "K" and ancestors[dataset] & ambiguous):
                continue
            column = "column:" + str(coordinate["column_index"]) if "column_index" in coordinate else coordinate["column"]
            quantity = semantics.get(identifier, {}).get(axis)
            origins = coordinate_origins(document, dataset, column, unit, quantity=quantity, datasets=datasets,
                                         column_facts=facts, explicit_quantity_binding=quantity is not None,
                                         binding_sources=binding_sources)
            for source, index, _start, _end, _context, _operations in origins:
                if quantity is None or source["source_id"] not in binding_sources:
                    continue
                key = source["source_id"], "column:" + str(index)
                if key in bindings and bindings[key] != quantity:
                    raise EngineError("managed_unit_quantity_conflict", "One original column cannot acquire conflicting scientific quantities.")
                bindings[key] = quantity
    for identifier, dataset in datasets.items():
        for column, values in dataset["columns"].items():
            original = facts[identifier][column]["raw_metadata"]["unit"]
            if original != values["unit"] and requires_unit_context(original, values["unit"]):
                coordinate_origins(document, identifier, column, values["unit"], datasets=datasets,
                                   column_facts=facts, bound_quantities=bindings)
    # Resolve every affected executed column, including columns absent from all
    # visible mappings. A fixed external or derived output has no implicit unit
    # lineage and must be refused rather than silently exempted.
    for node in nodes:
        if node["kind"] != "convert_unit":
            continue
        parameters = node["parameters"]
        if not (requires_unit_context(parameters["from_unit"], parameters["to_unit"])
                or ancestors[node["output"]] & ambiguous and "K" in {parameters["from_unit"], parameters["to_unit"]}):
            continue
        for column in parameters["columns"]:
            coordinate_origins(document, node["output"], column, parameters["to_unit"], datasets=datasets,
                               column_facts=facts, bound_quantities=bindings)
