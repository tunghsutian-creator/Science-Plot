"""Resolve complete source-bound acquisition stages without finite-row cropping."""
from itertools import permutations
from pathlib import Path
from typing import Any, NoReturn

from sciplot_core.data_mapping.original_tables import read_original_table
from sciplot_core.plot_document.errors import DocumentError
from sciplot_core.source_inspection.semantic_evidence import _finite, acquisition_time_regions
from sciplot_core.task_errors import TaskControlError
from sciplot_core.task_semantic_coordinates import resolved_binding


def _reject(code: str, message: str, **facts: Any) -> NoReturn:
    error = TaskControlError(code, message)
    error.issues = [{"path": "/intent/stages", "constraint": code, **facts}]
    error.repair = {"action": "revise_intent", "message":
        "Preserve this draft, its complete original regions and every missing position. No row is dropped, interpolated or reassigned. An explicit ordinary_xy request without cumulative assembly can retain these observations; no alternative experiment was selected automatically."}
    raise error


def stage_evidence(source: dict[str, Any], candidate: dict[str, Any],
                   bindings: list[dict[str, Any]] | None = None) -> None:
    """Observe complete domains; only a resolved X binding can locate resets."""
    frame = read_original_table(Path(source["path"]), candidate["sheet"], source["sha256"])
    stages: list[dict[str, Any]] = []
    unresolved: list[dict[str, Any]] = []
    for block in candidate["blocks"]:
        columns = {column["column_id"]: column for column in block.get("columns", candidate["columns"])}
        coordinate = resolved_binding(bindings, source, candidate, block)["coordinates"].get("x") if bindings is not None else None
        regions = [{"data_start_row": block["data_start_row"], "data_end_row": block["data_end_row"],
                    "point_count": block["data_end_row"] - block["data_start_row"]}]
        if coordinate is not None and coordinate["quantity"] == "time":
            regions, gaps = acquisition_time_regions(frame, coordinate["column_index"], block["data_start_row"], block["data_end_row"])
            unresolved.extend({**gap, "block_id": block["block_id"], "column_id": coordinate["column_id"],
                               "source_path": source["path"], "source_sha256": source["sha256"],
                               "table_selection": block["table_selection"]} for gap in gaps)
        for index, region in enumerate(regions):
            start, end = region["data_start_row"], region["data_end_row"]
            stages.append({**region, "stage_id": block["block_id"] + ":segment:" + str(index),
                "block_id": block["block_id"], **({"time_column_id": coordinate["column_id"]} if coordinate is not None else {}),
                "temperature_endpoints": {columns[name]["header"]: [_finite(frame.iat[row, columns[name]["column_index"]])
                    for row in (start, end - 1)] for name in block["temperature_columns"]}})
    candidate["stages"] = stages
    candidate.pop("unresolved_time_resets", None)
    if unresolved:
        candidate["unresolved_time_resets"] = unresolved
    suggestions = {}
    if len(stages) <= 8 and not unresolved:
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


def ordered_stages(candidate: dict[str, Any], intent: dict[str, Any], choices: dict[str, Any], header: str | None) -> list[dict[str, Any]]:
    stages: list[dict[str, Any]] = candidate["stages"]
    mode = intent.get("stages", {}).get("mode", choices.get("stage_mode"))
    if mode == "concatenate" and candidate.get("unresolved_time_resets"):
        _reject("semantic_stage_boundary_ambiguous", "A measured time decrease spans missing original times. Its acquisition boundary is not located; cumulative assembly cannot assign those rows to a stage.",
                unresolved_resets=candidate["unresolved_time_resets"], stages=stages)
    if len(stages) <= 1:
        return stages
    if mode != "concatenate":
        _reject("semantic_stage_choice_required", "Multiple original stages require explicit cumulative assembly; no stage is silently discarded.")
    strategy = intent.get("stages", {}).get("order", choices.get("stage_order"))
    if strategy == "temperature_continuity":
        suggestions = candidate["temperature_continuity"]
        suggestion = suggestions.get(header) if header is not None else next(iter(suggestions.values())) if len(suggestions) == 1 else None
        if suggestion is None:
            _reject("semantic_stage_order_ambiguous", "No unique temperature-continuity proposal exists for this exact selected temperature role. Choose explicit source order or provide a source-supported mapping.")
        return [next(stage for stage in stages if stage["stage_id"] == identifier) for identifier in suggestion["order"]]
    if strategy == "source_order":
        return stages
    _reject("semantic_stage_choice_required", "Confirm one advertised stage order.")


def validate_stage_domains(plan: dict[str, Any], source: dict[str, Any], candidate: dict[str, Any], stages: list[dict[str, Any]]) -> None:
    """Old unexecuted drafts cannot turn incomplete finite runs into bindings."""
    for block in candidate["blocks"]:
        selected = sorted((stage for stage in stages if stage["block_id"] == block["block_id"]),
                          key=lambda stage: stage["data_start_row"])
        cursor = block["data_start_row"]
        complete = True
        for stage in selected:
            start, end = stage["data_start_row"], stage["data_end_row"]
            complete &= start == cursor and start < end <= block["data_end_row"]
            cursor = end
        if not complete or cursor != block["data_end_row"]:
            _reject("semantic_stage_domain_confirmation_required", "This unexecuted stage draft does not cover its complete confirmed original block. Reconfirm the same draft; omitted observations were not reconstructed or discarded.",
                    source_path=source["path"], source_sha256=source["sha256"], block_id=block["block_id"],
                    table_selection=block["table_selection"], retained_stages=selected)
        if len(selected) > 1:
            coordinate = resolved_binding(plan["resolved_bindings"], source, candidate, block)["coordinates"]["x"]
            if any(stage.get("time_column_id", block["time_column"]) != coordinate["column_id"] for stage in selected):
                _reject("semantic_stage_domain_confirmation_required", "The internal acquisition boundaries lack this exact resolved time-column evidence. Reconfirm the unexecuted draft instead of applying another column's resets.",
                        block_id=block["block_id"], column_id=coordinate["column_id"], retained_stages=selected)


def stage_execution_error(error: DocumentError, source: dict[str, Any], stages: list[dict[str, Any]]) -> TaskControlError:
    """Project the sealed executor refusal without implementing its rules twice."""
    result = TaskControlError("semantic_stage_time_invalid", str(error))
    result.issues = [{"path": "/intent/stages", "constraint": error.reason_code,
                      "source_path": source["path"], "source_sha256": source["sha256"],
                      "complete_stages": stages, "executor_issues": error.issues}]
    result.repair = {"action": "revise_intent", "message":
        "The registered cumulative-time executor requires finite strictly increasing time in each complete input stage. Preserve all original rows and missing coordinates; no row was dropped to make the transform legal. An explicit unshifted original-value XY intent remains available without cumulative assembly."}
    return result
