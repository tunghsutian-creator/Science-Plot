"""Build one complete assistant history event."""

from __future__ import annotations

from typing import Any
from uuid import uuid4
from sciplot_core.assistant_provider import canonical_payload_sha256

from sciplot_gui.studio_assistant_history.contracts import (
    ASSISTANT_HISTORY_KIND,
    ASSISTANT_HISTORY_VERSION,
    ASSISTANT_HISTORY_STATUSES,
    ASSISTANT_HISTORY_REASON_CODES,
)

from sciplot_gui.studio_assistant_history.values import (
    _now,
    _required_text,
    _optional_text,
    _uuid_text,
    _sha256,
)

from sciplot_gui.studio_assistant_history.operations import (
    _operation_payload,
)

from sciplot_gui.studio_assistant_history.validation import (
    validate_assistant_history_event,
)


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
