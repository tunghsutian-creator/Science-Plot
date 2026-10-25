"""Finite fake-native controls exercise the real shared generation repository."""
from copy import deepcopy
import json
from pathlib import Path

import pytest

from sciplot_core.foundation.file_hashing import file_sha256
from sciplot_core.project_commands import ProjectCommandUnknown
from sciplot_core.project_store import FileProjectStore
from sciplot_core.workflow import native_suite_transactions as native
from sciplot_core.workflow.native_suite_creation import create_project
from sciplot_core.workflow.native_suite_objects import native_identity, require_object
from sciplot_core.workflow.rheology_tts_suite import _figure_folder
from sciplot_core.workflow.rheology_tts_tables import write_json


@pytest.fixture
def bound(tmp_path, monkeypatch):
    workspace, delivery = tmp_path / 'workspace', tmp_path / 'delivery'
    source = tmp_path / 'raw.csv'
    source.write_bytes(b'raw,scientific,units\n1,2,Pa\n')
    workspace.mkdir()
    (delivery / 'editable').mkdir(parents=True)
    sources = [{'path': str(source), 'sha256': file_sha256(source)}]
    documents, receipts = [], []
    for identifier in ('A', 'B'):
        path = delivery / 'editable' / (identifier + '.vsz')
        path.write_bytes((identifier + ':opaque native + arrays').encode())
        spec = workspace / (identifier + '.spec.json')
        figure = {'id': identifier, 'panels': [{'id': 'graph1', 'series': [], 'legend': 'upper_left', 'notes': []}]}
        write_json(spec, {'figure': figure, 'source_binding': {'sources': sources}})
        exports = []
        folder = _figure_folder(delivery, identifier)
        folder.mkdir(exist_ok=True)
        for fmt, suffix in [('pdf', '.pdf'), ('tiff_300', '_300dpi.tiff'), ('png_300', '_300dpi.png')]:
            output = folder / (identifier + suffix)
            output.write_bytes((identifier + fmt).encode())
            exports.append({'path': str(output), 'format': fmt, 'sha256': file_sha256(output)})
        documents.append({'id': identifier, 'path': str(path), 'sha256': file_sha256(path),
                          'exports': [item['path'] for item in exports]})
        receipts.append({'id': identifier, 'spec_path': str(spec), 'spec_sha256': file_sha256(spec),
                         'document': str(path), 'document_sha256': file_sha256(path), 'exports': exports})
    manifest = {'kind': 'sciplot_rheology_tts_suite', 'version': 1, 'workspace': str(workspace),
        'delivery': str(delivery), 'sources': sources, 'documents': documents,
        'native_result': {'figures': receipts}, 'last_export': deepcopy(receipts)}
    write_json(workspace / 'suite.json', manifest)
    write_json(delivery / 'data/delivery_manifest.json', manifest)
    calls = []
    def capture(context):
        receipt = next(item for item in receipts if item['id'] == context['figure_id'])
        return {**context, 'figure': {'id': context['figure_id'], 'panels': []},
            'scientific_hash': 'a' * 64, 'presentation_hash': file_sha256(Path(context['plot'])),
            'spec_sha256': receipt['spec_sha256'],
            **native_identity(str(workspace), context['figure_id'], sources, receipt['spec_sha256'], file_sha256(Path(context['plot']))),
            'state': {'targets': {'legend:graph1': {'properties': {'legend.location': 'top-left'}, 'native_fields': {}}}}}
    monkeypatch.setattr(native, 'capture_object', capture)
    from sciplot_core import rheology_tts_render as render
    def patch(path, candidate, figure, changes, expected):
        calls.append('patch')
        assert file_sha256(path) == expected
        candidate.parent.mkdir(parents=True, exist_ok=True)
        candidate.write_bytes(path.read_bytes() + b':reviewed legend delta')
        return {'document': str(candidate), 'document_sha256': file_sha256(candidate),
                'native_audit': {'status': 'passed'}, 'changes': changes}
    def export(path, out, figure):
        calls.append('export')
        out.parent.mkdir(parents=True, exist_ok=True)
        exports = []
        for fmt, suffix in [('pdf', '.pdf'), ('tiff_300', '_300dpi.tiff'), ('png_300', '_300dpi.png')]:
            output = out.parent / (out.name + suffix)
            output.write_bytes(path.read_bytes() + fmt.encode())
            exports.append({'format': fmt, 'path': str(output), 'sha256': file_sha256(output)})
        return {'document': str(path), 'document_sha256': file_sha256(path), 'exports': exports,
                'native_audit': {'status': 'passed', 'document': str(path), 'document_sha256': file_sha256(path)}}
    monkeypatch.setattr(render, 'patch_tts_display', patch)
    monkeypatch.setattr(render, 'export_tts_document', export)
    return workspace, delivery, source, documents, capture, calls, export


