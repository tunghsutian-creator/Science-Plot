"""Find existing creation receipts by exact source identity without a project catalog."""

from __future__ import annotations

from itertools import chain
from pathlib import Path
from typing import Any

from sciplot_core.output_contract import resolve_user_output_layout
from sciplot_core.studio_core.project_query_evidence import _tree_hash
from sciplot_core.studio_core.project_query_paths import canonical_path
from sciplot_core.task_contract import TaskControlError
from sciplot_core.task_storage import load_task


MAX_SCAN_RECORDS = 1000
MAX_RECORD_BYTES = 16 * 1024 * 1024


def find_tasks(source: Path, *, tasks_root: Path | None = None, limit: int = 20) -> dict[str, Any]:
    """Read only a task root and its direct children; missing evidence stays unknown."""
    if type(limit) is not int or not 1 <= limit <= 100:
        raise TaskControlError("invalid_find_limit", "limit 必须为 1–100 的整数。")
    source = canonical_path(source)
    root = canonical_path(tasks_root or resolve_user_output_layout(source).workspace_root.parent / "tasks")
    if root.exists() and not root.is_dir():
        raise TaskControlError("invalid_tasks_root", "请提供保存任务记录的目录。")
    matches: list[dict[str, Any]] = []
    issues: list[dict[str, str]] = []
    scanned, skipped, scan_complete = 0, 0, True
    records = chain([root / "task.json"] if (root / "task.json").is_file() else [], root.glob("*/task.json"))
    for candidate in records:
        if scanned == MAX_SCAN_RECORDS:
            scan_complete = False
            break
        scanned += 1
        try:
            record = canonical_path(candidate)
            if record.stat().st_size > MAX_RECORD_BYTES:
                raise TaskControlError("task_record_too_large", "任务记录过大，请单独检查。")
            state = load_task(record.parent)
            request = state["request"]
            if request["action"] != "create" or canonical_path(Path(request["source"])) != source:
                continue
            selected = state.get("selection") or {}
            if (
                not isinstance(selected, dict)
                or not all(isinstance(state.get(key), str) for key in ("status", "phase"))
                or any(state.get(key) is not None and not isinstance(state[key], str)
                       for key in ("project", "updated_at", "source_sha256"))
            ):
                raise TaskControlError("invalid_task", "任务摘要字段格式不匹配。")
            matches.append({
                "task_dir": state["task_dir"], "status": state["status"], "phase": state["phase"],
                "updated_at": state.get("updated_at"), "project": state.get("project"),
                "rule_id": selected.get("rule_id") or request.get("rule_id"),
                "recorded_source_sha256": state.get("source_sha256"),
            })
        except (OSError, ValueError, TypeError, KeyError) as exc:
            skipped += 1
            if len(issues) < 10:
                issues.append({"task_dir": str(candidate.parent),
                               "reason_code": getattr(exc, "reason_code", "unreadable_task"),
                               "message": str(exc)[:500]})
    current_hash, source_error = None, None
    if matches:
        try:
            current_hash = _tree_hash(source)
        except (OSError, ValueError) as exc:
            source_error = str(exc)[:500]
    for match in matches:
        expected = match["recorded_source_sha256"]
        match["source_current"] = current_hash == expected if expected and source_error is None else None
    matches.sort(key=lambda item: (item["updated_at"] or "", item["task_dir"]), reverse=True)
    return {
        "kind": "sciplot_task_search", "version": 1, "status": "ok",
        "source": str(source), "source_sha256": current_hash, "source_error": source_error,
        "tasks_root": str(root), "tasks_root_exists": root.is_dir(),
        "scope": "Creation receipts in this root and its direct task directories; exact recorded source path only.",
        "scan_complete": scan_complete and skipped == 0, "scanned_records": scanned,
        "skipped_records": skipped, "issues": issues, "match_count": len(matches),
        "matches": matches[:limit], "has_more_matches": len(matches) > limit,
        "selection_required": len(matches) > 1 or not scan_complete or skipped > 0,
        "ready_to_use": None, "readiness_evaluated": False,
        "continuation_policy": "Inspect the selected task or recorded project before resuming. No result is auto-selected or re-created; project paths are historical references.",
    }
