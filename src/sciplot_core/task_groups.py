"""Run independent experiment tasks and pause only the items needing judgment."""

from __future__ import annotations

from pathlib import Path
from subprocess import TimeoutExpired
from typing import Any

from sciplot_core.studio_core.project_query import inspect_project
from sciplot_core.studio_core.project_session import external_project_session
from sciplot_core.task_contract import TaskControlError
from sciplot_core.task_control import resume_task, start_task
from sciplot_core.task_group_contract import group_responses_schema, normalize_group_request, validate_shape
from sciplot_core.task_group_storage import active_step, group_path, load_group, save_group, step_state, validate_group_location
from sciplot_core.task_group_review import group_overview


def _step(root: Path, identifier: str, name: str, request: dict[str, Any]) -> dict[str, Any]:
    return {"name": name, "task_dir": str(root / "tasks" / identifier / name), "request": request}


def _advance(root: Path, state: dict[str, Any], item: dict[str, Any]) -> None:
    item.pop("blocker", None)
    while True:
        for step in item["steps"]:
            child = step_state(step)
            if child is None:
                start_task(step["request"], task_dir=Path(step["task_dir"]))
                child = step_state(step)
            elif child["status"] == "running":
                # The existing owner retains bounded uncertain-outcome recovery.
                resume_task(Path(step["task_dir"]), {"retry": True})
                child = step_state(step)
            if child is None:
                raise TaskControlError("group_task_missing", "本地任务未返回可继续的记录。")
            if child["status"] != "complete":
                item["status"] = child["status"]
                return
        if not item.get("styles_planned"):
            preset = state["request"].get("sample_style_preset")
            if preset:
                first = step_state(item["steps"][0])
                assert first is not None
                current = inspect_project(Path(first["project"]))
                additions = []
                for index, figure in enumerate(current["figures"], 1):
                    additions.append(_step(root, item["id"], f"style_{index:03}", {
                        "version": 1, "action": "edit", "project": current["project"],
                        "figure_id": figure["figure_id"], "expected_document_sha256": figure["document_sha256"],
                        "export": False, "operations": [{"op": "apply_sample_style_preset", **preset}],
                    }))
                if not additions:
                    raise TaskControlError("group_figures_missing", "项目没有可套用样品样式的图。")
                item["steps"].extend(additions)
                item["styles_planned"] = True
                save_group(root, state)  # Freeze requests before starting any child.
                continue
            item["styles_planned"] = True
        if not item.get("export_planned"):
            item["export_planned"] = True
            styles = [step_state(step) for step in item["steps"] if step["name"].startswith("style_")]
            if any(child and child.get("result", {}).get("status") == "saved" for child in styles):
                first = step_state(item["steps"][0])
                assert first is not None
                item["steps"].append(_step(root, item["id"], "export", {
                    "version": 1, "action": "export", "project": first["project"]}))
                save_group(root, state)
                continue
        item.update(status="complete", finished=True)
        return


def _run(root: Path, state: dict[str, Any], retry_items: set[str] | None = None) -> None:
    for item in state["items"]:
        if item.get("blocker") and item["id"] not in (retry_items or set()):
            continue
        try:
            _advance(root, state, item)
        except (ValueError, OSError, RuntimeError, TimeoutExpired) as exc:
            item.update(status="blocked", blocker={
                "reason_code": getattr(exc, "reason_code", "group_item_failed"), "message": str(exc),
            })
        save_group(root, state)


def start_group(request: dict[str, Any], *, group_dir: Path, base_dir: Path | None = None) -> dict[str, Any]:
    request = normalize_group_request(request, base_dir=base_dir)
    root = group_path(group_dir)
    validate_group_location(root, request)
    root.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    with external_project_session(root):
        if root.exists():
            state = load_group(root)
            if state["request"] != request:
                raise TaskControlError("group_already_exists", "实验组目录已用于另一份清单。")
        else:
            root.mkdir(mode=0o700)
            state = {"kind": "sciplot_task_group", "version": 1, "group_dir": str(root), "request": request,
                     "items": [{"id": item["id"], "label": item["label"], "status": "pending",
                                "steps": [_step(root, item["id"], "initial", item["request"])]}
                               for item in request["items"]]}
            save_group(root, state)
            _run(root, state)
        return group_overview(root, state)


def inspect_group(group: Path) -> dict[str, Any]:
    root = group_path(group)
    with external_project_session(root):
        return group_overview(root, load_group(root))


def resume_group(group: Path, responses: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    responses = [] if responses is None else responses
    validate_shape(responses, group_responses_schema())
    root = group_path(group)
    with external_project_session(root):
        state = load_group(root)
        entries = {item["id"]: item for item in state["items"]}
        seen = set()
        for response in responses:
            identifier = response["item_id"]
            if identifier not in entries or identifier in seen:
                raise TaskControlError("invalid_group_response", "答复必须指向不同的现有实验项。")
            seen.add(identifier)
            step, child = active_step(entries[identifier])
            if response["task_dir"] != step["task_dir"]:
                raise TaskControlError("stale_group_response", "答复对应的子任务已变化，请查询当前实验组。")
            answer = response["response"]
            if "accept_preview" in answer and not answer.get("expected_operation_id"):
                raise TaskControlError("invalid_group_response", "批量预览答复需包含每张当前预览的 expected_operation_id。")
            if child is None and answer != {"retry": True}:
                raise TaskControlError("invalid_group_response", "尚未建立的子任务仅支持 retry=true。")
        for response in responses:
            item = entries[response["item_id"]]
            step, child = active_step(item)
            if child is not None:
                resume_task(Path(step["task_dir"]), response["response"])
            item.pop("blocker", None)
            save_group(root, state)
        _run(root, state, seen)
        return group_overview(root, state)
