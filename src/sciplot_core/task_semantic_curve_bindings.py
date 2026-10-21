"""Explicit original column pairs for ordinary curves sharing one response axis."""
from copy import deepcopy
from typing import Any, NoReturn

from sciplot_core.plot_document.schema import closed
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
                for quantity in members:
                    binding = next(item for item in matches if item["y_quantity"] == quantity)
                    if binding["x_column_id"] == binding["y_column_id"]:
                        reject("Bind distinct original X and Y columns.")
                    coordinates = {}
                    for role in ("x", "y"):
                        coordinate = {key: value for key, value in intent[role].items() if key not in {"header", "headers", "column_id", "quantity_members"}}
                        coordinate.update(column_id=binding[role + "_column_id"])
                        if role == "y":
                            coordinate["quantity"] = quantity
                        columns = block.get("columns") or [column for column in candidate["columns"] if column["column_index"] in block["column_indices"]]
                        exact = [column for column in columns if column["column_id"] == binding[role + "_column_id"]]
                        if len(exact) != 1:
                            reject("Each qualified curve binding must name one existing original column within its original block.")
                        coordinates[role] = coordinate
                    # The confirmed physical region owns missing positions.
                    # Numeric extents describe observations, not source bounds.
                    pair_block = deepcopy(block)
                    stages = [deepcopy(stage) for stage in candidate["stages"] if stage["block_id"] == block["block_id"]]
                    view = {**deepcopy(candidate), "blocks": [pair_block], "table_selection": pair_block["table_selection"],
                            "sample_view": True, "curve_coordinates": coordinates,
                            "stages": stages}
                    views.append(({**source, "source_id": source["source_id"] + ":curve:" + str(len(views))}, view))
                    consumed.append(binding)
    if len(consumed) != len(bindings):
        reject("Curve bindings must name only selected original source/table/block references.")
    return views