def request(bound, identifier='A', key='display'):
    context = require_object(Path(next(item['path'] for item in bound[3] if item['id'] == identifier)))
    captured = bound[4](context)
    return {'plot_id': captured['plot_id'], 'base_revision': captured['revision'], 'idempotency_key': key,
        'intent_class': 'presentation', 'changes': [{'op': 'set', 'target': ['legend:graph1'],
            'property': 'legend.location', 'value': 'top-right'}]}


def test_cold_decision_and_reply_loss_never_repeat_native(bound):
    workspace, delivery, source, documents, _capture, calls, _export = bound
    path = Path(documents[0]['path'])
    before, raw = path.read_bytes(), source.read_bytes()
    req = request(bound)
    preview = native.patch_native(path, req)
    assert preview['status'] == 'needs_review'
    assert path.read_bytes() == before
    assert not (workspace / 'style_previews').exists()
    assert calls == ['patch', 'export']
    assert native.patch_native(path, req)['decision_id'] == preview['decision_id']
    decision = preview['next_step']['request']
    accepted = native.decide_native(path, decision)
    assert accepted['status'] == 'complete' and accepted['ready_to_use']
    assert accepted['presentation_hash'] == file_sha256(path)
    assert native.decide_native(path, decision)['replayed']
    assert native.patch_native(path, req)['replayed']
    assert calls == ['patch', 'export']
    assert source.read_bytes() == raw
    store = FileProjectStore(workspace, locations={'delivery': delivery})
    assert len(store.commands()) == 1 and store.commands()[0]['phase'] == 'complete'
    assert json.loads((workspace / 'suite.json').read_bytes()) == json.loads((delivery / 'data/delivery_manifest.json').read_bytes())


def test_unrelated_b_acceptance_survives_a_stale_manifest_candidate(bound):
    a, b = [Path(item['path']) for item in bound[3]]
    first = native.patch_native(a, request(bound, 'A', 'A'))
    second = native.patch_native(b, request(bound, 'B', 'B'))
    native.decide_native(b, second['next_step']['request'])
    b_bytes = b.read_bytes()
    native.decide_native(a, first['next_step']['request'])
    assert b.read_bytes() == b_bytes
    manifest = json.loads((bound[0] / 'suite.json').read_bytes())
    assert {item['id']: item['sha256'] for item in manifest['documents']} == {'A': file_sha256(a), 'B': file_sha256(b)}
    assert bound[5] == ['patch', 'export', 'patch', 'export']


def test_unknown_native_callback_is_never_replayed(bound, monkeypatch):
    from sciplot_core import rheology_tts_render as render
    path = Path(bound[3][0]['path'])
    before = path.read_bytes()
    calls = []
    def uncertain(*_args):
        calls.append('native-started')
        raise RuntimeError('worker reply lost after native may have saved its candidate')
    monkeypatch.setattr(render, 'patch_tts_display', uncertain)
    req = request(bound)
    with pytest.raises(RuntimeError, match='reply lost'):
        native.patch_native(path, req)
    with pytest.raises(ProjectCommandUnknown):
        native.patch_native(path, req)
    with pytest.raises(ProjectCommandUnknown):
        native.resume_native(path, {key: req[key] for key in ('plot_id', 'base_revision', 'idempotency_key')})
    assert calls == ['native-started'] and path.read_bytes() == before


