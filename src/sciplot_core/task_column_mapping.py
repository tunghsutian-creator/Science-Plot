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
from sciplot_core.data_mapping.table_choice import table_choice_snapshot, select_table, proposal_for_table_columns
from sciplot_core.data_mapping.contracts import DATA_MAPPING_EXECUTION_FILENAME
from sciplot_core.foundation.json_hashing import canonical_json_sha256
from sciplot_core.foundation.json_io import atomic_write_json
from sciplot_core.materials_rules.catalog import resolve_rule_template
from sciplot_core.task_contract import TaskControlError
from sciplot_core.task_storage import save_task


def column_question(source: Path, selected: dict[str, Any], *, explicit: bool = False) -> dict[str, Any] | None:
    snapshot = column_choice_snapshot(source, selected["rule_id"])
    if snapshot is None:
        table = table_choice_snapshot(source, selected["rule_id"]) if explicit or source.suffix.casefold() in {".xls", ".xlsx", ".xlsm"} else None
        if table is not None:
            question = {
                "field": "table_selection", "reason_code": "table_selection_required",
                "message": "请选择原始工作表、表头/单位/样品行和数据起止行；索引从 0 开始，结束行不包含在内。可再次回答 table_selection 更正区域。",
                "selection": {"rule_id": selected["rule_id"], "template": resolve_rule_template(selected["rule_id"], selected.get("template"))},
                "evidence": table,
            }
            question["question_id"] = canonical_json_sha256(question, allow_nan=False)
            return question
        if explicit:
            raise TaskControlError("column_mapping_unsupported", "列选择支持普通曲线规则的 CSV/TSV 和 Excel；需要原始坐标、单位和样品证据。")
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
            or not isinstance(choice, dict)
            or (set(choice) != {"pairs"} and (set(choice) != {"x_column", "y_column"}
            or any(type(value) is not int or value < 0 for value in choice.values())))):
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
        factory = proposal_for_table_columns if question["evidence"]["kind"] == "sciplot_table_columns" else proposal_for_column_choice
        values = response["column_mapping"]
        if factory is proposal_for_table_columns and "pairs" not in values:
            values = {"pairs": [values]}
        if factory is proposal_for_column_choice and "pairs" in values:
            raise ValueError("Use table_selection before selecting multiple pairs.")
        proposal = factory(
            question["evidence"], **values, request_path=request_path,
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


def accept_table_response(root: Path, state: dict[str, Any], response: dict[str, Any]) -> None:
    question = state["question"]
    if set(response) != {"expected_question_id", "table_selection"}:
        raise TaskControlError("invalid_task_response", "请回答 table_selection 并附当前 expected_question_id。")
    if response["expected_question_id"] != question["question_id"]:
        raise TaskControlError("stale_task_question", "此答案对应旧问题，请读取当前选择问题。")
    evidence = question["evidence"]
    snapshot = evidence.get("table_snapshot") or evidence
    if snapshot.get("kind") != "sciplot_table_choice":
        snapshot = table_choice_snapshot(Path(state["request"]["source"]), question["selection"]["rule_id"])
    try:
        columns = select_table(snapshot, response["table_selection"])
    except (ValueError, TypeError) as exc:
        raise TaskControlError("invalid_mapping_selection", str(exc)) from exc
    next_question = {"field": "column_mapping", "reason_code": "column_selection_required",
                     "message": "请查看逐列 rejection_reasons，确认 pairs；可用 metadata_confirmations 补充有证据的量名、单位和样品，或用 table_selection 更正区域。",
                     "selection": question["selection"], "evidence": columns}
    state.setdefault("scientific_choice_history", []).append({"question": question, "response": response})
    next_question["revision"] = len(state["scientific_choice_history"])
    next_question["question_id"] = canonical_json_sha256(next_question, allow_nan=False)
    state.pop("mapping_choice", None)
    state.pop("data_mapping", None)
    pause_for_columns(state, next_question)
    save_task(root, state)


def accept_metadata_response(root: Path, state: dict[str, Any], response: dict[str, Any]) -> None:
    question = state["question"]
    if question.get("field") != "column_mapping":
        raise TaskControlError("invalid_task_response", "请先用 table_selection 选择原始区域。")
    if set(response) != {"expected_question_id", "metadata_confirmations"}:
        raise TaskControlError("invalid_task_response", "Replace metadata_confirmations with the full current list and expected_question_id.")
    if response["expected_question_id"] != question["question_id"]:
        raise TaskControlError("stale_task_question", "此答案对应旧问题，请读取当前科学信息确认问题。")
    evidence = question["evidence"]
    if evidence.get("kind") != "sciplot_table_columns":
        raise TaskControlError("invalid_task_response", "请先用 table_selection 选择原始区域。")
    try:
        from sciplot_core.mapping_contract.table_metadata import validate_metadata_confirmations

        validate_metadata_confirmations(response["metadata_confirmations"])
        columns = select_table(evidence["table_snapshot"], evidence["table_selection"], response["metadata_confirmations"])
    except (ValueError, TypeError) as exc:
        raise TaskControlError("invalid_mapping_selection", str(exc)) from exc
    state.setdefault("scientific_choice_history", []).append({"question": question, "response": response})
    next_question = {"field": "column_mapping", "reason_code": "column_selection_required",
        "message": "请审阅 raw_metadata、metadata_confirmations 和逐列拒绝原因后选择 pairs。更正时提交完整 metadata_confirmations 列表；空列表撤回全部声明。冲突继续阻断。",
        "selection": question["selection"], "evidence": columns, "revision": len(state["scientific_choice_history"])}
    next_question["question_id"] = canonical_json_sha256(next_question, allow_nan=False)
    state.pop("mapping_choice", None)
    state.pop("data_mapping", None)
    state.pop("mapping_error", None)
    pause_for_columns(state, next_question)
    save_task(root, state)


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
