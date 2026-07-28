"""Validate editable-field capability values and operations."""

from __future__ import annotations

import json
from typing import Any
from sciplot_core.json_contract import (
    reject_unknown_keys,
    require_json_list,
    require_json_number,
    require_json_object,
)
from sciplot_core.assistant_operations import (
    _validate_json_value,
)

from sciplot_core.assistant_provider.contracts import (
    ASSISTANT_EDITABLE_FIELD_EDITORS,
    _MAX_EDITING_CAPABILITIES,
    _MAX_CAPABILITY_CHOICES,
    _MAX_CAPABILITY_VALUE_ITEMS,
    _MAX_CAPABILITY_VALUE_BYTES,
)

from sciplot_core.assistant_provider.text_validation import (
    _required_text,
    _optional_text,
    _free_text,
    _uuid_text,
)

from sciplot_core.assistant_provider.context_documents import (
    _text_list,
)


def _validate_capability_value(value: object, *, label: str) -> Any:
    """Accept only bounded Inspector scalars or flat scalar lists."""

    if isinstance(value, dict):
        raise ValueError(f"{label} must not be an object.")
    if isinstance(value, list):
        if len(value) > _MAX_CAPABILITY_VALUE_ITEMS:
            raise ValueError(f"{label} contains too many values.")
        if any(isinstance(item, (dict, list)) for item in value):
            raise ValueError(f"{label} must be a flat scalar list.")
    _validate_json_value(value, path=label)
    encoded = json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")
    if len(encoded) > _MAX_CAPABILITY_VALUE_BYTES:
        raise ValueError(f"{label} is too large for Assistant context.")
    return json.loads(encoded.decode("utf-8"))


def _optional_capability_number(value: object, *, label: str) -> float | int | None:
    if value is None:
        return None
    return require_json_number(value, label=label)


def _validate_editing_capabilities(
    payload: object,
    *,
    selection: dict[str, Any],
) -> dict[str, Any]:
    value = require_json_object(payload, label="context editing_capabilities")
    reject_unknown_keys(
        value,
        {"scope", "target_object_id", "allowed_operations"},
        label="context editing_capabilities",
    )
    scope = _required_text(
        value.get("scope"),
        "context editing_capabilities scope",
        maximum=64,
    )
    if scope != "selected_object":
        raise ValueError(
            "context editing_capabilities scope must be 'selected_object'."
        )
    target_id = _optional_text(
        value.get("target_object_id"),
        "context editing_capabilities target_object_id",
        maximum=96,
    )
    if target_id is not None:
        target_id = _uuid_text(
            target_id,
            "context editing_capabilities target_object_id",
        )
    primary_id = selection.get("primary_object_id")
    if target_id != primary_id:
        raise ValueError(
            "context editing_capabilities target must match the primary selection."
        )

    raw_operations = require_json_list(
        value.get("allowed_operations"),
        label="context editing_capabilities allowed_operations",
    )
    if len(raw_operations) > _MAX_EDITING_CAPABILITIES:
        raise ValueError("context editing_capabilities contains too many operations.")
    if target_id is None and raw_operations:
        raise ValueError(
            "context editing_capabilities cannot expose operations without a target."
        )

    normalized: list[dict[str, Any]] = []
    field_ids: set[str] = set()
    setting_paths: set[str] = set()
    for index, item in enumerate(raw_operations):
        operation = require_json_object(
            item,
            label=f"context editing_capabilities allowed_operations[{index}]",
        )
        reject_unknown_keys(
            operation,
            {
                "operation_type",
                "target_id",
                "field_id",
                "section",
                "label",
                "setting_path",
                "editor",
                "current_value",
                "choices",
                "minimum",
                "maximum",
                "help_text",
            },
            label=f"context editing_capabilities allowed_operations[{index}]",
        )
        if operation.get("operation_type") != "set_setting":
            raise ValueError(
                "Assistant editing capabilities currently allow only set_setting."
            )
        operation_target = _uuid_text(
            operation.get("target_id"),
            "context editing capability target_id",
        )
        if operation_target != target_id:
            raise ValueError(
                "Assistant editing capability target must match the selected object."
            )
        field_id = _required_text(
            operation.get("field_id"),
            "context editing capability field_id",
            maximum=96,
        )
        if field_id in field_ids:
            raise ValueError("Assistant editing capability field IDs must be unique.")
        field_ids.add(field_id)
        setting_path = _required_text(
            operation.get("setting_path"),
            "context editing capability setting_path",
            maximum=1024,
        )
        if not setting_path.startswith("/"):
            raise ValueError(
                "Assistant editing capability setting_path must be absolute."
            )
        if setting_path in setting_paths:
            raise ValueError(
                "Assistant editing capability setting paths must be unique."
            )
        setting_paths.add(setting_path)
        editor = _required_text(
            operation.get("editor"),
            "context editing capability editor",
            maximum=32,
        )
        if editor not in ASSISTANT_EDITABLE_FIELD_EDITORS:
            raise ValueError(
                f"Unsupported Assistant editing capability editor: {editor!r}"
            )
        choices = _text_list(
            operation.get("choices"),
            label="context editing capability choices",
            maximum_item_length=256,
        )
        if len(choices) > _MAX_CAPABILITY_CHOICES:
            raise ValueError("Assistant editing capability contains too many choices.")
        if editor == "choice" and not choices:
            raise ValueError("Choice editing capabilities require bounded choices.")
        minimum = _optional_capability_number(
            operation.get("minimum"),
            label="context editing capability minimum",
        )
        maximum = _optional_capability_number(
            operation.get("maximum"),
            label="context editing capability maximum",
        )
        if minimum is not None and maximum is not None and minimum > maximum:
            raise ValueError(
                "Assistant editing capability minimum cannot exceed maximum."
            )
        normalized.append(
            {
                "operation_type": "set_setting",
                "target_id": operation_target,
                "field_id": field_id,
                "section": _required_text(
                    operation.get("section"),
                    "context editing capability section",
                    maximum=128,
                ),
                "label": _required_text(
                    operation.get("label"),
                    "context editing capability label",
                    maximum=256,
                ),
                "setting_path": setting_path,
                "editor": editor,
                "current_value": _validate_capability_value(
                    operation.get("current_value"),
                    label="context editing capability current_value",
                ),
                "choices": list(choices),
                "minimum": minimum,
                "maximum": maximum,
                "help_text": _free_text(
                    operation.get("help_text", ""),
                    "context editing capability help_text",
                    maximum=1000,
                ),
            }
        )
    return {
        "scope": scope,
        "target_object_id": target_id,
        "allowed_operations": normalized,
    }
