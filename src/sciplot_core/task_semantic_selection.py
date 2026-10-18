"""Select existing source blocks before mapping or scientific execution.

References are local to the exact source SHA and observed physical regions.
Selection never edits raw cells or renumbers retained source/table/block IDs.
"""
from copy import deepcopy
from typing import Any, NoReturn

from sciplot_core.task_errors import TaskControlError


def _reference(block: dict[str, Any]) -> dict[str, str]:
    return {name: block[name] for name in ("source_id", "table_id", "block_id")}


def _key(block: dict[str, Any]) -> tuple[str, str, str]:
    return block["source_id"], block["table_id"], block["block_id"]


def _reject(reason: str, message: str, available: list[dict[str, Any]], **facts: Any) -> NoReturn:
    error = TaskControlError(reason, message)
    error.issues = [{"path": "/intent/selection", "constraint": reason, **facts}]
    error.repair = {"action": "revise_intent", "supported_selectors": ["intent.selection.test_names", "intent.selection.blocks"],
                    "available_blocks": deepcopy(available),
                    "message": "Revise this same draft using exact observed Test names or qualified source/table/block references. Both selectors intersect; no raw file or existing project was changed."}
    raise error


def select_source_blocks(sources: list[dict[str, Any]], selection: dict[str, Any] | None) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """Project selected copies and retain every available/excluded original block."""
    available: list[dict[str, Any]] = []
    for source in sources:
        for candidate in source["candidates"]:
            for block in candidate["blocks"]:
                count = block.get("point_count", sum(segment["point_count"] for segment in block["segments"])
                                  if block.get("segments") else block["data_end_row"] - block["data_start_row"])
                fact: dict[str, Any] = {"source_id": source["source_id"], "table_id": candidate["candidate_id"],
                        "block_id": block["block_id"], "source_sha256": source["sha256"],
                        "data_start_row": block["data_start_row"], "data_end_row": block["data_end_row"],
                        "point_count": count, "order": block["order"]}
                for name in ("test_name", "test_row", "result", "result_row", "sample", "label", "source_interval"):
                    if name in block:
                        fact[name] = deepcopy(block[name])
                available.append(fact)
    keys = [_key(block) for block in available]
    if len(keys) != len(set(keys)):
        _reject("semantic_source_selection_ambiguous", "Source block references are not unique; no ambiguous original block was selected.", available)
    selector = selection or {}
    tests = selector.get("test_names")
    references = selector.get("blocks")
    if tests is not None:
        observed = {block["test_name"] for block in available if "test_name" in block}
        if not observed:
            _reject("semantic_test_selection_unavailable", "These originals have no literal Test metadata. A filename or inferred sample cannot substitute for an observed Test name.", available)
        unmatched = [name for name in tests if name not in observed]
        if unmatched:
            _reject("semantic_source_selection_unmatched", "Every requested Test name must match literal original metadata exactly; no fuzzy or partial match was used.", available, unmatched_test_names=unmatched)
    if references is not None:
        unmatched_blocks = [reference for reference in references if _key(reference) not in keys]
        if unmatched_blocks:
            _reject("semantic_source_selection_unmatched", "Every requested block must identify an observed source/table/block in this exact source plan.", available, unmatched_blocks=unmatched_blocks)
    wanted = {_key(reference) for reference in references} if references is not None else None
    selected, excluded = [], []
    for block in available:
        reasons = []
        if tests is not None and block.get("test_name") not in tests:
            reasons.append("test_name_not_selected")
        if wanted is not None and _key(block) not in wanted:
            reasons.append("block_not_selected")
        if reasons:
            excluded.append({**_reference(block), "reasons": reasons})
        else:
            selected.append(_reference(block))
    if not selected:
        _reject("semantic_source_selection_empty", "The explicit Test and block predicates have no common original block; no fallback to all rows was performed.", available)
    selected_keys = {_key(block) for block in selected}
    projected = []
    for source in sources:
        retained = deepcopy(source)
        retained["candidates"] = []
        for candidate in source["candidates"]:
            blocks = [block for block in candidate["blocks"]
                      if (source["source_id"], candidate["candidate_id"], block["block_id"]) in selected_keys]
            if blocks:
                retained["candidates"].append({**deepcopy(candidate), "blocks": deepcopy(blocks)})
        if retained["candidates"]:
            projected.append(retained)
    return projected, {"mode": "explicit" if selection is not None else "all_original_blocks",
                       "selector": deepcopy(selector), "available": available, "selected": selected, "excluded": excluded,
                       "reference_scope": "exact original source SHA, table and physical rows; IDs are not rebound across source revisions"}


def selection_for_choices(report: dict[str, Any], choices: dict[str, Any]) -> dict[str, Any]:
    """Keep later confirmed table choices in the same selection provenance."""
    current = deepcopy(report)
    tables = choices.get("tables", {})
    retained = []
    for block in current["selected"]:
        if block["source_id"] in tables and block["table_id"] != tables[block["source_id"]]:
            current["excluded"].append({**block, "reasons": ["table_not_selected"]})
        else:
            retained.append(block)
    current["selected"] = retained
    return current


def selection_summary(report: dict[str, Any], choices: dict[str, Any] | None = None) -> dict[str, Any]:
    """Publish original identities/counts/reasons without coordinate arrays."""
    report = selection_for_choices(report, choices or {})
    by_key = {_key(block): block for block in report["available"]}
    return {"mode": report["mode"], "selector": deepcopy(report["selector"]),
            "available_block_count": len(report["available"]),
            "selected_block_count": len(report["selected"]),
            "selected_point_count": sum(by_key[_key(block)]["point_count"] for block in report["selected"]),
            "selected": [deepcopy(by_key[_key(block)]) for block in report["selected"]],
            "excluded": [{**deepcopy(by_key[_key(block)]), "reasons": list(block["reasons"])}
                         for block in report["excluded"]]}
