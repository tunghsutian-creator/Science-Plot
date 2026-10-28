"""Public initial request preparation preserves original and produced source roles."""
import json
import hashlib
import subprocess

import pytest

from sciplot_core.foundation.file_hashing import file_sha256
from sciplot_core.project_host_factory import project_store
from sciplot_core.project_store.runtime import project_runtime
from sciplot_core.studio_core.studio_prepare import prepare_studio_document


@pytest.fixture
def prepared_request(tmp_path, monkeypatch):
    from sciplot_core.studio_core import veusz_document
    from sciplot_core.source_coverage import document_audit

    source = tmp_path / 'UVvis.csv'
    source.write_text('Wavelength,Absorbance,Wavelength,Absorbance\nnm,a.u.,nm,a.u.\n'
                      'E2,E2,E4,E4\n400,1,400,2\n450,2,450,3\n500,3,500,4\n')
    project = tmp_path / 'project'
    project.mkdir()
    request = {'input': str(source), 'rule_id': 'uvvis_spectrum', 'template': 'curve',
               'output': str(project / 'runs/run_001'), 'delivery_output': str(tmp_path / 'delivery'),
               'render_options': {'reverse_x': True}}
    request_path = project / 'plot_request.json'
    request_path.write_text(json.dumps(request))
    def save(path, spec, **_kwargs):
        path.write_text("\n".join("Add('xy', name='series_%s')" % i for i in range(len(spec['series']))))
    def audit(*, spec_path, **_kwargs):
        spec = json.loads(spec_path.read_text())
        return {'status': 'passed', 'native_port_double': True}, spec
    monkeypatch.setattr(veusz_document, '_save_veusz_document_from_spec', save)
    monkeypatch.setattr(document_audit, '_audit_exact_document_data', audit)
    monkeypatch.setattr(subprocess, 'Popen', lambda *_a, **_k: pytest.fail('Pure preparation must not spawn native processes.'))
    monkeypatch.setattr(subprocess, 'run', lambda *_a, **_k: pytest.fail('Pure preparation must not spawn native processes.'))
    return project, source, request_path


def test_public_initial_json_captures_original_uuid_and_version_in_native_generation(prepared_request):
    project, source, request = prepared_request
    original, digest = source.read_bytes(), file_sha256(source)
    result = prepare_studio_document(request)
    store = project_store(project)
    snapshot = store.snapshot()
    originals = [(identity, entry) for identity, versions in snapshot['sources'].items()
                 for version, entry in versions.items() if entry.get('locator') == str(source) and version == digest]
    assert len(originals) == 1, 'The actual original input must join the same native generation.'
    assert originals[0][1].get('produced_resource') is None
    assert any(entry.get('produced_resource') for versions in snapshot['sources'].values() for entry in versions.values())
    assert result['project_command']['generation'] == snapshot['generation']
    assert source.read_bytes() == original
    from sciplot_core.studio_core.project_query_sources import current_source_files, current_source_tree
    with project_runtime(store):
        files, identities = current_source_files(project, source, [{'status': 'ready', 'spec': str(project / 'studio/spec.json')}])
        assert files == {str(source): digest} and identities == {str(source): originals[0][0]}
        assert current_source_tree(source, files, identities, expected=None)


def test_initial_json_original_is_portable_and_keeps_one_uuid_on_reopen(prepared_request, tmp_path):
    from sciplot_core.project_store import FileProjectStore
    from sciplot_core.foundation.source_locations import resolve_source_path
    from sciplot_core.studio_core.preparation_source_runtime import current_preparation_runtime

    project, source, request = prepared_request
    prepare_studio_document(request)
    store = project_store(project)
    snapshot = store.snapshot()
    original = source.read_bytes()
    cold = FileProjectStore.import_bundle(store.export_bundle(tmp_path / 'bundle'), tmp_path / 'cold')
    source.rename(tmp_path / 'original-offline.csv')
    with current_preparation_runtime(cold, cold.snapshot()):
        assert resolve_source_path(source, expected_sha256=hashlib.sha256(original).hexdigest()).read_bytes() == original
    result = prepare_studio_document(cold.root)
    assert result['preserved_existing_document'] is True
    assert cold.snapshot()['sources'] == snapshot['sources']
    assert json.loads(cold.read_bytes('plot_request.json'))['input'] == str(source)
    assert not source.exists()


@pytest.mark.parametrize('boundary', ['native', 'before-head'])
def test_initial_json_original_drift_cannot_enter_the_native_generation(prepared_request, monkeypatch, boundary):
    from sciplot_core.studio_core import veusz_document
    from sciplot_core.project_commands import ProjectCommands

    project, source, request = prepared_request
    store = project_store(project)
    before = store.snapshot(import_legacy=True)
    changed = b'deliberate later original version'
    if boundary == 'native':
        save = veusz_document._save_veusz_document_from_spec
        def drift(*args, **kwargs):
            result = save(*args, **kwargs)
            source.write_bytes(changed)
            return result
        monkeypatch.setattr(veusz_document, '_save_veusz_document_from_spec', drift)
    else:
        execute = ProjectCommands.execute
        def drift(self, *args, **kwargs):
            source.write_bytes(changed)
            return execute(self, *args, **kwargs)
        monkeypatch.setattr(ProjectCommands, 'execute', drift)
    with pytest.raises(ValueError, match='changed'):
        prepare_studio_document(request)
    assert source.read_bytes() == changed
    assert store.snapshot()['generation'] == before['generation']
    assert not (project / 'studio/document.vsz').exists()


