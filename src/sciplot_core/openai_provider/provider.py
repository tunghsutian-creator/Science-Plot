"""Translate assistant requests and model envelopes at the provider boundary."""

from __future__ import annotations

import json
from typing import Any, Callable
from sciplot_core.assistant_operations import (
    VeuszSettingOperation,
    VeuszSettingOperationBatch,
)
from sciplot_core.assistant_provider import (
    AssistantCancellationToken,
    AssistantProgressEvent,
    AssistantProviderDescriptor,
    AssistantRequest,
    AssistantResponse,
)

from sciplot_core.openai_provider.contracts import (
    OPENAI_PROVIDER_ID,
    OPENAI_ASSISTANT_OUTPUT_SCHEMA,
    _PROVIDER_INSTRUCTIONS,
)

from sciplot_core.openai_provider.errors import (
    _AssistantContextUnavailable,
)

from sciplot_core.openai_provider.validation import (
    _redact,
)

from sciplot_core.openai_provider.config import (
    OpenAIResponsesConfig,
)

from sciplot_core.openai_provider.sse_client import (
    _ResponsesSSEClient,
)

from sciplot_core.openai_provider.model_output import (
    _json_loads_strict,
    _model_envelope,
    _coerce_value,
    _provider_safe_context,
)


class OpenAIResponsesProvider:
    """Production Responses API adapter behind SciPlot's typed proposal boundary."""

    def __init__(
        self,
        config: OpenAIResponsesConfig,
        *,
        _connection_factory: Callable[[str, str, int | None, float], Any] | None = None,
    ) -> None:
        self.config = config
        self._descriptor = AssistantProviderDescriptor(
            provider_id=OPENAI_PROVIDER_ID,
            display_name="OpenAI Assistant",
            model_label=config.model,
            capabilities=("veusz_setting_operation_batch", "cancellation"),
        )
        self._client = _ResponsesSSEClient(
            config,
            connection_factory=_connection_factory,
        )

    @property
    def descriptor(self) -> AssistantProviderDescriptor:
        return self._descriptor

    def request_payload(self, request: AssistantRequest) -> dict[str, Any]:
        if request.provider_id != self.descriptor.provider_id:
            raise ValueError("Assistant request targets another provider.")
        if request.allowed_proposal_kinds != ("veusz_setting_operation_batch",):
            raise ValueError(
                "OpenAI provider currently accepts only "
                "VeuszSettingOperationBatch requests."
            )
        _provider_safe_context(request.context)
        user_payload = {
            "task": "Propose a bounded SciPlot Veusz selected-object edit.",
            "intent": request.intent,
            "base_revision": request.base_revision,
            "allowed_proposal_kinds": list(request.allowed_proposal_kinds),
            "context": request.context,
        }
        preview = request.visual_preview
        if preview is not None:
            user_payload["visual_preview"] = {
                "sha256": preview["sha256"],
                "width": preview["width"],
                "height": preview["height"],
                "revision": preview["revision"],
            }
        content: list[dict[str, Any]] = [
            {
                "type": "input_text",
                "text": json.dumps(
                    user_payload,
                    ensure_ascii=False,
                    sort_keys=True,
                    separators=(",", ":"),
                    allow_nan=False,
                ),
            }
        ]
        if preview is not None:
            content.append(
                {
                    "type": "input_image",
                    "image_url": f"data:image/png;base64,{preview['base64']}",
                    "detail": "high",
                }
            )
        return {
            "model": self.config.model,
            "store": False,
            "stream": True,
            "reasoning": {"effort": self.config.reasoning_effort},
            "max_output_tokens": self.config.max_output_tokens,
            "instructions": _PROVIDER_INSTRUCTIONS,
            "input": [
                {
                    "role": "user",
                    "content": content,
                }
            ],
            "text": {
                "format": {
                    "type": "json_schema",
                    "name": "sciplot_veusz_assistant_response",
                    "strict": True,
                    "schema": OPENAI_ASSISTANT_OUTPUT_SCHEMA,
                }
            },
        }

    def _response(
        self,
        request: AssistantRequest,
        *,
        status: str,
        understanding: str,
        warnings: tuple[str, ...] = (),
        batch: VeuszSettingOperationBatch | None = None,
    ) -> AssistantResponse:
        return AssistantResponse(
            request_id=request.request_id,
            transaction_id=request.transaction_id,
            provider_id=request.provider_id,
            request_sha256=request.payload_sha256,
            status=status,
            understanding=understanding,
            proposal_kind=(
                "veusz_setting_operation_batch" if batch is not None else None
            ),
            proposal=(batch.to_dict() if batch is not None else None),
            warnings=warnings,
        )

    def _typed_model_response(
        self,
        request: AssistantRequest,
        envelope: dict[str, Any],
    ) -> AssistantResponse:
        if envelope["status"] != "proposal":
            return self._response(
                request,
                status=envelope["status"],
                understanding=envelope["understanding"],
                warnings=envelope["warnings"],
            )
        capabilities = request.context["editing_capabilities"]
        allowed = {
            (item["target_id"], item["setting_path"]): item
            for item in capabilities["allowed_operations"]
        }
        operations: list[VeuszSettingOperation] = []
        seen_paths: set[str] = set()
        for draft in envelope["operations"]:
            key = (draft["target_id"], draft["setting_path"])
            capability = allowed.get(key)
            if capability is None:
                raise ValueError(
                    "Model proposed a target or setting outside the advertised catalog."
                )
            if draft["setting_path"] in seen_paths:
                raise ValueError("Model proposed the same setting more than once.")
            seen_paths.add(draft["setting_path"])
            try:
                raw_value = _json_loads_strict(draft["value_json"])
            except (json.JSONDecodeError, ValueError) as exc:
                raise ValueError("Model operation value_json is invalid.") from exc
            value = _coerce_value(capability, raw_value)
            if value == capability["current_value"]:
                continue
            operations.append(
                VeuszSettingOperation.set_setting(
                    target_id=draft["target_id"],
                    setting_path=draft["setting_path"],
                    value=value,
                    expected_value=capability["current_value"],
                    require_expected_value=True,
                )
            )
        if not operations:
            return self._response(
                request,
                status="needs_human_confirmation",
                understanding=(
                    "The requested result already matches the advertised current "
                    "settings, so there is no edit to preview."
                ),
                warnings=envelope["warnings"],
            )
        batch = VeuszSettingOperationBatch(
            base_revision=request.base_revision,
            operations=tuple(operations),
            provider=request.provider_id,
            rationale=envelope["rationale"],
        )
        return self._response(
            request,
            status="proposal",
            understanding=envelope["understanding"],
            warnings=envelope["warnings"],
            batch=batch,
        )

    def generate(
        self,
        request: AssistantRequest,
        *,
        emit_progress: Callable[[AssistantProgressEvent], None],
        cancellation: AssistantCancellationToken,
    ) -> AssistantResponse:
        restored = AssistantRequest.from_dict(request.to_dict())
        if restored.provider_id != self.descriptor.provider_id:
            raise ValueError("Assistant request targets another provider.")
        sequence = 0

        def progress(stage: str, message: str, value: float | None) -> None:
            nonlocal sequence
            sequence += 1
            emit_progress(
                AssistantProgressEvent(
                    request_id=restored.request_id,
                    provider_id=restored.provider_id,
                    sequence=sequence,
                    stage=stage,
                    message=message,
                    cancellable=True,
                    progress=value,
                )
            )

        cancellation.raise_if_cancelled()
        progress(
            "understanding",
            "Reading the selected object and its bounded editing catalog.",
            0.1,
        )
        try:
            payload = self.request_payload(restored)
        except _AssistantContextUnavailable as exc:
            return self._response(
                restored,
                status="needs_human_confirmation",
                understanding=(
                    "Select an editable Veusz object and submit the request again."
                ),
                warnings=(_redact(exc, secrets=()),),
            )
        except ValueError as exc:
            return self._response(
                restored,
                status="needs_rule_repair",
                understanding=(
                    "The local provider boundary rejected this request before any "
                    "data was sent. The figure was not changed."
                ),
                warnings=(f"Provider request rejected: {_redact(exc, secrets=())}",),
            )
        allowed_operations = restored.context["editing_capabilities"][
            "allowed_operations"
        ]
        if not allowed_operations:
            return self._response(
                restored,
                status="needs_human_confirmation",
                understanding=(
                    "The current selection has no bounded editable fields. Select "
                    "an axis, series, legend, graph, page, scalar field, or label."
                ),
            )
        proposing_emitted = False

        def headers_ready() -> None:
            progress(
                "planning",
                "The model is planning against the exact allowed settings.",
                0.35,
            )

        def text_started() -> None:
            nonlocal proposing_emitted
            if proposing_emitted:
                return
            proposing_emitted = True
            progress(
                "proposing",
                "A structured proposal is arriving for local validation.",
                0.7,
            )

        result = self._client.stream(
            payload,
            cancellation=cancellation,
            on_headers=headers_ready,
            on_text=text_started,
        )
        cancellation.raise_if_cancelled()
        if not proposing_emitted:
            text_started()
        progress(
            "validating",
            "Validating the response against the local typed operation boundary.",
            0.92,
        )
        if result.refusal:
            refusal = _redact(result.refusal, secrets=())[:500]
            return self._response(
                restored,
                status="needs_human_confirmation",
                understanding="The model declined to create a Veusz edit proposal.",
                warnings=(refusal,),
            )
        if result.incomplete_reason:
            return self._response(
                restored,
                status="needs_rule_repair",
                understanding=(
                    "The model response ended before a complete typed proposal was "
                    "available."
                ),
                warnings=(f"Incomplete response: {result.incomplete_reason[:400]}",),
            )
        try:
            envelope = _model_envelope(result.text)
            return self._typed_model_response(restored, envelope)
        except ValueError as exc:
            safe = _redact(exc, secrets=())[:420]
            return self._response(
                restored,
                status="needs_rule_repair",
                understanding=(
                    "The model response could not be converted into a safe "
                    "selected-object proposal. The figure was not changed."
                ),
                warnings=(f"Typed proposal rejected: {safe}",),
            )
