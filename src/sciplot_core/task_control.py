"""Public local task orchestration; no model, chat state or plotting reimplementation."""

from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timezone
from pathlib import Path
from subprocess import TimeoutExpired
from typing import Any, Literal

from sciplot_core.foundation.source_tree import source_tree_sha256
from sciplot_core.output_contract import resolve_user_output_layout
from sciplot_core.project_lifecycle.legacy_public_policy import require_public_editable
from sciplot_core.source_tables.read_session import with_table_reads
from sciplot_core.task_semantic_owner import managed_task_call
from sciplot_core.task_timing import timed_task_call, finish_timing, observe_phase
from sciplot_core.studio_core.annotation_schema import AnnotationOperationError, validate_operation_batch
from sciplot_core.project_lifecycle.figure_observation import resolve_project_path
from sciplot_core.studio_core.project_query import inspect_project
from sciplot_core.foundation.canonical_paths import canonical_path
from sciplot_core.studio_core.project_session import external_project_session
from sciplot_core.task_contract import (
    TaskControlError, task_request_schema, task_response_schema, validate_task_request,
)
from sciplot_core.task_execution import (
    can_resume_frequency_creation, record_failure, run_apply_export, run_creation, run_edit_preview, run_export,
)
from sciplot_core.task_column_mapping import accept_column_response, accept_table_response
from sciplot_core.task_ftir_block_choice import normalize_ftir_block_request
from sciplot_core.task_planning import accept_worksheet_response, assert_source_current
from sciplot_core.task_source_execution import accept_annotation_response, run_source_apply_export, run_source_preview, validate_source_response
from sciplot_core.task_editing import begin_preview_revision, validate_preview_response
from sciplot_core.task_repair import normalize_task_location, request_repair, response_repair
from sciplot_core.task_result_projection import current_task_result
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
    if "intent" in state["request"] and result is not None:
        # Include evidence checks in timing, then attach the resulting metadata.
        return {**result, **{key: state[key] for key in ("updated_at", "local_timing") if key in state}}
    return {**task_summary(state), **({key: result[key] for key in (
        "status", "blocker", "current_project", "next_step",
    ) if key in result} if result else {})}


def _current_result(state: dict[str, Any]) -> dict[str, Any]:
    return current_task_result(state, inspect_project=inspect_project)


def start_task(
    request: dict[str, Any], *, task_dir: Path | None = None,
    entry_intent: dict[str, Any] | None = None,
    defer_creation_export: bool = False,
    _owned_namespace: Path | None = None,
    _public_mutation: bool = False,
) -> dict[str, Any]:
    return _start_task(request, task_dir=task_dir, entry_intent=entry_intent,
                       defer_creation_export=defer_creation_export, _owned_namespace=_owned_namespace,
                       _public_mutation=_public_mutation)


def start_native_compatibility_creation(
    request: dict[str, Any], *, task_dir: Path, owned_namespace: Path,
    reason: Literal["historical_plot_create_receipt", "native_group_sample_style_preset"],
) -> dict[str, Any]:
    """Continue explicit native work with no change to its original publication timing."""
    return _start_task(request, task_dir=task_dir, _owned_namespace=owned_namespace, native_compatibility=reason)


