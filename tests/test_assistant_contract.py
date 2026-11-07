from __future__ import annotations

import pytest
from dataclasses import replace

import sciplot_core.setting_catalog as setting_catalog
from sciplot_core.assistant_provider import (
    ASSISTANT_PROPOSAL_KINDS,
    AssistantProviderDescriptor,
    AssistantRequest,
    AssistantResponse,
)
from sciplot_core.assistant_operations import (
    SUPPORTED_VEUSZ_SETTING_OPERATIONS,
    VEUSZ_SETTING_OPERATION_BATCH_KIND,
    VEUSZ_SETTING_OPERATION_KIND,
    VEUSZ_SETTING_OPERATION_VERSION,
    VeuszSettingOperation,
    VeuszSettingOperationBatch,
)


def test_assistant_operation_contract_is_set_setting_only() -> None:
    assert SUPPORTED_VEUSZ_SETTING_OPERATIONS == frozenset({"set_setting"})

    with pytest.raises(ValueError, match="Unsupported VeuszSettingOperation"):
        VeuszSettingOperation(
            operation_type="add_widget",
            target_id="selected",
            arguments={"widget_type": "label"},
        )


def test_assistant_provider_rejects_retired_data_mapping_proposals() -> None:
    assert ASSISTANT_PROPOSAL_KINDS == frozenset({"veusz_setting_operation_batch"})
    with pytest.raises(
        ValueError,
        match="provider capabilities contains unsupported values",
    ):
        AssistantProviderDescriptor(
            provider_id="legacy-mapping-provider",
            display_name="Legacy mapping provider",
            capabilities=("data_mapping_proposal",),
        )


def test_set_setting_batch_preserves_serialized_kind_and_version() -> None:
    operation = VeuszSettingOperation.set_setting(
        target_id="selected",
        setting_path="/page1/graph1/x/label",
        value="Time (s)",
        expected_value="Time",
        require_expected_value=True,
    )
    batch = VeuszSettingOperationBatch(
        base_revision=7,
        operations=(operation,),
        provider="test-provider",
        rationale="Clarify the selected axis label.",
    )

    operation_payload = operation.to_dict()
    batch_payload = batch.to_dict()
    assert operation_payload["kind"] == VEUSZ_SETTING_OPERATION_KIND
    assert batch_payload["kind"] == VEUSZ_SETTING_OPERATION_BATCH_KIND
    assert operation_payload["version"] == VEUSZ_SETTING_OPERATION_VERSION == 1
    assert batch_payload["version"] == VEUSZ_SETTING_OPERATION_VERSION
    assert VeuszSettingOperation.from_dict(operation_payload) == operation
    assert VeuszSettingOperationBatch.from_dict(batch_payload) == batch


def test_serialized_legacy_operations_fail_closed() -> None:
    operation = VeuszSettingOperation.set_setting(
        target_id="selected",
        setting_path="/page1/graph1/x/label",
        value="Time (s)",
    )
    payload = operation.to_dict()
    payload["operation_type"] = "composition_set_layout"
    payload["arguments"] = {
        "layout_id": "two_equal",
        "expected_layout_id": "one_panel",
    }

    with pytest.raises(ValueError, match="Unsupported VeuszSettingOperation"):
        VeuszSettingOperation.from_dict(payload)


def test_setting_catalog_exposes_specs_without_legacy_inspector_models() -> None:
    assert not hasattr(setting_catalog, "INSPECTOR_MODEL_KIND")
    assert not hasattr(setting_catalog, "INSPECTOR_MODEL_VERSION")
    assert setting_catalog.specs_for_object_type("axis")
    assert setting_catalog.specs_for_object_type("unsupported") == ()




def _request_and_batch():
    from sciplot_core.openai_provider_probe import _request

    request = _request("valid")
    capability, = request.context["editing_capabilities"]["allowed_operations"]
    operation = VeuszSettingOperation.set_setting(
        target_id=capability["target_id"], setting_path=capability["setting_path"],
        value="Frequency (Hz)", expected_value=capability["current_value"],
        require_expected_value=True,
    )
    batch = VeuszSettingOperationBatch(
        base_revision=request.base_revision, operations=(operation,),
        provider=request.provider_id, rationale="Clarify the selected axis label.",
    )
    return request, batch


def _response(request, batch):
    return AssistantResponse(
        request_id=request.request_id, transaction_id=request.transaction_id,
        provider_id=request.provider_id, request_sha256=request.payload_sha256,
        status="proposal", understanding="Change the selected label only.",
        proposal_kind="veusz_setting_operation_batch", proposal=batch.to_dict(),
    )


@pytest.mark.parametrize("provider", ["openai", "another-provider"])
def test_any_provider_response_is_bound_to_the_same_catalog(provider):
    request, batch = _request_and_batch()
    request = replace(request, provider_id=provider)
    batch = replace(batch, provider=provider)
    response = _response(request, batch)
    wire = response.to_dict()
    AssistantResponse.from_dict(wire).validate_for_request(request)
    assert response.to_dict() == wire
    assert AssistantRequest.from_dict(request.to_dict()) == request


@pytest.mark.parametrize("bad", ["target", "path", "duplicate", "missing_expected", "wrong_expected", "revision"])
def test_request_identity_alone_cannot_admit_an_out_of_scope_proposal(bad):
    request, batch = _request_and_batch()
    operation, = batch.operations
    if bad == "target":
        batch = replace(batch, operations=(replace(operation, target_id="another-object"),))
    elif bad == "path":
        batch = replace(batch, operations=(replace(operation, arguments={
            **operation.arguments, "setting_path": "/page1/graph1/y/label"}),))
    elif bad == "duplicate":
        batch = replace(batch, operations=(operation, replace(operation, operation_id="different-id")))
    elif bad == "revision":
        batch = replace(batch, base_revision=request.base_revision + 1)
    else:
        arguments = dict(operation.arguments)
        arguments.pop("expected_value")
        if bad == "wrong_expected":
            arguments["expected_value"] = "old label"
        batch = replace(batch, operations=(replace(operation, arguments=arguments),))
    # It is a valid typed/identity-bound response, but never an admitted command.
    response = _response(request, batch)
    before_request, before_response = request.to_dict(), response.to_dict()
    with pytest.raises(ValueError):
        response.validate_for_request(request)
    assert request.to_dict() == before_request and response.to_dict() == before_response


