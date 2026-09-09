"""Generate independent native edit tasks, then commit exactly one explicit choice."""

from __future__ import annotations

from pathlib import Path
from subprocess import TimeoutExpired
from typing import Any
from uuid import uuid4

from sciplot_core.foundation.file_hashing import file_sha256
from sciplot_core.studio_core.document_edit import preview_project_document
from sciplot_core.studio_core.document_edit_state import edit_state
from sciplot_core.studio_core.project_query import resolve_project_figure
from sciplot_core.studio_core.project_session import external_project_session
from sciplot_core.task_comparison_contract import (
    candidate_request, comparison_selection_schema, normalize_comparison_request,
)
from sciplot_core.task_comparison_review import comparison_overview, comparison_snapshot
from sciplot_core.task_comparison_storage import (
    candidate_review, candidate_task, comparison_path, load_comparison, save_comparison,
)
from sciplot_core.task_contract import TaskControlError
from sciplot_core.task_control import resume_task, start_task
from sciplot_core.task_group_contract import validate_shape
from sciplot_core.task_storage import load_task, task_location


def _require_baseline(state: dict[str, Any]) -> None:
    if edit_state(Path(state["request"]["project"])) != state["baseline"]:
        raise TaskControlError("comparison_baseline_stale", "项目、数据或成图版本已变化，请从当前图新建比较。")


def _record_failure(root: Path, state: dict[str, Any], exc: Exception) -> None:
    state.update(status="blocked", blocker={
        "reason_code": getattr(exc, "reason_code", "comparison_execution_failed"),
        "message": str(exc), "recovery": "保留比较目录；解决所述问题后 resume。基准已变化时须新建比较。",
    })
    save_comparison(root, state)


def _generate(root: Path, state: dict[str, Any]) -> None:
    request = state["request"]
    project = Path(request["project"])
    _require_baseline(state)
    state.update(status="generating")
    state.pop("blocker", None)
    save_comparison(root, state)
    if "baseline_preview" not in state:
        rendered = preview_project_document(project, figure_id=request["figure_id"],
                                            output_dir=root / ("baseline-" + uuid4().hex))
        _require_baseline(state)
        if rendered["document"]["sha256"] != request["expected_document_sha256"]:
            raise TaskControlError("comparison_baseline_stale", "原图预览版本已变化。")
        state["baseline_preview"] = rendered["preview"]
        save_comparison(root, state)
    for item in request["candidates"]:
        _require_baseline(state)
        errors = state.setdefault("candidate_errors", {})
        errors.pop(item["id"], None)
        try:
            child = candidate_task(root, state, item)
            directory = root / "candidates" / item["id"]
            if child is None:
                start_task(candidate_request(request, item), task_dir=directory)
            elif child["status"] in {"running", "blocked"}:
                if child.get("preview_accepted") or child["phase"] not in {"starting", "previewing"}:
                    raise TaskControlError("comparison_candidate_changed", "候选已在比较之外继续执行，请新建比较。")
                resume_task(directory, {"retry": True})
        except (ValueError, OSError, RuntimeError, TimeoutExpired) as exc:
            errors[item["id"]] = str(exc)
        save_comparison(root, state)
    _require_baseline(state)
    snapshot = comparison_snapshot(root, state)
    state["status"] = "needs_selection" if any(c["selectable"] for c in snapshot["candidates"]) else "blocked"
    save_comparison(root, state)


def _apply_selection(root: Path, state: dict[str, Any]) -> None:
    chosen = state["selection"]["candidate_id"]
    request = state["request"]
    if chosen != "baseline":
        item = next(c for c in request["candidates"] if c["id"] == chosen)
        child = candidate_task(root, state, item)
        if child is None:
            raise TaskControlError("comparison_candidate_missing", "选中候选的任务记录缺失。")
        review = candidate_review(root, state, item, child)
        if review["operation_id"] != state["selected_operation_id"]:
            raise TaskControlError("comparison_selection_changed", "选中候选的预览已变化，不能应用。")
        directory = Path(child["task_dir"])
        if child["status"] == "needs_review":
            resume_task(directory, {"accept_preview": True, "expected_operation_id": review["operation_id"]})
        elif child["status"] in {"blocked", "running"}:
            if child.get("preview_accepted") is not True:
                raise TaskControlError("comparison_selection_changed", "选中候选尚无已接受的操作记录。")
            resume_task(directory, {"retry": True})
        child = candidate_task(root, state, item)
        if child is None or child["status"] != "complete":
            raise TaskControlError("comparison_apply_incomplete", (child or {}).get("blocker", {}).get("message", "选中方案尚未完成，请恢复本比较。"))
        state["selection_outcome"] = child["result"]
        state["selected_spec_sha256"] = review["candidate_spec"]["sha256"]
    else:
        _require_baseline(state)
        state["selection_outcome"] = {"status": "kept_baseline", "document_changed": False,
                                      "document_sha256": request["expected_document_sha256"]}
        figure = resolve_project_figure(Path(request["project"]), request["figure_id"])
        relative = str(Path(figure["spec"]).relative_to(request["project"]))
        state["selected_spec_sha256"] = state["baseline"]["project_files"][relative]
    save_comparison(root, state)


