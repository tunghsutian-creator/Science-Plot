"""Validate document inventory and review context."""

from __future__ import annotations

from typing import Any
from sciplot_core.json_contract import (
    reject_unknown_keys,
    require_json_int,
    require_json_list,
    require_json_object,
)

from sciplot_core.assistant_provider.contracts import (
    _MAX_CONTEXT_OBJECTS,
    _MAX_CONTEXT_OBJECT_TYPES,
    _MAX_REVIEW_ANNOTATIONS,
)

from sciplot_core.assistant_provider.text_validation import (
    _required_text,
    _optional_text,
    _free_text,
)


def _text_list(
    value: object,
    *,
    label: str,
    allowed: frozenset[str] | None = None,
    maximum_item_length: int | None = None,
) -> tuple[str, ...]:
    items = require_json_list(value, label=label)
    result = tuple(
        _required_text(
            item,
            f"{label} item",
            maximum=maximum_item_length,
        )
        for item in items
    )
    if len(set(result)) != len(result):
        raise ValueError(f"{label} must contain unique values.")
    if allowed is not None:
        unsupported = sorted(set(result) - set(allowed))
        if unsupported:
            raise ValueError(f"{label} contains unsupported values: {unsupported!r}")
    return result


def _validate_document_inventory(payload: object) -> dict[str, Any]:
    value = require_json_object(payload, label="context document_inventory")
    reject_unknown_keys(
        value,
        {"object_count", "object_types"},
        label="context document_inventory",
    )
    object_count = require_json_int(
        value.get("object_count"),
        label="context document_inventory object_count",
    )
    if not 0 <= object_count <= _MAX_CONTEXT_OBJECTS:
        raise ValueError(
            "context document_inventory object_count is outside the supported bound."
        )
    raw_types = require_json_object(
        value.get("object_types"),
        label="context document_inventory object_types",
    )
    if len(raw_types) > _MAX_CONTEXT_OBJECT_TYPES:
        raise ValueError("context document_inventory contains too many object types.")
    object_types: dict[str, int] = {}
    for key, item in raw_types.items():
        object_type = _required_text(
            key,
            "context document_inventory object type",
            maximum=64,
        )
        count = require_json_int(
            item,
            label=f"context document_inventory count for {object_type!r}",
        )
        if count < 0:
            raise ValueError("context document_inventory counts must be non-negative.")
        object_types[object_type] = count
    if sum(object_types.values()) != object_count:
        raise ValueError("context document_inventory counts must sum to object_count.")
    return {
        "object_count": object_count,
        "object_types": dict(sorted(object_types.items())),
    }


def _validate_review(payload: object) -> dict[str, Any]:
    value = require_json_object(payload, label="context review")
    reject_unknown_keys(
        value,
        {"active_count", "annotations"},
        label="context review",
    )
    active_count = require_json_int(
        value.get("active_count"),
        label="context review active_count",
    )
    annotations = require_json_list(
        value.get("annotations"),
        label="context review annotations",
    )
    if active_count != len(annotations):
        raise ValueError("context review active_count must match annotations.")
    if len(annotations) > _MAX_REVIEW_ANNOTATIONS:
        raise ValueError("context review contains too many annotations.")
    normalized: list[dict[str, Any]] = []
    annotation_ids: set[str] = set()
    for index, item in enumerate(annotations):
        annotation = require_json_object(
            item,
            label=f"context review annotations[{index}]",
        )
        reject_unknown_keys(
            annotation,
            {
                "annotation_id",
                "shape",
                "coordinate_space",
                "target_object_id",
                "text",
            },
            label=f"context review annotations[{index}]",
        )
        annotation_id = _required_text(
            annotation.get("annotation_id"),
            "context review annotation_id",
            maximum=96,
        )
        if annotation_id in annotation_ids:
            raise ValueError("context review annotation IDs must be unique.")
        annotation_ids.add(annotation_id)
        target = _optional_text(
            annotation.get("target_object_id"),
            "context review target_object_id",
            maximum=96,
        )
        normalized.append(
            {
                "annotation_id": annotation_id,
                "shape": _required_text(
                    annotation.get("shape"),
                    "context review shape",
                    maximum=32,
                ),
                "coordinate_space": _required_text(
                    annotation.get("coordinate_space"),
                    "context review coordinate_space",
                    maximum=32,
                ),
                "target_object_id": target,
                "text": _free_text(
                    annotation.get("text", ""),
                    "context review text",
                    maximum=2000,
                ),
            }
        )
    return {"active_count": active_count, "annotations": normalized}
