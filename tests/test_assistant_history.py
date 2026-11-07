"""Existing assistant history remains strictly readable after GUI retirement."""

from dataclasses import replace
import json

import pytest

from sciplot_core.assistant_operations import VeuszSettingOperation, VeuszSettingOperationBatch
from sciplot_core.assistant_provider import AssistantProviderDescriptor, AssistantResponse, ProviderFacts, canonical_payload_sha256
from sciplot_core.openai_provider_probe import _request, _visual_preview
from sciplot_core.assistant_history import read_assistant_history, validate_assistant_history_event
from assistant_history_fixtures import append_assistant_history_event, build_assistant_history_event

def _inputs():
    request = _request("offline GUI", visual_preview=_visual_preview())
    descriptor = AssistantProviderDescriptor(
        provider_id=request.provider_id, display_name="Offline fixture",
        capabilities=("veusz_setting_operation_batch", "cancellation", "properties_disclosure"),
    )
    capability, = request.context["editing_capabilities"]["allowed_operations"]
    batch = VeuszSettingOperationBatch(
        base_revision=request.base_revision, provider=request.provider_id,
        operations=(VeuszSettingOperation.set_setting(
            target_id=capability["target_id"], setting_path=capability["setting_path"],
            expected_value=capability["current_value"], value="Frequency (Hz)",
            require_expected_value=True,
        ),),
    )
    facts = ProviderFacts.from_values(response_id="resp_external_123", model="fixture-model",
                                      usage={"input_tokens": 17, "output_tokens": 5,
                                             "input_tokens_details": {"cached_tokens": 2}},
                                      usage_status="reported", terminal_status="completed")
    response = AssistantResponse(
        request_id=request.request_id, transaction_id=request.transaction_id,
        provider_id=request.provider_id, request_sha256=request.payload_sha256,
        status="proposal", understanding="Offline proposal.",
        proposal_kind="veusz_setting_operation_batch", proposal=batch.to_dict(),
        provider_facts=facts,
    )
    return request, descriptor, batch, response, facts


@pytest.mark.parametrize('status', [
    'proposal_ready', 'apply_started', 'applied', 'applied_unverified', 'rejected',
    'cancelled', 'needs_human_confirmation', 'needs_rule_repair', 'failed',
])
def test_history_retains_observed_facts_through_each_terminal_and_edit_state(status, tmp_path):
    request, descriptor, batch, response, facts = _inputs()
    request = replace(request, disclosure='properties')
    response = replace(response, request_sha256=request.payload_sha256)
    kwargs = {}
    if status in {'proposal_ready', 'apply_started', 'applied', 'applied_unverified'}:
        kwargs['batch'] = batch
    if status in {'apply_started', 'applied', 'applied_unverified'}:
        kwargs['native_undo_label'] = 'SciPlot AI fixture'
    if status in {'applied', 'applied_unverified'}:
        kwargs['applied_revision'] = request.base_revision + 1
    if status == 'applied':
        kwargs.update(after_page_render_sha256='a' * 64, render_changed=True)
    event = build_assistant_history_event(status=status, request=request,
                                           descriptor=descriptor, response=response, **kwargs)
    assert event['disclosure'] == 'properties'
    assert event['provider_facts'] == facts.to_dict()
    assert event['response_id'] == response.response_id
    assert event['provider_facts']['response_id'] != event['response_id']
    path = tmp_path / 'history.jsonl'
    append_assistant_history_event(path, event)
    assert read_assistant_history(path) == [event]
    persisted = path.read_text()
    assert request.intent not in persisted and request.visual_preview['base64'] not in persisted
    assert all(key not in persisted for key in ('"api_key"', '"visual_preview"', '"understanding"'))


def test_legacy_history_is_unchanged_and_optional_fields_are_not_synthesized(tmp_path):
    request, _, _, _, _ = _inputs()
    event = build_assistant_history_event(status='submitted', request=request)
    assert 'disclosure' not in event and 'provider_facts' not in event
    assert 'provider_facts' not in replace(_inputs()[3], provider_facts=None).to_dict()
    original_sha = canonical_payload_sha256(event)
    path = tmp_path / 'old.jsonl'
    path.write_text(json.dumps(event) + '\n')
    old_bytes = path.read_bytes()
    assert read_assistant_history(path) == [event]
    assert canonical_payload_sha256(read_assistant_history(path)[0]) == original_sha
    assert path.read_bytes() == old_bytes


@pytest.mark.parametrize('bad', ['disclosure', 'secret', 'submitted_facts'])
def test_history_uses_shared_facts_validation_and_refuses_new_invalid_fields(bad):
    request, _, _, _, facts = _inputs()
    event = build_assistant_history_event(status='submitted', request=request)
    if bad == 'disclosure':
        event['disclosure'] = 'infer-from-prompt'
    else:
        event['provider_facts'] = facts.to_dict()
        if bad == 'secret':
            event['provider_facts']['api_key'] = 'not-a-history-field'
    with pytest.raises(ValueError):
        validate_assistant_history_event(event)


@pytest.mark.parametrize('usage_status', ['not_reported', 'not_observed', 'invalid'])
def test_unknown_usage_is_not_persisted_as_zero(usage_status):
    facts = ProviderFacts.from_values(usage_status=usage_status)
    request, _, _, _, _ = _inputs()
    event = build_assistant_history_event(status='failed', request=request, provider_facts=facts)
    assert event['provider_facts']['usage'] is None
    assert event['provider_facts']['usage_status'] == usage_status
