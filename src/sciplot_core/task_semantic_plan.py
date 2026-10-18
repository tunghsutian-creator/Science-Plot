"""Prepare one original-evidence question; candidates never silently become science."""
from itertools import permutations
from pathlib import Path
from typing import Any

from sciplot_core.data_mapping.table_choice import read_original_table
from sciplot_core.task_errors import TaskControlError


def _endpoints(frame: Any, column: int, start: int, end: int) -> list[float | None]:
    values = [frame.iat[index, column] for index in (start, end - 1)]
    result = []
    for value in values:
        try:
            number = float(value)
        except (TypeError, ValueError):
            number = float("nan")
        import math

        result.append(number if math.isfinite(number) else None)
    return result


def _stage_evidence(source: dict[str, Any], candidate: dict[str, Any]) -> None:
    frame = read_original_table(Path(source["path"]), candidate["sheet"], source["sha256"])
    columns = {column["column_id"]: column for column in candidate["columns"]}
    stages = []
    for block in candidate["blocks"]:
        segments = block["segments"] or [{"data_start_row": block["data_start_row"],
            "data_end_row": block["data_end_row"], "point_count": block["data_end_row"] - block["data_start_row"]}]
        for index, segment in enumerate(segments):
            start, end = segment["data_start_row"], segment["data_end_row"]
            stages.append({**segment, "stage_id": block["block_id"] + ":segment:" + str(index),
                "block_id": block["block_id"], "temperature_endpoints": {
                    columns[name]["header"]: _endpoints(frame, columns[name]["column_index"], start, end)
                    for name in block["temperature_columns"]}})
    candidate["stages"] = stages
    suggestions = {}
    if len(stages) <= 8:
        headers = set.intersection(*(set(stage["temperature_endpoints"]) for stage in stages)) if stages else set()
        for header in sorted(headers):
            if any(None in stage["temperature_endpoints"][header] for stage in stages):
                continue
            ranked = []
            for order in permutations(stages):
                cost = sum(abs(a["temperature_endpoints"][header][1] - b["temperature_endpoints"][header][0])
                           for a, b in zip(order, order[1:], strict=False))
                ranked.append((cost, [stage["stage_id"] for stage in order]))
            ranked.sort()
            if ranked and (len(ranked) == 1 or ranked[0][0] < ranked[1][0]):
                suggestions[header] = {"order": ranked[0][1], "absolute_boundary_gap_sum": ranked[0][0],
                    "basis": "unique minimum adjacent observed temperature endpoint gap; a proposal requiring explicit confirmation"}
    candidate["temperature_continuity"] = suggestions


def _coordinate_decisions(sources: list[dict[str, Any]], intent: dict[str, Any]) -> list[dict[str, Any]]:
    decisions = []
    for role in ("x", "y"):
        coordinate = intent[role]
        groups = []
        for source in sources:
            for candidate in source["candidates"]:
                for block in candidate["blocks"]:
                    columns = block.get("columns") or [column for column in candidate["columns"] if column["column_index"] in block["column_indices"]]
                    eligible = [column for column in columns if column["quantity"] == coordinate["quantity"]]
                    derived = block.get("derived_coordinates", {}).get(coordinate["quantity"])
                    has_selector = any(field in coordinate for field in ("header", "column_id"))
                    if not eligible and derived and not has_selector:
                        eligible = [derived]
                    elif not eligible and role == "y":
                        eligible = [column for column in columns if column["quantity"] is None and column["column_id"] in block["response_columns"]]
                    for field in ("header", "column_id"):
                        if field in coordinate:
                            eligible = [column for column in eligible if column[field] == coordinate[field]]
                    groups.append({"source_id": source["source_id"], "table_id": candidate["candidate_id"],
                                   "block_id": block["block_id"], "columns": eligible,
                                   **({"available_derivation": derived} if derived else {})})
        if all(len(group["columns"]) == 1 for group in groups):
            continue
        common = set.intersection(*(set(column["header"] for column in group["columns"]) for group in groups)) if groups else set()
        headers = [header for header in sorted(common) if all(sum(column["header"] == header for column in group["columns"]) == 1 for group in groups)]
        if headers and "header" not in coordinate and "column_id" not in coordinate:
            decisions.append({"field": role + "_header", "options": headers,
                              "message": "Select the exact observed original column header for this coordinate; units alone do not choose a response."})
            continue
        error = TaskControlError("semantic_coordinate_mapping_required", "This source needs a more specific original coordinate binding. Select an exact header/column_id in the small coordinate intent where it applies, or use the existing explicit source mapping route; no column was silently selected.")
        error.issues = [{"path": "/intent/" + role, "constraint": "unique_original_coordinate", "source_blocks": groups}]
        error.repair = {"action": "choose_original_coordinate", "supported_selectors": ["intent." + role + ".header", "intent." + role + ".column_id"],
                        "existing_mapping_route": "task start create.mapping for ordinary single-source XY, or expert plot create with source Binding for differently selected original blocks"}
        derivations = [group for group in groups if "available_derivation" in group]
        if derivations:
            error.repair["available_derivations"] = derivations
            error.repair["draft_correction"] = {
                "action": "revise_intent", "omit_fields": ["intent." + role + ".header", "intent." + role + ".column_id"],
                "message": "To request the advertised source-derived quantity, retain its quantity/unit and omit a selector naming a different measured component. Revise this same task with its current expected_intent_revision; never relabel a real or imaginary component as magnitude."}
        raise error
    return decisions


