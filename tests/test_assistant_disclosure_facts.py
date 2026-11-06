"""Offline disclosure projections and factual provider metadata boundaries."""

from __future__ import annotations

from copy import deepcopy
from dataclasses import replace
import hashlib
import io
import json
from uuid import UUID

import pytest

from sciplot_core.assistant_provider import (
    AssistantCancellationToken,
    AssistantRequest,
    ProviderFacts,
)
from sciplot_core.openai_provider import OpenAIResponsesConfig, OpenAIResponsesProvider
from sciplot_core.openai_provider.contracts import (
    OPENAI_ASSISTANT_OUTPUT_SCHEMA,
    OPENAI_PROVIDER_ID,
    _PROVIDER_INSTRUCTIONS,
)
from sciplot_core.openai_provider_probe import _context, _visual_preview


_KEY = "offline-disclosure-key-never-send"
_EXTERNAL_ID = "resp_external.not-a-local-uuid"
_USAGE = {
    "input_tokens": 19,
    "output_tokens": 7,
    "total_tokens": 26,
    "input_tokens_details": {"cached_tokens": 3},
    "output_tokens_details": {"reasoning_tokens": 2},
}
_ABSENT = object()


def _request():
    context = _context()
    context["document_inventory"] = {
        "object_count": 2,
        "object_types": {"axis": 1, "unselected-inventory-sentinel": 1},
    }
    context["review"] = {"active_count": 1, "annotations": [{
        "annotation_id": "review-sentinel", "shape": "rectangle",
        "coordinate_space": "page", "target_object_id": None,
        "text": "private-review-sentinel",
    }]}
    context["qa"]["structural_warning_ids"] = ["whole-document-qa-sentinel"]
    return AssistantRequest(
        request_id="33333333-3333-4333-8333-333333333333",
        transaction_id="44444444-4444-4444-8444-444444444444",
        provider_id=OPENAI_PROVIDER_ID, intent="Rename only the selected axis.",
        base_revision=7, context=context,
        allowed_proposal_kinds=("veusz_setting_operation_batch",),
        created_at="2026-11-06T00:00:00+00:00", visual_preview=_visual_preview(),
    )


def _canonical_sha(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":"),
                                     ensure_ascii=False, allow_nan=False).encode()).hexdigest()


def _provider(connection_factory=None):
    return OpenAIResponsesProvider(OpenAIResponsesConfig(
        api_key=_KEY, model="configured-offline-model",
        base_url="http://127.0.0.1:1/v1",
    ), _connection_factory=connection_factory)


def test_legacy_request_wire_digest_and_png_are_unchanged_by_default_disclosure():
    request = _request()
    expected = {
        "kind": "sciplot_assistant_request", "version": 1,
        "request_id": request.request_id, "transaction_id": request.transaction_id,
        "provider_id": OPENAI_PROVIDER_ID, "intent": "Rename only the selected axis.",
        "base_revision": 7, "context": deepcopy(request.context),
        "context_sha256": _canonical_sha(request.context),
        "allowed_proposal_kinds": ["veusz_setting_operation_batch"],
        "created_at": "2026-11-06T00:00:00+00:00",
        "visual_preview": _visual_preview(),
    }
    assert request.disclosure == "visual"
    assert request.to_dict() == expected
    assert request.payload_sha256 == _canonical_sha(expected)
    assert AssistantRequest.from_dict(expected).to_dict() == expected
    assert replace(request, disclosure="visual").to_dict() == expected
    properties = replace(request, disclosure="properties")
    assert properties.to_dict() == {**expected, "disclosure": "properties"}
    assert properties.context_sha256 == request.context_sha256
    assert properties.payload_sha256 != request.payload_sha256
    assert AssistantRequest.from_dict(properties.to_dict()) == properties


@pytest.mark.parametrize("invalid", ["", "all", "VISUAL", None, False, {}],
                         ids=["empty", "unknown", "case", "null", "boolean", "object"])
def test_disclosure_refuses_unadvertised_modes(invalid):
    request = _request()
    with pytest.raises(ValueError):
        replace(request, disclosure=invalid)
    with pytest.raises(ValueError):
        AssistantRequest.from_dict({**request.to_dict(), "disclosure": invalid})


