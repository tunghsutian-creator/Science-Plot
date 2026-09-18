"""Public local task orchestration; no model, chat state or plotting reimplementation."""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from subprocess import TimeoutExpired
from typing import Any

from sciplot_core.foundation.source_tree import source_tree_sha256
from sciplot_core.output_contract import resolve_user_output_layout
from sciplot_core.source_tables.read_session import with_table_reads
from sciplot_core.task_timing import timed_task_call, finish_timing, observe_phase
from sciplot_core.studio_core.annotation_schema import validate_operation_batch
from sciplot_core.studio_core.project_query import inspect_project, resolve_project_path
from sciplot_core.studio_core.project_query_paths import canonical_path
from sciplot_core.studio_core.project_session import external_project_session
from sciplot_core.task_contract import (
    TaskControlError, task_request_schema, task_response_schema, validate_task_request,
)
from sciplot_core.task_execution import (
    record_failure, run_apply_export, run_creation, run_edit_preview, run_export,
)
from sciplot_core.task_column_mapping import accept_column_response, accept_table_response
from sciplot_core.task_planning import assert_source_current
from sciplot_core.task_source_execution import accept_annotation_response, run_source_apply_export, run_source_preview, validate_source_response
from sciplot_core.task_editing import begin_preview_revision, validate_preview_response
from sciplot_core.task_repair import normalize_task_location, request_repair, response_repair
from sciplot_core.task_output_choice import accept_output_response, creation_output
from sciplot_core.task_storage import (
    load_task, save_task, task_location, task_path, task_summary,
)


def _finished_call(root: Path, state: dict[str, Any]) -> dict[str, Any]:
    if state["status"] == "complete":
        observe_phase(root, {"phase": "checking_current_project"})
    result = _current_result(state) if state["status"] == "complete" else None
    finish_timing(state)
    save_task(root, state)
    return {**task_summary(state), **({key: result[key] for key in ("current_project", "next_step") if key in result} if result else {})}


def _current_result(state: dict[str, Any]) -> dict[str, Any]:
    summary = task_summary(state)
    if state.get("project"):
        try:
            current = inspect_project(Path(state["project"]))
            summary["current_project"] = {key: current[key] for key in (
                "project", "primary_figure_id", "figures", "source", "qa", "delivery",
                "ready_to_use", "readiness_evaluated", "document_authority", "live_gui_state_evaluated",
            ) if key in current}
            if (state["status"] == "complete" and (state.get("result", {}).get("studio_run") or {}).get("ready_to_use") is True
                    and all((current.get(key) or {}).get("current") is True for key in ("source", "qa", "delivery"))):
                summary["next_step"] = {
                    "action": "review_exports_and_deliver", "task": state["task_dir"],
                    "images": [item["path"] for figure in state["result"].get("figures", [])
                               for item in figure.get("exports", []) if item.get("format") == "tiff"],
                    "message": "Current source/QA/delivery were queried in this call. Review the exported images, then deliver; requery after later changes. No additional native preview or inspect is required for this unchanged result.",
                }
        except (ValueError, OSError, RuntimeError, TimeoutExpired) as exc:
            summary["current_project"] = {"status": "unknown", "message": str(exc)}
    return summary


@with_table_reads
@timed_task_call
def start_task(
    request: dict[str, Any], *, task_dir: Path | None = None,
) -> dict[str, Any]:
    original_request = request
    try:
        request, task_dir, corrections = normalize_task_location(request, task_dir)
        request = validate_task_request(request)
    except TaskControlError as exc:
        exc.repair = request_repair(original_request, exc)
        raise
    if request["action"] == "edit":
        validate_operation_batch(request["operations"])
    if request["action"] in {"create", "update_source"}:
        source = canonical_path(Path(request["source"]))
        digest = source_tree_sha256(source)
        if digest is None:
            raise TaskControlError("source_not_found", "未找到原始数据文件或目录。")
        request["source"] = str(source)
    else:
        digest = None
    if request["action"] != "create":
        request["project"] = str(resolve_project_path(Path(request["project"])))
    for key in ("out", "profile"):
        if key in request:
            request[key] = str(canonical_path(Path(request[key])))
    root = task_location(request, task_dir)
    root.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    with external_project_session(root):
        if root.exists():
            state = load_task(root)
            if state["request"] != request:
                raise TaskControlError("task_already_exists", "此任务目录已用于其他请求。")
            return _current_result(state) if state["status"] == "complete" else task_summary(state)
        root.mkdir(parents=True, mode=0o700)
        state = {
            "kind": "sciplot_task", "version": 1, "task_dir": str(root),
            "created_at": datetime.now(timezone.utc).isoformat(),
            "request": request, "source_sha256": digest,
            "status": "running", "phase": "starting",
            **({"automatic_corrections": corrections} if corrections else {}),
        }
        save_task(root, state)
        try:
            if request["action"] == "create":
                run_creation(root, state)
            elif request["action"] == "edit":
                run_edit_preview(root, state)
            elif request["action"] == "update_source":
                run_source_preview(root, state)
            else:
                run_export(root, state)
        except (ValueError, OSError, RuntimeError, TimeoutExpired) as exc:
            record_failure(root, state, exc)
        return _finished_call(root, state)


@with_table_reads
def inspect_task(task: Path) -> dict[str, Any]:
    state = load_task(task_path(task))
    return _current_result(state)


