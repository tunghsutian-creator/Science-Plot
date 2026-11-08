"""New confirmations publish one envelope; legacy inputs keep their readers."""

import json
import os
from dataclasses import replace
from pathlib import Path

import pytest

from sciplot_core.intake import application, session as sessions, session_adapter as adapter
from sciplot_core.intake import session_contract
from sciplot_core.materials_rules import get_rule


@pytest.fixture
def publications(monkeypatch):
    observed = []
    write, replace = Path.write_text, os.replace

    def record_write(path, text, *args, **kwargs):
        result = write(path, text, *args, **kwargs)
        if path.parent.name == 'sessions':
            observed.append((path, json.loads(text)))
        return result

    def record_replace(source, target, *args, **kwargs):
        result = replace(source, target, *args, **kwargs)
        path = Path(target)
        if path.parent.name == 'sessions':
            observed.append((path, json.loads(path.read_text())))
        return result

    monkeypatch.setattr(Path, 'write_text', record_write)
    monkeypatch.setattr(os, 'replace', record_replace)
    return observed


def dsc_source(tmp_path):
    source = tmp_path / 'original.csv'
    source.write_bytes(b'Temperature (C),Heat Flow (W/g)\n10,1\n20,2\n30,3\n')
    return source


@pytest.mark.parametrize('entry', ['local', 'legacy-python'])
def test_new_sessions_have_one_envelope_publication_and_keep_legacy_metadata(tmp_path, publications, entry):
    source = dsc_source(tmp_path)
    original = source.read_bytes()
    if entry == 'local':
        result = adapter.prepare_session(source, output_root=tmp_path / 'out', rule_id='dsc_curve')
        path = Path(result['session'])
    else:
        result = sessions.prepare_intake_session(source, output_root=tmp_path / 'out', requested_rule_id='dsc_curve')
        path = Path(result['session_path'])
        assert result['kind'] == 'sciplot_intake_session' and result['rule_id'] == 'dsc_curve'
    saved = json.loads(path.read_text())
    assert publications == [(path, saved)]
    assert saved['kind'] == 'sciplot_local_intake_session' and saved['version'] == 1
    assert saved['context']['session_path'] == str(path) and saved['context']['session_id'] == path.stem
    assert saved['request']['group_order_is_explicit'] is False
    assert source.read_bytes() == original


def test_new_envelope_path_uses_request_only_and_the_real_source_reader(tmp_path):
    source = dsc_source(tmp_path)
    prepared = adapter.prepare_session(source, output_root=tmp_path / 'out', rule_id='dsc_curve')
    path = Path(prepared['session'])
    value = json.loads(path.read_text())
    value['context'] = {'semantic': {'rule_id': 'invented'}, 'pending_rule_review': True}
    value['capabilities'] = {'ready_rule_ids': ['invented']}
    path.write_text(json.dumps(value))
    calls = []

    def project(**arguments):
        calls.append(arguments)
        return {'project_dir': 'controlled-project-boundary'}

    assert application.create_intake_project_from_session(path, project_factory=project)['project_dir'] == 'controlled-project-boundary'
    assert len(calls) == 1 and len(calls[0]['groups']) == 1
    assert calls[0]['groups'][0].files[0].content == source.read_bytes()
    assert calls[0]['experiment_type_id'] == 'dsc_curve'
    assert calls[0]['recognition']['rule_id'] == 'dsc_curve'
    assert 'pending_rule_review' not in calls[0]['recognition']


@pytest.mark.parametrize('entry', ['studio', 'curate'])
def test_raw_entry_names_are_frozen_in_one_session_without_changing_filename_identity(
    tmp_path, monkeypatch, publications, entry
):
    from sciplot_core import curate
    from sciplot_core.intake import project as intake_project
    from sciplot_core.studio_core import studio_prepare
    from curation_fixture_helpers import _generated_torque_sources

    captured = []

    class ProjectBoundary(RuntimeError):
        pass

    def stop_project(session, **_options):
        captured.append(session)
        raise ProjectBoundary('Stopped before project/native preparation')

    if entry == 'studio':
        source = dsc_source(tmp_path)
        monkeypatch.setattr(intake_project, 'create_intake_project_from_session', stop_project)
        def execute():
            return studio_prepare.prepare_studio_document(source, output_root=tmp_path / 'out',
                project_name='Chosen', rule_id='dsc_curve', template='curve')
    else:
        source = tmp_path / 'original'
        _generated_torque_sources(source)
        monkeypatch.setattr(curate, 'create_intake_project_from_session', stop_project)
        def execute():
            return curate.curate_torque_project(source, output_root=tmp_path / 'out', project_name='Chosen')
    with pytest.raises(ProjectBoundary):
        execute()
    assert len(captured) == 1 and len(publications) == 1
    path, value = publications[0]
    assert value['kind'] == 'sciplot_local_intake_session' and value['request']['project_name'] == 'Chosen'
    assert captured[0]['project_name'] == 'Chosen' and captured[0]['session_path'] == str(path)
    assert path.stem != 'Chosen' and value['context']['session_id'] == path.stem
    assert json.loads(path.read_text()) == value


