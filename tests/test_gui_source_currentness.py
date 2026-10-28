"""Source currentness follows an admitted clone, never a preserved old locator."""
import hashlib
import json

import pytest

from sciplot_core.project_store import FileProjectStore
from test_initial_request_source_capture import prepared_request as prepared_request
from sciplot_gui.studio_project.status_adapter import build_studio_project_status


class Document:
    changeset = 1
    def isModified(self):
        return False


def legacy_record(directory):
    digest = hashlib.sha256()
    size = 0
    count = 0
    for path in sorted(directory.rglob('*')):
        if path.is_file():
            data = path.read_bytes()
            digest.update(path.relative_to(directory).as_posix().encode())
            digest.update(hashlib.sha256(data).hexdigest().encode())
            size += len(data)
            count += 1
    return {'kind': 'directory', 'size_bytes': size, 'member_count': count, 'sha256': digest.hexdigest()}


def clone(tmp_path):
    original = tmp_path / 'original'
    (original / 'source').mkdir(parents=True)
    (original / 'source/data.csv').write_bytes(b'x,y\n1,2\n')
    (original / 'studio').mkdir()
    (original / 'studio/document.vsz').write_bytes(b'Synthetic saved document, no native execution.')
    request = {'input': str(original / 'source')}
    (original / 'plot_request.json').write_text(json.dumps(request))
    run = original / 'runs/studio_001'
    run.mkdir(parents=True)
    (run / 'request_snapshot.json').write_text(json.dumps(request))
    (run / 'manifest.json').write_text(json.dumps({'request': request, 'transform_ledger': {'steps': [
        {'input_artifacts': [{'path': str(original / 'source'), **legacy_record(original / 'source')}]}]}}))
    store = FileProjectStore(original)
    store.snapshot(import_legacy=True)
    copied = FileProjectStore.import_bundle(store.export_bundle(tmp_path / 'bundle'), tmp_path / 'clone')
    return original, copied.root


@pytest.mark.parametrize('change', [False, True])
def test_clone_status_uses_current_physical_source_and_preserved_lineage_identity(tmp_path, change):
    original, copied = clone(tmp_path)
    source = original / 'source/data.csv'
    before = source.read_bytes(), source.stat().st_mode, source.stat().st_mtime_ns
    if change:
        (copied / 'source/data.csv').write_bytes(b'x,y\n1,9\n')
    status = build_studio_project_status(document_path=copied / 'studio/document.vsz', document=Document(),
        project_dir=copied, request_path=copied / 'plot_request.json', audit_source=True,
        _figure_set_scope_resolver=lambda **_kw: (None, 'not_applicable'))
    assert status['source']['audit_status'] == ('changed_since_last_run' if change else 'matches_last_run_lineage')
    assert status['source']['path'] == str(copied / 'source')
    assert status['source']['identity_path'] == str(original / 'source')
    assert status['source']['sha256'] == legacy_record(copied / 'source')['sha256']
    assert (source.read_bytes(), source.stat().st_mode, source.stat().st_mtime_ns) == before


def status(project, *, audit=True):
    return build_studio_project_status(document_path=project / 'studio/document.vsz', document=Document(),
        project_dir=project, request_path=project / 'plot_request.json', audit_source=audit,
        _figure_set_scope_resolver=lambda **_kw: (None, 'not_applicable'))


def test_plain_refresh_does_not_hash_registered_source_contents(tmp_path, monkeypatch):
    from sciplot_core.studio_core import source_content_observation as core
    _original, copied = clone(tmp_path)
    monkeypatch.setattr(core, '_files', lambda *_a, **_k: pytest.fail('Ordinary refresh must not hash the source tree.'))
    monkeypatch.setattr(core, 'read_file', lambda *_a, **_k: pytest.fail('Ordinary refresh must not read source contents.'))
    source = status(copied, audit=False)['source']
    assert source['exists'] is True and source['audit_status'] == 'not_computed'
    assert 'sha256' not in source and source['path'] == str(copied / 'source')


