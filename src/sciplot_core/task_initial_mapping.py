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


def apply_initial_mapping(root: Path, state: dict[str, Any], source: Path,
                          selected: dict[str, Any]) -> bool:
    """Return False for a correctable choice, preserving the current question."""
    mapping = state["request"]["mapping"]
    if not source.is_file() or file_sha256(source) != mapping["source_sha256"]:
        raise TaskControlError("source_changed", "mapping 的 SHA 与原文件不符；请重新读取当前原始数据。")
    if state.get("initial_mapping_attempted"):
        return False
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
        state["initial_mapping_attempted"] = True
        save_task(root, state)
        return False
    state["initial_mapping_attempted"] = True
    save_task(root, state)
    return True