def test_export_failure_resumes_only_frozen_native_then_publishes_reviewed_exports(bound, monkeypatch):
    from sciplot_core import rheology_tts_render as render
    path = Path(bound[3][0]['path'])
    req = request(bound)
    def fail(*_args):
        raise RuntimeError('read-only exporter failed')
    monkeypatch.setattr(render, 'export_tts_document', fail)
    blocked = native.patch_native(path, req)
    assert blocked['status'] == 'blocked'
    assert bound[5] == ['patch']
    monkeypatch.setattr(render, 'export_tts_document', bound[6])
    resumed = native.resume_native(path, {key: req[key] for key in ('plot_id', 'base_revision', 'idempotency_key')})
    assert resumed['status'] == 'needs_review'
    accepted = native.decide_native(path, resumed['next_step']['request'])
    assert accepted['ready_to_use'] and len(accepted['exports']) == 3
    assert bound[5] == ['patch', 'export']


def test_source_change_refuses_frozen_acceptance(bound):
    path = Path(bound[3][0]['path'])
    before = path.read_bytes()
    preview = native.patch_native(path, request(bound))
    bound[2].write_bytes(b'changed original raw')
    with pytest.raises(ValueError, match='Original source changed'):
        native.decide_native(path, preview['next_step']['request'])
    assert path.read_bytes() == before


def test_creation_native_reply_loss_discovers_sealed_artifacts_before_atomic_publish(tmp_path, monkeypatch):
    from sciplot_core.project_commands import ProjectCommands
    workspace, delivery = tmp_path / 'workspace', tmp_path / 'delivery'
    source = tmp_path / 'raw.csv'
    source.write_bytes(b'unchanged raw')
    sources = [{'path': str(source), 'sha256': file_sha256(source)}]
    calls = []
    def prepare(candidate_workspace, candidate_delivery):
        calls.append('native')
        candidate_workspace.mkdir()
        candidate_delivery.mkdir()
        (candidate_workspace / 'spec.json').write_bytes(b'{"science":[1,2,3]}')
        (candidate_delivery / 'A.vsz').write_bytes(b'opaque native')
        launcher = candidate_delivery / 'Open.command'
        launcher.write_text('#!/bin/zsh\n')
        launcher.chmod(0o755)
        return {'status': 'ready', 'workspace': str(candidate_workspace), 'delivery': str(candidate_delivery)}
    execute = ProjectCommands.execute
    def lose_reply(self, command, callback):
        result = execute(self, command, callback)
        if command.kind.value == 'native_create':
            raise RuntimeError('native complete reply lost')
        return result
    monkeypatch.setattr(ProjectCommands, 'execute', lose_reply)
    with pytest.raises(RuntimeError, match='reply lost'):
        create_project(workspace, delivery, {'prepared': 'same'}, sources, prepare)
    assert not (delivery / 'A.vsz').exists()
    monkeypatch.setattr(ProjectCommands, 'execute', execute)
    result = create_project(workspace, delivery, {'prepared': 'same'}, sources, prepare, resume=True)
    assert result['status'] == 'ready' and calls == ['native']
    assert (delivery / 'A.vsz').read_bytes() == b'opaque native'
    assert (delivery / 'Open.command').stat().st_mode & 0o100
    assert source.read_bytes() == b'unchanged raw'
    assert not (workspace / 'creation_checkpoint.json').exists()