@pytest.mark.parametrize('change', ['extra', 'empty', 'alias', 'mode', 'missing'])
def test_source_namespace_refusals_do_not_retry_original_or_read_unknown_bytes(tmp_path, monkeypatch, change):
    from sciplot_core.project_store import source_tree_io
    original, copied = clone(tmp_path)
    target = copied / 'source/data.csv'
    before = (original / 'source/data.csv').read_bytes()
    if change == 'extra':
        (copied / 'source/unknown.csv').write_bytes(b'No source grant.')
    elif change == 'empty':
        (copied / 'source/unknown').mkdir()
    elif change == 'alias':
        target.unlink()
        target.symlink_to(original / 'source/data.csv')
    elif change == 'mode':
        target.chmod(0o600 if target.stat().st_mode & 0o777 != 0o600 else 0o644)
    else:
        target.unlink()
    read = source_tree_io.read_file
    def confined(fd, name, **kwargs):
        assert name != 'unknown.csv', 'Unknown bytes are not observation input.'
        return read(fd, name, **kwargs)
    monkeypatch.setattr(source_tree_io, 'read_file', confined)
    source = status(copied)['source']
    assert source['audit_status'] == 'audit_failed'
    assert source['path'] is None and source['identity_path'] == str(original / 'source')
    assert (original / 'source/data.csv').read_bytes() == before


def test_old_project_offline_does_not_break_clone_identity_match(tmp_path):
    original, copied = clone(tmp_path)
    old = str(original / 'source')
    original.rename(tmp_path / 'original-offline')
    source = status(copied)['source']
    assert source['audit_status'] == 'matches_last_run_lineage'
    assert source['identity_path'] == old and source['path'] == str(copied / 'source')


def test_source_observer_cannot_read_another_registered_project_artifact(tmp_path, monkeypatch):
    from sciplot_core.studio import observe_studio_source_content
    from sciplot_core.studio_core import source_content_observation as core
    _original, copied = clone(tmp_path)
    monkeypatch.setattr(core, '_record', lambda *_a, **_k: pytest.fail('Foreign source role reached contents.'))
    with pytest.raises(ValueError, match='canonical request input'):
        observe_studio_source_content(copied / 'studio/document.vsz', project_dir=copied,
            request_path=copied / 'plot_request.json', audit_source=True)


def test_invalid_canonical_request_refuses_before_gui_mapping_or_source_io(tmp_path, monkeypatch):
    from sciplot_gui.studio_project_status import builder
    _original, copied = clone(tmp_path)
    (copied / 'plot_request.json').write_bytes(b'{"input":"/unadmitted/new-source"}')
    monkeypatch.setattr(builder, '_mapping_status', lambda *_a, **_k: pytest.fail('An unregistered request reached mapping IO.'))
    with pytest.raises(ValueError, match='registered generation'):
        status(copied)


def test_status_observation_does_not_materialize_or_rewrite_project_members(tmp_path):
    from test_project_query_readonly_sources import inventory
    original, copied = clone(tmp_path)
    before = inventory(tmp_path)
    assert status(copied)['source']['audit_status'] == 'matches_last_run_lineage'
    assert inventory(tmp_path) == before


@pytest.mark.parametrize('change', ['replace_root', 'late_neighbour'])
def test_post_observation_namespace_race_cannot_certify_a_current_path(tmp_path, monkeypatch, change):
    from sciplot_core.studio_core import source_content_observation as core
    _original, copied = clone(tmp_path)
    observe = core._files
    def race(*args, **kwargs):
        result = observe(*args, **kwargs)
        if change == 'replace_root':
            (copied / 'source').rename(copied / 'source-old')
            (copied / 'source').mkdir()
            (copied / 'source/data.csv').write_bytes(b'x,y\n1,2\n')
        else:
            (copied / 'source/new.csv').write_bytes(b'Unknown late bytes.')
        return result
    monkeypatch.setattr(core, '_files', race)
    assert status(copied)['source']['audit_status'] == 'audit_failed'


def test_exact_registered_file_retains_legacy_record_shape_in_clone(tmp_path):
    from sciplot_core.studio import observe_studio_source_content
    original, copied = clone(tmp_path)
    result = observe_studio_source_content(original / 'source/data.csv', project_dir=copied,
        request_path=copied / 'plot_request.json', audit_source=True)
    assert result['content'] == {'kind': 'file', 'size_bytes': 8,
        'sha256': hashlib.sha256(b'x,y\n1,2\n').hexdigest()}
    assert result['path'] == str(copied / 'source/data.csv')
    assert result['identity_path'] == str(original / 'source/data.csv')