def _finish_selection(root: Path, state: dict[str, Any]) -> None:
    request = state["request"]
    state.update(status="applying")
    state.pop("blocker", None)
    save_comparison(root, state)
    if "selection_outcome" not in state:
        _apply_selection(root, state)
    _require_selected_figure(state)
    if request["export"]:
        directory = root / "export"
        state["export_task"] = str(directory)
        save_comparison(root, state)
        if directory.exists():
            exported = load_task(directory)
            if exported["request"] != {"version": 1, "action": "export", "project": request["project"]}:
                raise TaskControlError("comparison_export_changed", "导出任务记录与选定项目不匹配。")
            if exported["status"] != "complete":
                resume_task(directory, {"retry": True})
        else:
            start_task({"version": 1, "action": "export", "project": request["project"]}, task_dir=directory)
        exported = load_task(directory)
        if exported["status"] != "complete":
            raise TaskControlError("comparison_export_incomplete", exported.get("blocker", {}).get("message", "所选图已保存，导出尚未完成。"))
        _require_selected_figure(state)
    state["status"] = "complete"
    save_comparison(root, state)


def _require_selected_figure(state: dict[str, Any]) -> None:
    request = state["request"]
    figure = resolve_project_figure(Path(request["project"]), request["figure_id"])
    if (file_sha256(Path(figure["document"])) != state["selection_outcome"]["document_sha256"]
            or file_sha256(Path(figure["spec"])) != state["selected_spec_sha256"]):
        raise TaskControlError("comparison_selected_figure_changed", "选定图已被后续修改，不能将新版本当作本次选择导出。")


def start_comparison(request: dict[str, Any], *, comparison_dir: Path, base_dir: Path | None = None) -> dict[str, Any]:
    request = normalize_comparison_request(request, base_dir=base_dir)
    root = task_location(candidate_request(request, request["candidates"][0]), comparison_path(comparison_dir))
    root.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    with external_project_session(root):
        if root.exists():
            state = load_comparison(root)
            if state["request"] != request:
                raise TaskControlError("comparison_already_exists", "此目录已用于另一个比较。")
            return comparison_overview(root, state)
        project = Path(request["project"])
        figure = resolve_project_figure(project, request["figure_id"])
        baseline = edit_state(project)
        if (file_sha256(Path(figure["document"])) != request["expected_document_sha256"]
                or baseline["project_files"].get(str(Path(figure["document"]).relative_to(project))) != request["expected_document_sha256"]):
            raise TaskControlError("comparison_baseline_stale", "请使用当前图的文档版本创建比较。")
        root.mkdir(mode=0o700)
        state = {"kind": "sciplot_task_comparison", "version": 1, "comparison_dir": str(root),
                 "request": request, "baseline": baseline, "status": "generating"}
        save_comparison(root, state)
        try:
            _generate(root, state)
        except (ValueError, OSError, RuntimeError, TimeoutExpired) as exc:
            _record_failure(root, state, exc)
        return comparison_overview(root, state)


def inspect_comparison(comparison: Path) -> dict[str, Any]:
    root = comparison_path(comparison)
    with external_project_session(root):
        return comparison_overview(root, load_comparison(root))


def resume_comparison(comparison: Path) -> dict[str, Any]:
    root = comparison_path(comparison)
    with external_project_session(root):
        state = load_comparison(root)
        if state["status"] != "complete":
            try:
                if "selection" in state:
                    _finish_selection(root, state)
                else:
                    _generate(root, state)
            except (ValueError, OSError, RuntimeError, TimeoutExpired) as exc:
                _record_failure(root, state, exc)
        return comparison_overview(root, state)


def select_comparison(comparison: Path, selection: dict[str, Any]) -> dict[str, Any]:
    validate_shape(selection, comparison_selection_schema())
    root = comparison_path(comparison)
    with external_project_session(root):
        state = load_comparison(root)
        if "selection" in state:
            if selection != state["selection"]:
                raise TaskControlError("comparison_already_selected", "此比较已选定方案；不能再应用第二个候选。")
        else:
            result = comparison_snapshot(root, state)
            if selection["expected_comparison_id"] != result["comparison_id"]:
                raise TaskControlError("stale_comparison_selection", "比较内容已变化，请重新查询后选择。")
            _require_baseline(state)
            chosen = next((c for c in [result["baseline"], *result["candidates"]] if c["id"] == selection["candidate_id"]), None)
            if chosen is None or not chosen["selectable"]:
                raise TaskControlError("comparison_not_selectable", "该候选或原图基准当前不可采用，请查询比较。")
            state["selection"] = dict(selection)
            if "operation_id" in chosen:
                state["selected_operation_id"] = chosen["operation_id"]
            save_comparison(root, state)  # Freeze the choice before any native write.
        if state["status"] != "complete":
            try:
                _finish_selection(root, state)
            except (ValueError, OSError, RuntimeError, TimeoutExpired) as exc:
                _record_failure(root, state, exc)
        return comparison_overview(root, state)
