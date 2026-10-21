"""Append original XY table bindings through the existing Managed transaction."""

from copy import deepcopy
from pathlib import Path
from typing import Any, NoReturn

from sciplot_core.data_mapping.original_tables import source_table_snapshot
from sciplot_core.data_mapping.table_choice import select_table
from sciplot_core.foundation.file_hashing import file_sha256
from sciplot_core.foundation.json_hashing import canonical_json_sha256
from sciplot_core.plot_document.schema import IDENTIFIER, closed
from sciplot_core.plot_document.templates import binding_schema
from sciplot_core.plot_document.validation import validate_wire
from sciplot_core.plot_ir.figure_document import figure_spec, is_figure, store_spec
from sciplot_core.plot_transforms import builtin_executor
from sciplot_core.plot_transforms.unit_relations import requires_unit_context, resolve_unit_relation
from sciplot_core.source_tables.read_session import with_table_reads

from .append_target_lineage import coordinate_origin
from .append_source_regions import append_source_candidates, confirm_append_region
from .errors import EngineError
from .content_store import resolve_provenance_value
from .managed_sources import load_source_facts


def append_schema() -> dict[str, Any]:
    source = binding_schema()["properties"]["data_sources"]["items"]
    source["required"].append("table_selection")
    source["properties"]["path"]["pattern"] = "^/"
    curve = closed({"sample": {"type": "string", "minLength": 1, "maxLength": 4096, "pattern": r"\S"},
        "x_column_index": {"type": "integer", "minimum": 0},
        "y_column_index": {"type": "integer", "minimum": 0},
        "x_quantity": {"type": "string", "minLength": 1, "maxLength": 128},
        "y_quantity": {"type": "string", "minLength": 1, "maxLength": 128},
        "x_unit": {"type": "string", "minLength": 1, "maxLength": 128},
        "y_unit": {"type": "string", "minLength": 1, "maxLength": 128},
        "label": {"type": "string", "minLength": 1, "maxLength": 4096, "pattern": r"\S"},
        "color": {"type": "string", "pattern": "^#(?:[0-9a-fA-F]{6}|[0-9a-fA-F]{12})$"},
        "line_width_pt": {"type": "number", "exclusiveMinimum": 0}},
        ["sample", "x_column_index", "y_column_index"])
    context = {"type": "string", "minLength": 1, "maxLength": 2000}
    facts = closed({"source": closed({"source_id": IDENTIFIER,
        "path": {"type": "string", "minLength": 1, "pattern": "^/"}}), "source_context": context}, ["source"])
    complete = closed({"source": source, "curves": {"type": "array", "minItems": 1, "maxItems": 32, "items": curve},
        "source_context": context}, ["source", "curves"])
    return {"oneOf": [facts, complete]}


def append_targets(document: dict[str, Any], *, root: Path | None = None) -> dict[str, dict[str, Any]]:
    """Advertise the operation only for represented original-value numeric XY views."""
    if not is_figure(document) or "rule_id" not in document["scientific"]["provenance"]["managed"]:
        return {}
    if root is not None:
        document = deepcopy(document)
        document["scientific"]["provenance"]["binding"] = resolve_provenance_value(root, document, "binding") or {}
    spec = figure_spec(document)
    if spec["composition"]["kind"] != "single":
        return {}
    scales = {scale["id"]: scale for scale in spec["scales"]}
    facts = None
    if root is not None and any(requires_unit_context(scale["unit"], scale["unit"]) or scale["unit"] == "K"
                                for scale in scales.values()):
        facts = load_source_facts(document, document["scientific"]["provenance"]["managed"]["rule_id"])
    result = {}
    for view in spec["views"]:
        pairs = {(layer["x_scale"], layer["y_scale"]) for layer in view["layers"]}
        if len(pairs) != 1 or any(layer["role"] != "measurement" or
                any(mark["type"] not in {"line", "point"} or "interpolation" in mark for mark in layer["marks"])
                for layer in view["layers"]):
            continue
        x, y = next(iter(pairs))
        if any(scales[name]["transform"] not in {"linear", "log"} for name in (x, y)):
            continue
        try:
            for layer in view["layers"]:
                for axis, scale in (("x", x), ("y", y)):
                    coordinate_origin(document, layer["dataset_id"], layer["mappings"][axis], scales[scale]["unit"],
                                      quantity=layer["mapping_semantics"][axis], column_facts=facts,
                                      explicit_quantity_binding=True)
        except (ValueError, KeyError):
            continue
        result[view["id"]] = {"scales": {axis: deepcopy(scales[name]) for axis, name in (("x", x), ("y", y))},
            "sources": [{key: deepcopy(source[key]) for key in ("source_id", "path", "sha256", "table_selection")}
                        for source in document["scientific"]["data_sources"]],
            "boundary": "Original XY values from a new file, an unused response column in an already bound original table, or an exactly confirmed independent physical Test block in the same original file; exact quantities and registered unit relations; current axes and existing presentation are preserved. "
                        "A numeric unit conversion requires the curve's explicit x_unit or y_unit equal to the current axis unit. No normalization, fitting or stage assembly. Supply an explicit scientific sample identity."}
    return result