def test_explicit_saved_native_import_audits_exact_bytes_without_render_or_edit(bound, monkeypatch):
    from sciplot_core import rheology_tts_render as render
    from sciplot_core.workflow.native_suite_generation import adopt_saved_native, open_store
    workspace, delivery, source, documents, *_ = bound
    path = Path(documents[0]['path'])
    store = open_store(workspace, delivery)
    previous = store.snapshot()['files'][store.logical_path(path)]['sha256']
    path.write_bytes(path.read_bytes() + b':user-saved opaque annotation')
    observed = file_sha256(path)
    audit_calls = []
    def audit(saved, figure):
        audit_calls.append((saved, figure['id']))
        return {'status': 'passed', 'document': str(saved), 'document_sha256': file_sha256(saved),
                'arrays': 'unchanged', 'opaque_annotation': 'preserved'}
    monkeypatch.setattr(render, 'audit_tts_document', audit)
    manifest = json.loads((workspace / 'suite.json').read_bytes())
    adopt_saved_native(store, manifest, ('A',))
    assert store.read_bytes(store.logical_path(path)) == path.read_bytes()
    assert previous != observed
    record = next(item for item in store.commands() if item['metadata']['kind'] == 'native_import')
    adoption = record['metadata']['native_adoptions'][0]
    assert adoption['before_sha256'] == previous and adoption['observed_sha256'] == observed
    assert record['metadata']['kind'] == 'native_import'
    assert json.loads(Path(record['artifact_paths']['native-audit.json']).read_bytes())['arrays'] == 'unchanged'
    assert audit_calls == [(path, 'A')] and not bound[5]
    adopt_saved_native(store, manifest, ('A',))
    assert len(audit_calls) == 1 and len(store.commands()) == 2
    assert file_sha256(source) == manifest['sources'][0]['sha256']


def test_retired_direct_writers_cannot_create_new_journals(tmp_path):
    from sciplot_core.workflow.rheology_tts_style_storage import publish_files
    from sciplot_core.workflow.rheology_tts_publication_recovery import seal_publication
    with pytest.raises(RuntimeError, match='retired'):
        publish_files([], tmp_path / 'backup', expected={}, candidates={}, allowed_roots=(tmp_path,))
    with pytest.raises(RuntimeError, match='retired'):
        seal_publication(tmp_path, {}, [], {}, {})
    assert not list(tmp_path.iterdir())


def test_truthful_foundation_busy_owner_keeps_closed_worker_marker(monkeypatch, capsys):
    from sciplot_core import rheology_tts_render as render
    from sciplot_core.foundation.project_session_lease import ProjectSessionBusy
    from sciplot_core.studio_core.project_session import ProjectSessionBusy as HistoricalImport
    assert HistoricalImport is ProjectSessionBusy
    assert ProjectSessionBusy.__module__ == 'sciplot_core.foundation.project_session_lease'
    error = ProjectSessionBusy('actual foundation owner')
    def fail(_request):
        raise error
    monkeypatch.setattr(render, '_run_native', fail)
    with pytest.raises(ProjectSessionBusy) as caught:
        render._worker_result({'action': 'render'})
    assert caught.value is error
    assert json.loads(capsys.readouterr().out) == {'kind': 'sciplot_tts_native_failure', 'version': 1,
                                                   'native_reason_code': 'project_busy'}


def test_public_exact_export_adopts_saved_native_then_exports_without_native_edit(bound, monkeypatch):
    from sciplot_core import rheology_tts_render as render
    from sciplot_core.workflow.native_suite_generation import open_store
    workspace, delivery, _source, documents, *_ = bound
    store = open_store(workspace, delivery)
    path = Path(documents[0]['path'])
    path.write_bytes(path.read_bytes() + b':explicit manual native save')
    monkeypatch.setattr(render, 'audit_tts_document', lambda saved, figure: {
        'status': 'passed', 'document': str(saved), 'document_sha256': file_sha256(saved)})
    monkeypatch.setattr(render, 'export_tts_documents', lambda entries: [bound[6](*entry) for entry in entries])
    before = path.read_bytes()
    result = native.export_native(path)
    assert result['exact_saved_export'] and result['ready_to_use']
    assert path.read_bytes() == before and bound[5] == ['export']
    assert [item['metadata']['kind'] for item in store.commands()].count('native_import') == 1
    assert sum(item['metadata']['request'].get('adapter') == 'native_suite_export' for item in store.commands()) == 1
    assert sum(item['metadata']['request'].get('adapter') == 'native_saved_audit' for item in store.commands()) == 1
    assert not (workspace / 'export_stages').exists()


