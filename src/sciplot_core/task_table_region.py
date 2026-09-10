"""Read a bounded original rectangle without changing a pending task question."""

from pathlib import Path
from typing import Any

from jsonschema import Draft202012Validator

from sciplot_core.data_mapping.table_choice import _read, _original_text, table_choice_snapshot
from sciplot_core.foundation.file_hashing import file_sha256
from sciplot_core.task_choice_schema import table_region_schema
from sciplot_core.task_contract import TaskControlError
from sciplot_core.task_storage import load_task, task_path


def inspect_table_region(task: Path, query: dict[str, Any]) -> dict[str, Any]:
    errors = list(Draft202012Validator(table_region_schema()).iter_errors(query))
    if errors:
        raise TaskControlError("invalid_task_response", errors[0].message)
    state = load_task(task_path(task))
    question = state.get("question", {})
    if state["status"] != "needs_input" or question.get("field") not in {"table_selection", "column_mapping"}:
        raise TaskControlError("invalid_task_response", "Original region queries require a pending table/column question.")
    if query["expected_question_id"] != question["question_id"]:
        raise TaskControlError("stale_task_question", "Query the current table question before reading its cells.")
    evidence = question["evidence"]
    source = Path(state["request"]["source"])
    digest = evidence["file_sha256"]
    if file_sha256(source) != digest:
        raise TaskControlError("stale_task_question", "Original source bytes changed.")
    snapshot = evidence.get("table_snapshot", evidence)
    if snapshot["kind"] != "sciplot_table_choice":
        snapshot = table_choice_snapshot(source, evidence["rule_id"])
    if snapshot is None or query["sheet"] not in [item["sheet"] for item in snapshot["tables"]]:
        raise TaskControlError("invalid_task_response", "Select an exact original worksheet name.")
    rs, re, cs, ce = (query[key] for key in ("row_start", "row_end", "column_start", "column_end"))
    if not (rs < re <= rs + 128 and cs < ce <= cs + 64):
        raise TaskControlError("invalid_task_response", "Region bounds must increase; at most 128 rows and 64 columns per query.")
    frame = _read(source, query["sheet"], digest)
    if re > len(frame) or ce > frame.shape[1]:
        raise TaskControlError("invalid_task_response", "Region is outside the original table.")
    rows = [{"row_index": row, "cells": [
        {"column_index": column, "text": _original_text(frame.iat[row, column])}
        for column in range(cs, ce)]} for row in range(rs, re)]
    if file_sha256(source) != digest:
        raise TaskControlError("stale_task_question", "Original source changed during region query.")
    return {"kind": "sciplot_original_table_region", "version": 1, "source": str(source),
            "source_sha256": digest, **query, "rows": rows, "writes_performed": False,
            "cell_values": "decoded original values; formulas/styles/merged-cell expansion are not inferred"}
