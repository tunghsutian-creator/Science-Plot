"""Versioned complete-task requests, separate from rendering and scientific state."""

from __future__ import annotations

import json
from typing import Any
from sciplot_core.task_choice_schema import annotation_response_schema, column_mapping_schema, table_response_schema, metadata_response_schema


class TaskControlError(ValueError):
    def __init__(self, reason_code: str, message: str) -> None:
        super().__init__(message)
        self.reason_code = reason_code


_FIELDS = {
    "create": {"source", "rule_id", "template", "out", "profile", "choose_columns"},
    "edit": {"project", "figure_id", "expected_document_sha256", "operations", "export"},
    "export": {"project"},
    "update_source": {"project", "source", "worksheet", "choose_columns"},
}
_REQUIRED = {
    "create": {"source"},
    "edit": {"project", "expected_document_sha256", "operations"},
    "export": {"project"},
    "update_source": {"project", "source"},
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
        if action in {"create", "update_source"}:
            properties["choose_columns"] = {
                "type": "boolean", "const": True,
                "description": "Select original worksheet, metadata/data rows and x/y pairs in CSV/TSV or Excel; answer source-bound questions.",
            }
        if action == "edit":
            properties["export"] = {"type": "boolean", "default": True,
                                    "description": "False saves the reviewed edit for continued work; export later with an export task."}
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
    from sciplot_core.studio_core.annotation_schema import annotation_operation_capabilities

    operation_id = {"type": "string", "pattern": "^[a-f0-9]{64}$",
                    "description": "Current preview operation_id. Required for revisions and for accepting or rejecting a revised preview."}
    replacement = {**annotation_operation_capabilities()["operations_schema"],
                   "description": "Replace the whole batch against the same saved document; this does not append to the old preview."}
    return {
        "oneOf": [
            table_response_schema(),
            metadata_response_schema(),
            annotation_response_schema(),
            {"type": "object", "additionalProperties": False,
             "properties": {
                 "expected_question_id": {"type": "string", "pattern": "^[a-f0-9]{64}$"},
                 "column_mapping": column_mapping_schema()},
             "required": ["expected_question_id", "column_mapping"]},
            {"type": "object", "additionalProperties": False,
             "properties": {"accept_source_update": {"type": "boolean"},
                            "expected_revision_id": {"type": "string", "pattern": "^[a-f0-9]{64}$"}},
             "required": ["accept_source_update", "expected_revision_id"]},
            {"type": "object", "additionalProperties": False,
             "properties": {key: {"type": "string", "minLength": 1}
                            for key in ("rule_id", "template")},
             "required": ["rule_id"]},
            {"type": "object", "additionalProperties": False,
             "properties": {"accept_preview": {"type": "boolean"},
                            "expected_operation_id": operation_id},
             "required": ["accept_preview"]},
            {"type": "object", "additionalProperties": False,
             "properties": {"revise_operations": replacement,
                            "expected_operation_id": operation_id},
             "required": ["revise_operations", "expected_operation_id"]},
            {"type": "object", "additionalProperties": False,
             "properties": {"revise_operations": replacement,
                            "expected_preview_revision": {"type": "integer", "minimum": 1,
                                "description": "Current preview_revision, only for blocked/previewing tasks. A needs_review preview requires its expected_operation_id instead."}},
             "required": ["revise_operations", "expected_preview_revision"]},
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
        raise TaskControlError("unsupported_task_action", "任务支持 create、edit、export、update_source。")
    allowed = {"version", "action"} | _FIELDS[action]
    if set(value) - allowed or not _REQUIRED[action] <= set(value):
        raise TaskControlError("invalid_task_fields", "任务参数缺失或含未支持的字段。")
    for key in _FIELDS[action] & set(value) - {"operations", "export", "choose_columns"}:
        if not isinstance(value[key], str) or not value[key].strip():
            raise TaskControlError("invalid_task_field", f"{key} 必须是非空字符串。")
    if action == "edit":
        if "export" in value and type(value["export"]) is not bool:
            raise TaskControlError("invalid_export_choice", "export 必须为 true 或 false。")
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
    if "choose_columns" in value and value["choose_columns"] is not True:
        raise TaskControlError("invalid_column_choice", "显式列选择使用 choose_columns=true。")
    if value.get("choose_columns") and value.get("profile"):
        raise TaskControlError("profile_selection_conflict", "列选择需要当前原始证据，不能同时复用旧配置。")
    return dict(json.loads(json.dumps(value, ensure_ascii=False, allow_nan=False)))
