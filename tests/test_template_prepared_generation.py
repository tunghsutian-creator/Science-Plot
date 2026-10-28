"""Prepared template admission follows Store generations, not control-file churn."""

from __future__ import annotations

import json
from contextlib import contextmanager

import pytest

from sciplot_core.foundation.source_tree import source_tree_sha256
from sciplot_core.foundation.project_session_lease import external_project_session
from sciplot_core.project_commands import ProjectCommand, ProjectCommands, ProjectMutation
from sciplot_core.project_store import FileProjectStore
from sciplot_core.project_store.runtime import selected_project_store
from sciplot_core.project_lifecycle.attachment_index import INDEX, OWNER, attachment_id, encode
from sciplot_core.project_lifecycle.context import repository_scope
from sciplot_core.project_lifecycle.repository import FileProjectRepository
from sciplot_core.project_lifecycle.template_creation import _open_prepared
from sciplot_core.task_prepared_creation import checkpoint_prepared, prepared_admission, require_prepared_current


@pytest.fixture
def prepared(tmp_path):
    source = tmp_path / 'original'
    source.mkdir()
    (source / 'a.csv').write_text('x,y\n1,2\n')
    project = tmp_path / 'project'
    (project / 'studio').mkdir(parents=True)
    (project / 'studio/document.vsz').write_bytes(b'prepared native')
    (project / 'studio/spec.json').write_bytes(b'{"series":[]}')
    (project / 'plot_request.json').write_text(json.dumps({'input': str(source)}))
    store = FileProjectStore(project)
    store.snapshot(import_legacy=True)
    task = tmp_path / 'task'
    task.mkdir()
    state = {'kind': 'sciplot_task', 'version': 1, 'task_dir': str(task), 'defer_creation_export': True,
             'request': {'version': 1, 'action': 'create', 'source': str(source)},
             'source_sha256': source_tree_sha256(source)}
    checkpoint_prepared(task, state, {'project_dir': str(project), 'document': str(project / 'studio/document.vsz'),
                                      'request': str(project / 'plot_request.json')})
    return source, project, store, task, state


def attach(store):
    before = store.snapshot()
    identity = attachment_id(before['project_id'], 'legacy:primary')
    namespace = '.sciplot_semantic/' + identity
    entry = {'id': identity, 'namespace': namespace, 'origin_root': str(store.root / namespace),
             'project_origin': str(store.root), 'plot_id': 'plot:primary', 'figure_id': 'primary'}
    writes = {INDEX: encode({'kind': 'sciplot_semantic_attachment_index', 'version': 1,
                            'project_id': before['project_id'], 'attachments': {identity: entry}}),
              namespace + '/' + OWNER: encode({'kind': 'sciplot_semantic_owner', 'version': 1,
                  'origin_root': str(store.root / namespace), 'project': str(store.root),
                  'project_id': before['project_id'], 'attachment_id': identity}),
              namespace + '/head.json': b'{"synthetic_semantic_head":true}'}
    command = ProjectCommand.create('semantic_record', 'synthetic-attach', project_id=before['project_id'],
        expected_generation=before['generation'], read_set={name: None for name in writes},
        write_set=sorted(writes), request={'attachment_id': identity})
    ProjectCommands(store).execute(command, lambda: ProjectMutation(writes, {}))
    return namespace


def test_admitted_semantic_attachment_does_not_invalidate_prepared_native_inputs(prepared):
    _source, _project, store, _task, state = prepared
    attach(store)
    require_prepared_current(state)
    assert state['result']['export_performed'] is False


def test_template_open_uses_store_owner_without_nested_legacy_exclusion(prepared):
    _source, project, store, task, task_state = prepared
    creation = {'request': {'template_definition': {}, 'data_binding': {'slots': {}}}}

    class Service:
        def open_created(self, target, **_kwargs):
            assert target == project
            selected = selected_project_store()
            assert selected is not None and selected.root == store.root
            attach(selected)
            return {'status': 'current', 'plot': str(project / '.sciplot_semantic/selected')}

    with repository_scope(FileProjectRepository(lease=external_project_session)):
        result = _open_prepared(Service(), task.parent, creation, task_state)
    assert result['status'] == 'current'


@pytest.mark.parametrize('changed', ['source', 'source_member', 'native', 'spec', 'mode', 'foreign_file', 'semantic_phantom'])
def test_prepared_science_native_mode_and_foreign_members_remain_guarded(prepared, changed):
    source, project, store, _task, state = prepared
    namespace = attach(store)
    if changed == 'source':
        (source / 'a.csv').write_text('x,y\n1,999\n')
    elif changed == 'source_member':
        (source / 'late.csv').write_text('x,y\n2,3\n')
    elif changed == 'mode':
        target = project / 'studio/document.vsz'
        target.chmod(0o600 if target.stat().st_mode & 0o777 != 0o600 else 0o644)
    else:
        name = {'native': 'studio/document.vsz', 'spec': 'studio/spec.json',
                'foreign_file': 'unregistered.csv', 'semantic_phantom': namespace + '/unregistered.json'}[changed]
        (project / name).write_bytes(b'foreign data')
    with pytest.raises(ValueError):
        require_prepared_current(state)


