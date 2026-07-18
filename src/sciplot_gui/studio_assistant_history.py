from __future__ import annotations

import hashlib
import json
import os
import re
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from uuid import UUID, uuid4

from sciplot_core.canvas.provider import canonical_payload_sha256

ASSISTANT_HISTORY_KIND = "sciplot_studio_assistant_history_event"
ASSISTANT_HISTORY_VERSION = 1
ASSISTANT_HISTORY_FILENAME = "assistant_history.jsonl"

ASSISTANT_HISTORY_STATUSES = frozenset(
    {
        "submitted",
        "proposal_ready",
        "apply_started",
        "applied",
        "applied_unverified",
        "rejected",
        "cancelled",
        "needs_human_confirmation",
        "needs_rule_repair",
        "failed",
    }
)
ASSISTANT_HISTORY_REASON_CODES = frozenset(
    {
        "after_render_verification_failed",
        "apply_failed",
        "document_revision_changed",
        "history_write_failed",
        "no_active_request",
        "provider_failed",
        "request_submit_failed",
        "superseded_by_new_request",
        "typed_validation_failed",
        "unsupported_proposal_kind",
        "user_rejected",
        "window_closed",
    }
)

_SHA256 = re.compile(r"[0-9a-f]{64}")
_EVENT_FIELDS = frozenset(
    {
        "kind",
        "version",
        "event_id",
        "recorded_at",
        "status",
        "reason_code",
        "request_id",
        "transaction_id",
        "provider_id",
        "model_label",
        "request_sha256",
        "context_sha256",
        "document_id",
        "project_id",
        "page",
        "base_revision",
        "applied_revision",
        "before_page_render_sha256",
        "after_page_render_sha256",
        "response_id",
        "response_sha256",
        "batch_id",
        "batch_sha256",
        "render_changed",
        "selected_object",
        "operations",
        "native_undo_label",
    }
)
_REQUIRED_EVENT_FIELDS = frozenset(
    {
        "kind",
        "version",
        "event_id",
        "recorded_at",
        "status",
        "request_id",
        "transaction_id",
        "provider_id",
        "request_sha256",
        "context_sha256",
        "document_id",
        "project_id",
        "page",
        "base_revision",
        "operations",
    }
)
_SELECTED_OBJECT_FIELDS = frozenset({"object_id", "object_type"})
_OPERATION_FIELDS = frozenset(
    {
        "operation_id",
        "operation_type",
        "target_id",
        "setting_path",
        "old_value_sha256",
        "new_value_sha256",
    }
)


def _now() -> str:
    return datetime.now(UTC).isoformat()


def _required_text(value: object, label: str, *, maximum: int = 512) -> str:
    if not isinstance(value, str):
        raise ValueError(f"{label} must be text.")
    text = value.strip()
    if not text:
        raise ValueError(f"{label} must not be empty.")
    if len(text) > maximum:
        raise ValueError(f"{label} must contain at most {maximum} characters.")
    return text


def _optional_text(
    value: object,
    label: str,
    *,
    maximum: int = 512,
) -> str | None:
    if value is None:
        return None
    return _required_text(value, label, maximum=maximum)


def _uuid_text(value: object, label: str) -> str:
    text = _required_text(value, label, maximum=64)
    try:
        return str(UUID(text))
    except ValueError as exc:
        raise ValueError(f"{label} must be a UUID.") from exc


def _sha256(value: object, label: str) -> str:
    text = _required_text(value, label, maximum=64).casefold()
    if _SHA256.fullmatch(text) is None:
        raise ValueError(f"{label} must be a lowercase SHA-256 digest.")
    return text


