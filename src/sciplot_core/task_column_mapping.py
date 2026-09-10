"""Bind one explicit column choice to the existing DataMapping transaction."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from sciplot_core.data_mapping import (
    create_data_mapping_confirmation, execute_data_mapping_proposal,
    preview_data_mapping_proposal,
)
from sciplot_core.data_mapping.column_choice import column_choice_snapshot, proposal_for_column_choice
from sciplot_core.data_mapping.contracts import DATA_MAPPING_EXECUTION_FILENAME
from sciplot_core.foundation.json_hashing import canonical_json_sha256
from sciplot_core.foundation.json_io import atomic_write_json
from sciplot_core.materials_rules.catalog import resolve_rule_template
from sciplot_core.task_contract import TaskControlError
from sciplot_core.task_storage import save_task


def column_question(source: Path, selected: dict[str, Any], *, explicit: bool = False) -> dict[str, Any] | None:
    snapshot = column_choice_snapshot(source, selected["rule_id"])
    if snapshot is None:
        if explicit:
            raise TaskControlError("column_mapping_unsupported", "列选择仅支持已有普通曲线规则的 CSV/TSV，需明确单位及单行或规范三行表头。")
        return None
    x_columns = [column for column in snapshot["columns"] if column["x_eligible"]]
    y_columns = [column for column in snapshot["columns"] if column["y_eligible"]]
    # Normal multi-sample paired tables retain their existing all-sample route.
    if not explicit and not (len(x_columns) == 1 and len(y_columns) > 1):
        return None
    if not x_columns or not y_columns:
        if explicit:
            raise TaskControlError("column_mapping_unsupported", "原始表头未提供与此实验一致的坐标、响应及单位，不能通过选列补造科学事实。")
        return None
    question = {
        "field": "column_mapping", "reason_code": "column_selection_required",
        "message": "请选择本图的一对 x/y 原始列（索引从 0 开始）。本图只使用所选两列，其他列保留在原始文件。",
        "selection": {"rule_id": selected["rule_id"], "template": resolve_rule_template(selected["rule_id"], selected.get("template"))},
        "evidence": snapshot,
    }
    question["question_id"] = canonical_json_sha256(question, allow_nan=False)
    return question


def pause_for_columns(state: dict[str, Any], question: dict[str, Any]) -> None:
    state.pop("blocker", None)
    state.update(status="needs_input", phase="scientific_choice", question=question,
                 selection=question["selection"])


def validate_column_response(state: dict[str, Any], response: dict[str, Any]) -> None:
    question = state["question"]
    choice = response.get("column_mapping")
    if (set(response) != {"expected_question_id", "column_mapping"}
            or not isinstance(choice, dict) or set(choice) != {"x_column", "y_column"}
            or any(type(value) is not int or value < 0 for value in choice.values())):
        raise TaskControlError("invalid_task_response", "请回答 column_mapping 的 x_column/y_column，并附当前 expected_question_id。")
    if response["expected_question_id"] != question["question_id"]:
        raise TaskControlError("stale_task_question", "此答案对应旧问题，请读取当前列选择问题。")


def accept_column_response(root: Path, state: dict[str, Any], response: dict[str, Any]) -> None:
    validate_column_response(state, response)
    question = state["question"]
    answer_id = canonical_json_sha256(response, allow_nan=False)
    attempt = root / "column_choices" / answer_id
    attempt.mkdir(parents=True, exist_ok=True)
    request_path = attempt / "request.json"
    seed = {
        "input": state["request"]["source"], "output": str(attempt / "run"),
        **question["selection"], "exports": ["pdf", "tiff_300"],
    }
    if request_path.exists():
        if json.loads(request_path.read_text()) != seed:
            raise TaskControlError("task_mapping_changed", "原始映射请求记录已变化。")
    else:
        atomic_write_json(request_path, seed)
    try:
        proposal = proposal_for_column_choice(
            question["evidence"], **response["column_mapping"], request_path=request_path,
            proposal_id=f"columns_{answer_id}", created_at=state["created_at"],
        )
        preview_data_mapping_proposal(proposal, source_root=Path(seed["input"]).parent,
                                      request_path=request_path)
    except ValueError as exc:
        raise TaskControlError("invalid_mapping_selection", str(exc)) from exc
    proposal_path = attempt / "proposal.json"
    receipt_path = attempt / "confirmation.json"
    if proposal_path.exists() and json.loads(proposal_path.read_text()) != proposal.to_dict():
        raise TaskControlError("task_mapping_changed", "已保存的列映射提案发生变化。")
    atomic_write_json(proposal_path, proposal.to_dict())
    if not receipt_path.exists():
        receipt = create_data_mapping_confirmation(
            proposal, source_root=Path(seed["input"]).parent, request_path=request_path,
            output_root=attempt / "execution", confirmed_by="external_task_column_selection",
        )
        atomic_write_json(receipt_path, receipt.to_dict())
    state["mapping_choice"] = {
        "response": response, "question": question, "request_path": str(request_path),
        "proposal_path": str(proposal_path), "confirmation_path": str(receipt_path),
        "output_root": str(attempt / "execution"),
    }
    save_task(root, state)  # Recover the same confirmation if materialization is interrupted.


def mapped_plan_request(state: dict[str, Any]) -> dict[str, Any]:
    choice = state["mapping_choice"]
    result = execute_data_mapping_proposal(
        choice["proposal_path"], choice["confirmation_path"],
        source_root=Path(state["request"]["source"]).parent,
        request_path=choice["request_path"], output_root=choice["output_root"],
    )
    state["data_mapping"] = {
        "data_mapping_execution": str(Path(result["output_root"]) / DATA_MAPPING_EXECUTION_FILENAME),
        "data_mapping_proposal_id": result["proposal_id"],
    }
    return {**choice["question"]["selection"], **state["data_mapping"]}