@pytest.mark.parametrize('problem', ['missing', 'alias'])
def test_initial_json_original_missing_or_aliased_is_rejected_before_native(prepared_request, monkeypatch, tmp_path, problem):
    from sciplot_core.studio_core import veusz_document

    project, source, request = prepared_request
    store = project_store(project)
    before = store.snapshot(import_legacy=True)
    if problem == 'alias':
        target = tmp_path / 'unselected.csv'
        source.rename(target)
        source.symlink_to(target)
    else:
        source.unlink()
    monkeypatch.setattr(veusz_document, '_save_veusz_document_from_spec', lambda *_a, **_k: pytest.fail('No native preparation for a missing/aliased original.'))
    with pytest.raises((ValueError, OSError)):
        prepare_studio_document(request)
    assert store.snapshot()['generation'] == before['generation']
    assert not (project / 'studio/document.vsz').exists()


@pytest.mark.parametrize('problem', ['foreign-same-bytes', 'wrong-hash'])
def test_initial_ledger_is_not_permission_to_read_or_claim_another_original(prepared_request, monkeypatch, tmp_path, problem):
    from sciplot_core.studio_core import preparation_commands as commands
    from sciplot_core.studio_core import preparation_original_sources as captures

    project, source, request = prepared_request
    store = project_store(project)
    before = store.snapshot(import_legacy=True)
    foreign = tmp_path / 'foreign' / source.name
    foreign.parent.mkdir()
    foreign.write_bytes(source.read_bytes())
    prepare = commands.prepare_studio_candidate
    def tamper(candidate, **kwargs):
        result = prepare(candidate, **kwargs)
        payload = json.loads(candidate.read_member('plot_request.json').data)
        record = payload['transform_ledger']['steps'][0]['input_artifacts'][0]
        record['path' if problem == 'foreign-same-bytes' else 'sha256'] = str(foreign) if problem == 'foreign-same-bytes' else 'a' * 64
        candidate.write_request(payload)
        return result
    observe = captures._physical_file_snapshot
    def confined(path, **kwargs):
        assert path != foreign, 'Ledger text must not cause even a read of the unselected neighbor.'
        return observe(path, **kwargs)
    monkeypatch.setattr(commands, 'prepare_studio_candidate', tamper)
    monkeypatch.setattr(captures, '_physical_file_snapshot', confined)
    with pytest.raises(ValueError, match='authorized observation'):
        prepare_studio_document(request)
    assert store.snapshot()['generation'] == before['generation']
    assert not (project / 'studio/document.vsz').exists()


def directory_request(prepared_request, tmp_path):
    project, _source, request_path = prepared_request
    directory = tmp_path / 'frequency'
    directory.mkdir()
    for sample, value in [('A', 100), ('B', 200)]:
        (directory / f'{sample}.csv').write_text(
            f'Angular Frequency,Storage Modulus\nrad/s,Pa\n1,{value}\n10,{value + 20}\n100,{value + 40}\n')
    (directory / 'unused.md').write_bytes(b'Unplotted original member.\n')
    (directory / 'empty').mkdir()
    (directory / 'A').mkdir()
    (directory / 'A/unused.md').write_bytes(b'Nested unplotted original member.\n')
    request = json.loads(request_path.read_bytes())
    request.update(input=str(directory), rule_id='rheology_frequency_sweep', template='point_line')
    request_path.write_text(json.dumps(request))
    return project, directory, request_path


def test_initial_directory_captures_unused_members_and_complete_cold_tree(prepared_request, tmp_path):
    from sciplot_core.project_store import FileProjectStore
    from sciplot_core.studio_core.preparation_source_runtime import current_preparation_runtime
    from sciplot_core.foundation.source_locations import resolve_source_path

    project, directory, request_path = directory_request(prepared_request, tmp_path)
    result = prepare_studio_document(request_path)
    store = project_store(project)
    snapshot = store.snapshot()
    record = store.query(result['project_command']['command_id'])
    assert set(record['source_tree_origins'][str(directory)]['members']) == {'A.csv', 'B.csv', 'unused.md', 'empty', 'A', 'A/unused.md'}
    inventory = {name: (directory / name).read_bytes() for name in ['A.csv', 'B.csv', 'unused.md', 'A/unused.md']}
    for name, data in inventory.items():
        owners = [identity for identity, versions in snapshot['sources'].items()
                  if versions.get(hashlib.sha256(data).hexdigest(), {}).get('locator') == str(directory / name)]
        assert len(owners) == 1
    cold = FileProjectStore.import_bundle(store.export_bundle(tmp_path / 'bundle'), tmp_path / 'cold')
    directory.rename(tmp_path / 'frequency-offline')
    with current_preparation_runtime(cold, cold.snapshot()):
        actual = resolve_source_path(directory)
        assert (actual / 'empty').is_dir()
        assert {name: (actual / name).read_bytes() for name in inventory} == inventory
    prepare_studio_document(cold.root, regenerate_generated=True)
    assert json.loads(cold.read_bytes('plot_request.json'))['input'] == str(directory)
    assert not directory.exists()
    prepare_studio_document(cold.root)