def prepare_plan(paths: list[Path], intent: dict[str, Any]) -> dict[str, Any]:
    from sciplot_core.source_inspection.semantic_evidence import inspect_semantic_tables

    sources = []
    for index, path in enumerate(paths):
        evidence = inspect_semantic_tables(path, rule_id=intent.get("rule_id"))
        if not evidence["candidates"]:
            raise TaskControlError("semantic_table_not_found", "No byte-bound table with explicit quantity/unit metadata was found. Preserve the original and provide its missing scientific metadata through the supported mapping route.")
        source = {"source_id": f"source:{index}", "path": str(path), "name": path.name,
                  "sha256": evidence["sha256"], "candidates": evidence["candidates"],
                  "scientific_identity": evidence["scientific_identity"]}
        sources.append(source)
    from sciplot_core.task_semantic_selection import select_source_blocks

    sources, selection = select_source_blocks(sources, intent.get("selection"))
    for source in sources:
        for candidate in source["candidates"]:
            _stage_evidence(source, candidate)
    return {"sources": sources, "selection": selection, "intent": intent, "decisions": _plan_decisions(sources, intent),
            "authority": "Preparation evidence only. Confirmed source facts compile into the existing Managed document; original bytes stay immutable.",
            "raw_data": "original bytes retained; selected original blocks and explicit exclusions are recorded; source row bounds are zero-based and data_end_row is exclusive",
            "interpolation": "Display interpolation retains raw marker points; gaps and non-increasing time boundaries remain separate runs."}


def _plan_decisions(sources: list[dict[str, Any]], intent: dict[str, Any], choices: dict[str, Any] | None = None) -> list[dict[str, Any]]:
    from sciplot_core.task_semantic_temperature import temperature_decisions, temperature_selector

    temperature_selector(intent, choices)
    multiple = {source["source_id"]: [candidate["candidate_id"] for candidate in source["candidates"]]
                for source in sources if len(source["candidates"]) > 1}
    if multiple:
        return [{"field": "tables", "options": multiple,
                 "message": "Choose one exact original table candidate for every listed source before coordinate validation. No alternative was silently excluded."}]
    decisions = _coordinate_decisions(sources, intent)
    segmented = any(len(candidate["stages"]) > 1 for source in sources for candidate in source["candidates"])
    decisions.extend(temperature_decisions(sources, intent, segmented, choices))
    if intent.get("secondary_y") and len(sources) > 1 and "temperature_source" not in intent:
        decisions.append({"field": "temperature_source", "options": [source["source_id"] for source in sources],
                          "message": "Choose the exact recorded attachment for the right-axis temperature; other schedules are not assumed equal."})
    if segmented and intent["x"]["quantity"] == "time":
        if (intent.get("stages") or {}).get("mode") != "concatenate":
            decisions.append({"field": "stage_mode", "options": ["concatenate"],
                              "message": "The originals contain multiple acquisition stages/time resets. Confirm cumulative stage assembly; no stage may be silently dropped."})
        if "order" not in intent.get("stages", {}):
            order_options = ["source_order"]
            if all(candidate["temperature_continuity"] for source in sources for candidate in source["candidates"]):
                order_options.append("temperature_continuity")
            decisions.append({"field": "stage_order", "options": order_options,
                              "message": "Confirm stage order from source evidence. Temperature continuity is an explicit proposal, never an automatic experiment interpretation."})
        if "boundary" not in intent.get("stages", {}):
            decisions.append({"field": "time_boundary", "options": ["preserve_endpoint", "next_sample"],
                "message": "preserve_endpoint retains both boundary points at equal cumulative time; next_sample also retains both and advances by the entering stage's first measured positive sample interval. Neither policy invents measurements."})
    return decisions


def selected_table_plan(plan: dict[str, Any], intent: dict[str, Any], choices: dict[str, Any]) -> dict[str, Any]:
    """Replan after an explicit table answer without rereading or dropping evidence."""
    from copy import deepcopy
    from sciplot_core.task_semantic_figure import _source_candidate

    selected = deepcopy(plan)
    selected["sources"] = [{**source, "candidates": [_source_candidate(source, choices)]}
                           for source in selected["sources"]]
    selected["decisions"] = _plan_decisions(selected["sources"], intent, choices)
    return selected
