from __future__ import annotations

from dataclasses import replace
import json
import threading
from types import SimpleNamespace

import pytest
from PyQt6 import QtCore, QtWidgets

from sciplot_core.assistant_operations import VeuszSettingOperation, VeuszSettingOperationBatch
from sciplot_core.assistant_provider import (
    AssistantCancellationToken, AssistantCancelled, AssistantProviderDescriptor,
    AssistantProviderFailure, AssistantResponse, ProviderFacts, canonical_payload_sha256,
)
from sciplot_core.openai_provider_probe import _request, _visual_preview
from sciplot_gui.assistant_runtime import AssistantRequestRunner, _AssistantProviderWorker
from sciplot_gui.studio_assistant.context_history import ContextHistoryMixin
from sciplot_gui.studio_assistant.dock import DockMixin
from sciplot_gui.studio_assistant.rejection import RejectionMixin
from sciplot_gui.studio_assistant.request_context import RequestContextMixin
from sciplot_gui.studio_assistant.request_flow import RequestFlowMixin, provider_facts_text
from sciplot_gui.studio_assistant_history import (
    append_assistant_history_event, build_assistant_history_event,
    read_assistant_history, validate_assistant_history_event,
)


@pytest.fixture(scope="module")
def application():
    app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
    yield app


def _inputs():
    request = _request("offline GUI", visual_preview=_visual_preview())
    descriptor = AssistantProviderDescriptor(
        provider_id=request.provider_id, display_name="Offline fixture",
        capabilities=("veusz_setting_operation_batch", "cancellation"),
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


class _Signal:
    def __init__(self):
        self.values = []

    def emit(self, value):
        self.values.append(value)


class _Bridge(RejectionMixin, RequestFlowMixin, RequestContextMixin, ContextHistoryMixin, DockMixin):
    def __init__(self, tmp_path):
        self.template, descriptor, _, _, _ = _inputs()
        self.window = QtWidgets.QMainWindow()
        self.runner = SimpleNamespace(descriptor=descriptor, request=self.template, active=False)
        self.provider = object()
        self.document = SimpleNamespace(changeset=self.template.base_revision)
        self._pending_request = self.template
        self._pending_response = self._pending_batch = None
        self._pending_capabilities = {}
        self._selected_widget = object()
        self.blocker = None
        self.same_selection = True
        self.prepared = []
        self.history_path = tmp_path / 'assistant_history.jsonl'
        self.historyRecorded = _Signal()
        self.requestRejected = _Signal()
        self.proposalReady = _Signal()
        self.dock = self._build_dock()

    def _document_context_blocker(self):
        return self.blocker

    def _refresh_ask_button(self):
        pass

    def _request_targets_current_selection(self, _request):
        return self.same_selection

    def context_for_current_selection(self):
        return self.template.context

    def capture_current_plot_png(self):
        return b'local fixture snapshot', self.template.visual_preview

    def _prepare_native_operations(self, batch, **_kwargs):
        self.prepared.append(batch)


def test_disclosure_is_an_explicit_control_and_keeps_local_snapshot(application, tmp_path):
    bridge = _Bridge(tmp_path)
    assert bridge.disclosure_combo.currentData() == 'visual'
    visual = bridge.build_request('Do not send any image')
    assert visual.disclosure == 'visual' and 'disclosure' not in visual.to_dict()
    bridge.disclosure_combo.setCurrentIndex(1)
    properties = bridge.build_request('Look at this picture')
    assert properties.disclosure == 'properties'
    assert properties.to_dict()['disclosure'] == 'properties'
    assert properties.visual_preview == visual.visual_preview == bridge.template.visual_preview
    assert 'No page image is sent' in bridge.build_request('').intent
    assert 'no image' in bridge.disclosure_combo.currentText().lower()
    assert 'rendered page' in bridge.intro_label.text()
    assert 'selected object' in bridge.intro_label.text()


def test_capture_still_refuses_revision_drift_in_properties_mode(application, tmp_path):
    bridge = _Bridge(tmp_path)
    bridge.disclosure_combo.setCurrentIndex(1)

    def capture():
        bridge.document.changeset += 1
        return b'local', bridge.template.visual_preview

    bridge.capture_current_plot_png = capture
    with pytest.raises(RuntimeError, match='document changed'):
        bridge.build_request('Only properties')


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
def test_unknown_usage_is_not_displayed_or_persisted_as_zero(usage_status):
    facts = ProviderFacts.from_values(usage_status=usage_status)
    request, _, _, _, _ = _inputs()
    event = build_assistant_history_event(status='failed', request=request, provider_facts=facts)
    assert event['provider_facts']['usage'] is None
    assert event['provider_facts']['usage_status'] == usage_status
    assert 'unknown' in provider_facts_text(facts)
    assert 'counters:' not in provider_facts_text(facts)


@pytest.mark.parametrize('outcome', ['normal', 'late_cancel', 'cancel_exception', 'failure', 'unsafe'])
def test_worker_keeps_facts_when_discarding_or_failing_a_result(outcome):
    request, descriptor, batch, response, facts = _inputs()
    cancellation = AssistantCancellationToken()

    def generate(_request, **_kwargs):
        if outcome == 'cancel_exception':
            raise AssistantCancelled('offline stop', provider_facts=facts)
        if outcome == 'failure':
            raise AssistantProviderFailure('offline failure', provider_facts=facts)
        if outcome == 'late_cancel':
            cancellation.cancel()
        if outcome == 'unsafe':
            operation, = batch.operations
            unsafe = replace(batch, operations=(replace(operation, target_id='unadvertised'),))
            return replace(response, proposal=unsafe.to_dict())
        return response

    worker = _AssistantProviderWorker(provider=SimpleNamespace(descriptor=descriptor, generate=generate),
                                      descriptor=descriptor, request=request, cancellation=cancellation)
    responses, failures, finished = [], [], []
    worker.response.connect(responses.append)
    worker.failed.connect(failures.append)
    worker.finished.connect(lambda: finished.append(True))
    worker.run()
    assert finished == [True] and len(responses) + len(failures) == 1
    if outcome in {'failure', 'unsafe'}:
        assert failures[0]['provider_facts'] == facts
    else:
        assert responses[0].provider_facts == facts
        assert responses[0].status == ('proposal' if outcome == 'normal' else 'cancelled')
        if outcome != 'normal':
            assert responses[0].proposal is None


@pytest.mark.parametrize('stale', ['path', 'selection', 'revision', 'cleared'])
def test_stale_results_record_original_usage_without_admitting_a_proposal(application, tmp_path, stale):
    bridge = _Bridge(tmp_path)
    _, _, _, response, facts = _inputs()
    response = replace(response, request_id=bridge.template.request_id,
                       transaction_id=bridge.template.transaction_id,
                       request_sha256=bridge.template.payload_sha256)
    reason = {'path': 'document_context_changed', 'selection': 'selected_object_changed',
              'revision': 'document_revision_changed', 'cleared': 'no_active_request'}[stale]
    if stale == 'path':
        bridge.blocker = 'Document moved or replaced.'
    elif stale == 'selection':
        bridge.same_selection = False
    elif stale == 'revision':
        bridge.document.changeset += 1
    else:
        bridge._pending_request = None
    bridge._provider_response(response)
    event, = read_assistant_history(bridge.history_path)
    assert event['reason_code'] == reason and event['status'] == 'rejected'
    assert event['request_id'] == bridge.template.request_id
    assert event['provider_facts'] == facts.to_dict()
    assert bridge.prepared == [] and not bridge.apply_button.isEnabled()


def test_failed_and_foreign_results_never_borrow_another_requests_identity(application, tmp_path):
    bridge = _Bridge(tmp_path)
    request, _, _, response, facts = _inputs()
    bridge._provider_response(response)
    bridge._provider_failed({'request_id': request.request_id, 'error': 'foreign', 'provider_facts': facts})
    assert not bridge.history_path.exists() and bridge._pending_request is bridge.template
    bridge.blocker = 'Document changed.'
    bridge._pending_request = None
    bridge._provider_failed({'request_id': bridge.template.request_id, 'error': 'offline', 'provider_facts': facts})
    event, = read_assistant_history(bridge.history_path)
    assert event['status'] == 'failed' and event['provider_facts'] == facts.to_dict()
    assert event['request_id'] == bridge.template.request_id and 'response_id' not in event


class _ForeignReceiver(QtCore.QObject):
    def __init__(self):
        super().__init__()
        self.calls = 0

    @QtCore.pyqtSlot()
    def receive(self):
        self.calls += 1


@pytest.mark.parametrize('already_returned', [False, True])
def test_shutdown_delivers_only_this_runners_observed_terminal_after_real_wait(application, tmp_path, already_returned):
    bridge = _Bridge(tmp_path)
    request = bridge.template
    _, descriptor, _, response, facts = _inputs()
    response = replace(response, request_id=request.request_id, transaction_id=request.transaction_id,
                       request_sha256=request.payload_sha256)
    started, release = threading.Event(), threading.Event()

    def generate(_request, **_kwargs):
        started.set()
        assert release.wait(2)
        return response

    runner = AssistantRequestRunner(SimpleNamespace(descriptor=descriptor, generate=generate))
    bridge.runner = runner
    runner.response.connect(bridge._provider_response)
    runner.failed.connect(bridge._provider_failed)
    runner.submit(request)
    assert started.wait(1)
    foreign = _ForeignReceiver()
    QtCore.QMetaObject.invokeMethod(foreign, 'receive', QtCore.Qt.ConnectionType.QueuedConnection)
    if not already_returned:
        assert runner.shutdown(wait_ms=1) is False
        assert not bridge.history_path.exists() and foreign.calls == 0
    release.set()
    assert runner._thread.wait(1000)
    assert not bridge.history_path.exists()
    bridge._shutdown()
    assert foreign.calls == 0 and bridge.prepared == []
    event, = read_assistant_history(bridge.history_path)
    assert event['status'] == 'cancelled' and event['reason_code'] == 'window_closed'
    assert event['provider_facts'] == facts.to_dict() and runner.request is None
    QtCore.QCoreApplication.sendPostedEvents(foreign, QtCore.QEvent.Type.MetaCall)
    assert foreign.calls == 1