@pytest.mark.parametrize('change', ['unused', 'phantom', 'empty', 'mode'])
def test_original_tree_change_before_head_cannot_publish_a_partial_capture(prepared_request, monkeypatch, tmp_path, change):
    from sciplot_core.project_store import state

    project, source, request = directory_request(prepared_request, tmp_path)
    store = project_store(project)
    before = store.snapshot(import_legacy=True)
    def boundary(name):
        if name != 'before_head':
            return
        if change == 'unused':
            (source / 'unused.md').write_bytes(b'Changed unused original')
        elif change == 'phantom':
            (source / 'new.md').write_bytes(b'Uncaptured original member')
        elif change == 'empty':
            (source / 'empty').rmdir()
        else:
            (source / 'A.csv').chmod(0o600)
    monkeypatch.setattr(state, 'boundary', boundary)
    with pytest.raises(ValueError, match='tree changed|source tree changed'):
        prepare_studio_document(request)
    assert store.snapshot()['generation'] == before['generation']
    assert not (project / 'studio/document.vsz').exists()


def test_original_capture_rechecks_permissions_after_command_admission(prepared_request, monkeypatch):
    from sciplot_core.project_commands import ProjectCommands

    project, source, request = prepared_request
    store = project_store(project)
    before = store.snapshot(import_legacy=True)
    execute = ProjectCommands.execute
    def changed(self, *args, **kwargs):
        source.chmod(0o600)
        return execute(self, *args, **kwargs)
    monkeypatch.setattr(ProjectCommands, 'execute', changed)
    with pytest.raises(ValueError, match='changed'):
        prepare_studio_document(request)
    assert store.snapshot()['generation'] == before['generation']
    assert not (project / 'studio/document.vsz').exists()


def test_initial_source_cannot_choose_between_registered_uuids(prepared_request):
    from sciplot_core.project_commands import PreparedSource, ProjectCommand, ProjectCommands, ProjectMutation
    from sciplot_core.project_store.incoming_sources import SourceExpectation
    from sciplot_core.project_store.runtime import incoming_source_runtime

    project, source, request = prepared_request
    store = project_store(project)
    before = store.snapshot(import_legacy=True)
    digest = file_sha256(source)
    command = ProjectCommand.create('semantic_record', 'ambiguous-source-identities', project_id=before['project_id'],
        expected_generation=before['generation'], read_set={}, write_set=[], request={})
    ProjectCommands(store).execute(command, lambda: ProjectMutation({}, {}, prepared_sources=tuple(
        PreparedSource(identity * 32, str(source), digest, source.read_bytes(), mode=source.stat().st_mode & 0o777)
        for identity in ['a', 'b'])))
    current = store.snapshot()
    with pytest.raises(ValueError, match='unique registered source identity'):
        with incoming_source_runtime(store, [SourceExpectation(str(source), 'a' * 32, digest)]):
            prepare_studio_document(request)
    from sciplot_core.studio_core.preparation_original_sources import source_identity_for_locator
    with pytest.raises(ValueError, match='ambiguous'):
        source_identity_for_locator(current, str(source))
    assert store.snapshot()['generation'] == current['generation']
    assert not (project / 'studio/document.vsz').exists()


def test_initial_native_binding_carries_the_verified_original_byte_version(prepared_request, monkeypatch):
    from sciplot_core.plot_backends import veusz_import
    from sciplot_core.studio_core.project_query import inspect_project

    project, source, request = prepared_request
    prepare_studio_document(request)
    def inspect(*args, **kwargs):
        query = inspect_project(*args, **{**kwargs, 'native': False})
        query['selected_figure']['objects'] = {}
        return query
    monkeypatch.setattr(veusz_import, 'inspect_project', inspect)
    monkeypatch.setattr(veusz_import, '_presentation', lambda *_args: ({}, {}))
    monkeypatch.setattr(veusz_import, 'audit_edited_document', lambda *_args: {'status': 'passed', 'native_port_double': True})
    document, binding = veusz_import.import_project(project, None, 'initial-json-original')
    assert document['scientific_hash']
    assert binding['files'][str(source)] == file_sha256(source)
    assert binding['fingerprint']['files'][str(source)] == file_sha256(source)
    assert binding['source_trees'][str(source)] != file_sha256(source)
    # This is a binding witness, not a rewrite of the imported scientific model.
    assert str(source) not in {item['path'] for item in document['scientific']['data_sources']}
