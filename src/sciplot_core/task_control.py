"""Public local task orchestration; no model, chat state or plotting reimplementation."""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from sciplot_core.foundation.source_tree import source_tree_sha256
from sciplot_core.output_contract import resolve_user_output_layout
from sciplot_core.studio_core.project_query import inspect_project, resolve_project_path
from sciplot_core.studio_core.project_query_paths import canonical_path
from sciplot_core.studio_core.project_session import external_project_session
from sciplot_core.task_contract import (
    TaskControlError, task_request_schema, task_response_schema, validate_task_request,
)
from sciplot_core.task_execution import (
    record_failure, run_apply_export, run_creation, run_edit_preview, run_export,
)
from sciplot_core.task_storage import (
    load_task, save_task, task_location, task_path, task_summary,
)


def start_task(
    request: dict[str, Any], *, task_dir: Path | None = None,
) -> dict[str, Any]:
    request = validate_task_request(request)
    if request["action"] == "create":
        source = canonical_path(Path(request["source"]))
        digest = source_tree_sha256(source)
        if digest is None:
            raise TaskControlError("source_not_found", "未找到原始数据文件或目录。")
        request["source"] = str(source)
    else:
        request["project"] = str(resolve_project_path(Path(request["project"])))
        digest = None
    for key in ("out", "profile"):
        if key in request:
            request[key] = str(canonical_path(Path(request[key])))
    root = task_location(request, task_dir)
    with external_project_session(root):
        if root.exists():
            state = load_task(root)
            if state["request"] != request:
                raise TaskControlError("task_already_exists", "此任务目录已用于其他请求。")
            return task_summary(state)
        root.mkdir(parents=True, mode=0o700)
        state = {
            "kind": "sciplot_task", "version": 1, "task_dir": str(root),
            "created_at": datetime.now(timezone.utc).isoformat(),
            "request": request, "source_sha256": digest,
            "status": "running", "phase": "starting",
        }
        save_task(root, state)
        try:
            if request["action"] == "create":
                run_creation(root, state)
            elif request["action"] == "edit":
                run_edit_preview(root, state)
            else:
                run_export(root, state)
        except (ValueError, OSError, RuntimeError) as exc:
            record_failure(root, state, exc)
        return task_summary(state)


def inspect_task(task: Path) -> dict[str, Any]:
    state = load_task(task_path(task))
    summary = task_summary(state)
    if state.get("project"):
        try:
            current = inspect_project(Path(state["project"]))
            summary["current_project"] = {
                key: current[key] for key in ("project", "source", "qa", "delivery")
                if key in current
            }
        except (ValueError, OSError, RuntimeError) as exc:
            summary["current_project"] = {"status": "unknown", "message": str(exc)}
    return summary


def _resume(root: Path, state: dict[str, Any], response: dict[str, Any]) -> None:
    if state["status"] in {"complete", "cancelled"}:
        return
    if state["status"] == "needs_input":
        if (
            set(response) - {"rule_id", "template"}
            or not isinstance(response.get("rule_id"), str)
            or not response["rule_id"].strip()
            or ("template" in response and (
                not isinstance(response["template"], str) or not response["template"].strip()
            ))
        ):
            raise TaskControlError("invalid_task_response", "请选择当前问题所需的实验规则。")
        state["selection"] = dict(response)
        run_creation(root, state)
    elif state["status"] == "needs_review":
        if set(response) != {"accept_preview"} or type(response["accept_preview"]) is not bool:
            raise TaskControlError("invalid_task_response", "请返回是否采纳当前预览。")
        if not response["accept_preview"]:
            state.update({"status": "cancelled", "phase": "finished"})
            save_task(root, state)
            return
        state["preview_accepted"] = True
        save_task(root, state)
        run_apply_export(root, state)
    else:
        if response != {"retry": True} or type(response.get("retry")) is not bool:
            raise TaskControlError("invalid_task_response", "修复具体问题后使用 retry=true。")
        phase = state["phase"]
        if phase == "exporting":
            run_export(root, state)
        elif phase == "applying" and state.get("preview_accepted") is True:
            run_apply_export(root, state)
        elif phase == "previewing":
            run_edit_preview(root, state)
        elif phase in {"planning", "creating", "starting"}:
            request = state["request"]
            if request["action"] != "create":
                raise TaskControlError("task_recovery_required", "请查询项目后开始新任务。")
            layout = resolve_user_output_layout(
                request["source"], requested_delivery_root=request.get("out"),
            )
            if layout.workspace_root.exists() or layout.delivery_root.exists():
                raise TaskControlError(
                    "creation_outcome_uncertain",
                    "建项可能已经执行。请查询现有输出，不会覆盖或自动创建第二份项目。",
                )
            run_creation(root, state)
        else:
            raise TaskControlError("task_recovery_required", "请查询当前任务的具体问题。")


def resume_task(task: Path, response: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(response, dict):
        raise TaskControlError("invalid_task_response", "任务答复必须是 JSON 对象。")
    root = task_path(task)
    with external_project_session(root):
        state = load_task(root)
        try:
            _resume(root, state, response)
        except TaskControlError as exc:
            if exc.reason_code == "invalid_task_response":
                raise
            record_failure(root, state, exc)
        except (ValueError, OSError, RuntimeError) as exc:
            record_failure(root, state, exc)
        return task_summary(state)


__all__ = ["start_task", "inspect_task", "resume_task", "task_request_schema", "task_response_schema"]
