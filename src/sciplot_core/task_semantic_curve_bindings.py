"""Explicit original column pairs for ordinary curves sharing one response axis."""
from collections import Counter
from itertools import pairwise
from typing import Any, NoReturn

from sciplot_core.plot_document.errors import DocumentError
from sciplot_core.plot_document.schema import closed
from sciplot_core.task_semantic_coordinates import block_columns, unit_path
from sciplot_core.task_errors import TaskControlError


def curve_binding_schema() -> dict[str, Any]:
    return closed({"source_id": {"type": "string", "pattern": "^source:[0-9]+$"},
                   "table_id": {"type": "string", "pattern": "^table:[0-9]+$"},
                   "block_id": {"type": "string", "pattern": "^block:[0-9]+$"},
                   "x_column_id": {"type": "string", "pattern": "^column:[0-9]+$"},
                   "y_column_id": {"type": "string", "pattern": "^column:[0-9]+$"},
                   "y_quantity": {"type": "string", "minLength": 1, "maxLength": 128}})


def bound_views(sources: list[dict[str, Any]], intent: dict[str, Any]) -> list[tuple[dict[str, Any], dict[str, Any]]]:
    """Validate complete qualified bindings, then retain each pair's original grid."""
    def reject(message: str) -> NoReturn:
        raise TaskControlError("semantic_curve_bindings_invalid", message)

    members, bindings = intent["y"].get("quantity_members"), intent.get("curve_bindings")
    if (not members or not bindings or intent.get("rule_id", "ordinary_xy") != "ordinary_xy"
            or any(field in intent for field in ("stages", "secondary_y"))):
        reject("Shared quantity members require complete curve_bindings in an ordinary raw XY intent without rule, stage or secondary-axis interpretation.")
    if any(field in intent[role] for role in ("x", "y") for field in ("header", "headers", "column_id")):
        reject("Each curve binding owns its exact original column pair. Keep shared axes free of conflicting global column selectors.")
    views: list[tuple[dict[str, Any], dict[str, Any]]] = []
    consumed = []
    for source in sources:
        for candidate in source["candidates"]:
            if candidate.get("format") not in {None, "sample_column_blocks"}:
                reject("Explicit ordinary curve bindings cannot replace an instrument scientific adapter.")
            for block in candidate["blocks"]:
                matches = [binding for binding in bindings if (binding["source_id"], binding["table_id"], binding["block_id"]) ==
                           (source["source_id"], candidate["candidate_id"], block["block_id"])]
                if len(matches) != len(members) or {item["y_quantity"] for item in matches} != set(members):
                    reject("Every selected original block requires exactly one explicit X/Y column pair for every declared quantity member; no curve is silently omitted.")
                if len({item["y_column_id"] for item in matches}) != len(matches):
                    reject("An original response column cannot be duplicated as another quantity.")
                column_counts = Counter(column["column_id"] for column in block_columns(candidate, block))
                stages = [stage for stage in candidate["stages"] if stage["block_id"] == block["block_id"]]
                by_quantity = {item["y_quantity"]: item for item in matches}
                for quantity in members:
                    binding = by_quantity[quantity]
                    x, y = binding["x_column_id"], binding["y_column_id"]
                    if x == y:
                        reject("Bind distinct original X and Y columns.")
                    if column_counts[x] != 1 or column_counts[y] != 1:
                        reject("Each qualified curve binding must name one existing original column within its original block.")
                    coordinates = {"x": {**intent["x"], "column_id": x},
                                   "y": {**intent["y"], "quantity": quantity, "column_id": y}}
                    coordinates["y"].pop("quantity_members")
                    # Temporary views read the selected source. The plan owner freezes the result.
                    view = {**candidate, "blocks": [block], "table_selection": block["table_selection"],
                            "sample_view": True, "curve_coordinates": coordinates, "stages": stages}
                    views.append(({**source, "source_id": source["source_id"] + ":curve:" + str(len(views))}, view))
                    consumed.append(binding)
    if len(consumed) != len(bindings):
        reject("Curve bindings must name only selected original source/table/block references.")
    return views


def _error(code: str, message: str, **facts: Any) -> NoReturn:
    error = TaskControlError(code, message)
    error.issues = [{"path": "/intent", "constraint": code, **facts}]
    error.repair = {"action": "revise_intent", "message": "Preserve this task and the original source. Correct the complete uncommitted intent using its current intent_revision; no source or coordinate is replaced automatically."}
    raise error


