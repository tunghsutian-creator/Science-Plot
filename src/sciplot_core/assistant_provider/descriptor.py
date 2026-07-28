"""Represent one assistant provider descriptor."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any
from sciplot_core.json_contract import (
    reject_unknown_keys,
    require_json_int,
    require_json_object,
)

from sciplot_core.assistant_provider.contracts import (
    ASSISTANT_PROVIDER_DESCRIPTOR_KIND,
    ASSISTANT_PROVIDER_DESCRIPTOR_VERSION,
    ASSISTANT_PROPOSAL_KINDS,
    ASSISTANT_PROVIDER_CAPABILITIES,
    ASSISTANT_DATA_POLICY,
)

from sciplot_core.assistant_provider.text_validation import (
    _required_text,
    _optional_text,
    _provider_id,
)

from sciplot_core.assistant_provider.context_documents import (
    _text_list,
)


@dataclass(frozen=True)
class AssistantProviderDescriptor:
    provider_id: str
    display_name: str
    capabilities: tuple[str, ...]
    model_label: str | None = None
    data_policy: str = ASSISTANT_DATA_POLICY

    def __post_init__(self) -> None:
        object.__setattr__(self, "provider_id", _provider_id(self.provider_id))
        object.__setattr__(
            self,
            "display_name",
            _required_text(self.display_name, "display_name", maximum=120),
        )
        capabilities = tuple(self.capabilities)
        if not capabilities:
            raise ValueError("Assistant provider must declare at least one capability.")
        _text_list(
            list(capabilities),
            label="provider capabilities",
            allowed=ASSISTANT_PROVIDER_CAPABILITIES,
        )
        if not set(capabilities) & set(ASSISTANT_PROPOSAL_KINDS):
            raise ValueError(
                "Assistant provider must support at least one typed proposal kind."
            )
        object.__setattr__(self, "capabilities", capabilities)
        object.__setattr__(
            self,
            "model_label",
            _optional_text(self.model_label, "model_label", maximum=120),
        )
        if self.data_policy != ASSISTANT_DATA_POLICY:
            raise ValueError("Assistant provider has an unsupported data policy.")

    @property
    def supports_cancellation(self) -> bool:
        return "cancellation" in self.capabilities

    @property
    def proposal_kinds(self) -> tuple[str, ...]:
        return tuple(
            item for item in self.capabilities if item in ASSISTANT_PROPOSAL_KINDS
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "kind": ASSISTANT_PROVIDER_DESCRIPTOR_KIND,
            "version": ASSISTANT_PROVIDER_DESCRIPTOR_VERSION,
            "provider_id": self.provider_id,
            "display_name": self.display_name,
            "model_label": self.model_label,
            "capabilities": list(self.capabilities),
            "data_policy": self.data_policy,
        }

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> AssistantProviderDescriptor:
        value = require_json_object(payload, label="AssistantProviderDescriptor")
        reject_unknown_keys(
            value,
            {
                "kind",
                "version",
                "provider_id",
                "display_name",
                "model_label",
                "capabilities",
                "data_policy",
            },
            label="AssistantProviderDescriptor",
        )
        if value.get("kind") != ASSISTANT_PROVIDER_DESCRIPTOR_KIND:
            raise ValueError("Not a SciPlot AssistantProviderDescriptor payload.")
        if require_json_int(value.get("version", 0), label="version") != (
            ASSISTANT_PROVIDER_DESCRIPTOR_VERSION
        ):
            raise ValueError("Unsupported AssistantProviderDescriptor version.")
        return cls(
            provider_id=_provider_id(value.get("provider_id")),
            display_name=_required_text(
                value.get("display_name"), "display_name", maximum=120
            ),
            model_label=_optional_text(
                value.get("model_label"), "model_label", maximum=120
            ),
            capabilities=_text_list(
                value.get("capabilities"),
                label="provider capabilities",
                allowed=ASSISTANT_PROVIDER_CAPABILITIES,
            ),
            data_policy=_required_text(value.get("data_policy"), "data_policy"),
        )