def _resume(root: Path, state: dict[str, Any], response: dict[str, Any]) -> None:
    if "revise_operations" in response:
        if begin_preview_revision(state, response):
            run_edit_preview(root, state)
        return
    if state["status"] in {"complete", "cancelled"}:
        return
    if "out" in response:
        assert_source_current(state)
        accept_output_response(state, response)
        save_task(root, state)
        run_creation(root, state)
        return
    if "mapping_candidate_id" in response:
        from sciplot_core.task_initial_mapping import candidate_mapping_response

        response = candidate_mapping_response(state, response)
    if "mapping" in response or (response == {"retry": True} and state.get("pending_mapping_response")):
        from sciplot_core.task_initial_mapping import accept_mapping_response, resume_mapping_response

        if state["request"]["action"] not in {"create", "update_source"}:
            raise TaskControlError("invalid_task_response", "当前操作没有原表映射恢复阶段。")
        assert_source_current(state)
        ready = (accept_mapping_response(root, state, response) if "mapping" in response
                 else resume_mapping_response(root, state))
        if ready:
            if state["request"]["action"] == "update_source":
                run_source_preview(root, state)
            else:
                run_creation(root, state)
        return
    if (response == {"retry": True} and response.get("retry") is True
            and state["request"]["action"] == "create" and state["request"].get("mapping")
            and state.get("phase") == "scientific_choice" and not state.get("initial_mapping_attempted")
            and not state.get("project")):
        # An interrupted batch may checkpoint one question/confirmation. Resume
        # only the caller's original explicit choices, before any native creation.
        run_creation(root, state)
        return
    if (response == {"retry": True} and state.get("mapping_choice")
            and state.get("phase") == "scientific_choice" and state["request"]["action"] == "create"
            and not state.get("project")):
        run_creation(root, state)
        return
    if state["status"] == "needs_input":
        if "metadata_confirmations" in response:
            from sciplot_core.task_column_mapping import accept_metadata_response

            assert_source_current(state)
            accept_metadata_response(root, state, response)
            return
        if state["question"].get("field") == "annotation_rebinding":
            assert_source_current(state)
            accept_annotation_response(root, state, response)
            return
        if state["question"].get("field") == "table_selection" or "table_selection" in response:
            assert_source_current(state)
            accept_table_response(root, state, response)
            return
        if state["question"].get("field") == "column_mapping":
            assert_source_current(state)
            accept_column_response(root, state, response)
            if state["request"]["action"] == "update_source":
                run_source_preview(root, state)
            else:
                run_creation(root, state)
            return
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
        if state["request"]["action"] == "update_source":
            validate_source_response(state, response)
            if not response["accept_source_update"]:
                state.update(status="cancelled", phase="finished")
                save_task(root, state)
                return
            state["preview_accepted"] = True
            save_task(root, state)
            run_source_apply_export(root, state)
            return
        validate_preview_response(state, response)
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
        if state["request"]["action"] == "update_source":
            if phase == "exporting":
                run_export(root, state)
            elif phase == "applying" and state.get("preview_accepted") is True:
                run_source_apply_export(root, state)
            elif phase in {"starting", "previewing", "scientific_choice"}:
                run_source_preview(root, state)
            else:
                raise TaskControlError("task_recovery_required", "请查询源更新任务的具体状态。")
            return
        if phase == "exporting":
            run_export(root, state)
        elif phase == "applying" and state.get("preview_accepted") is True:
            run_apply_export(root, state)
        elif phase == "previewing":
            run_edit_preview(root, state)
        elif phase == "starting" and state["request"]["action"] == "edit":
            run_edit_preview(root, state)
        elif phase == "starting" and state["request"]["action"] == "export":
            run_export(root, state)
        elif phase in {"planning", "creating", "starting"}:
            request = state["request"]
            if request["action"] != "create":
                raise TaskControlError("task_recovery_required", "请查询项目后开始新任务。")
            layout = resolve_user_output_layout(
                request["source"], requested_delivery_root=creation_output(state),
            )
            if layout.workspace_root.exists() or layout.delivery_root.exists():
                raise TaskControlError(
                    "creation_outcome_uncertain",
                    "建项可能已经执行。请查询现有输出，不会覆盖或自动创建第二份项目。",
                )
            run_creation(root, state)
        else:
            raise TaskControlError("task_recovery_required", "请查询当前任务的具体问题。")


@with_table_reads
@timed_task_call
def resume_task(task: Path, response: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(response, dict):
        raise TaskControlError("invalid_task_response", "任务答复必须是 JSON 对象。")
    root = task_path(task)
    with external_project_session(root):
        state = load_task(root)
        if state["status"] in {"complete", "cancelled"} and "revise_operations" not in response:
            return _current_result(state) if state["status"] == "complete" else task_summary(state)
        original_revision = state["state_sha256"]
        try:
            _resume(root, state, response)
        except TaskControlError as exc:
            if exc.reason_code in {"invalid_task_response", "stale_task_preview", "task_not_revisable",
                                    "stale_task_question", "invalid_mapping_selection", "invalid_mapping_candidate", "stale_source_review"}:
                exc.repair = response_repair(state, response, exc)
                raise
            record_failure(root, state, exc)
        except (ValueError, OSError, RuntimeError, TimeoutExpired) as exc:
            record_failure(root, state, exc)
        if state["state_sha256"] == original_revision:
            return _current_result(state) if state["status"] == "complete" else task_summary(state)
        return _finished_call(root, state)


__all__ = ["start_task", "inspect_task", "resume_task", "task_request_schema", "task_response_schema"]