@pytest.mark.parametrize('form', ['historical-path', 'historical-dict', 'envelope-path', 'envelope-dict', 'request-dict'])
def test_all_supported_read_forms_keep_original_bytes_and_legacy_metadata(tmp_path, form):
    source = dsc_source(tmp_path)
    legacy = sessions.prepare_intake_session(source, output_root=tmp_path / 'out', requested_rule_id='dsc_curve')
    envelope = json.loads(Path(legacy['session_path']).read_text())
    historical = tmp_path / 'historical.json'
    historical.write_text(json.dumps({**legacy, 'pending_rule_review': True}))
    candidates = {'historical-path': historical, 'historical-dict': {**legacy, 'pending_rule_review': True},
        'envelope-path': Path(legacy['session_path']), 'envelope-dict': envelope,
        'request-dict': {**envelope['request'], 'rule_id': 'dsc_curve'}}
    calls = []
    application.create_intake_project_from_session(candidates[form], project_factory=lambda **kw: calls.append(kw) or {})
    assert len(calls) == 1 and calls[0]['groups'][0].files[0].content == source.read_bytes()
    assert calls[0]['groups'][0].files[0].source_path == str(source)
    assert calls[0]['recognition'].get('pending_rule_review') is (True if form.startswith('historical-') else None)
    assert json.loads(historical.read_text()) == {**legacy, 'pending_rule_review': True}


def test_envelope_review_uses_current_rule_and_explicit_template_not_context(tmp_path, monkeypatch):
    from sciplot_core.intake.project import create_intake_project_from_session
    source = dsc_source(tmp_path)
    prepared = adapter.prepare_session(source, output_root=tmp_path / 'out', rule_id='dsc_curve')
    path = Path(prepared['session'])
    value = json.loads(path.read_text())
    value['context']['pending_rule_review'] = False
    value['capabilities']['ready_rule_ids'] = ['dsc_curve']
    path.write_text(json.dumps(value))
    pending = replace(get_rule('dsc_curve'), fixture_status='pending')
    monkeypatch.setattr(session_contract, 'get_rule', lambda _rule: pending)
    calls = []
    for template in (None, '', '  '):
        with pytest.raises(adapter.IntakeSessionError, match='explicit rule plus template'):
            create_intake_project_from_session(path, template=template,
                studio_preparer=lambda _project: pytest.fail('Refused review reached preparation'),
                project_factory=lambda **kw: calls.append(kw) or {})
    with pytest.raises(adapter.IntakeSessionError, match='currently ready'):
        adapter.create_session(path)
    assert calls == []
    create_intake_project_from_session(path, template='curve',
        studio_preparer=lambda _project: pytest.fail('Controlled factory must own preparation'),
        project_factory=lambda **kw: calls.append(kw) or {})
    assert len(calls) == 1 and calls[0]['recognition']['pending_rule_review'] is True
    assert calls[0]['template'] == 'curve'


@pytest.mark.parametrize('entry', ['adapter', 'path'])
def test_envelope_admission_refuses_occupied_output_and_invalid_render_before_project(tmp_path, monkeypatch, entry):
    source = dsc_source(tmp_path)
    prepared = adapter.prepare_session(source, output_root=tmp_path / 'out', rule_id='dsc_curve')
    path = Path(prepared['session'])
    original = json.loads(path.read_text())
    occupied = tmp_path / 'occupied'
    occupied.mkdir()
    monkeypatch.setattr(application, 'create_intake_project', lambda **_kw: pytest.fail('Invalid request reached project creation'))
    for field, value in (('plot_output', str(occupied)), ('render_options', {'size': 'not-a-size'})):
        changed = json.loads(json.dumps(original))
        changed['request'][field] = value
        path.write_text(json.dumps(changed))
        with pytest.raises(ValueError):
            if entry == 'adapter':
                adapter.create_session(path)
            else:
                application.create_intake_project_from_session(path)
    assert list(occupied.iterdir()) == []


