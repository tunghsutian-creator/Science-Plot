"""Durable task receipts outside raw inputs, canonical projects and deliveries."""

from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from sciplot_core.foundation.json_hashing import canonical_json_sha256
from sciplot_core.foundation.json_io import atomic_write_json
from sciplot_core.output_contract import resolve_user_output_layout, requested_delivery_root
from sciplot_core.studio_core.project_query import resolve_project_path
from sciplot_core.studio_core.project_query_paths import canonical_path
from sciplot_core.task_contract import TaskControlError, validate_task_request


def task_path(path: Path) -> Path:
    root = canonical_path(path)
    return root.parent if root.name == "task.json" else root


def task_location(request: dict[str, Any], supplied: Path | None) -> Path:
    if request["action"] == "create":
        source = canonical_path(Path(request["source"]))
        layout = resolve_user_output_layout(
            source, requested_delivery_root=request.get("out"),
        )
        protected = [source, layout.delivery_root, layout.workspace_root]
        parent = layout.workspace_root.parent / "tasks"
    else:
        project = resolve_project_path(Path(request["project"]))
        original = json.loads((project / "plot_request.json").read_text())
        delivery = requested_delivery_root({"request": original}, run_output=project)
        protected = [project, delivery]
        for key in ("input", "input_path", "data_dir"):
            source = original.get(key)
            if isinstance(source, str):
                path = Path(source).expanduser()
                protected.append((project / path).resolve() if not path.is_absolute() else path.resolve())
        for sample in (original.get("study_model") or {}).get("samples", []):
            for replicate in sample.get("replicates", []):
                raw = (replicate.get("source_file") or {}).get("raw_path")
                if isinstance(raw, str):
                    protected.append(Path(raw).expanduser().resolve())
        parent = project.parent / ".sciplot_tasks"
    root = canonical_path(supplied or parent / uuid.uuid4().hex)
    for path in protected:
        if root == path or root.is_relative_to(path) or path.is_relative_to(root):
            raise TaskControlError(
                "task_path_overlap", "任务记录目录不能与原始数据、项目或成图目录重叠。",
            )
    return root


def save_task(root: Path, state: dict[str, Any]) -> None:
    state["updated_at"] = datetime.now(timezone.utc).isoformat()
    state["state_sha256"] = canonical_json_sha256(
        {key: value for key, value in state.items() if key != "state_sha256"},
        allow_nan=False,
    )
    atomic_write_json(canonical_path(root / "task.json"), state)


def load_task(root: Path) -> dict[str, Any]:
    payload = json.loads(canonical_path(root / "task.json").read_text())
    if not isinstance(payload, dict) or payload.get("kind") != "sciplot_task":
        raise TaskControlError("invalid_task", "这不是 SciPlot 任务记录。")
    if payload.get("task_dir") != str(root) or payload.get("version") != 1:
        raise TaskControlError("invalid_task", "任务位置或版本不匹配。")
    digest = canonical_json_sha256(
        {key: value for key, value in payload.items() if key != "state_sha256"},
        allow_nan=False,
    )
    if digest != payload.get("state_sha256"):
        raise TaskControlError("task_record_changed", "任务记录发生变化，请保留原记录。")
    validate_task_request(payload["request"])
    return dict(payload)


def task_summary(state: dict[str, Any]) -> dict[str, Any]:
    keys = (
        "kind", "version", "task_dir", "status", "phase", "updated_at", "question",
        "blocker", "result", "preview", "operation_id", "profile", "profile_unavailable", "project",
    )
    return {
        **{key: state[key] for key in keys if key in state},
        "model_calls_by_sciplot": 0,
        "external_model_tokens": None,
        "ready_to_use": None,
        "readiness_evaluated": False,
        "completion_scope": "Task receipt; current project evidence is queried separately.",
    }