def test_finite_archive_cap_does_not_grant_its_source_parent(tmp_path, monkeypatch):
    from sciplot_core.project_store import ResourceRoot
    from sciplot_core.studio import observe_studio_source_content
    from sciplot_core.studio_core import source_content_observation as core
    project = tmp_path / 'project'
    project.mkdir()
    (project / 'plot_request.json').write_text(json.dumps({'input': str(tmp_path)}))
    (tmp_path / 'project.zip').write_bytes(b'finite archive only')
    store = FileProjectStore(project, locations={'snapshot': ResourceRoot(tmp_path, ('project.zip',))})
    store.snapshot(import_legacy=True)
    monkeypatch.setattr(core, '_record', lambda *_a, **_k: pytest.fail('Finite parent reached source contents.'))
    with pytest.raises(ValueError, match='finite-cap parent'):
        observe_studio_source_content(tmp_path, project_dir=project,
            request_path=project / 'plot_request.json', audit_source=True)


def test_managed_clone_mapping_cannot_read_old_origin_before_source_callback(tmp_path, monkeypatch):
    from sciplot_core.data_mapping import execution_inputs
    from sciplot_core.foundation.source_locations import selected_source_resolver
    from sciplot_core.studio import resolve_studio_mapping_application
    from test_mapping_execution_portability import confirmed_project
    from test_project_query_readonly_sources import inventory

    origin, project, store, request, _execution = confirmed_project(tmp_path, monkeypatch)
    copied = FileProjectStore.import_bundle(store.export_bundle(tmp_path / 'official-bundle'), tmp_path / 'portable')
    before = inventory(tmp_path)
    read = execution_inputs._read
    def confined(*args, **kwargs):
        selected = selected_source_resolver()
        assert selected is not None and selected.store.root == copied.root, 'Known clone mapping used ambient old-origin IO.'
        result = read(*args, **kwargs)
        assert not result[1].is_relative_to(origin), 'Current mapping cannot consume old-origin bytes.'
        return result
    monkeypatch.setattr(execution_inputs, '_read', confined)
    with pytest.raises(ValueError, match='historical evidence'):
        resolve_studio_mapping_application(request, project_dir=copied.root, request_path=copied.root / 'plot_request.json')
    gui = status(copied.root)
    assert gui['mapping']['status'] == 'not_evaluated'
    assert gui['source']['audit_status'] == 'not_currently_observed'
    assert gui['provenance']['full_project_evidence_current'] is False
    assert inventory(tmp_path) == before
    assert selected_source_resolver() is None
    assert (project / 'plot_request.json').is_file()


def test_status_builder_cannot_silently_switch_generations_after_precheck(tmp_path, monkeypatch):
    from sciplot_core.project_commands import ProjectCommand, ProjectCommands, ProjectMutation
    from sciplot_gui.studio_project import status_adapter
    _original, copied = clone(tmp_path)
    build = status_adapter._build_studio_project_status
    def advance(**kwargs):
        store = FileProjectStore(copied)
        before = store.snapshot()
        command = ProjectCommand.create('figure_set', 'concurrent-legitimate-metadata', project_id=before['project_id'],
            expected_generation=before['generation'], read_set={'note.txt': None}, write_set=['note.txt'], request={})
        ProjectCommands(store).execute(command, lambda: ProjectMutation({'note.txt': b'legitimate next generation'}, {}))
        return build(**kwargs)
    monkeypatch.setattr(status_adapter, '_build_studio_project_status', advance)
    result = status(copied)
    assert result['source']['audit_status'] == 'audit_failed'
    assert 'revision changed' in result['source']['audit_error']


def test_cold_mapping_status_is_not_evaluated_instead_of_invalid(tmp_path, monkeypatch):
    from sciplot_core.studio import resolve_studio_mapping_application
    from sciplot_gui.studio_project_status.mapping_status import _mapping_status
    from test_mapping_execution_portability import confirmed_project
    _origin, _project, store, request, _execution = confirmed_project(tmp_path, monkeypatch)
    copied = FileProjectStore.import_bundle(store.export_bundle(tmp_path / 'bundle-cold'), tmp_path / 'cold')
    mapping, _effective = _mapping_status(request, request_path=copied.root / 'plot_request.json', latest_run={},
        request_error=None, artifact_qa_current=True, audit_mapping=True,
        _mapping_resolver=lambda payload: resolve_studio_mapping_application(payload, project_dir=copied.root,
            request_path=copied.root / 'plot_request.json'))
    assert mapping['status'] == 'not_evaluated'
    assert mapping['verification_base_valid'] is False and mapping['evidence_current'] is False


