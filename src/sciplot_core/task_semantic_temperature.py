"""One original-column selector for secondary temperature planning and binding."""
from typing import Any, NoReturn

from sciplot_core.task_errors import TaskControlError


def _reject(reason: str, message: str, **facts: Any) -> NoReturn:
    error = TaskControlError(reason, message)
    error.issues = [{"path": "/intent/secondary_y", "constraint": reason, **facts}]
    error.repair = {"action": "revise_intent", "supported_selectors": [
        "intent.secondary_y.header", "intent.secondary_y.column_id", "intent.temperature_header"],
        "message": "Select one observed temperature column per retained original block. Explicit selectors intersect; legacy temperature_header and secondary_y.header must agree."}
    raise error


def temperature_selector(intent: dict[str, Any], choices: dict[str, Any] | None = None) -> dict[str, str]:
    coordinate = intent.get("secondary_y", {})
    declared = {name: value for name, value in {
        "secondary_y.header": coordinate.get("header"), "temperature_header": intent.get("temperature_header"),
        "choices.temperature_header": (choices or {}).get("temperature_header")}.items() if value is not None}
    if len(set(declared.values())) > 1:
        _reject("semantic_temperature_selector_conflict", "Explicit temperature headers disagree; no declaration overrides another scientific binding.", declared=declared)
    selector = {"header": next(iter(declared.values()))} if declared else {}
    if "column_id" in coordinate:
        selector["column_id"] = coordinate["column_id"]
    return selector


def temperature_columns(candidate: dict[str, Any], block: dict[str, Any], selector: dict[str, str]) -> list[dict[str, Any]]:
    columns = block.get("columns") or [column for column in candidate["columns"]
                                       if column["column_index"] in block["column_indices"]]
    return [column for column in columns if column["quantity"] == "temperature"
            and all(column[field] == value for field, value in selector.items())]


def temperature_column(candidate: dict[str, Any], block: dict[str, Any], selector: dict[str, str]) -> dict[str, Any]:
    columns = temperature_columns(candidate, block, selector)
    if len(columns) != 1:
        _reject("semantic_temperature_mapping_required", "The temperature selectors do not identify exactly one original column in this selected block.",
                block_id=block["block_id"], selector=selector, columns=columns)
    return dict(columns[0])


def temperature_decisions(sources: list[dict[str, Any]], intent: dict[str, Any], segmented: bool,
                          choices: dict[str, Any] | None = None) -> list[dict[str, Any]]:
    selector = temperature_selector(intent, choices)
    order = intent.get("stages", {}).get("order", (choices or {}).get("stage_order"))
    if not intent.get("secondary_y") and not (segmented and order == "temperature_continuity"):
        return []
    groups = [{"source_id": source["source_id"], "table_id": candidate["candidate_id"],
               "block_id": block["block_id"], "columns": temperature_columns(candidate, block, selector)}
              for source in sources for candidate in source["candidates"] for block in candidate["blocks"]]
    if selector:
        if any(len(group["columns"]) != 1 for group in groups):
            _reject("semantic_temperature_mapping_required", "The explicit temperature selectors must resolve uniquely in every selected original block.",
                    selector=selector, source_blocks=groups)
        return []
    headers = set.intersection(*(set(column["header"] for column in group["columns"]) for group in groups)) if groups else set()
    options = [header for header in sorted(headers) if all(
        sum(column["header"] == header for column in group["columns"]) == 1 for group in groups)]
    if len(options) == 1 and all(len(group["columns"]) == 1 for group in groups):
        return []
    if options:
        return [{"field": "temperature_header", "options": options,
                 "message": "Select the original temperature role. Equal numbers do not make Ts and Tr interchangeable scientific identities."}]
    _reject("semantic_temperature_mapping_required", "No one exact temperature header is available in every selected block; revise the source/column binding rather than substituting roles.", source_blocks=groups)