def append_descriptor() -> dict[str, Any]:
    return {"value_schema": append_schema(), "risk": "scientific"}


def _clarify(code: str, message: str, **facts: Any) -> NoReturn:
    raise EngineError(code, message, action="clarify_source_append", **facts)


def _quantity_matches(header: str, quantity: str) -> bool:
    from sciplot_core.semantic_sources.paired_curve_table_metadata import header_quantity_text
    from sciplot_core.source_inspection.semantic_evidence import _quantity

    literal = header_quantity_text(header).replace("_", " ").strip().casefold()
    return literal == quantity.replace("_", " ").strip().casefold() or _quantity(header) == quantity


def _source_facts(snapshot: dict[str, Any], source: dict[str, Any], request: dict[str, Any]) -> NoReturn:
    candidates = append_source_candidates(snapshot)
    value = request["changes"][0]["value"]
    template = {"source": {**source, "sha256": snapshot["file_sha256"]}, "curves": [],
                **({"source_context": value["source_context"]} if "source_context" in value else {})}
    _clarify("managed_append_source_confirmation_required", "Choose the original table region and coordinate columns, and declare each scientific sample. No plot transaction was allocated.",
        source_sha256=snapshot["file_sha256"], tables=[{key: table[key] for key in ("sheet", "row_count", "column_count")}
                                                    for table in snapshot["tables"]], candidates=candidates,
        next_step={"action": "plot.patch", "same_idempotency_key": True,
                   "plot_id": request["plot_id"], "base_revision": request["base_revision"],
                   "idempotency_key": request["idempotency_key"], "intent_class": "scientific",
                   "required_fields": ["value.source.table_selection", "value.curves[].sample",
                                       "value.curves[].x_column_index", "value.curves[].y_column_index"],
                   "value_template": template})


def _coordinates(curve: dict[str, Any], columns: dict[int, dict[str, Any]],
                 scales: dict[str, Any]) -> dict[str, Any]:
    selected = {}
    if curve["x_column_index"] == curve["y_column_index"]:
        _clarify("managed_append_coordinate_conflict", "Choose distinct original X and Y columns.")
    for axis in ("x", "y"):
        index = curve[axis + "_column_index"]
        column = columns.get(index)
        if column is None:
            _clarify("managed_append_column_missing", "Choose an existing original column.", coordinate=axis,
                     column_index=index, available_columns=list(columns))
        assert column is not None
        if column["metadata_conflicts"]:
            _clarify("managed_append_metadata_conflict", "Resolve the original column metadata conflict explicitly.",
                     coordinate=axis, column_index=index, issues=column["metadata_conflicts"])
        scale = scales[axis]
        quantity = curve.get(axis + "_quantity", scale["quantity"])
        if ("quantity_members" in scale and axis + "_quantity" not in curve
                or quantity not in scale.get("quantity_members", [scale["quantity"]])):
            _clarify("managed_append_quantity_conflict", "Explicit shared-quantity scales require each appended curve's actual original quantity member.", coordinate=axis)
        if not column["header"] or not _quantity_matches(column["header"], quantity):
            _clarify("managed_append_quantity_conflict", "The original quantity must match this view's existing scientific axis.",
                     coordinate=axis, column_index=index, observed=column["header"], expected=quantity,
                     allowed_changes=["original_column_selection", "metadata_confirmation_for_absent_quantity"])
        try:
            relation = resolve_unit_relation(column["unit"], scale["unit"], quantity=quantity,
                                             explicit_quantity_binding=True)
        except ValueError:
            _clarify("managed_append_unit_conflict", "The original unit needs an exact identity or registered scientific conversion to the current axis unit.",
                     coordinate=axis, column_index=index, observed=column["unit"], expected=scale["unit"])
        if (axis + "_unit" in curve and curve[axis + "_unit"] != scale["unit"]
                or relation["kind"] == "conversion" and axis + "_unit" not in curve):
            _clarify("managed_append_unit_conflict", "A numeric unit conversion requires an explicit curve target unit equal to the existing axis unit.",
                     coordinate=axis, column_index=index, observed=column["unit"], expected=scale["unit"],
                     required_field=axis + "_unit", unit_relation=relation)
        if column["sample"] and column["sample"] != curve["sample"]:
            _clarify("managed_append_sample_conflict", "The scientific sample must preserve original metadata; use label for display text.",
                     coordinate=axis, column_index=index, observed=column["sample"], expected=curve["sample"])
        selected[axis] = {**column, "unit_relation": relation}
    return selected


