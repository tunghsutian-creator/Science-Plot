"""Versioned complete-task requests, separate from rendering and scientific state."""

from __future__ import annotations

import json
from typing import Any


class TaskControlError(ValueError):
    def __init__(self, reason_code: str, message: str) -> None:
        super().__init__(message)
        self.reason_code = reason_code


_FIELDS = {
    "create": {"source", "rule_id", "template", "out", "profile"},
    "edit": {"project", "figure_id", "expected_document_sha256", "operations"},
    "export": {"project"},
}
_REQUIRED = {
    "create": {"source"},
    "edit": {"project", "expected_document_sha256", "operations"},
    "export": {"project"},
}


def task_request_schema() -> dict[str, Any]:
    from sciplot_core.studio_core.annotation_schema import annotation_operation_capabilities

    variants = []
    for action, fields in _FIELDS.items():
        properties: dict[str, Any] = {
            "version": {"type": "integer", "const": 1},
            "action": {"type": "string", "const": action},
            **{key: {"type": "string", "minLength": 1} for key in sorted(fields)},
        }
        if action == "edit":
            properties["expected_document_sha256"] = {
                "type": "string", "pattern": "^[a-f0-9]{64}$",
            }
            properties["operations"] = annotation_operation_capabilities()["operations_schema"]
        variants.append({
            "type": "object", "additionalProperties": False,
            "properties": properties,
            "required": ["version", "action", *sorted(_REQUIRED[action])],
        })
    return {"oneOf": variants}


def task_response_schema() -> dict[str, Any]:
    return {
        "oneOf": [
            {"type": "object", "additionalProperties": False,
             "properties": {key: {"type": "string", "minLength": 1}
                            for key in ("rule_id", "template")},
             "required": ["rule_id"]},
            {"type": "object", "additionalProperties": False,
             "properties": {"accept_preview": {"type": "boolean"}},
             "required": ["accept_preview"]},
            {"type": "object", "additionalProperties": False,
             "properties": {"retry": {"type": "boolean", "const": True}},
             "required": ["retry"]},
        ],
    }


def validate_task_request(value: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise TaskControlError("invalid_task_request", "任务请求必须是 JSON 对象。")
    action = value.get("action")
    if type(value.get("version")) is not int or value["version"] != 1:
        raise TaskControlError("unsupported_task_version", "任务接口版本必须为 1。")
    if not isinstance(action, str) or action not in _FIELDS:
        raise TaskControlError("unsupported_task_action", "任务支持 create、edit、export。")
    allowed = {"version", "action"} | _FIELDS[action]
    if set(value) - allowed or not _REQUIRED[action] <= set(value):
        raise TaskControlError("invalid_task_fields", "任务参数缺失或含未支持的字段。")
    for key in _FIELDS[action] & set(value) - {"operations"}:
        if not isinstance(value[key], str) or not value[key].strip():
            raise TaskControlError("invalid_task_field", f"{key} 必须是非空字符串。")
    if action == "edit":
        digest = value["expected_document_sha256"]
        if len(digest) != 64 or any(c not in "0123456789abcdef" for c in digest):
            raise TaskControlError("invalid_document_revision", "请使用查询返回的文档版本。")
        operations = value["operations"]
        if not isinstance(operations, list) or not 1 <= len(operations) <= 100:
            raise TaskControlError("invalid_operations", "一次请求需要 1–100 个操作。")
        if not all(isinstance(item, dict) for item in operations):
            raise TaskControlError("invalid_operations", "每个操作必须是 JSON 对象。")
    if value.get("profile") and (value.get("rule_id") or value.get("template")):
        raise TaskControlError("profile_selection_conflict", "复用配置时不同时覆盖规则和模板。")
    return dict(json.loads(json.dumps(value, ensure_ascii=False, allow_nan=False)))