def test_committed_head_reply_loss_requires_explicit_repair_then_no_native_reapply(bound, monkeypatch):
    from sciplot_core.project_store import state
    from sciplot_core.project_store import ProjectRecoveryRequired
    from sciplot_core.workflow.native_suite_objects import resolve_native_object
    path = Path(bound[3][0]['path'])
    req = request(bound)
    preview = native.patch_native(path, req)
    def lose_reply(name):
        if name == 'after_head':
            raise RuntimeError('head committed; process reply lost')
    monkeypatch.setattr(state, 'boundary', lose_reply)
    with pytest.raises(RuntimeError, match='head committed'):
        native.decide_native(path, preview['next_step']['request'])
    with pytest.raises(ProjectRecoveryRequired):
        resolve_native_object(path)  # read-only describe must not install views
    monkeypatch.setattr(state, 'boundary', lambda _name: None)
    resumed = native.resume_native(path, {key: req[key] for key in ('plot_id', 'base_revision', 'idempotency_key')})
    assert resumed['ready_to_use'] and bound[5] == ['patch', 'export']


def test_whole_style_preview_and_cold_apply_use_same_store_not_old_publication(bound, monkeypatch):
    from sciplot_core.workflow import rheology_tts_style_update as style
    workspace, delivery, _source, documents, *_ = bound
    manifest = json.loads((workspace / 'suite.json').read_bytes())
    manifest['figure_layout'] = 'separate_polymer_modulus'
    write_json(workspace / 'suite.json', manifest)
    write_json(delivery / 'data/delivery_manifest.json', manifest)
    write_json(workspace / 'figure_plan.json', {'numeric': 'unchanged'})
    write_json(delivery / 'data/figure_plan.json', {'numeric': 'unchanged'})
    before = Path(documents[0]['path']).read_bytes()
    def prepare(_workspace, directory, *, presentation_plan=None):
        directory.mkdir(exist_ok=True)
        write_json(directory / 'figure_plan.json', {'numeric': 'unchanged', 'presentation': 'new labels'})
        specs = []
        for receipt in manifest['native_result']['figures']:
            spec = directory / (receipt['id'] + '.spec.json')
            spec.write_bytes(Path(receipt['spec_path']).read_bytes())
            specs.append({'id': receipt['id'], 'spec_path': str(spec), 'spec_sha256': file_sha256(spec)})
        candidate = directory / 'A.vsz'
        candidate.write_bytes(before + b':style-only')
        exported = bound[6](candidate, directory / 'exports' / 'A', {'id': 'A'})
        return {'kind': 'sciplot_rheology_style_preview', 'version': 1, 'status': 'preview_ready',
            'contract_sha256': 'f' * 64, 'sources': manifest['sources'], 'figures': specs,
            'candidates': [{'id': 'A', 'edit': {'changes': [{'field': 'legend'}]}, 'export': exported}],
            'plan': str(directory / 'figure_plan.json')}
    monkeypatch.setattr(style, '_prepare_style_preview', prepare)
    preview = style.preview_suite_style(workspace)
    assert Path(documents[0]['path']).read_bytes() == before
    assert preview['status'] == 'preview_ready' and preview['changed_figures'] == 1
    accepted = style.apply_suite_style(workspace, Path(preview['preview']))
    assert accepted['exact_candidate_export'] and accepted['numerical_refit'] is False
    assert Path(documents[0]['path']).read_bytes() == before + b':style-only'
    assert style.apply_suite_style(workspace, Path(preview['preview']))['already_applied']
    assert not (workspace / 'style_previews').exists()
    records = FileProjectStore(workspace, locations={'delivery': delivery}).commands()
    assert len(records) == 1 and records[0]['phase'] == 'complete'


