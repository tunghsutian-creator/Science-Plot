"""Represent one immutable assistant request."""

from __future__ import annotations

import copy
from dataclasses import dataclass, field
from typing import Any
from uuid import uuid4
from sciplot_core.json_contract import (
    reject_unknown_keys,
    require_json_int,
    require_json_object,
)

from sciplot_core.assistant_provider.contracts import (
    ASSISTANT_REQUEST_KIND,
    ASSISTANT_REQUEST_VERSION,
    ASSISTANT_PROPOSAL_KINDS,
    ASSISTANT_MAX_INTENT_LENGTH,
)

from sciplot_core.assistant_provider.text_validation import (
    _now,
    _required_text,
    _uuid_text,
    _provider_id,
    _timestamp,
    _sha256,
    canonical_payload_sha256,
)

from sciplot_core.assistant_provider.visual_preview import (
    _validate_visual_preview,
)

from sciplot_core.assistant_provider.context_documents import (
    _text_list,
)

from sciplot_core.assistant_provider.context_validation import (
    _validate_context,
)


@dataclass(frozen=True)
class AssistantRequest:
    transaction_id: str
    provider_id: str
    intent: str
    base_revision: int
    context: dict[str, Any]
    allowed_proposal_kinds: tuple[str, ...]
    request_id: str = field(default_factory=lambda: str(uuid4()))
    context_sha256: str | None = None
    created_at: str = field(default_factory=_now)
    visual_preview: dict[str, Any] | None = None

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "request_id", _uuid_text(self.request_id, "request_id")
        )
        object.__setattr__(
            self,
            "transaction_id",
            _uuid_text(self.transaction_id, "transaction_id"),
        )
        object.__setattr__(self, "provider_id", _provider_id(self.provider_id))
        object.__setattr__(
            self,
            "intent",
            _required_text(
                self.intent,
                "assistant intent",
                maximum=ASSISTANT_MAX_INTENT_LENGTH,
            ),
        )
        if isinstance(self.base_revision, bool) or not isinstance(
            self.base_revision, int
        ):
            raise ValueError("Assistant request base_revision must be an integer.")
        if self.base_revision < 0:
            raise ValueError("Assistant request base_revision must be non-negative.")
        context = _validate_context(self.context)
        object.__setattr__(self, "context", context)
        allowed = _text_list(
            list(self.allowed_proposal_kinds),
            label="allowed_proposal_kinds",
            allowed=ASSISTANT_PROPOSAL_KINDS,
        )
        if not allowed:
            raise ValueError("Assistant request must allow a typed proposal kind.")
        object.__setattr__(self, "allowed_proposal_kinds", allowed)
        expected_sha = canonical_payload_sha256(context)
        if self.context_sha256 is not None:
            supplied = _sha256(self.context_sha256, "context_sha256")
            if supplied != expected_sha:
                raise ValueError(
                    "Assistant request context_sha256 does not match context."
                )
        object.__setattr__(self, "context_sha256", expected_sha)
        object.__setattr__(
            self, "created_at", _timestamp(self.created_at, "request created_at")
        )
        if context["revision"] != self.base_revision:
            raise ValueError(
                "Assistant request context revision must match base_revision."
            )
        object.__setattr__(
            self,
            "visual_preview",
            _validate_visual_preview(
                self.visual_preview,
                base_revision=self.base_revision,
            ),
        )

    def to_dict(self) -> dict[str, Any]:
        payload = {
            "kind": ASSISTANT_REQUEST_KIND,
            "version": ASSISTANT_REQUEST_VERSION,
            "request_id": self.request_id,
            "transaction_id": self.transaction_id,
            "provider_id": self.provider_id,
            "intent": self.intent,
            "base_revision": self.base_revision,
            "context": copy.deepcopy(self.context),
            "context_sha256": self.context_sha256,
            "allowed_proposal_kinds": list(self.allowed_proposal_kinds),
            "created_at": self.created_at,
        }
        if self.visual_preview is not None:
            payload["visual_preview"] = copy.deepcopy(self.visual_preview)
        return payload

    @property
    def payload_sha256(self) -> str:
        return canonical_payload_sha256(self.to_dict())

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> AssistantRequest:
        value = require_json_object(payload, label="AssistantRequest")
        reject_unknown_keys(
            value,
            {
                "kind",
                "version",
                "request_id",
                "transaction_id",
                "provider_id",
                "intent",
                "base_revision",
                "context",
                "context_sha256",
                "allowed_proposal_kinds",
                "created_at",
                "visual_preview",
            },
            label="AssistantRequest",
        )
        if value.get("kind") != ASSISTANT_REQUEST_KIND:
            raise ValueError("Not a SciPlot AssistantRequest payload.")
        if require_json_int(value.get("version", 0), label="version") != (
            ASSISTANT_REQUEST_VERSION
        ):
            raise ValueError("Unsupported AssistantRequest version.")
        return cls(
            request_id=_uuid_text(value.get("request_id"), "request_id"),
            transaction_id=_uuid_text(value.get("transaction_id"), "transaction_id"),
            provider_id=_provider_id(value.get("provider_id")),
            intent=_required_text(
                value.get("intent"),
                "assistant intent",
                maximum=ASSISTANT_MAX_INTENT_LENGTH,
            ),
            base_revision=require_json_int(
                value.get("base_revision"), label="base_revision"
            ),
            context=dict(require_json_object(value.get("context"), label="context")),
            context_sha256=_sha256(value.get("context_sha256"), "context_sha256"),
            allowed_proposal_kinds=_text_list(
                value.get("allowed_proposal_kinds"),
                label="allowed_proposal_kinds",
                allowed=ASSISTANT_PROPOSAL_KINDS,
            ),
            created_at=_timestamp(value.get("created_at"), "request created_at"),
            visual_preview=(
                dict(
                    require_json_object(
                        value["visual_preview"],
                        label="visual_preview",
                    )
                )
                if "visual_preview" in value
                else None
            ),
        )
