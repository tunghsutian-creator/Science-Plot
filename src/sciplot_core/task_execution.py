"""Advance deterministic tasks through existing native lifecycle services."""

from __future__ import annotations

import json
from pathlib import Path
from subprocess import TimeoutExpired
from typing import Any

from sciplot_core.foundation.json_io import atomic_write_json
from sciplot_core.studio_core.document_edit import apply_document_edit
from sciplot_core.studio_core.project_creation import create_project, export_project
from sciplot_core.studio_core.project_query_paths import canonical_path
from sciplot_core.task_contract import TaskControlError
from sciplot_core.task_editing import current_edit_request, unchanged_style_review
from sciplot_core.task_planning import plan_task, save_profile
from sciplot_core.task_storage import save_task


def _phase(root: Path, state: dict[str, Any], value: str) -> None:
    state.update({"status": "running", "phase": value})
    state.pop("blocker", None)
    save_task(root, state)


def _completed(root: Path, state: dict[str, Any], result: dict[str, Any]) -> None:
    ready = result["studio_run"]["ready_to_use"] is True
    state.update({
        "result": result, "project": result["project_dir"],
        "status": "complete" if ready else "blocked",
        "phase": "finished" if ready else "exporting",
    })
    if not ready:
        state["blocker"] = {
            "reason_code": "export_not_ready",
            "message": result["studio_run"]["failure_reason"],
            "recovery": "保留当前项目；修复具体导出问题后重试，不重新准备原始数据。",
        }
    save_task(root, state)


def run_creation(root: Path, state: dict[str, Any]) -> None:
    _phase(root, state, "planning")
    plan = plan_task(root, state)
    if plan is None:
        save_task(root, state)
        return
    save_profile(root, state)
    _phase(root, state, "creating")
    request = state["request"]
    def checkpoint(prepared: dict[str, Any]) -> None:
        state["project"] = prepared["project_dir"]
        _phase(root, state, "exporting")

    result = create_project(
        Path(request["source"]), expected_plan=plan,
        output_dir=Path(request["out"]) if request.get("out") else None,
        on_prepared=checkpoint,
    )
    _completed(root, state, result)


def run_edit_preview(root: Path, state: dict[str, Any]) -> None:
    from sciplot_core.studio_core.annotation_operations import preview_document_operations

    _phase(root, state, "previewing")
    request = current_edit_request(state)
    # Retries use a fresh location; previous candidate evidence is preserved.
    index = int(state.get("preview_attempt", 0)) + 1
    state["preview_attempt"] = index
    save_task(root, state)
    review = preview_document_operations(
        Path(request["project"]), request["operations"],
        output_dir=root / f"preview_{index:03}",
        figure_id=request.get("figure_id"),
        expected_document_sha256=request["expected_document_sha256"],
    )
    atomic_write_json(root / "review.json", review)
    state.update({
        "status": "needs_review", "phase": "review", "project": review["project"],
        "operation_id": review["operation_id"],
        "preview": {"image": review["preview"],
                    "review_path": str(root / "review.json"),
                    "changes": review.get("actual_changes"),
                    "scientific_audit": review["scientific_audit"]},
    })
    if unchanged_style_review(review):
        outcome = {
            "status": "unchanged", "document_changed": False,
            "document": review["document"], "document_sha256": review["document_sha256"],
            "figure_id": review["figure_id"], "review_path": str(root / "review.json"),
        }
        state["edit_outcome"] = outcome
        if request.get("export", True):
            run_export(root, state)
        else:
            state.update(status="complete", phase="finished", result={
                "kind": "sciplot_task_edit_result", "version": 1, **outcome,
                "project_dir": review["project"], "export_performed": False,
                "export_required": None, "ready_to_use": None, "readiness_evaluated": False,
            })
            save_task(root, state)
        return
    save_task(root, state)


def run_export(root: Path, state: dict[str, Any]) -> None:
    _phase(root, state, "exporting")
    result = export_project(Path(state.get("project") or state["request"]["project"]))
    _completed(root, state, result)


def run_apply_export(root: Path, state: dict[str, Any]) -> None:
    review = json.loads(canonical_path(root / "review.json").read_text())
    if review.get("operation_id") != state.get("operation_id"):
        raise TaskControlError("task_review_changed", "任务预览记录已变化，请重新查询。")
    _phase(root, state, "applying")
    result = apply_document_edit(Path(state["project"]), review)
    if result.get("status") not in {"applied", "already_applied"}:
        raise TaskControlError("edit_not_applied", "修改尚未完成，保留预览并查询操作状态。")
    state["applied_operation"] = result
    save_task(root, state)
    if state["request"].get("export", True) is False:
        state.update({
            "status": "complete", "phase": "finished",
            "result": {
                "kind": "sciplot_task_edit_result", "version": 1, "status": "saved",
                "project_dir": state["project"], "figure_id": review["figure_id"],
                "document": result["document"],
                "document_sha256": result["result_sha256"],
                "operation_id": result["operation_id"],
                "export_performed": False, "export_required": True,
                "ready_to_use": False, "readiness_evaluated": False,
            },
        })
        save_task(root, state)
        return
    run_export(root, state)


def record_failure(root: Path, state: dict[str, Any], exc: Exception) -> None:
    timed_out = isinstance(exc, TimeoutExpired)
    state.update({
        "status": "blocked",
        "blocker": {
            "reason_code": "task_worker_timeout" if timed_out else getattr(exc, "reason_code", "task_execution_failed"),
            "message": "本地工作进程超时，任务进度已保留；查询当前状态后可重试。" if timed_out else str(exc),
            **({"timeout_seconds": exc.timeout} if isinstance(exc, TimeoutExpired) else {}),
            "recovery": "保留此任务；解决所述问题后查询或重试。原始数据不会自动修改。",
        },
    })
    save_task(root, state)
