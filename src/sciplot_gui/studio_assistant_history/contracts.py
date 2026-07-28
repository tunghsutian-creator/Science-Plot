"""Declare versioned assistant history fields, statuses, and limits."""

from __future__ import annotations

import re


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
        "selected_object_changed",
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