@pytest.mark.parametrize('cold', [False, True])
def test_current_external_file_is_observed_live_or_explicitly_unknown_when_imported(tmp_path, monkeypatch, cold):
    from sciplot_core.project_commands import PreparedSource, ProjectCommand, ProjectCommands, ProjectMutation
    from sciplot_core.studio import observe_studio_source_content
    from sciplot_core.studio_core import source_content_observation as core
    from test_project_query_readonly_sources import inventory
    raw = tmp_path / 'selected.csv'
    raw.write_bytes(b'x,y\n1,2\n')
    project = tmp_path / 'project'
    project.mkdir()
    digest = hashlib.sha256(raw.read_bytes()).hexdigest()
    request = {'input': str(raw), 'transform_ledger': {'steps': [{'input_artifacts': [
        {'kind': 'file', 'path': str(raw), 'sha256': digest}]}]}}
    (project / 'plot_request.json').write_text(json.dumps(request))
    store = FileProjectStore(project)
    before = store.snapshot(import_legacy=True)
    command = ProjectCommand.create('figure_set', 'freeze-selected-file', project_id=before['project_id'],
        expected_generation=before['generation'], read_set={}, write_set=[], request={})
    ProjectCommands(store).execute(command, lambda: ProjectMutation({}, {}, prepared_sources=(
        PreparedSource('f' * 32, str(raw), digest, raw.read_bytes(), mode=raw.stat().st_mode & 0o777),)))
    if cold:
        store = FileProjectStore.import_bundle(store.export_bundle(tmp_path / 'bundle-file'), tmp_path / 'cold-file')
        monkeypatch.setattr(core, '_record', lambda *_a, **_k: pytest.fail('A sealed version cannot be read as a live old origin.'))
    inventory_before = inventory(tmp_path)
    result = observe_studio_source_content(raw, project_dir=store.root, request_path=store.root / 'plot_request.json', audit_source=True)
    if cold:
        assert result['sealed'] is True and result['status'] == 'not_observed'
        assert result['exists'] is False and result['path'] is None
    else:
        assert result['content'] == {'kind': 'file', 'size_bytes': 8, 'sha256': digest}
        assert result['path'] == str(raw)
    assert inventory(tmp_path) == inventory_before


@pytest.mark.parametrize('cold', [False, True, 'root_mode', 'empty_mode', 'missing_empty'])
def test_complete_external_tree_author_keeps_unused_members_and_cold_unknown(prepared_request, tmp_path, cold):
    from sciplot_core.studio import prepare_studio_document, observe_studio_source_content
    from sciplot_core.project_host_factory import project_store
    from test_project_query_readonly_sources import inventory
    project, raw, request_path = prepared_request
    selected = tmp_path / 'complete-selected'
    selected.mkdir()
    (selected / 'UVvis.csv').write_bytes(raw.read_bytes())
    (selected / 'unused.md').write_bytes(b'Not plotted, still selected.')
    (selected / 'empty').mkdir()
    request = json.loads(request_path.read_bytes())
    request['input'] = str(selected)
    request_path.write_text(json.dumps(request))
    prepare_studio_document(request_path)
    store = project_store(project)
    if cold is True:
        store = FileProjectStore.import_bundle(store.export_bundle(tmp_path / 'bundle-tree'), tmp_path / 'cold-tree')
    if isinstance(cold, str):
        target = selected if cold == 'root_mode' else selected / 'empty'
        if cold == 'missing_empty':
            target.rmdir()
        else:
            target.chmod(0o700 if target.stat().st_mode & 0o777 != 0o700 else 0o755)
        before = inventory(tmp_path)
        with pytest.raises(ValueError, match='permissions|shape'):
            observe_studio_source_content(selected, project_dir=store.root, request_path=store.root / 'plot_request.json', audit_source=True)
        assert inventory(tmp_path) == before
        return
    before = inventory(tmp_path)
    result = observe_studio_source_content(selected, project_dir=store.root, request_path=store.root / 'plot_request.json', audit_source=True)
    if cold:
        assert result['sealed'] is True and result['status'] == 'not_observed' and result['path'] is None
    else:
        assert result['content']['member_count'] == 2
        assert result['content']['sha256'] == legacy_record(selected)['sha256']
    assert inventory(tmp_path) == before


def test_live_mapping_observation_reuses_full_numeric_contract_without_views(tmp_path, monkeypatch):
    from sciplot_core.studio import resolve_studio_mapping_application
    from test_mapping_execution_portability import confirmed_project
    from test_project_query_readonly_sources import inventory
    _origin, project, _store, request, execution = confirmed_project(tmp_path, monkeypatch)
    before = inventory(tmp_path)
    effective, application = resolve_studio_mapping_application(request, project_dir=project,
        request_path=project / 'plot_request.json')
    assert application['status'] == 'validated' and application['outputs_verified'] is True
    assert effective['input'] == execution['effective_input']
    assert inventory(tmp_path) == before
