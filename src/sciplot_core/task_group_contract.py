"""Explicit experiment lists; existing tasks retain scientific meaning and execution."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from jsonschema import Draft202012Validator

from sciplot_core.studio_core.annotation_schema import object_schema, validate_operation_batch
from sciplot_core.studio_core.project_query_paths import canonical_path
from sciplot_core.task_contract import TaskControlError, task_request_schema, task_response_schema, validate_task_request


def group_request_schema() -> dict[str, Any]:
    text = {"type": "string", "minLength": 1, "maxLength": 200}
    preset = object_schema({
        "preset": {"type": "string", "minLength": 1},
        "expected_preset_sha256": {"type": "string", "pattern": "^[a-f0-9]{64}$"},
    }, ["preset", "expected_preset_sha256"])
    return object_schema({
        "version": {"type": "integer", "const": 1}, "title": text,
        "sample_style_preset": preset,
        "items": {"type": "array", "minItems": 1, "maxItems": 32, "items": object_schema({
            "id": {"type": "string", "pattern": "^[a-zA-Z0-9][a-zA-Z0-9_-]{0,63}$"},
            "label": text, "request": task_request_schema(),
        }, ["id", "label", "request"])},
    }, ["version", "title", "items"])


def group_responses_schema() -> dict[str, Any]:
    return {"type": "array", "maxItems": 32, "items": object_schema({
        "item_id": {"type": "string", "minLength": 1},
        "task_dir": {"type": "string", "minLength": 1},
        "response": task_response_schema(),
    }, ["item_id", "task_dir", "response"])}


def validate_shape(value: Any, schema: dict[str, Any]) -> None:
    try:
        json.dumps(value, allow_nan=False)
        error = next(Draft202012Validator(schema).iter_errors(value), None)
        if error:
            location = "/".join(map(str, error.absolute_path))
            raise ValueError(f"{location}: {error.message[:400]}")
    except (TypeError, ValueError) as exc:
        raise TaskControlError("invalid_task_group", str(exc)) from exc


def normalize_group_request(value: dict[str, Any], *, base_dir: Path | None = None) -> dict[str, Any]:
    validate_shape(value, group_request_schema())
    request = json.loads(json.dumps(value, ensure_ascii=False))
    base = base_dir or Path.cwd()

    def absolute(raw: str) -> str:
        path = Path(raw).expanduser()
        return str(canonical_path(path if path.is_absolute() else base / path))

    ids = [item["id"] for item in request["items"]]
    if len(set(ids)) != len(ids):
        raise TaskControlError("duplicate_group_item", "实验组中的 id 必须唯一。")
    for item in request["items"]:
        task = validate_task_request(item["request"])
        for key in ("source", "project", "out", "profile"):
            if key in task:
                task[key] = absolute(task[key])
        if task["action"] == "edit":
            validate_operation_batch(task["operations"])
            for operation in task["operations"]:
                if operation["op"] == "apply_sample_style_preset":
                    operation["preset"] = absolute(operation["preset"])
        if request.get("sample_style_preset") and task["action"] != "create":
            raise TaskControlError("group_preset_scope", "共享样品预设用于新建实验组；已有图请提供显式 edit 请求。")
        item["request"] = task
    if "sample_style_preset" in request:
        request["sample_style_preset"]["preset"] = absolute(request["sample_style_preset"]["preset"])
    return dict(request)