def canonical_value_sha256(value: Any) -> str:
    """Hash one JSON-safe setting value without retaining the value itself."""

    encoded = json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def assistant_history_path(document_path: Path) -> Path:
    """Return a project-local sidecar path without exposing it in history rows."""

    resolved = document_path.expanduser().resolve()
    if (
        resolved.parent.name == "studio"
        and (resolved.parent.parent / "plot_request.json").is_file()
    ):
        return resolved.parent.parent / ".sciplot_studio" / ASSISTANT_HISTORY_FILENAME
    path_key = hashlib.sha256(str(resolved).encode("utf-8")).hexdigest()[:12]
    return (
        resolved.parent
        / ".sciplot_studio"
        / f"{resolved.stem}_{path_key}"
        / ASSISTANT_HISTORY_FILENAME
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


def build_assistant_history_event(
    *,
    status: str,
    request: Any,
    descriptor: Any | None = None,
    response: Any | None = None,
    batch: Any | None = None,
    operations: list[Any] | tuple[Any, ...] | None = None,
    reason_code: str | None = None,
    applied_revision: int | None = None,
    after_page_render_sha256: str | None = None,
    render_changed: bool | None = None,
    native_undo_label: str | None = None,
) -> dict[str, Any]:
    """Build an allowlisted history row from typed host-owned objects.

    The function intentionally projects hashes and identifiers only. It never
    serializes the request image, intent, provider instructions, model text,
    credentials, endpoint configuration, or raw setting values.
    """

    normalized_status = _required_text(status, "status", maximum=64)
    if normalized_status not in ASSISTANT_HISTORY_STATUSES:
        raise ValueError(f"Unsupported Assistant history status: {status!r}")
    if reason_code is not None:
        reason_code = _required_text(reason_code, "reason_code", maximum=64)
        if reason_code not in ASSISTANT_HISTORY_REASON_CODES:
            raise ValueError(
                f"Unsupported Assistant history reason code: {reason_code!r}"
            )

    context = request.context
    selected = context.get("selected_object")
    selected_payload = None
    if isinstance(selected, dict):
        selected_payload = {
            "object_id": _uuid_text(
                selected.get("object_id"),
                "selected object_id",
            ),
            "object_type": _required_text(
                selected.get("object_type"),
                "selected object_type",
                maximum=64,
            ),
        }
    preview = request.visual_preview
    before_render = (
        _sha256(preview.get("sha256"), "before page render sha256")
        if isinstance(preview, dict)
        else None
    )
    model_label = (
        _optional_text(
            getattr(descriptor, "model_label", None),
            "model_label",
            maximum=120,
        )
        if descriptor is not None
        else None
    )
    operation_values = (
        list(operations)
        if operations is not None
        else list(getattr(batch, "operations", ()))
        if batch is not None
        else []
    )
    payload: dict[str, Any] = {
        "kind": ASSISTANT_HISTORY_KIND,
        "version": ASSISTANT_HISTORY_VERSION,
        "event_id": str(uuid4()),
        "recorded_at": _now(),
        "status": normalized_status,
        "request_id": _uuid_text(request.request_id, "request_id"),
        "transaction_id": _uuid_text(
            request.transaction_id,
            "transaction_id",
        ),
        "provider_id": _required_text(
            request.provider_id,
            "provider_id",
            maximum=96,
        ),
        "request_sha256": _sha256(
            request.payload_sha256,
            "request_sha256",
        ),
        "context_sha256": _sha256(
            request.context_sha256,
            "context_sha256",
        ),
        "document_id": _uuid_text(
            context.get("document_id"),
            "document_id",
        ),
        "project_id": _required_text(
            context.get("project_id"),
            "project_id",
            maximum=256,
        ),
        "page": int(context.get("page")),
        "base_revision": int(request.base_revision),
        "operations": [_operation_payload(operation) for operation in operation_values],
    }
    if reason_code is not None:
        payload["reason_code"] = reason_code
    if model_label is not None:
        payload["model_label"] = model_label
    if before_render is not None:
        payload["before_page_render_sha256"] = before_render
    if selected_payload is not None:
        payload["selected_object"] = selected_payload
    if response is not None:
        payload["response_id"] = _uuid_text(
            response.response_id,
            "response_id",
        )
        payload["response_sha256"] = canonical_payload_sha256(response.to_dict())
    if batch is not None:
        payload["batch_id"] = _uuid_text(batch.batch_id, "batch_id")
        payload["batch_sha256"] = canonical_payload_sha256(batch.to_dict())
    if applied_revision is not None:
        payload["applied_revision"] = int(applied_revision)
    if after_page_render_sha256 is not None:
        payload["after_page_render_sha256"] = _sha256(
            after_page_render_sha256,
            "after page render sha256",
        )
    if render_changed is not None:
        if type(render_changed) is not bool:
            raise ValueError("render_changed must be a boolean.")
        payload["render_changed"] = render_changed
    if native_undo_label is not None:
        payload["native_undo_label"] = _required_text(
            native_undo_label,
            "native_undo_label",
            maximum=120,
        )
    return validate_assistant_history_event(payload)


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
    try:
        parsed_recorded_at = datetime.fromisoformat(recorded_at)
    except ValueError as exc:
        raise ValueError("recorded_at must be an ISO timestamp.") from exc
    if parsed_recorded_at.tzinfo is None:
        raise ValueError("recorded_at must include a timezone.")
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


def append_assistant_history_event(
    path: Path,
    payload: dict[str, Any],
) -> Path:
    event = validate_assistant_history_event(payload)
    target = path.expanduser().resolve()
    target.parent.mkdir(parents=True, exist_ok=True)
    encoded = json.dumps(
        event,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    )
    with target.open("a", encoding="utf-8") as handle:
        handle.write(encoded)
        handle.write("\n")
        handle.flush()
        os.fsync(handle.fileno())
    return target


def read_assistant_history(path: Path) -> list[dict[str, Any]]:
    target = path.expanduser()
    if not target.is_file():
        return []
    events: list[dict[str, Any]] = []
    for line_number, line in enumerate(
        target.read_text(encoding="utf-8").splitlines(),
        1,
    ):
        if not line.strip():
            continue
        payload = json.loads(line)
        if not isinstance(payload, dict):
            raise ValueError(f"Assistant history line {line_number} is not an object.")
        events.append(validate_assistant_history_event(payload))
    return events


__all__ = [
    "ASSISTANT_HISTORY_FILENAME",
    "ASSISTANT_HISTORY_KIND",
    "ASSISTANT_HISTORY_REASON_CODES",
    "ASSISTANT_HISTORY_STATUSES",
    "ASSISTANT_HISTORY_VERSION",
    "append_assistant_history_event",
    "assistant_history_path",
    "build_assistant_history_event",
    "canonical_value_sha256",
    "read_assistant_history",
    "validate_assistant_history_event",
]