def _select_column(candidate: dict[str, Any], block: dict[str, Any], coordinate: dict[str, Any], role: str) -> dict[str, Any]:
    """Validate a resolved literal column; lowering cannot reinterpret quantity."""
    columns = block_columns(candidate, block)
    exact = [column for column in columns if all(column[field] == coordinate[field] for field in ("column_id", "column_index", "header"))
             and column["quantity"] == coordinate["observed_quantity"] and column["unit"] == coordinate["observed_unit"]]
    if len(exact) != 1:
        _error("semantic_resolved_binding_changed", "An original coordinate differs from its resolved source binding; no replacement column was chosen.",
               role=role, block_id=block["block_id"])
    from sciplot_core.plot_transforms.unit_relations import requires_unit_context, resolve_unit_relation

    relations = unit_path(coordinate)
    if (relations[0]["from_unit"] != coordinate["source_unit"] or relations[-1]["to_unit"] != coordinate["unit"]
            or any(a["to_unit"] != b["from_unit"] for a, b in pairwise(relations))):
        _error("semantic_resolved_binding_changed", "The resolved unit relation differs from its exact coordinate binding.", role=role)
    relation = relations[0]
    if coordinate["source_unit"] == coordinate["unit"] and (len(relations) != 1 or relation["kind"] != "identity" or relation["factor"] != 1 or relation["offset"] != 0 or relation["canonical_from_unit"] != relation["canonical_to_unit"]):
        _error("semantic_resolved_binding_changed", "An unchanged original unit does not match its resolved identity relation.", role=role)
    if requires_unit_context(coordinate["source_unit"], coordinate["unit"]):
        context = coordinate.get("unit_context")
        if context is None and coordinate["quantity"] == "temperature" and coordinate["observed_quantity"] != "temperature":
            _error("semantic_unit_context_confirmation_required", "This uncommitted legacy C binding has no recorded source temperature or exact selected user quantity fact. Reconfirm it through revise_intent; its old draft was not reinterpreted.", role=role)
        if context is not None and (context.get("version") != 1 or any(
                context.get(field) != coordinate[key] for field, key in (
                    ("quantity", "quantity"), ("observed_quantity", "observed_quantity"), ("source_header", "header")))
                or type(context.get("explicit_quantity_binding")) is not bool):
            _error("semantic_resolved_binding_changed", "The frozen unit context differs from its exact source coordinate.", role=role)
        try:
            admitted = resolve_unit_relation(coordinate["source_unit"], coordinate["unit"],
                quantity=coordinate["quantity"], observed_quantity=coordinate["observed_quantity"],
                explicit_quantity_binding=context["explicit_quantity_binding"] if context else False)
        except DocumentError:
            _error("semantic_unit_context_confirmation_required", "This uncommitted coordinate lacks a supported unit context. Explicitly reconfirm its quantity and exact original selector with revise_intent in this same draft; no saved request or source value was changed.", role=role)
        if [admitted] != relations:
            _error("semantic_resolved_binding_changed", "The frozen relation differs from its source-supported unit context; revise this same uncommitted draft.", role=role)
    return {**exact[0], "unit": coordinate["source_unit"]}


def _source_metadata(source: dict[str, Any], candidate: dict[str, Any], bindings: list[dict[str, Any]],
                     registered: dict[str, Any] | None = None) -> list[dict[str, Any]]:
    """Archive missing-unit declarations through the existing metadata contract."""
    confirmations = []
    for binding in bindings:
        block = next(block for block in candidate["blocks"] if block["block_id"] == binding["block_id"])
        for role, coordinate in binding["coordinates"].items():
            if "derivation" in coordinate or coordinate["observed_unit"]:
                continue
            column = _select_column(candidate, block, coordinate, role)
            confirmation = {"source_sha256": source["sha256"], "sheet": candidate["sheet"],
                            "column_index": column["column_index"], "field": "unit", "value": column["unit"],
                            "evidence": registered if registered is not None and role == "y" else {"kind": "user_statement", "asserted_by": "semantic_task_intent",
                                         "statement": f"intent.{role}.source_unit explicitly declares the original unit of {column['header']!r} as {column['unit']!r}; the original cell is absent."}}
            if confirmation not in confirmations:
                confirmations.append(confirmation)
    return confirmations