def test_visual_keeps_the_existing_complete_provider_body_and_image():
    request = _request()
    before = deepcopy(request.to_dict())
    preview = request.visual_preview
    user = {
        "task": "Propose a bounded SciPlot Veusz selected-object edit.",
        "intent": request.intent, "base_revision": 7,
        "allowed_proposal_kinds": ["veusz_setting_operation_batch"],
        "context": deepcopy(request.context),
        "visual_preview": {key: preview[key] for key in ("sha256", "width", "height", "revision")},
    }
    assert _provider().request_payload(request) == {
        "model": "configured-offline-model", "store": False, "stream": True,
        "reasoning": {"effort": "medium"}, "max_output_tokens": 2400,
        "instructions": _PROVIDER_INSTRUCTIONS,
        "input": [{"role": "user", "content": [
            {"type": "input_text", "text": json.dumps(user, ensure_ascii=False,
                sort_keys=True, separators=(",", ":"), allow_nan=False)},
            {"type": "input_image", "image_url": "data:image/png;base64," + preview["base64"],
             "detail": "high"},
        ]}],
        "text": {"format": {"type": "json_schema", "name": "sciplot_veusz_assistant_response",
                            "strict": True, "schema": OPENAI_ASSISTANT_OUTPUT_SCHEMA}},
    }
    assert request.to_dict() == before


@pytest.mark.parametrize("selected_point", [False, True], ids=["object-only", "local-selected-point"])
def test_properties_sends_selected_properties_without_image_or_whole_document_context(selected_point):
    request = _request()
    if selected_point:
        context = deepcopy(request.context)
        context["selection"]["data_point"] = {
            "target_object_id": context["selection"]["primary_object_id"],
            "x": 1.25, "y": 2.5, "graph_x": 0.25, "graph_y": 0.5,
            "x_label": "local-point-sentinel", "y_label": "response", "index": "3",
            "display_type": ["numeric", "numeric"],
        }
        context["explicit_selected_point_included"] = True
        request = replace(request, context=context, context_sha256=None)
    request = replace(request, disclosure="properties")
    before = deepcopy(request.to_dict())
    body = _provider().request_payload(request)
    content = body["input"][0]["content"]
    assert [part["type"] for part in content] == ["input_text"]
    user = json.loads(content[0]["text"])
    assert user["intent"] == request.intent and user["base_revision"] == 7
    assert user["context"]["selected_object"] == request.context["selected_object"]
    assert user["context"]["editing_capabilities"] == request.context["editing_capabilities"]
    assert not {"document_inventory", "review", "qa"} & user["context"].keys()
    assert "data_point" not in user["context"]["selection"]
    assert user["context"]["explicit_selected_point_included"] is False
    assert "visual_preview" not in user
    encoded = json.dumps(body)
    for omitted in ("unselected-inventory-sentinel", "private-review-sentinel",
                    "whole-document-qa-sentinel", "local-point-sentinel",
                    request.visual_preview["base64"], "input_image"):
        assert omitted not in encoded
    assert request.to_dict() == before
    user["context"]["editing_capabilities"]["allowed_operations"].clear()
    assert request.to_dict() == before


def test_provider_facts_are_detached_and_external_identity_remains_external():
    supplied = deepcopy(_USAGE)
    facts = ProviderFacts.from_values(response_id=_EXTERNAL_ID, model="observed-model",
                                     usage=supplied, usage_status="reported", terminal_status="completed")
    expected = {"response_id": _EXTERNAL_ID, "model": "observed-model", "usage": _USAGE,
                "usage_status": "reported", "terminal_status": "completed"}
    assert facts.to_dict() == expected
    assert ProviderFacts.from_dict(facts.to_dict()) == facts
    supplied["input_tokens_details"]["cached_tokens"] = 999
    exported = facts.to_dict()
    exported["usage"]["output_tokens"] = 999
    observed = facts.usage
    observed["input_tokens"] = 999
    assert facts.to_dict() == expected
    with pytest.raises((AttributeError, TypeError)):
        facts.model = "mutated"
    with pytest.raises(ValueError):
        UUID(facts.response_id)
    with pytest.raises(ValueError):
        ProviderFacts.from_dict({**facts.to_dict(), "prompt": "never metadata"})