def test_complete_native_project_moves_offline_without_rewriting_scientific_json(bound, monkeypatch):
    from sciplot_core import rheology_tts_render as render
    from sciplot_core.workflow.native_suite_objects import resolve_native_object, selected_spec
    workspace, delivery, source, documents, *_ = bound
    original = Path(documents[0]['path'])
    preview = native.patch_native(original, request(bound))
    native.decide_native(original, preview['next_step']['request'])
    store = FileProjectStore(workspace, locations={'delivery': delivery})
    original_spec = (workspace / 'A.spec.json').read_bytes()
    raw = source.read_bytes()
    store.export_bundle(workspace.parent / 'offline-bundle')
    moved = FileProjectStore.import_bundle(workspace.parent / 'offline-bundle', workspace.parent / 'cold-project')
    workspace.rename(workspace.with_name('archived-workspace'))
    delivery.rename(delivery.with_name('archived-delivery'))
    source.rename(source.with_name('archived-raw.csv'))
    selected = moved.locations['delivery'] / 'editable/A.vsz'
    context = resolve_native_object(selected)
    assert context is not None and context['workspace'] == str(moved.root)
    # The host locator selects physical data; serialized scientific coordinates,
    # source locators, hashes, units and provenance bytes remain exactly original.
    from sciplot_core.workflow.native_suite_runtime import suite_runtime
    with suite_runtime(selected):
        spec, _figure = selected_spec(context)
        assert spec.read_bytes() == original_spec
        from sciplot_core.workflow.rheology_tts_suite import _check_sources
        _check_sources(context['manifest']['sources'])
    monkeypatch.setattr(render, 'export_tts_documents', lambda entries: [bound[6](*entry) for entry in entries])
    result = native.export_native(selected)
    assert result['ready_to_use'] and all(Path(item['path']).is_relative_to(moved.locations['delivery']) for item in result['exports'])
    assert moved.read_bytes('A.spec.json') == original_spec
    published = json.loads(moved.read_bytes('suite.json'))
    exported = next(item for item in published['last_export'] if Path(item['document']).stem == 'A')
    audit = moved.resolve_path(exported['native_audit_path'])
    assert json.loads(audit.read_bytes()) == exported['native_audit']
    assert moved.resolve_path(str(source), expected_sha256=__import__('hashlib').sha256(raw).hexdigest()).read_bytes() == raw
    assert not source.exists()


def test_immediate_creation_sealed_before_head_resumes_without_native_callback(tmp_path, monkeypatch):
    from sciplot_core.project_store import state
    workspace, delivery = tmp_path / 'workspace', tmp_path / 'delivery'
    source = tmp_path / 'source.csv'
    source.write_bytes(b'raw bytes')
    calls = []
    def prepare(candidate_workspace, candidate_delivery):
        calls.append('native')
        candidate_workspace.mkdir()
        candidate_delivery.mkdir()
        (candidate_delivery / 'A.vsz').write_bytes(b'exact sealed candidate')
        return {'status': 'ready', 'workspace': str(candidate_workspace), 'delivery': str(candidate_delivery)}
    def fail(name):
        if name == 'before_storage':
            raise RuntimeError('complete candidate sealed before head')
    monkeypatch.setattr(state, 'boundary', fail)
    sources = [{'path': str(source), 'sha256': file_sha256(source)}]
    with pytest.raises(RuntimeError, match='sealed before head'):
        create_project(workspace, delivery, {'same': 'request'}, sources, prepare)
    store = FileProjectStore(workspace, locations={'delivery': delivery})
    assert store.commands()[0]['phase'] == 'accepted'
    assert not (delivery / 'A.vsz').exists()
    monkeypatch.setattr(state, 'boundary', lambda _name: None)
    result = create_project(workspace, delivery, {'same': 'request'}, sources, prepare, resume=True)
    assert result['status'] == 'ready' and calls == ['native']
    assert (delivery / 'A.vsz').read_bytes() == b'exact sealed candidate'