@with_table_reads
@timed_task_call
@managed_task_call
def _start_task(
    request: dict[str, Any], *, task_dir: Path | None = None,
    entry_intent: dict[str, Any] | None = None,
    defer_creation_export: bool = False,
    _owned_namespace: Path | None = None,
    _public_mutation: bool = False,
    native_compatibility: str | None = None,
) -> dict[str, Any]:
    original_request = request
    try:
        request, task_dir, corrections = normalize_task_location(request, task_dir)
        request = validate_task_request(request)
        request = request if defer_creation_export or native_compatibility else normalize_ftir_block_request(request)
        if type(defer_creation_export) is not bool or (defer_creation_export and request["action"] != "create"):
            raise TaskControlError("invalid_creation_mode", "Deferred native preparation is an internal create-only mode.")
        if native_compatibility and (request["action"] != "create" or "source" not in request):
            raise TaskControlError("invalid_creation_mode", "Native compatibility requires an original source create request.")
        if request["action"] == "edit":
            validate_operation_batch(request["operations"])
    except (TaskControlError, AnnotationOperationError) as exc:
        exc.repair = request_repair(original_request, exc)
        raise
    source_hashes = None
    append = "append_to" in request
    if append:
        target = canonical_path(Path(request["append_to"]))
        if target.suffix != ".sciplot":
            raise TaskControlError("invalid_project_file_append", "Choose an existing .sciplot file for append.")
        request["append_to"] = str(target)
        request["sources"] = [str(canonical_path(Path(value))) for value in request["sources"]]
        digest = None
    elif "intent" in request:
        from sciplot_core.task_semantic_creation import normalize_sources

        source_hashes = normalize_sources(request)
        digest = None
    elif request["action"] in {"create", "update_source"}:
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
    if _public_mutation and request["action"] != "create" and not root.exists():
        require_public_editable(Path(request["project"]), figure_id=request.get("figure_id"))
    if not root.exists():
        from sciplot_core.foundation.research_destination import require_data_destination
        require_data_destination(root, existing_namespace=_owned_namespace)
        if request["action"] == "create" and not append:
            layout = resolve_user_output_layout(request.get("source", request.get("sources", [None])[0]),
                                                requested_delivery_root=request.get("out"))
            for destination in (layout.delivery_root, layout.workspace_root):
                inherited = (_owned_namespace if _owned_namespace is not None
                             and destination.is_relative_to(_owned_namespace.resolve()) else None)
                require_data_destination(destination, existing_namespace=inherited)
    root.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    with external_project_session(root):
        if root.exists():
            state = load_task(root)
            if bool(state.get("defer_creation_export", False)) != defer_creation_export:
                raise TaskControlError("task_creation_mode_conflict", "This task has a different frozen creation publication mode.")
            if entry_intent is not None:
                if state.get("entry_intent") != entry_intent:
                    raise TaskControlError("task_intent_conflict", "This task directory belongs to a different or unrecorded typed intent.")
                # A concurrent exact intent retains its original bound request and SHA.
                return _current_result(state) if state["status"] == "complete" else task_summary(state)
            if state["request"] != request and state.get("initial_request") != request:
                raise TaskControlError("task_already_exists", "此任务目录已用于其他请求。")
            return _current_result(state) if state["status"] == "complete" else task_summary(state)
        if append:
            from sciplot_core.task_semantic_creation import normalize_sources

            target = Path(request["append_to"])
            if not target.is_file():
                raise TaskControlError("path_not_found", "Append needs an existing .sciplot file; no project was created.")
            source_hashes = normalize_sources(request)
        root.mkdir(parents=True, mode=0o700)
        state = {
            "kind": "sciplot_task", "version": 1, "task_dir": str(root),
            "created_at": datetime.now(timezone.utc).isoformat(),
            "request": request, "source_sha256": digest,
            **({"source_hashes": source_hashes, "intent_revision": 1, "initial_request": deepcopy(request)} if source_hashes is not None else {}),
            "status": "running", "phase": "starting",
            **({"entry_intent": deepcopy(entry_intent)} if entry_intent is not None else {}),
            **({"defer_creation_export": True} if defer_creation_export else {}),
            **({"prefer_managed_raw": True} if (request["action"] == "create" and "source" in request
                                                and not native_compatibility and not defer_creation_export) else {}),
            **({"creation_admission": {"route": "native_compatibility", "reason_code": "native_deferred_presentation",
                                       "message": "This native presentation workflow prepares the exact VSZ for review before first export."}}
               if defer_creation_export else {}),
            **({"creation_admission": {"route": "native_compatibility", "reason_code": native_compatibility,
                                       "message": ("Resume the frozen pre-Managed creation receipt on its original route."
                                                   if native_compatibility == "historical_plot_create_receipt" else
                                                   "The explicit shared preset uses saved native sample styles and native review.")}}
               if native_compatibility else {}),
            **({"automatic_corrections": corrections} if corrections else {}),
        }
        save_task(root, state)
        try:
            if "intent" in request:
                from sciplot_core.task_semantic_creation import run_creation as run_semantic

                run_semantic(root, state)
            elif request["action"] == "create":
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
@managed_task_call
def inspect_task(task: Path) -> dict[str, Any]:
    state = load_task(task_path(task))
    return _current_result(state)