def publish(store, *, kind, name, data, attachment=None):
    before = store.snapshot()
    command = ProjectCommand.create(kind, 'followup-' + name, project_id=before['project_id'],
        expected_generation=before['generation'], read_set={name: before['files'].get(name, {}).get('sha256')},
        write_set=[name], request={'attachment_id': attachment} if attachment is not None else {})
    ProjectCommands(store).execute(command, lambda: ProjectMutation({name: data}, {}))


def test_registered_semantic_revision_is_allowed_without_changing_prepared_native(prepared):
    _source, project, store, _task, state = prepared
    namespace = attach(store)
    native = (project / 'studio/document.vsz').read_bytes()
    publish(store, kind='semantic_record', name=namespace + '/head.json',
            data=b'{"synthetic_semantic_head":2}', attachment=namespace.split('/')[1])
    require_prepared_current(state)
    assert (project / 'studio/document.vsz').read_bytes() == native


@pytest.mark.parametrize('kind,name', [('figure_set', 'new.csv'), ('figure_set', 'studio/document.vsz'),
                                      ('semantic_record', 'new.csv'), ('figure_set', 'semantic')])
def test_registered_unrelated_or_misidentified_publication_cannot_change_preparation(prepared, kind, name):
    _source, _project, store, _task, state = prepared
    namespace = attach(store)
    target = namespace + '/head.json' if name == 'semantic' else name
    publish(store, kind=kind, name=target, data=b'foreign publication', attachment=namespace.split('/')[1])
    with pytest.raises(ValueError, match='Unrelated publication|prepared native'):
        require_prepared_current(state)


@pytest.mark.parametrize('changed', ['legacy', 'generation', 'project_id', 'files', 'missing_store'])
def test_checkpoint_needs_its_exact_registered_generation(prepared, changed):
    _source, project, _store, _task, state = prepared
    checkpoint = state['prepared_creation']
    if changed == 'legacy':
        checkpoint.pop('store_binding')
    elif changed == 'files':
        checkpoint['files']['studio/document.vsz'] = '0' * 64
    elif changed == 'missing_store':
        (project / '.sciplot_store').rename(project.parent / 'preserved-store')
    else:
        checkpoint['store_binding'][changed] = '0' * 32
    with pytest.raises(ValueError):
        require_prepared_current(state)


def test_foreign_change_during_semantic_open_is_rejected_by_postcondition(prepared):
    _source, project, store, task, task_state = prepared
    creation = {'request': {'template_definition': {}, 'data_binding': {'slots': {}}}}

    class Service:
        def open_created(self, _target, **_kwargs):
            attach(store)
            (project / 'studio/document.vsz').write_bytes(b'foreign save during adoption')
            return {'status': 'current', 'plot': str(project / '.sciplot_semantic/selected')}

    with repository_scope(FileProjectRepository(lease=external_project_session)), pytest.raises(ValueError):
        _open_prepared(Service(), task.parent, creation, task_state)


def test_unknown_native_command_cannot_be_ignored_by_prepared_adoption(prepared):
    _source, _project, store, _task, state = prepared
    before = store.snapshot()
    name = 'studio/document.vsz'
    command = ProjectCommand.create('native_patch', 'uncertain-native', project_id=before['project_id'],
        expected_generation=before['generation'], read_set={name: before['files'][name]['sha256']},
        write_set=[name], request={})
    store.reserve(command.key, command.command_digest, expected_generation=command.expected_generation,
                  read_set=dict(command.read_set), write_set=command.write_set, metadata=command.to_payload())
    store.mark_applying(command.key, command.command_digest)
    with pytest.raises(ValueError, match='unresolved'):
        require_prepared_current(state)


def test_legacy_preparation_is_checked_after_its_lease_is_entered(prepared, monkeypatch):
    from sciplot_core.studio_core import project_session

    _source, project, _store, task, state = prepared
    (project / '.sciplot_store').rename(project.parent / 'preserved-store')
    checkpoint_prepared(task, state, {'project_dir': str(project), 'document': str(project / 'studio/document.vsz'),
                                     'request': str(project / 'plot_request.json')})
    calls = []

    @contextmanager
    def intervening_lease(target):
        assert target == project
        (project / 'studio/document.vsz').write_bytes(b'legitimate writer before lease acquisition')
        yield

    monkeypatch.setattr(project_session, 'external_project_session', intervening_lease)
    with pytest.raises(ValueError, match='prepared native project changed'):
        with prepared_admission(state):
            calls.append('must not adopt an unchecked new native baseline')
    assert calls == []