@with_table_reads
def prepare_append(document: dict[str, Any], request: dict[str, Any]) -> tuple[dict[str, Any], list[dict[str, Any]], str, bool]:
    if request["intent_class"] != "scientific":
        raise EngineError("managed_append_scientific_intent_required", "Adding an original source requires explicit scientific intent.")
    if len(request["changes"]) != 1 or len(request["changes"][0]["target"]) != 1:
        raise EngineError("managed_append_atomic_scope", "Append one source to one view in its own scientific transaction.")
    change = request["changes"][0]
    target, value = change["target"][0], change["value"]
    validate_wire(value, append_schema(), code="managed_append_invalid_value")
    context = append_targets(document).get(target)
    if context is None:
        _clarify("managed_append_view_unsupported", "Choose an advertised original-value numeric XY view. Legacy, derived science and ambiguous scales require a separate supported scientific operation.")
    assert context is not None
    source = deepcopy(value["source"])
    path = Path(source["path"])
    existing = document["scientific"]["data_sources"]
    outputs = {node["output"] for node in document["scientific"]["transforms"]}
    if source["source_id"] in {item["source_id"] for item in existing} | outputs:
        _clarify("managed_append_source_exists", "Use a fresh source binding identity; original file identity and existing observations remain guarded separately.")
    if not path.is_absolute() or not path.is_file():
        _clarify("managed_append_source_changed", "Supply the exact current original file path and SHA-256.")
    rule_id = document["scientific"]["provenance"]["managed"]["rule_id"]
    snapshot = source_table_snapshot(path, rule_id=rule_id,
        sheets=[source["table_selection"]["sheet"]] if "curves" in value else None)
    if snapshot is None:
        _clarify("managed_append_source_unsupported", "Choose an original CSV, TSV or Excel table.")
    assert snapshot is not None
    if "curves" not in value:
        _source_facts(snapshot, source, request)
    if snapshot["file_sha256"] != source["sha256"]:
        _clarify("managed_append_source_changed", "Supply the exact current original file path and SHA-256.")
    region_proof = confirm_append_region(snapshot, source, value["curves"])
    try:
        selected = select_table(snapshot, source["table_selection"], source.get("metadata_confirmations"))
    except ValueError as exc:
        _clarify("managed_append_table_rejected", "Correct the original table selection or its explicit metadata evidence.",
                 detail=str(exc)[:400], table_selection=source["table_selection"])
    columns = {column["index"]: column for column in selected["columns"]}
    pairs = [_coordinates(curve, columns, context["scales"]) for curve in value["curves"]]
    if len({curve["y_column_index"] for curve in value["curves"]}) != len(pairs):
        _clarify("managed_append_duplicate_curve", "Bind each original response column once; do not duplicate observations as another sample.")
    from .append_measurement_identity import validate_append_identity

    validate_append_identity(document, source, value["curves"], region_proof=region_proof)
    result, spec = deepcopy(document), figure_spec(document)
    science = result["scientific"]
    science["data_sources"].append(source)
    identity = canonical_json_sha256(source)[0:24]
    output = "append:" + identity
    node = {"id": "append-select:" + identity, "kind": "select", "inputs": [source["source_id"]], "output": output,
            "parameters": {"columns": list(dict.fromkeys(f"column:{column['index']}" for pair in pairs for column in pair.values()))},
            "executor": builtin_executor(), "determinism": "deterministic"}
    if output in outputs | {item["source_id"] for item in science["data_sources"]} or any(
            item["id"] == node["id"] for item in science["transforms"]):
        raise EngineError("managed_append_identity_collision", "The generated append identity collides with an existing scientific object.")
    science["transforms"].append(node)
    projections: dict[str, dict[str, Any]] = {}
    unit_relations = []
    for curve, pair in zip(value["curves"], pairs, strict=True):
        unit_relations.append({"sample": curve["sample"], **{axis: deepcopy(pair[axis]["unit_relation"]) for axis in ("x", "y")}})
        for axis in ("x", "y"):
            column = f"column:{pair[axis]['index']}"
            relation = pair[axis]["unit_relation"]
            if column in projections and projections[column] != relation:
                _clarify("managed_append_unit_conflict", "One appended original column cannot acquire conflicting target units in the same view.", column=column)
            projections[column] = relation
    for index, (column, relation) in enumerate(projections.items()):
        if relation["from_unit"] == relation["to_unit"]:
            continue
        projected = f"append-unit:{identity}:{index}"
        if projected in outputs | {item["source_id"] for item in science["data_sources"]} or any(
                item["id"] == projected for item in science["transforms"]):
            raise EngineError("managed_append_identity_collision", "The generated unit projection identity already exists.")
        science["transforms"].append({"id": projected, "kind": "convert_unit", "inputs": [output], "output": projected,
            "parameters": {"columns": [column], "from_unit": relation["from_unit"], "to_unit": relation["to_unit"]},
            "executor": builtin_executor(), "determinism": "deterministic"})
        output = projected
    view = next(view for view in spec["views"] if view["id"] == target)
    new_layers = []
    first_z = max(layer["z_order"] for layer in view["layers"]) + 1
    for index, (curve, pair) in enumerate(zip(value["curves"], pairs, strict=True)):
        identifier = f"layer:append:{identity}:{index}"
        if identifier in document["presentation"]["objects"]:
            raise EngineError("managed_append_identity_collision", "The generated layer identity already exists.")
        label = curve.get("label", curve["sample"])
        line_style = {field: curve[key] for key, field in (("color", "line_color"), ("line_width_pt", "line_width_pt")) if key in curve}
        points = {"marker_color": curve["color"]} if "color" in curve else {}
        layer = {"id": identifier, "dataset_id": output,
            "mappings": {axis: f"column:{pair[axis]['index']}" for axis in ("x", "y")},
            "mapping_semantics": {axis: curve.get(axis + "_quantity", context["scales"][axis]["quantity"]) for axis in ("x", "y")},
            "x_scale": context["scales"]["x"]["id"], "y_scale": context["scales"]["y"]["id"],
            "marks": [{"id": identifier + ":line", "type": "line", "style": line_style},
                      {"id": identifier + ":point", "type": "point", "style": points}],
            "role": "measurement", "label": label, "legend": {"visible": True, "label": label},
            "z_order": first_z + index, "style": {}}
        view["layers"].append(layer)
        science["mappings"][identifier] = {"series_id": identifier, "sample": curve["sample"],
            **{axis: {"source_id": output, "column": layer["mappings"][axis]} for axis in ("x", "y")},
            **{axis + "_unit": context["scales"][axis]["unit"] for axis in ("x", "y")}}
        new_layers.append(identifier)
    for guide in spec["guides"]:
        if guide["scope"] == "view" and guide["view_id"] != target:
            continue
        for field in ("layer_ids", "order"):
            if guide[field]:
                guide[field].extend(new_layers)
    science["provenance"].setdefault("source_appends", []).append({"source_id": source["source_id"],
        "sha256": source["sha256"], "table_selection": deepcopy(source["table_selection"]), "view_id": target,
        "layer_ids": new_layers, "curves": deepcopy(value["curves"]), "unit_relations": unit_relations,
        **({"physical_region": region_proof} if region_proof is not None else {}),
        **({"source_context": value["source_context"]} if "source_context" in value else {})})
    result = store_spec(result, spec)
    if file_sha256(path) != source["sha256"]:
        _clarify("managed_append_source_changed", "The original file changed while preparing the append.")
    return result, [{"target": target, "property": "source.append", "before": None,
        "after": {"source": source, "layer_ids": new_layers, "curves": deepcopy(value["curves"]), "unit_relations": unit_relations,
                  **({"physical_region": region_proof} if region_proof is not None else {}),
                  "row_count": selected["table_selection"]["data_end_row"] - selected["table_selection"]["data_start_row"],
                  **({"preserved_domain_rules": {axis: deepcopy(context["scales"][axis]["domain_rule"]) for axis in ("x", "y")}}
                     if "domain_semantics" in spec else
                     {"preserved_scale_domains": {axis: context["scales"][axis]["domain"] for axis in ("x", "y")}})},
        "risk": "scientific"}], "review", True