@pytest.mark.parametrize("usage,status", [
    (None, "not_reported"), ({"input_tokens": 13}, "reported"),
    ({"input_tokens": 0, "output_tokens": 0, "total_tokens": 0}, "reported"),
    ({"input_tokens": 9, "output_tokens": 2, "total_tokens": 50}, "reported"),
    ({"input_tokens": True}, "invalid"), ({"input_tokens": -1}, "invalid"),
    ({"input_tokens": "19"}, "invalid"), ({"unknown": "prompt-or-image"}, "invalid"),
    ({"input_tokens_details": {"cached_tokens": -1}}, "invalid"),
], ids=["missing", "partial", "reported-zero", "reported-total", "boolean", "negative", "string", "unknown-string", "nested-negative"])
def test_usage_preserves_only_observed_counts_without_inventing_zero(usage, status):
    if status == "invalid":
        with pytest.raises(ValueError):
            ProviderFacts.from_values(response_id=_EXTERNAL_ID, model="observed-model",
                usage=usage, usage_status="reported", terminal_status="completed")
        return
    facts = ProviderFacts.from_values(response_id=_EXTERNAL_ID, model="observed-model",
                                     usage=usage, usage_status=status, terminal_status="completed")
    assert facts.usage_status == status
    assert facts.usage == (usage if status == "reported" else None)
    assert facts.response_id == _EXTERNAL_ID and facts.model == "observed-model"


class _Response:
    status = 200

    def __init__(self, wire):
        self.body = io.BytesIO(wire)
        self.closed = 0

    def getheader(self, _name):
        return "text/event-stream"

    def readline(self, limit):
        return self.body.readline(limit)

    def close(self):
        self.closed += 1
        self.body.close()


class _Connection:
    sock = None

    def __init__(self, wire):
        self.response = _Response(wire)
        self.closed = 0
        self.sent = []

    def connect(self):
        pass

    def request(self, _method, _path, *, body, headers):
        self.sent.append(json.loads(body))

    def getresponse(self):
        return self.response

    def close(self):
        self.closed += 1


def _terminal(scenario, *, usage=_ABSENT, identity=True):
    envelope = {"status": "proposal", "understanding": "Rename the selected axis.",
        "proposal_kind": "veusz_setting_operation_batch", "rationale": "Requested edit.",
        "warnings": [], "operations": [{"operation_type": "set_setting",
            "target_id": "11111111-1111-4111-8111-111111111111",
            "setting_path": "/page1/graph1/x/label", "value_json": '"Frequency (Hz)"'}]}
    if scenario == "out-of-scope":
        envelope["operations"][0]["setting_path"] = "/page1/graph1/y/label"
    text = "not a model envelope" if scenario == "malformed" else json.dumps(envelope)
    content = ([{"type": "refusal", "refusal": "Declined."}] if scenario == "refusal"
               else [{"type": "output_text", "text": text}])
    status = "incomplete" if scenario == "incomplete" else "completed"
    response = {"status": status, "output": [{"content": content}]}
    if identity:
        response.update(id=_EXTERNAL_ID, model="observed-model")
    if usage is not _ABSENT:
        response["usage"] = usage
    if status == "incomplete":
        response["incomplete_details"] = {"reason": "max_output_tokens"}
    return ("data: " + json.dumps({"type": "response." + status, "response": response}) + "\n\n").encode()


