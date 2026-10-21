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


def replicate_mapping_mode(state: dict[str, Any], selected: dict[str, Any]) -> bool:
    """Share scientific shape selection between initial, interactive and update choices."""
    from sciplot_core.data_mapping.curve_support import table_mapping_shape
    from sciplot_core.materials_rules import get_rule

    summary = state["request"].get("summary_statistic")
    if state["request"]["action"] == "update_source":
        from sciplot_core.data_mapping.plan_binding import project_replicate_binding

        previous = json.loads((Path(state["request"]["project"]) / "plot_request.json").read_text())
        summary = "raw_only" if project_replicate_binding(previous) is not None else None
    return table_mapping_shape(get_rule(selected["rule_id"]), summary_statistic=summary) == "replicates"


def table_question(source: Path, selected: dict[str, Any], *, mapping_shape: str = "xy") -> dict[str, Any] | None:
    if mapping_shape == "replicates":
        from sciplot_core.data_mapping.table_choice import source_table_snapshot
        from sciplot_core.data_mapping.curve_support import supports_replicate_mapping
        from sciplot_core.materials_rules import get_rule

        table = source_table_snapshot(source, rule_id=selected["rule_id"]) if supports_replicate_mapping(get_rule(selected["rule_id"])) else None
    else:
        table = table_choice_snapshot(source, selected["rule_id"])
    if table is not None:
        from sciplot_core.data_mapping.table_diagnostics import table_diagnostics

        question: dict[str, Any] = {
            "field": "table_selection", "reason_code": "table_selection_required",
            "message": "原表布局需要明确选择。可一次回复 mapping 指定工作表、行范围、元数据及 XY 列；索引从 0 开始，结束行不包含在内。无需另建源文件或重建任务。",
            "selection": {"rule_id": selected["rule_id"], "template": resolve_rule_template(selected["rule_id"], selected.get("template"))},
            "evidence": table,
            "diagnostics": table_diagnostics(table),
        }
        if mapping_shape == "replicates":
            question.update(mapping_shape="replicates", message="Select original sheet, metadata/data rows and independent replicate columns. Keep complete original row domains and missing positions; no X coordinate or summary is inferred.")
        from sciplot_core.data_mapping.table_candidates import wide_table_candidates

        candidates = wide_table_candidates(table, question["diagnostics"]) if mapping_shape == "xy" else []
        if candidates:
            question["mapping_candidates"] = candidates
        if selected["rule_id"] == "ftir_spectrum":
            question["metadata_hint"] = (
                "For explicit %T data use quantity='%T', unit='%' (unchanged numeric values); "
                "Absorbance and Spectral response are different identities. Declare quantity/unit/sample "
                "for every selected Y column missing that metadata. sheet is the target worksheet; "
                "evidence.sheet may cite a note elsewhere in the same workbook."
            )
        question["question_id"] = canonical_json_sha256(question, allow_nan=False)
        return question
    return None


def column_question(source: Path, selected: dict[str, Any], *, explicit: bool = False,
                    mapping_shape: str = "xy") -> dict[str, Any] | None:
    if mapping_shape == "replicates":
        return table_question(source, selected, mapping_shape=mapping_shape) if explicit else None
    snapshot = column_choice_snapshot(source, selected["rule_id"])
    if snapshot is None:
        question = table_question(source, selected) if explicit or source.suffix.casefold() in {".xls", ".xlsx", ".xlsm"} else None
        if question is not None:
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
    from jsonschema import Draft202012Validator
    from sciplot_core.task_choice_schema import column_mapping_schema

    question = state["question"]
    choice = response.get("column_mapping")
    if (set(response) != {"expected_question_id", "column_mapping"} or not isinstance(choice, dict)
            or not Draft202012Validator(column_mapping_schema()).is_valid(choice)):
        raise TaskControlError("invalid_task_response", "请回答 column_mapping 的 x_column/y_column，并附当前 expected_question_id。")
    replicate_question = question.get("mapping_shape") == "replicates"
    if ("replicates" in choice) != replicate_question or (
            replicate_question and not replicate_mapping_mode(state, question["selection"])):
        raise TaskControlError("invalid_mapping_selection", "Use the advertised source shape: independent replicate columns require the current raw-only replicate question.")
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
        **({"xscale": state["request"]["xscale"]} if "xscale" in state["request"] else {}),
        **({"summary_statistic": "raw_only"} if question.get("mapping_shape") == "replicates" else {}),
    }
    if request_path.exists():
        if json.loads(request_path.read_text()) != seed:
            raise TaskControlError("task_mapping_changed", "原始映射请求记录已变化。")
    else:
        atomic_write_json(request_path, seed)
    try:
        factory = proposal_for_table_columns if question["evidence"]["kind"] == "sciplot_table_columns" else proposal_for_column_choice
        values = response["column_mapping"]
        if factory is proposal_for_table_columns and not ({"pairs", "replicates"} & set(values)):
            values = {"pairs": [values]}
        if factory is proposal_for_column_choice and (not {"x_column", "y_column"} <= set(values)
                                                     or set(values) - {"x_column", "y_column", "label"}):
            raise ValueError("Use table_selection before selecting multiple pairs.")
        proposal = factory(
            question["evidence"], **values, request_path=request_path,
            proposal_id=f"columns_{answer_id}", created_at=state["created_at"],
        )
        preview_data_mapping_proposal(proposal, source_root=Path(seed["input"]).parent,
                                      request_path=request_path)
    except ValueError as exc:
        error = TaskControlError("invalid_mapping_selection", str(exc))
        error.issues = getattr(exc, "issues", None)
        raise error from exc
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
                     "message": "请查看逐列 rejection_reasons，确认 pairs。每组可指定独立的完整 table_selection 和 metadata_confirmations；另一工作表不继承声明。可用 metadata_confirmations 补充有证据的量名、单位和样品，或用 table_selection 更正默认区域。",
                     "selection": question["selection"], "evidence": columns}
    if question.get("mapping_shape") == "replicates":
        next_question.update(mapping_shape="replicates", message="Select column_mapping.replicates using original physical column indices. Each group may override the complete original table_selection; original metric, sample, unit and full row mask remain bound.")
    state.setdefault("scientific_choice_history", []).append({"question": question, "response": response})
    next_question["revision"] = len(state["scientific_choice_history"])
    if "metadata_hint" in question:
        next_question["metadata_hint"] = question["metadata_hint"]
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
    if question.get("mapping_shape") == "replicates":
        next_question["mapping_shape"] = "replicates"
    if "metadata_hint" in question:
        next_question["metadata_hint"] = question["metadata_hint"]
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
