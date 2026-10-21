"""Shared literal coordinate binding and explicit missing-source-unit contract."""

from typing import Any

from sciplot_core.task_errors import TaskControlError


def coordinate_columns(columns: list[dict[str, Any]], block: dict[str, Any], coordinate: dict[str, Any], role: str) -> list[dict[str, Any]]:
    """Resolve literal selectors without replacing a known scientific identity."""
    has_selector = any(field in coordinate for field in ("header", "headers", "column_id"))
    selected = [column for column in columns if column["quantity"] == coordinate["quantity"]
                or (has_selector and column["quantity"] is None)]
    if not selected:
        selected = [column for column in columns if column["quantity"] is None
                    and (has_selector or (role == "y" and column["column_id"] in block["response_columns"]))]
    for field in ("header", "column_id"):
        if field in coordinate:
            selected = [column for column in selected if column[field] == coordinate[field]]
    if "headers" in coordinate:
        selected = [column for column in selected if column["header"] in coordinate["headers"]]
    return selected


def resolved_binding(bindings: list[dict[str, Any]], source: dict[str, Any], candidate: dict[str, Any], block: dict[str, Any]) -> dict[str, Any]:
    """Look up a literal binding; never choose a column or reconstruct intent."""
    quantities = {role: candidate.get("curve_coordinates", {}).get(role, {}).get("quantity") for role in ("x", "y")}
    matches = [item for item in bindings if (item["source_path"], item["source_sha256"], item["table_id"], item["block_id"]) ==
               (source["path"], source["sha256"], candidate["candidate_id"], block["block_id"])
               and all(value is None or item["quantities"][role] == value for role, value in quantities.items())]
    if len(matches) != 1 or matches[0]["table_selection"] != block["table_selection"]:
        raise TaskControlError("semantic_resolved_binding_changed", "The frozen source/region binding does not match this plan. Revise this same uncommitted draft; no alternative source or column was inferred.")
    return matches[0]


def source_unit(column: dict[str, Any], coordinate: dict[str, Any], role: str) -> str:
    """Missing source units require an explicit, selector-bound declaration."""
    observed = column["unit"]
    declared = coordinate.get("source_unit")
    if observed:
        if declared is not None:
            from sciplot_core.plot_document.errors import DocumentError
            from sciplot_core.plot_transforms.unit_relations import resolve_unit_relation

            try:
                identity = resolve_unit_relation(observed, declared, quantity=coordinate["quantity"],
                    observed_quantity=column["quantity"], explicit_quantity_binding=any(
                        field in coordinate for field in ("header", "headers", "column_id")))["kind"] == "identity"
            except DocumentError:
                identity = False
            if not identity:
                error = TaskControlError("semantic_source_unit_conflict", "An explicit source_unit cannot replace an observed original unit. Use unit for a registered display conversion.")
                error.issues = [{"path": "/intent/" + role + "/source_unit", "expected": observed, "actual": declared}]
                raise error
        return str(observed)
    if declared and any(field in coordinate for field in ("header", "headers", "column_id")):
        return str(declared)
    error = TaskControlError("semantic_source_unit_required", "The selected original field has no unit. Bind its exact header/column_id and declare source_unit from an explicit user fact; unit only selects the output unit.")
    error.issues = [{"path": "/intent/" + role + "/source_unit", "header": column["header"], "column_id": column["column_id"]}]
    error.repair = {"action": "revise_intent", "supported_selectors": ["intent." + role + ".header", "intent." + role + ".headers", "intent." + role + ".column_id"],
                    "required_field": "intent." + role + ".source_unit", "message": "Keep this draft and original source. Record a confirmed original unit separately from the requested output unit; never infer it from values."}
    raise error