def test_legacy_context_remains_readable_but_cannot_authorize_bounded_edits():
    from sciplot_core.openai_provider_probe import _request

    request = _request("legacy", version=2)
    _, batch = _request_and_batch()
    nonproposal = AssistantResponse(
        request_id=request.request_id, transaction_id=request.transaction_id,
        provider_id=request.provider_id, request_sha256=request.payload_sha256,
        status="needs_human_confirmation", understanding="Select an editable object.",
    )
    AssistantResponse.from_dict(nonproposal.to_dict()).validate_for_request(request)
    with pytest.raises(ValueError, match="advertised setting catalog"):
        _response(request, batch).validate_for_request(request)


@pytest.mark.parametrize("current,expected,accepted", [
    (False, 0, False), (0, False, False), ([False], [0], False),
    ([1.0], [1], True), (1.0, 1, True), (False, False, True),
])
def test_expected_values_preserve_boolean_identity_and_numeric_equivalence(current, expected, accepted):
    from sciplot_core.assistant_provider.capabilities import bind_setting_batch

    _, batch = _request_and_batch()
    operation, = batch.operations
    batch = replace(batch, operations=(replace(operation, arguments={
        **operation.arguments, "expected_value": expected}),))
    catalog = {"allowed_operations": [{"target_id": operation.target_id,
        "setting_path": operation.arguments["setting_path"], "current_value": current}]}
    if accepted:
        assert bind_setting_batch(batch, base_revision=batch.base_revision, capabilities=catalog)
    else:
        with pytest.raises(ValueError, match="expected_value"):
            bind_setting_batch(batch, base_revision=batch.base_revision, capabilities=catalog)


def test_model_adapter_checks_duplicate_noops_before_filtering_and_preserves_noop_response():
    import json
    from sciplot_core.openai_provider import OpenAIResponsesConfig, OpenAIResponsesProvider

    request, batch = _request_and_batch()
    operation, = batch.operations
    provider = OpenAIResponsesProvider(OpenAIResponsesConfig(api_key="test-local-only", model="test"))
    draft = {"operation_type": "set_setting", "target_id": operation.target_id,
             "setting_path": operation.arguments["setting_path"],
             "value_json": json.dumps(operation.arguments["expected_value"])}
    envelope = {"status": "proposal", "understanding": "Keep the current label.",
                "rationale": "The requested label is current.", "warnings": (), "operations": [draft]}
    noop = provider._typed_model_response(request, envelope)
    assert noop.status == "needs_human_confirmation" and noop.proposal is None
    with pytest.raises(ValueError, match="same setting"):
        provider._typed_model_response(request, {**envelope, "operations": [draft, draft]})
    envelope["operations"] = [{**draft, "value_json": json.dumps("Frequency (Hz)")}]
    response = provider._typed_model_response(request, envelope)
    response.validate_for_request(request)
    assert response.proposal["operations"][0]["arguments"] == operation.arguments






def test_legacy_response_wire_omits_optional_provider_facts_and_keeps_local_identity():
    from sciplot_core.assistant_provider import ProviderFacts

    request, batch = _request_and_batch()
    response = _response(request, batch)
    legacy = response.to_dict()
    assert "provider_facts" not in legacy
    assert AssistantResponse.from_dict(legacy).to_dict() == legacy
    assert AssistantResponse.from_dict(legacy).provider_facts is None
    facts = ProviderFacts.from_values(
        response_id="resp_external-not-a-uuid", model="observed-model",
        usage={"input_tokens": 3}, usage_status="reported", terminal_status="completed",
    )
    observed = replace(response, provider_facts=facts)
    assert observed.to_dict() == {**legacy, "provider_facts": facts.to_dict()}
    assert observed.response_id == response.response_id != facts.response_id
    restored = AssistantResponse.from_dict(observed.to_dict())
    restored.validate_for_request(request)
    assert restored.to_dict() == observed.to_dict()
    assert replace(observed, provider_facts=None).to_dict() == legacy


@pytest.mark.parametrize("violation", ["target", "path", "revision", "request_digest"],
                         ids=["target", "path", "revision", "request-digest"])
def test_reported_provider_facts_cannot_authorize_a_bad_local_response(violation):
    from sciplot_core.assistant_provider import ProviderFacts

    request, batch = _request_and_batch()
    operation, = batch.operations
    if violation == "target":
        batch = replace(batch, operations=(replace(operation, target_id="unadvertised-object"),))
    elif violation == "path":
        batch = replace(batch, operations=(replace(operation, arguments={
            **operation.arguments, "setting_path": "/page1/graph1/y/label"}),))
    elif violation == "revision":
        batch = replace(batch, base_revision=request.base_revision + 1)
    response = replace(_response(request, batch), provider_facts=ProviderFacts.from_values(
        response_id="resp_completed", model="observed-model", usage={"total_tokens": 12},
        usage_status="reported", terminal_status="completed",
    ))
    if violation == "request_digest":
        response = replace(response, request_sha256="0" * 64)
    before = response.to_dict()
    with pytest.raises(ValueError):
        AssistantResponse.from_dict(before).validate_for_request(request)
    assert response.to_dict() == before