def test_rheology_worker_receives_closed_host_runtime_descriptor(bound, monkeypatch):
    import subprocess
    from sciplot_core import rheology_tts_render as render
    from sciplot_core.workflow.native_suite_generation import open_store
    from sciplot_core.project_store.runtime import project_runtime
    workspace, delivery, *_ = bound
    store = open_store(workspace, delivery)
    commands = []
    def run(command, **_kwargs):
        commands.append(command)
        assert command[-3] == '--project-runtime'
        descriptor = json.loads(Path(command[-2]).read_bytes())
        assert descriptor['project']['project_id'] == store.snapshot()['project_id']
        assert descriptor['project']['generation'] == store.snapshot()['generation']
        assert descriptor['parent_pid'] == __import__('os').getpid()
        assert json.loads(Path(command[4]).read_bytes()) == {'action': 'audit', 'private': 'request'}
        return subprocess.CompletedProcess(command, 0, stdout='{"bound":true}', stderr='')
    monkeypatch.setattr(render, 'needs_veusz_worker_process', lambda: True)
    monkeypatch.setattr(render.subprocess, 'run', run)
    with project_runtime(store):
        assert render._dispatch({'action': 'audit', 'private': 'request'}) == {'bound': True}
    assert len(commands) == 1
    assert not Path(commands[0][-2]).exists()  # host private binding lifetime closes


def test_rheology_worker_entry_resets_runtime_on_native_failure(tmp_path, monkeypatch):
    from contextlib import contextmanager
    from sciplot_core import rheology_tts_render as render
    from sciplot_core.project_store import worker_binding
    path = tmp_path / 'request.json'
    write_json(path, {'action': 'audit'})
    trace = []
    @contextmanager
    def scope(reference, arguments):
        trace.append(('enter', reference, arguments))
        try:
            yield
        finally:
            trace.append(('exit',))
    def fail(_request):
        assert trace[0][0] == 'enter'
        raise RuntimeError('native original failure')
    monkeypatch.setattr(worker_binding, 'worker_project_runtime', scope)
    monkeypatch.setattr(render, '_worker_result', fail)
    with pytest.raises(RuntimeError, match='original failure'):
        render._worker_entry(['--worker', str(path), '--project-runtime', '/private/host/binding.json', 'a' * 64])
    assert trace[-1] == ('exit',)
    assert trace[0][1] == {'path': '/private/host/binding.json', 'sha256': 'a' * 64}
    with pytest.raises(ValueError, match='exact host-created'):
        render._worker_entry(['--worker', str(path), '--unknown', 'value', 'hash'])


@pytest.mark.parametrize('accept', [False, True])
def test_sealed_legacy_preview_migrates_without_reapplying_native_and_keeps_decision(bound, monkeypatch, accept):
    from sciplot_core import rheology_tts_render as render
    from sciplot_core.foundation.json_hashing import canonical_json_sha256
    from sciplot_core.workflow.native_suite_storage import operation_path, pending_operation
    from sciplot_core.workflow.native_suite_preview import baseline_files
    from sciplot_core.workflow.rheology_tts_contract import rheology_capabilities
    from sciplot_core.workflow.rheology_tts_style_storage import snapshot
    workspace, delivery, _source, documents, capture, calls, export = bound
    path = Path(documents[0]['path'])
    context = require_object(path)
    captured = capture(context)
    req = request(bound, key='old-sealed-display')
    diff, changes = native._changes(captured, req)
    operation = operation_path(context, req['idempotency_key'])
    directory = operation.parent
    directory.mkdir(parents=True)
    baseline = baseline_files(context)
    candidate = directory / 'native/A.vsz'
    edited = render.patch_tts_display(path, candidate, captured['figure'], changes, file_sha256(path))
    edited.update(source_document=str(path), source_document_sha256=file_sha256(path),
                  baseline_audit={'status': 'passed'}, candidate_audit={'status': 'passed',
                      'document_sha256': file_sha256(candidate),
                      'changed_presentation': {'unrelated_native_state_unchanged': True}})
    exported = export(candidate, directory / 'exports/A', captured['figure'])
    preview = {'kind': 'sciplot_native_display_preview', 'version': 1,
        'workspace': str(workspace), 'delivery': str(delivery), 'sources': context['manifest']['sources'],
        'contract_sha256': rheology_capabilities()['contract_sha256'], 'baseline': baseline,
        'candidate_files': snapshot([candidate, *(Path(item['path']) for item in exported['exports'])]),
        'figures': context['manifest']['native_result']['figures'],
        'candidates': [{'id': 'A', 'edit': edited, 'export': exported}], 'presentation_plan': {}}
    preview_path = directory / 'preview.json'
    write_json(preview_path, preview)
    (directory / 'preview.sha256').write_text(canonical_json_sha256(preview))
    spec = Path(context['manifest']['native_result']['figures'][0]['spec_path'])
    legacy = {'kind': 'sciplot_native_display_operation', 'version': 1, 'plot': str(path), 'figure_id': 'A',
        'phase': 'needs_review', 'request': req, 'decision_id': 'd' * 64,
        'scientific_hash': canonical_json_sha256(json.loads(spec.read_bytes())),
        'before_native_sha256': file_sha256(path), 'spec_sha256': file_sha256(spec),
        'sources': context['manifest']['sources'], 'baseline': baseline, 'diff': diff,
        'native_changes': changes, 'preview': str(preview_path)}
    write_json(operation, legacy)
    original_record = operation.read_bytes()
    audits = []
    def audit(saved, _figure):
        audits.append(saved)
        return {'status': 'passed', 'document_sha256': file_sha256(saved)}
    monkeypatch.setattr(render, 'audit_tts_document', audit)
    imported = native.patch_native(path, req)
    assert imported['status'] == 'needs_review' and calls == ['patch', 'export']
    assert audits == [candidate]
    result = native.decide_native(path, {'decision_id': legacy['decision_id'], 'base_revision': req['base_revision'], 'accept': accept})
    assert result['status'] == ('complete' if accept else 'rejected')
    assert operation.read_bytes() == original_record  # history never rewritten
    assert pending_operation(require_object(path)) is None
    assert calls == ['patch', 'export']
    assert native.patch_native(path, req)['replayed']


