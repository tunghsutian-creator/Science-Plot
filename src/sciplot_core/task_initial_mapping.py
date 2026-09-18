"""Consume caller-reviewed source-bound choices in one local task call."""

from pathlib import Path
from typing import Any

from sciplot_core.foundation.file_hashing import file_sha256
from sciplot_core.task_column_mapping import (
    accept_column_response, accept_metadata_response, accept_table_response,
    pause_for_columns, table_question,
)
from sciplot_core.task_contract import TaskControlError
from sciplot_core.task_storage import save_task
from sciplot_core.materials_rules.catalog import resolve_rule_template
from sciplot_core.task_choice_schema import mapping_response_schema
from jsonschema import Draft202012Validator


def apply_initial_mapping(root: Path, state: dict[str, Any], source: Path,
                          selected: dict[str, Any]) -> bool:
    """Return False for a correctable choice, preserving the current question."""
    mapping = state["request"]["mapping"]
    if not source.is_file() or file_sha256(source) != mapping["source_sha256"]:
        raise TaskControlError("source_changed", "mapping 的 SHA 与原文件不符；请重新读取当前原始数据。")
    if state.get("initial_mapping_attempted"):
        return False
    result = apply_mapping_choices(root, state, mapping, source, selected)
    state["initial_mapping_attempted"] = True
    save_task(root, state)
    return result


def apply_mapping_choices(root: Path, state: dict[str, Any], mapping: dict[str, Any],
                          source: Path, selected: dict[str, Any]) -> bool:
    """Run the same checked choices locally, stopping only at an actual error."""
    if not source.is_file() or file_sha256(source) != mapping["source_sha256"]:
        raise TaskControlError("source_changed", "mapping 的 SHA 与原文件不符；请重新读取当前原始数据。")
    question = table_question(source, selected)
    if question is None:
        raise TaskControlError("column_mapping_unsupported", "此来源不支持原表区域映射。")
    pause_for_columns(state, question)
    try:
        accept_table_response(root, state, {
            "expected_question_id": state["question"]["question_id"],
            "table_selection": mapping["table_selection"],
        })
        if "metadata_confirmations" in mapping:
            accept_metadata_response(root, state, {
                "expected_question_id": state["question"]["question_id"],
                "metadata_confirmations": mapping["metadata_confirmations"],
            })
        accept_column_response(root, state, {
            "expected_question_id": state["question"]["question_id"],
            "column_mapping": mapping["column_mapping"],
        })
    except TaskControlError as exc:
        if exc.reason_code != "invalid_mapping_selection":
            raise
        state["mapping_error"] = {"reason_code": exc.reason_code, "message": str(exc)}
        save_task(root, state)
        return False
    state.pop("mapping_error", None)
    save_task(root, state)
    return True


def accept_mapping_response(root: Path, state: dict[str, Any], response: dict[str, Any]) -> bool:
    """Bind a single recovery decision before any native project is created."""
    if not Draft202012Validator(mapping_response_schema()).is_valid(response):
        raise TaskControlError("invalid_task_response", "提交 expected_question_id 和完整 mapping；可一起指定 rule_id/template。")
    question = state.get("question") or {}
    if (state["status"] != "needs_input" or question.get("field") not in {"rule_id", "table_selection", "column_mapping"}
            or state["request"]["action"] not in {"create", "update_source"}):
        raise TaskControlError("invalid_task_response", "当前任务没有可更正的原表选择问题。")
    if response["expected_question_id"] != question.get("question_id"):
        raise TaskControlError("stale_task_question", "此答案对应旧问题，请使用当前 question_id。")
    selected = dict(question.get("selection") or state.get("selection") or {})
    selected.update({key: response[key] for key in ("rule_id", "template") if key in response})
    if "rule_id" not in selected:
        raise TaskControlError("invalid_task_response", "本次 mapping 需要一起指定原数据对应的 rule_id。")
    if state["request"]["action"] == "update_source" and selected != question.get("selection"):
        raise TaskControlError("invalid_task_response", "源更新必须保留当前项目的实验规则和模板。")
    try:
        selected["template"] = resolve_rule_template(selected["rule_id"], selected.get("template"))
    except ValueError as exc:
        raise TaskControlError("invalid_task_response", str(exc)) from exc
    source = Path(state["request"]["source"])
    if not source.is_file() or file_sha256(source) != response["mapping"]["source_sha256"]:
        state["mapping_error"] = {"reason_code": "mapping_source_mismatch",
                                  "message": "答案的 SHA 与当前原文件不符；使用当前问题中的 file_sha256 更正答案。"}
        save_task(root, state)
        return False
    state["pending_mapping_response"] = {"response": response, "selection": selected}
    save_task(root, state)
    return resume_mapping_response(root, state)


def resume_mapping_response(root: Path, state: dict[str, Any]) -> bool:
    pending = state["pending_mapping_response"]
    if state.get("mapping_choice"):
        result = True  # Reuse a checkpointed confirmation after interruption.
    else:
        result = apply_mapping_choices(root, state, pending["response"]["mapping"],
                                       Path(state["request"]["source"]), pending["selection"])
    state.pop("pending_mapping_response", None)
    state["initial_mapping_attempted"] = True  # Never replay superseded create.mapping.
    save_task(root, state)
    return result


def candidate_mapping_response(state: dict[str, Any], response: dict[str, Any]) -> dict[str, Any]:
    from copy import deepcopy
    from sciplot_core.task_choice_schema import mapping_candidate_response_schema

    if not Draft202012Validator(mapping_candidate_response_schema()).is_valid(response):
        raise TaskControlError("invalid_task_response", "Select mapping_candidate_id with current expected_question_id and optional unique pair_indices.")
    question = state.get("question") or {}
    if response["expected_question_id"] != question.get("question_id"):
        raise TaskControlError("stale_task_question", "此候选答案对应旧问题，请使用当前 question_id。")
    candidate = next((item for item in question.get("mapping_candidates", [])
                      if item["candidate_id"] == response["mapping_candidate_id"]), None)
    if candidate is None:
        raise TaskControlError("invalid_mapping_candidate", "Select a candidate_id advertised in the current question.")
    mapping = deepcopy(candidate["mapping"])
    if "pair_indices" in response:
        pairs = mapping["column_mapping"]["pairs"]
        if any(index >= len(pairs) for index in response["pair_indices"]):
            raise TaskControlError("invalid_mapping_candidate", "pair_indices must refer to the advertised candidate pairs.")
        mapping["column_mapping"]["pairs"] = [pairs[index] for index in response["pair_indices"]]
    return {"expected_question_id": response["expected_question_id"], "mapping": mapping}