def test_internal_adapter_request_is_admitted_once_and_columns_are_checked_at_the_source_owner(tmp_path, monkeypatch):
    from sciplot_core.intake.project import session_project
    source = dsc_source(tmp_path)
    result = adapter.prepare_session(source, output_root=tmp_path / 'out', rule_id='dsc_curve')
    path = Path(result['session'])
    value = json.loads(path.read_text())
    value['request']['column_confirmations'] = [adapter.preview_session_table(path, group_index=0, file_index=0)['confirmation_request']]
    path.write_text(json.dumps(value))
    counts = {'admit': 0, 'columns': 0}
    check, columns = session_contract.checked_session_request, session_project._validate_columns

    def observe_check(value):
        counts['admit'] += 1
        return check(value)

    def observe_columns(*args, **kwargs):
        counts['columns'] += 1
        return columns(*args, **kwargs)

    monkeypatch.setattr(session_contract, 'checked_session_request', observe_check)
    monkeypatch.setattr(session_project, '_validate_columns', observe_columns)
    monkeypatch.setattr(application, 'create_intake_project', lambda **_kw: {'project_dir': 'controlled-source-boundary'})
    monkeypatch.setattr(adapter, 'publish_prepared_intake_project', lambda prepared: prepared)
    assert adapter.create_session(path)['status'] == 'complete'
    assert counts == {'admit': 1, 'columns': 1}


def test_session_publication_failure_preserves_existing_sessions_and_original_permission_error(tmp_path, monkeypatch):
    source = dsc_source(tmp_path)
    first = adapter.prepare_session(source, output_root=tmp_path / 'out', rule_id='dsc_curve')
    path = Path(first['session'])
    before = path.read_bytes(), source.read_bytes()
    refusal = PermissionError('controlled session publisher refusal')

    def deny(*_args, **_kwargs):
        raise refusal

    monkeypatch.setattr(sessions, 'atomic_write_json', deny)
    with pytest.raises(PermissionError) as error:
        sessions.prepare_intake_session(source, output_root=tmp_path / 'out', requested_rule_id='dsc_curve')
    assert error.value is refusal and list(path.parent.iterdir()) == [path]
    assert (path.read_bytes(), source.read_bytes()) == before


def test_session_cleanup_refusal_cannot_replace_the_original_publication_error(tmp_path, monkeypatch):
    source = dsc_source(tmp_path)
    original = PermissionError('original publication refusal')
    unlink = Path.unlink

    def refuse_write(*_args, **_kwargs):
        raise original

    def refuse_cleanup(path, *args, **kwargs):
        if path.parent.name == 'sessions':
            raise PermissionError('cleanup also refused')
        return unlink(path, *args, **kwargs)

    with monkeypatch.context() as patch:
        patch.setattr(sessions, 'atomic_write_json', refuse_write)
        patch.setattr(Path, 'unlink', refuse_cleanup)
        with pytest.raises(PermissionError) as error:
            adapter.prepare_session(source, output_root=tmp_path / 'out', rule_id='dsc_curve')
    assert error.value is original
    assert any('cleanup also refused' in note for note in original.__notes__)


@pytest.mark.parametrize('fault', ['source-bytes', 'missing-source', 'declared-sha'])
def test_new_envelope_path_keeps_fresh_source_refusals_before_factory(tmp_path, fault):
    source = dsc_source(tmp_path)
    prepared = adapter.prepare_session(source, output_root=tmp_path / 'out', rule_id='dsc_curve')
    path = Path(prepared['session'])
    value = json.loads(path.read_text())
    if fault == 'source-bytes':
        source.write_bytes(b'changed after confirmation')
    elif fault == 'missing-source':
        source.unlink()
    else:
        value['request']['groups'][0]['files'][0]['sha256'] = '0' * 64
        path.write_text(json.dumps(value))
    with pytest.raises((ValueError, FileNotFoundError)):
        application.create_intake_project_from_session(path,
            project_factory=lambda **_kw: pytest.fail('Refused source reached project creation'))


def test_legacy_column_metadata_uses_the_same_exact_source_guard_before_custom_factory(tmp_path):
    from sciplot_core.semantic_sources.confirmation_contract import bind_materialized_confirmations
    source = dsc_source(tmp_path)
    prepared = sessions.prepare_intake_session(source, output_root=tmp_path / 'out', requested_rule_id='dsc_curve')
    confirmation = adapter.preview_session_table(Path(prepared['session_path']), group_index=0, file_index=0)['confirmation_request']
    confirmation['columns'][0]['name'] = 'invented original header'
    prepared['column_confirmations'] = [confirmation]
    bound = bind_materialized_confirmations([confirmation], [{'sample': confirmation['sample'],
        'files': [{'original_name': source.name, 'source_path': str(source),
                   'sha256': confirmation['source_sha256']}]}])
    assert bound[0]['columns'][0]['name'] == 'invented original header'  # File binding never verified headers.
    legacy = tmp_path / 'legacy.json'
    legacy.write_text(json.dumps(prepared))
    for value in (prepared, legacy):
        with pytest.raises(adapter.IntakeSessionError, match='Column identities'):
            application.create_intake_project_from_session(value,
                project_factory=lambda **_kw: pytest.fail('Bad legacy columns reached project creation'))