def test_patch_inspects_native_only_after_exact_parent_admission(bound, monkeypatch):
    events = []
    entered = FileProjectStore.mark_applying
    def mark(store, key, digest):
        result = entered(store, key, digest)
        events.append(('admit', key))
        return result
    capture = native.capture_object
    def inspect(context):
        assert events and events[-1][0] == 'admit'
        events.append(('inspect',))
        return capture(context)
    monkeypatch.setattr(FileProjectStore, 'mark_applying', mark)
    monkeypatch.setattr(native, 'capture_object', inspect)
    path = Path(bound[3][0]['path'])
    native.patch_native(path, request(bound))
    assert [item[0] for item in events] == ['admit', 'inspect']


def test_invalid_closed_patch_does_not_import_or_execute_native_even_after_manual_save(bound, monkeypatch):
    from sciplot_core import rheology_tts_render as render
    from sciplot_core.workflow.native_suite_generation import open_store
    workspace, delivery, *_ = bound
    store = open_store(workspace, delivery)
    path = Path(bound[3][0]['path'])
    path.write_bytes(path.read_bytes() + b':manual save')
    req = request(bound)
    req['changes'][0]['property'] = 'numeric.coordinates'
    def forbidden(*_args):
        pytest.fail('An invalid preadmission request must not run native inspection/audit/edit/export.')
    monkeypatch.setattr(native, 'capture_object', forbidden)
    monkeypatch.setattr(render, 'audit_tts_document', forbidden)
    with pytest.raises(Exception) as caught:
        native.patch_native(path, req)
    assert getattr(caught.value, 'code', getattr(caught.value, 'reason_code', None)) == 'document_unsupported_property'
    assert store.commands() == () and not bound[5]


def test_source_version_reuses_existing_registered_identity(tmp_path):
    from sciplot_core.workflow.native_suite_generation import open_store, source_versions
    workspace, delivery = tmp_path / 'workspace', tmp_path / 'delivery'
    workspace.mkdir()
    delivery.mkdir()
    source = workspace / 'original.csv'
    source.write_bytes(b'original raw')
    store = open_store(workspace, delivery)
    current = store.snapshot()
    existing = next(identity for identity, versions in current['sources'].items()
                    if versions.get(file_sha256(source), {}).get('locator') == str(source))
    supplied = source_versions(store, [{'path': str(source), 'sha256': file_sha256(source)}])
    assert supplied == [{'source_id': existing, 'path': str(source), 'version': file_sha256(source)}]
