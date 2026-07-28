"""Normalize an assistant operation batch for durable history."""

from __future__ import annotations

from typing import Any

from sciplot_gui.studio_assistant_history.values import (
    _required_text,
    _uuid_text,
    canonical_value_sha256,
)


def _operation_payload(operation: Any) -> dict[str, Any]:
    if isinstance(operation, dict):
        operation_id = operation.get("operation_id")
        operation_type = operation.get("operation_type") or "set_setting"
        target_id = operation.get("target_id")
        setting_path = operation.get("setting_path")
        old_value = operation.get("old_value")
        new_value = operation.get("new_value")
    else:
        arguments = getattr(operation, "arguments", {})
        operation_id = getattr(operation, "operation_id", None)
        operation_type = getattr(operation, "operation_type", None)
        target_id = getattr(operation, "target_id", None)
        setting_path = arguments.get("setting_path")
        old_value = arguments.get("expected_value")
        new_value = arguments.get("value")
    return {
        "operation_id": _uuid_text(operation_id, "operation_id"),
        "operation_type": _required_text(
            operation_type,
            "operation_type",
            maximum=64,
        ),
        "target_id": _uuid_text(target_id, "target_id"),
        "setting_path": _required_text(
            setting_path,
            "setting_path",
            maximum=1024,
        ),
        "old_value_sha256": canonical_value_sha256(old_value),
        "new_value_sha256": canonical_value_sha256(new_value),
    }