@pytest.mark.parametrize("scenario,expected_status", [
    ("proposal", "proposal"), ("refusal", "needs_human_confirmation"),
    ("incomplete", "needs_rule_repair"), ("malformed", "needs_rule_repair"),
    ("out-of-scope", "needs_rule_repair"),
], ids=["proposal", "refusal", "incomplete", "malformed", "out-of-scope"])
def test_reported_facts_survive_provider_translation_without_authorizing_a_proposal(scenario, expected_status):
    request = replace(_request(), disclosure="properties")
    connection = _Connection(_terminal(scenario, usage=_USAGE))
    provider = _provider(lambda *_args: connection)
    response = provider.generate(request, emit_progress=lambda _event: None,
                                 cancellation=AssistantCancellationToken())
    assert response.status == expected_status
    assert (response.proposal is not None) is (expected_status == "proposal")
    response.validate_for_request(request)
    assert response.provider_facts.response_id == _EXTERNAL_ID
    assert response.provider_facts.model == "observed-model"
    assert response.provider_facts.usage == _USAGE
    assert response.provider_facts.usage_status == "reported"
    assert response.provider_facts.terminal_status == ("incomplete" if scenario == "incomplete" else "completed")
    assert str(UUID(response.response_id)) == response.response_id != _EXTERNAL_ID
    assert connection.closed == connection.response.closed == 1
    encoded = json.dumps(response.provider_facts.to_dict())
    assert _KEY not in encoded and request.intent not in encoded
    assert request.visual_preview["base64"] not in encoded and "operations" not in encoded


@pytest.mark.parametrize("usage,status", [(_ABSENT, "not_reported"), (None, "not_reported"),
    ({"input_tokens": "19", "debug_prompt": _KEY}, "invalid")],
    ids=["omitted", "null", "invalid"])
def test_missing_or_invalid_usage_does_not_erase_a_valid_proposal_or_fill_zero(usage, status):
    connection = _Connection(_terminal("proposal", usage=usage))
    request = _request()
    response = _provider(lambda *_args: connection).generate(
        request, emit_progress=lambda _event: None, cancellation=AssistantCancellationToken())
    assert response.status == "proposal"
    response.validate_for_request(request)
    assert response.provider_facts.usage is None
    assert response.provider_facts.usage_status == status
    assert _KEY not in json.dumps(response.provider_facts.to_dict())
    assert _KEY not in repr(response.provider_facts)


def test_unreported_provider_identity_is_not_filled_from_local_uuid_or_configured_model():
    connection = _Connection(_terminal("proposal", identity=False))
    response = _provider(lambda *_args: connection).generate(
        _request(), emit_progress=lambda _event: None, cancellation=AssistantCancellationToken())
    assert response.status == "proposal"
    assert response.provider_facts.response_id is None
    assert response.provider_facts.model is None
    assert response.provider_facts.usage is None
    assert response.provider_facts.usage_status == "not_reported"


@pytest.mark.parametrize("field", ["id", "model"], ids=["response-id", "model"])
def test_a_provider_echoing_the_configured_key_cannot_persist_it_as_metadata(field):
    event = json.loads(_terminal("proposal", usage=_USAGE).decode().removeprefix("data: "))
    event["response"][field] = _KEY
    wire = ("data: " + json.dumps(event) + "\n\n").encode()
    connection = _Connection(wire)
    response = _provider(lambda *_args: connection).generate(
        _request(), emit_progress=lambda _event: None, cancellation=AssistantCancellationToken())
    assert response.status == "proposal" and response.provider_facts.usage == _USAGE
    assert _KEY not in json.dumps(response.provider_facts.to_dict())
    assert _KEY not in repr(response.provider_facts)


def test_changed_provider_metadata_records_the_terminal_observation_without_vetoing_a_valid_edit():
    created = ("data: " + json.dumps({"type": "response.created", "response": {
        "id": "resp_initial-observation", "model": "initial-model", "status": "in_progress",
    }}) + "\n\n").encode()
    connection = _Connection(created + _terminal("proposal", usage=_USAGE))
    request = _request()
    before = request.to_dict()
    response = _provider(lambda *_args: connection).generate(
        request, emit_progress=lambda _event: None, cancellation=AssistantCancellationToken())
    assert response.status == "proposal"
    response.validate_for_request(request)
    assert response.provider_facts.response_id == _EXTERNAL_ID
    assert response.provider_facts.model == "observed-model"
    assert response.provider_facts.usage == _USAGE
    assert response.provider_facts.terminal_status == "completed"
    assert response.response_id not in {"resp_initial-observation", _EXTERNAL_ID}
    assert request.to_dict() == before
    assert connection.closed == connection.response.closed == 1
