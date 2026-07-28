"""Represent one typed assistant response."""

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
from sciplot_core.assistant_operations import (
    VeuszSettingOperationBatch,
)

from sciplot_core.assistant_provider.contracts import (
    ASSISTANT_RESPONSE_KIND,
    ASSISTANT_RESPONSE_VERSION,
    ASSISTANT_PROPOSAL_KINDS,
    ASSISTANT_RESPONSE_STATUSES,
    _MAX_UNDERSTANDING_LENGTH,
    _MAX_WARNING_LENGTH,
)

from sciplot_core.assistant_provider.text_validation import (
    _now,
    _required_text,
    _optional_text,
    _uuid_text,
    _provider_id,
    _timestamp,
    _sha256,
)

from sciplot_core.assistant_provider.context_documents import (
    _text_list,
)

from sciplot_core.assistant_provider.request import (
    AssistantRequest,
)


@dataclass(frozen=True)
class AssistantResponse:
    request_id: str
    transaction_id: str
    provider_id: str
    request_sha256: str
    status: str
    understanding: str
    proposal_kind: str | None = None
    proposal: dict[str, Any] | None = None
    warnings: tuple[str, ...] = ()
    response_id: str = field(default_factory=lambda: str(uuid4()))
    created_at: str = field(default_factory=_now)

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "response_id", _uuid_text(self.response_id, "response_id")
        )
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
            "request_sha256",
            _sha256(self.request_sha256, "request_sha256"),
        )
        if self.status not in ASSISTANT_RESPONSE_STATUSES:
            raise ValueError(f"Unsupported Assistant response status: {self.status!r}")
        object.__setattr__(
            self,
            "understanding",
            _required_text(
                self.understanding,
                "assistant understanding",
                maximum=_MAX_UNDERSTANDING_LENGTH,
            ),
        )
        warnings = _text_list(
            list(self.warnings),
            label="assistant warnings",
            maximum_item_length=_MAX_WARNING_LENGTH,
        )
        object.__setattr__(self, "warnings", warnings)
        if self.status == "proposal":
            if self.proposal_kind not in ASSISTANT_PROPOSAL_KINDS:
                raise ValueError(
                    "Proposal response requires a supported proposal_kind."
                )
            if not isinstance(self.proposal, dict):
                raise ValueError("Proposal response requires a proposal object.")
            parsed = VeuszSettingOperationBatch.from_dict(self.proposal)
            if parsed.provider != self.provider_id:
                raise ValueError(
                    "Assistant response proposal provider must match provider_id."
                )
            object.__setattr__(self, "proposal", parsed.to_dict())
        elif self.proposal_kind is not None or self.proposal is not None:
            raise ValueError(
                "Non-proposal Assistant responses must not contain a proposal."
            )
        object.__setattr__(
            self, "created_at", _timestamp(self.created_at, "response created_at")
        )

    def validate_for_request(self, request: AssistantRequest) -> None:
        if self.request_id != request.request_id:
            raise ValueError("Assistant response request_id does not match request.")
        if self.transaction_id != request.transaction_id:
            raise ValueError(
                "Assistant response transaction_id does not match request."
            )
        if self.provider_id != request.provider_id:
            raise ValueError("Assistant response provider_id does not match request.")
        if self.request_sha256 != request.payload_sha256:
            raise ValueError(
                "Assistant response request_sha256 does not match the exact request."
            )
        if self.proposal_kind is not None and (
            self.proposal_kind not in request.allowed_proposal_kinds
        ):
            raise ValueError(
                "Assistant response uses a proposal kind not allowed by request."
            )
        if self.proposal_kind == "veusz_setting_operation_batch":
            batch = VeuszSettingOperationBatch.from_dict(dict(self.proposal or {}))
            if batch.base_revision != request.base_revision:
                raise ValueError(
                    "Assistant VeuszSettingOperationBatch base_revision does not "
                    "match request."
                )

    def to_dict(self) -> dict[str, Any]:
        return {
            "kind": ASSISTANT_RESPONSE_KIND,
            "version": ASSISTANT_RESPONSE_VERSION,
            "response_id": self.response_id,
            "request_id": self.request_id,
            "transaction_id": self.transaction_id,
            "provider_id": self.provider_id,
            "request_sha256": self.request_sha256,
            "status": self.status,
            "understanding": self.understanding,
            "proposal_kind": self.proposal_kind,
            "proposal": (
                copy.deepcopy(self.proposal) if self.proposal is not None else None
            ),
            "warnings": list(self.warnings),
            "created_at": self.created_at,
        }

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> AssistantResponse:
        value = require_json_object(payload, label="AssistantResponse")
        reject_unknown_keys(
            value,
            {
                "kind",
                "version",
                "response_id",
                "request_id",
                "transaction_id",
                "provider_id",
                "request_sha256",
                "status",
                "understanding",
                "proposal_kind",
                "proposal",
                "warnings",
                "created_at",
            },
            label="AssistantResponse",
        )
        if value.get("kind") != ASSISTANT_RESPONSE_KIND:
            raise ValueError("Not a SciPlot AssistantResponse payload.")
        if require_json_int(value.get("version", 0), label="version") != (
            ASSISTANT_RESPONSE_VERSION
        ):
            raise ValueError("Unsupported AssistantResponse version.")
        proposal = value.get("proposal")
        if proposal is not None:
            proposal = dict(
                require_json_object(proposal, label="Assistant response proposal")
            )
        return cls(
            response_id=_uuid_text(value.get("response_id"), "response_id"),
            request_id=_uuid_text(value.get("request_id"), "request_id"),
            transaction_id=_uuid_text(value.get("transaction_id"), "transaction_id"),
            provider_id=_provider_id(value.get("provider_id")),
            request_sha256=_sha256(
                value.get("request_sha256"),
                "request_sha256",
            ),
            status=_required_text(value.get("status"), "status"),
            understanding=_required_text(
                value.get("understanding"),
                "assistant understanding",
                maximum=_MAX_UNDERSTANDING_LENGTH,
            ),
            proposal_kind=_optional_text(
                value.get("proposal_kind"), "proposal_kind", maximum=64
            ),
            proposal=proposal,
            warnings=_text_list(
                value.get("warnings", []),
                label="assistant warnings",
                maximum_item_length=_MAX_WARNING_LENGTH,
            ),
            created_at=_timestamp(value.get("created_at"), "response created_at"),
        )