def _resume(root: Path, state: dict[str, Any], response: dict[str, Any], *, _public_mutation: bool = False) -> None:
    if "intent" in state["request"]:
        from sciplot_core.task_semantic_creation import resume

        resume(root, state, response)
        return
    if state.get("defer_creation_export") is True and "prepared_creation" in state and response == {"retry": True}:
        from sciplot_core.task_prepared_creation import complete_prepared

        complete_prepared(root, state)
        return
    if "revise_operations" in response:
        if _public_mutation and state["request"].get("project"):
            require_public_editable(Path(state["request"]["project"]), figure_id=state["request"].get("figure_id"))
        if begin_preview_revision(state, response):
            run_edit_preview(root, state, new_revision=True)
        return
    if state["status"] in {"complete", "cancelled"}:
        return
    if "categorical" in response and "categorical" in state["request"]:
        from sciplot_core.task_categorical_creation import accept_categorical_response

        accept_categorical_response(state, response)
        save_task(root, state)
        run_creation(root, state)
        return
    if "missing_values" in response:
        from sciplot_core.task_missing_values import accept_missing_values_response

        assert_source_current(state)
        accept_missing_values_response(state, response)
        save_task(root, state)
        run_creation(root, state)
        return
    if "worksheet" in response or "out" in response:
        if "worksheet" in response:
            accept_worksheet_response(state, response)
        else:
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
        # Replay only original explicit choices before creating native outputs.
        run_creation(root, state)
        return
    if (response == {"retry": True} and state.get("mapping_choice")
            and state.get("phase") == "scientific_choice" and state["request"]["action"] == "create"
            and not state.get("project")):
        run_creation(root, state)
        return
    if state["status"] == "needs_input":
        if state["question"].get("field") == "missing_values":
            raise TaskControlError("invalid_task_response", "Answer the current missing_values question explicitly; rule or metadata answers cannot supply a missing-value policy.")
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
            from sciplot_core.task_native_edit import cancel_native_task

            cancel_native_task(root, state)
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
        if can_resume_frequency_creation(state):
            run_creation(root, state)
        elif phase == "exporting":
            run_export(root, state)
        elif phase == "applying" and state.get("preview_accepted") is True:
            if state["request"]["action"] == "update_source":
                run_source_apply_export(root, state)
            else:
                run_apply_export(root, state)
        elif state["request"]["action"] == "update_source":
            if phase in {"starting", "previewing", "scientific_choice"}:
                run_source_preview(root, state)
            else:
                raise TaskControlError("task_recovery_required", "请查询源更新任务的具体状态。")
        elif phase == "previewing" or (phase == "starting" and state["request"]["action"] == "edit"):
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
            if ((state.get("blocker") or {}).get("reason_code") == "creation_outcome_uncertain"
                    or layout.workspace_root.exists() or layout.delivery_root.exists()):
                raise TaskControlError(
                    "creation_outcome_uncertain",
                    "建项可能已经执行。请查询现有输出，不会覆盖或自动创建第二份项目。",
                )
            run_creation(root, state)
        else:
            raise TaskControlError("task_recovery_required", "请查询当前任务的具体问题。")


@with_table_reads
@timed_task_call
@managed_task_call
def resume_task(task: Path, response: dict[str, Any], *, _public_mutation: bool = False) -> dict[str, Any]:
    if not isinstance(response, dict):
        raise TaskControlError("invalid_task_response", "任务答复必须是 JSON 对象。")
    root = task_path(task)
    with external_project_session(root):
        state = load_task(root)
        if "intent" in state["request"] and state["status"] == "complete" and response == {"retry": True}:
            current = _current_result(state)
            if current.get("ready_to_use") is True or "formats" in state["request"]:
                return current
        semantic_continuation = ("intent" in state["request"] and (response == {"retry": True} or "revise_intent" in response))
        if state["status"] in {"complete", "cancelled"} and "revise_operations" not in response and not semantic_continuation:
            return _current_result(state) if state["status"] == "complete" else task_summary(state)
        original_revision = state["state_sha256"]
        try:
            _resume(root, state, response, _public_mutation=_public_mutation)
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
