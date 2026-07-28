"""Represent one provider progress event."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any
from sciplot_core.json_contract import (
    reject_unknown_keys,
    require_json_bool,
    require_json_int,
    require_json_number,
    require_json_object,
)

from sciplot_core.assistant_provider.contracts import (
    ASSISTANT_PROGRESS_KIND,
    ASSISTANT_PROGRESS_VERSION,
    ASSISTANT_PROGRESS_STAGES,
    _MAX_PROGRESS_MESSAGE_LENGTH,
)

from sciplot_core.assistant_provider.text_validation import (
    _now,
    _required_text,
    _uuid_text,
    _provider_id,
    _timestamp,
)


@dataclass(frozen=True)
class AssistantProgressEvent:
    request_id: str
    provider_id: str
    sequence: int
    stage: str
    message: str
    cancellable: bool
    progress: float | None = None
    created_at: str = field(default_factory=_now)

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "request_id", _uuid_text(self.request_id, "request_id")
        )
        object.__setattr__(self, "provider_id", _provider_id(self.provider_id))
        if isinstance(self.sequence, bool) or not isinstance(self.sequence, int):
            raise ValueError("Assistant progress sequence must be an integer.")
        if self.sequence < 1:
            raise ValueError("Assistant progress sequence must be positive.")
        if self.stage not in ASSISTANT_PROGRESS_STAGES:
            raise ValueError(f"Unsupported Assistant progress stage: {self.stage!r}")
        object.__setattr__(
            self,
            "message",
            _required_text(
                self.message,
                "progress message",
                maximum=_MAX_PROGRESS_MESSAGE_LENGTH,
            ),
        )
        if type(self.cancellable) is not bool:
            raise ValueError("Assistant progress cancellable must be a boolean.")
        if self.progress is not None:
            progress = require_json_number(self.progress, label="progress")
            if not 0.0 <= progress <= 1.0:
                raise ValueError("Assistant progress must be between zero and one.")
            object.__setattr__(self, "progress", progress)
        object.__setattr__(
            self, "created_at", _timestamp(self.created_at, "progress created_at")
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "kind": ASSISTANT_PROGRESS_KIND,
            "version": ASSISTANT_PROGRESS_VERSION,
            "request_id": self.request_id,
            "provider_id": self.provider_id,
            "sequence": self.sequence,
            "stage": self.stage,
            "message": self.message,
            "cancellable": self.cancellable,
            "progress": self.progress,
            "created_at": self.created_at,
        }

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> AssistantProgressEvent:
        value = require_json_object(payload, label="AssistantProgressEvent")
        reject_unknown_keys(
            value,
            {
                "kind",
                "version",
                "request_id",
                "provider_id",
                "sequence",
                "stage",
                "message",
                "cancellable",
                "progress",
                "created_at",
            },
            label="AssistantProgressEvent",
        )
        if value.get("kind") != ASSISTANT_PROGRESS_KIND:
            raise ValueError("Not a SciPlot AssistantProgressEvent payload.")
        if require_json_int(value.get("version", 0), label="version") != (
            ASSISTANT_PROGRESS_VERSION
        ):
            raise ValueError("Unsupported AssistantProgressEvent version.")
        return cls(
            request_id=_uuid_text(value.get("request_id"), "request_id"),
            provider_id=_provider_id(value.get("provider_id")),
            sequence=require_json_int(value.get("sequence"), label="sequence"),
            stage=_required_text(value.get("stage"), "stage"),
            message=_required_text(
                value.get("message"),
                "progress message",
                maximum=_MAX_PROGRESS_MESSAGE_LENGTH,
            ),
            cancellable=require_json_bool(
                value.get("cancellable"), label="cancellable"
            ),
            progress=(
                require_json_number(value["progress"], label="progress")
                if value.get("progress") is not None
                else None
            ),
            created_at=_timestamp(value.get("created_at"), "progress created_at"),
        )
