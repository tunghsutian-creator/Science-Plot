"""Validate one persisted assistant history event."""

from __future__ import annotations

import json
from typing import Any

from sciplot_core.foundation.iso_timestamps import (
    require_zoned_iso_timestamp as _timestamp,
)
from sciplot_gui.studio_assistant_history.contracts import (
    ASSISTANT_HISTORY_KIND,
    ASSISTANT_HISTORY_VERSION,
    ASSISTANT_HISTORY_STATUSES,
    ASSISTANT_HISTORY_REASON_CODES,
    _EVENT_FIELDS,
    _REQUIRED_EVENT_FIELDS,
    _SELECTED_OBJECT_FIELDS,
    _OPERATION_FIELDS,
)

from sciplot_gui.studio_assistant_history.values import (
    _required_text,
    _uuid_text,
    _sha256,
)


def validate_assistant_history_event(payload: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(payload, dict):
        raise ValueError("Assistant history event must be an object.")
    unknown = set(payload) - _EVENT_FIELDS
    if unknown:
        raise ValueError(
            f"Assistant history event has unknown fields: {sorted(unknown)!r}"
        )
    missing = _REQUIRED_EVENT_FIELDS - set(payload)
    if missing:
        raise ValueError(
            f"Assistant history event is missing fields: {sorted(missing)!r}"
        )
    if payload.get("kind") != ASSISTANT_HISTORY_KIND:
        raise ValueError("Not a SciPlot Studio Assistant history event.")
    if payload.get("version") != ASSISTANT_HISTORY_VERSION:
        raise ValueError("Unsupported Studio Assistant history version.")
    _uuid_text(payload.get("event_id"), "event_id")
    recorded_at = _required_text(
        payload.get("recorded_at"),
        "recorded_at",
        maximum=64,
    )
    _timestamp(recorded_at, "recorded_at")
    status = _required_text(payload.get("status"), "status", maximum=64)
    if status not in ASSISTANT_HISTORY_STATUSES:
        raise ValueError(f"Unsupported Assistant history status: {status!r}")
    reason_code = payload.get("reason_code")
    if reason_code is not None:
        reason_code = _required_text(reason_code, "reason_code", maximum=64)
        if reason_code not in ASSISTANT_HISTORY_REASON_CODES:
            raise ValueError(
                f"Unsupported Assistant history reason code: {reason_code!r}"
            )
    _required_text(payload.get("provider_id"), "provider_id", maximum=96)
    _required_text(payload.get("project_id"), "project_id", maximum=256)
    if "model_label" in payload:
        _required_text(payload["model_label"], "model_label", maximum=120)
    if "native_undo_label" in payload:
        _required_text(
            payload["native_undo_label"],
            "native_undo_label",
            maximum=120,
        )
    for field in (
        "request_id",
        "transaction_id",
        "document_id",
    ):
        _uuid_text(payload.get(field), field)
    for field in ("request_sha256", "context_sha256"):
        _sha256(payload.get(field), field)
    for field in ("response_sha256", "batch_sha256"):
        if field in payload:
            _sha256(payload[field], field)
    for field in ("response_id", "batch_id"):
        if field in payload:
            _uuid_text(payload[field], field)
    for field in ("page", "base_revision", "applied_revision"):
        if field not in payload:
            continue
        if isinstance(payload[field], bool) or not isinstance(payload[field], int):
            raise ValueError(f"{field} must be an integer.")
        if payload[field] < 0:
            raise ValueError(f"{field} must be non-negative.")
    for field in (
        "before_page_render_sha256",
        "after_page_render_sha256",
    ):
        if field in payload:
            _sha256(payload[field], field)
    if "render_changed" in payload and type(payload["render_changed"]) is not bool:
        raise ValueError("render_changed must be a boolean.")
    selected = payload.get("selected_object")
    if selected is not None:
        if not isinstance(selected, dict):
            raise ValueError("selected_object must be an object.")
        unknown_selected = set(selected) - _SELECTED_OBJECT_FIELDS
        if unknown_selected:
            raise ValueError(
                f"selected_object has unknown fields: {sorted(unknown_selected)!r}"
            )
        _uuid_text(selected.get("object_id"), "selected object_id")
        _required_text(
            selected.get("object_type"),
            "selected object_type",
            maximum=64,
        )
    operations = payload.get("operations")
    if not isinstance(operations, list):
        raise ValueError("operations must be a list.")
    for operation in operations:
        if not isinstance(operation, dict):
            raise ValueError("Every operation must be an object.")
        unknown_operation = set(operation) - _OPERATION_FIELDS
        if unknown_operation:
            raise ValueError(
                f"operation has unknown fields: {sorted(unknown_operation)!r}"
            )
        if set(operation) != _OPERATION_FIELDS:
            missing = sorted(_OPERATION_FIELDS - set(operation))
            raise ValueError(f"operation is missing fields: {missing!r}")
        _uuid_text(operation.get("operation_id"), "operation_id")
        _required_text(
            operation.get("operation_type"),
            "operation_type",
            maximum=64,
        )
        _uuid_text(operation.get("target_id"), "target_id")
        _required_text(
            operation.get("setting_path"),
            "setting_path",
            maximum=1024,
        )
        _sha256(operation.get("old_value_sha256"), "old_value_sha256")
        _sha256(operation.get("new_value_sha256"), "new_value_sha256")
    if status == "submitted" and (
        operations
        or any(
            field in payload
            for field in (
                "response_id",
                "response_sha256",
                "batch_id",
                "batch_sha256",
                "applied_revision",
                "after_page_render_sha256",
            )
        )
    ):
        raise ValueError("submitted history events must contain request metadata only.")
    if status in {"proposal_ready", "apply_started", "applied", "applied_unverified"}:
        required_proposal_fields = {
            "response_id",
            "response_sha256",
            "batch_id",
            "batch_sha256",
        }
        missing_proposal = required_proposal_fields - set(payload)
        if missing_proposal or not operations:
            raise ValueError(
                f"{status} history events require a typed non-empty proposal."
            )
    if status in {"apply_started", "applied", "applied_unverified"} and (
        "native_undo_label" not in payload
    ):
        raise ValueError(f"{status} history events require native_undo_label.")
    if status == "applied":
        required_applied = {
            "applied_revision",
            "before_page_render_sha256",
            "after_page_render_sha256",
            "render_changed",
        }
        missing_applied = required_applied - set(payload)
        if missing_applied:
            raise ValueError(
                f"applied history event is missing fields: {sorted(missing_applied)!r}"
            )
    if status == "applied_unverified":
        if "applied_revision" not in payload:
            raise ValueError(
                "applied_unverified history events require applied_revision."
            )
        if "after_page_render_sha256" in payload or "render_changed" in payload:
            raise ValueError(
                "applied_unverified history events cannot claim an after render."
            )
    return json.loads(
        json.dumps(
            payload,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        )
    )
