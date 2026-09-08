"""Group progress references ordinary task receipts; it stores no plotted data."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from sciplot_core.foundation.json_hashing import canonical_json_sha256
from sciplot_core.foundation.json_io import atomic_write_json
from sciplot_core.output_contract import resolve_user_output_layout
from sciplot_core.studio_core.project_query import resolve_project_path
from sciplot_core.studio_core.project_query_paths import canonical_path
from sciplot_core.task_contract import TaskControlError
from sciplot_core.task_group_contract import group_request_schema, validate_shape
from sciplot_core.task_storage import load_task, task_location


def group_path(path: Path) -> Path:
    path = canonical_path(path)
    return path.parent if path.name == "group.json" else path


def validate_group_location(root: Path, request: dict[str, Any]) -> None:
    destinations: list[tuple[str, Path]] = []
    sources = []
    for item in request["items"]:
        task = item["request"]
        task_location(task, root)  # Includes original source/project/delivery boundaries.
        if task["action"] == "create":
            source = Path(task["source"])
            sources.append(source)
            layout = resolve_user_output_layout(source, requested_delivery_root=task.get("out"))
            destinations.extend((item["id"], path) for path in (layout.workspace_root, layout.delivery_root))
        else:
            destinations.append((item["id"], resolve_project_path(Path(task["project"]))))
    for index, (identifier, path) in enumerate(destinations):
        for other_id, other in destinations[:index]:
            if identifier != other_id and (path == other or path.is_relative_to(other) or other.is_relative_to(path)):
                raise TaskControlError("group_output_overlap", "不同实验需要独立项目和输出目录。")
        for source in sources:
            if path == source or path.is_relative_to(source) or source.is_relative_to(path):
                raise TaskControlError("group_source_overlap", "成图目录不能与实验组的任何原始输入重叠。")


def save_group(root: Path, state: dict[str, Any]) -> None:
    state["updated_at"] = datetime.now(timezone.utc).isoformat()
    state["state_sha256"] = canonical_json_sha256({k: v for k, v in state.items() if k != "state_sha256"}, allow_nan=False)
    atomic_write_json(canonical_path(root / "group.json"), state)


def load_group(root: Path) -> dict[str, Any]:
    state = json.loads(canonical_path(root / "group.json").read_text())
    if (not isinstance(state, dict) or state.get("kind") != "sciplot_task_group"
            or state.get("version") != 1 or state.get("group_dir") != str(root)):
        raise TaskControlError("invalid_task_group", "实验组记录的位置或版本不匹配。")
    digest = canonical_json_sha256({k: v for k, v in state.items() if k != "state_sha256"}, allow_nan=False)
    if digest != state.get("state_sha256"):
        raise TaskControlError("group_record_changed", "实验组记录已变化，请保留原记录。")
    validate_shape(state["request"], group_request_schema())
    return dict(state)


def step_state(step: dict[str, Any]) -> dict[str, Any] | None:
    path = canonical_path(Path(step["task_dir"]))
    if not path.exists():
        return None
    return load_task(path)


def active_step(item: dict[str, Any]) -> tuple[dict[str, Any], dict[str, Any] | None]:
    for step in item["steps"]:
        state = step_state(step)
        if state is None or state["status"] != "complete":
            return step, state
    step = item["steps"][-1]
    return step, step_state(step)
