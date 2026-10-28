"""Explicit originals, registered roots and mapping namespaces keep distinct roles."""
import json
from pathlib import Path

import pytest

from sciplot_core.project_host_factory import project_store
from sciplot_core.studio import prepare_studio_document
from test_initial_request_source_capture import prepared_request as prepared_request


@pytest.mark.parametrize('entry', ['raw_file', 'raw_directory', 'request_directory', 'selected'])
def test_creation_frontdoors_capture_registered_original_directory_before_transform(prepared_request, tmp_path, entry):
    project, source, request_path = prepared_request
    original = source.read_bytes()
    if entry == 'request_directory':
        directory = project / 'source'
        directory.mkdir()
        (directory / 'UVvis.csv').write_bytes(original)
        (directory / 'unused.md').write_bytes(b'Keep this original, even though it is not plotted.\n')
        request = json.loads(request_path.read_bytes())
        request['input'] = str(directory)
        request_path.write_text(json.dumps(request))
        result = prepare_studio_document(request_path)
    elif entry == 'selected':
        from sciplot_core.plan_preview import build_plan_preview
        from sciplot_core.studio_core.project_creation import create_project

        plan = dict(build_plan_preview(source, request={'rule_id': 'uvvis_spectrum', 'template': 'curve'}))
        assert plan['status'] == 'planned', plan
        result = create_project(source, expected_plan=plan, output_dir=tmp_path / 'visible', publish=False)
    else:
        target = source
        if entry == 'raw_directory':
            target = tmp_path / 'incoming'
            target.mkdir()
            (target / source.name).write_bytes(original)
        result = prepare_studio_document(target, output_root=tmp_path / 'projects',
            delivery_root=tmp_path / 'visible', rule_id='uvvis_spectrum', template='curve')
    root = Path(result['project_dir'])
    store = project_store(root, with_snapshot=True)
    snapshot = store.snapshot()
    original_members = {name: fact for name, fact in snapshot['files'].items() if name.startswith('source/')}
    assert original_members
    for name, fact in original_members.items():
        matches = [(identity, version) for identity, versions in snapshot['sources'].items() for version, record in versions.items()
                   if record.get('locator') == str(root / name) and record.get('sha256') == fact['sha256']]
        assert len(matches) == 1
        assert snapshot['sources'][matches[0][0]][matches[0][1]].get('produced_resource') is None
    assert source.read_bytes() == original
    assert any(record.get('produced_resource') for versions in snapshot['sources'].values() for record in versions.values())
    from sciplot_core.studio_core.project_query import inspect_project
    assert inspect_project(root, native=False)['source']['current'] is True
    native_bytes = (root / 'studio/document.vsz').read_bytes()
    reopened = prepare_studio_document(root)
    assert reopened['preserved_existing_document'] is True
    assert (root / 'studio/document.vsz').read_bytes() == native_bytes


def mapped_inputs(tmp_path, *, verification='full'):
    from sciplot_core.data_mapping import load_data_mapping_execution
    from sciplot_core.data_mapping.execution_inputs import mapping_input_reads
    from test_mapping_execution_directories import directory_execution

    _origin, request, execution = directory_execution(tmp_path)
    reference = request['data_mapping_execution']
    if verification == 'v1':
        confirmation = Path(execution['confirmation'])
        payload = json.loads(confirmation.read_bytes())
        payload = {key: value for key, value in payload.items() if key not in {'source_root', 'request_path', 'output_root'}}
        payload['version'] = 1
        confirmation.write_text(json.dumps(payload))
    with mapping_input_reads(reference) as readset:
        result = load_data_mapping_execution(reference, verify=verification not in {'header', 'seal'})
        if verification == 'seal':
            readset.seal()
    return request, execution, readset, result


def test_multifile_mapping_keeps_namespace_ledger_without_granting_parent_reads(tmp_path, monkeypatch):
    from sciplot_core.project_commands import ProjectCommand, ProjectCommands, ProjectMutation
    from sciplot_core.studio_core import preparation_original_sources as inputs

    request, execution, readset, _verified = mapped_inputs(tmp_path)
    original_ledger = Path(execution['transform_ledger']).read_bytes()
    ledger_request = {'transform_ledger': json.loads(original_ledger)}
    source_root = Path(execution['source_root'])
    (source_root / 'unselected.md').write_bytes(b'Not a selected mapping input.\n')
    observe = inputs.observe
    def confined(locator, **kwargs):
        assert Path(locator) != source_root, 'Mapping namespace metadata cannot authorize a directory read.'
        return observe(locator, **kwargs)
    monkeypatch.setattr(inputs, 'observe', confined)
    project = tmp_path / 'project'
    project.mkdir()
    (project / 'plot_request.json').write_text(json.dumps(request))
    store = project_store(project)
    before = store.snapshot(import_legacy=True)
    sources = readset.prepared_sources(before)
    inputs.verify_original_ledger(ledger_request, (), prepared_sources=sources, mapping_inputs=[readset])
    command = ProjectCommand.create('figure_set', 'verified-mapping-closed-inputs', project_id=before['project_id'],
        expected_generation=before['generation'], read_set={}, write_set=[], request={'execution': readset.execution},
        source_trees=tuple(readset.trees.values()))
    record = ProjectCommands(store).execute(command, lambda: ProjectMutation({}, {}, prepared_sources=sources,
        artifacts={'ledger.json': original_ledger}))
    assert str(source_root) not in record['source_tree_origins']
    assert str(Path(execution['data_dir'])) in record['source_tree_origins']
    assert Path(record['artifact_paths']['ledger.json']).read_bytes() == original_ledger
    assert not any(entry.get('locator') == str(source_root / 'unselected.md')
                   for versions in store.snapshot()['sources'].values() for entry in versions.values())


@pytest.mark.parametrize('verification', ['header', 'seal', 'v1'])
def test_metadata_only_or_v1_mapping_cannot_authorize_namespace_step(tmp_path, verification):
    from sciplot_core.studio_core.preparation_original_sources import verify_original_ledger

    _request, execution, readset, verified = mapped_inputs(tmp_path, verification=verification)
    assert readset.numeric_inputs_sha256 is None
    if verification == 'v1':
        assert verified['confirmation_schema_version'] == 1 and verified['handoff_allowed'] is False
    ledger = {'transform_ledger': json.loads(Path(execution['transform_ledger']).read_bytes())}
    with pytest.raises(ValueError, match='directory was not selected'):
        verify_original_ledger(ledger, (), prepared_sources=(), mapping_inputs=[readset])


@pytest.mark.parametrize('change', ['kind', 'path', 'hash', 'extra', 'step', 'after_verify'])
def test_verified_mapping_never_adopts_changed_or_extra_namespace_claims(tmp_path, change):
    from sciplot_core.studio_core.preparation_original_sources import verify_original_ledger

    _request, execution, readset, _verified = mapped_inputs(tmp_path)
    ledger = {'transform_ledger': json.loads(Path(execution['transform_ledger']).read_bytes())}
    step = ledger['transform_ledger']['steps'][0]
    artifact = step['input_artifacts'][0]
    if change == 'kind':
        artifact['kind'] = 'file'
    elif change == 'path':
        artifact['path'] = str(tmp_path / 'same-name-foreign')
    elif change == 'hash':
        artifact['sha256'] = 'f' * 64
    elif change == 'extra':
        step['input_artifacts'].append({**artifact, 'path': str(tmp_path / 'foreign')})
    elif change == 'step':
        step['operation'] = 'another_scientific_method'
    else:
        target = Path(execution['transform_ledger'])
        target.write_bytes(target.read_bytes() + b' ')
    with pytest.raises(ValueError):
        verify_original_ledger(ledger, (), prepared_sources=(), mapping_inputs=[readset])


@pytest.mark.parametrize('change', ['unknown_file', 'empty_directory', 'missing', 'mode', 'alias'])
def test_registered_input_namespace_refuses_unadmitted_shape_before_content_io(tmp_path, monkeypatch, change):
    from sciplot_core.project_store import FileProjectStore, source_tree_io
    from sciplot_core.studio_core.preparation_candidate import studio_preparation_candidate
    from sciplot_core.studio_core.preparation_original_sources import capture_original_input

    root = tmp_path / 'project'
    (root / 'source').mkdir(parents=True)
    (root / 'source/data.csv').write_bytes(b'x,y\n1,2\n')
    (root / 'plot_request.json').write_text(json.dumps({'input': str(root / 'source')}))
    store = FileProjectStore(root)
    before = store.snapshot(import_legacy=True)
    with studio_preparation_candidate(store, snapshot=before) as candidate:
        source = candidate.project_dir / 'source'
        member = source / 'data.csv'
        if change == 'unknown_file':
            (source / 'unregistered.csv').write_bytes(b'Not admitted even though its parent is registered.')
        elif change == 'empty_directory':
            (source / 'unknown_empty').mkdir()
        elif change == 'missing':
            member.unlink()
        elif change == 'mode':
            member.chmod(0o600 if member.stat().st_mode & 0o777 != 0o600 else 0o644)
        else:
            member.unlink()
            member.symlink_to(root / 'source/data.csv')
        monkeypatch.setattr(source_tree_io, 'read_file', lambda *_a, **_k: pytest.fail('Unadmitted namespace reached content IO.'))
        with pytest.raises((ValueError, OSError)):
            capture_original_input({'input': str(root / 'source')}, base_dir=candidate.project_dir, snapshot=before)
    assert store.snapshot()['generation'] == before['generation']


def test_mapping_numeric_stamp_does_not_follow_mutable_readset_versions(tmp_path):
    from dataclasses import replace
    from sciplot_core.studio_core.preparation_original_sources import verify_original_ledger

    _request, execution, readset, _verified = mapped_inputs(tmp_path)
    ledger = {'transform_ledger': json.loads(Path(execution['transform_ledger']).read_bytes())}
    raw = Path(execution['source_root']) / 'one.csv'
    data = raw.read_bytes().replace(b'400,3', b'400,9')
    raw.write_bytes(data)
    readset.files[str(raw)] = replace(readset.files[str(raw)], data=data)
    with pytest.raises(ValueError):
        verify_original_ledger(ledger, (), prepared_sources=(), mapping_inputs=[readset])


@pytest.mark.parametrize('kind', ['new_private', 'foreign_store', 'finite_parent', 'produced_directory'])
def test_unproven_or_derived_roots_never_become_original_directory_grants(tmp_path, monkeypatch, kind):
    from sciplot_core.project_commands import PreparedFile, PreparedSource, ProjectCommand, ProjectCommands, ProjectMutation
    from sciplot_core.project_store import FileProjectStore, ResourceRoot, source_tree_io
    from sciplot_core.studio_core.preparation_candidate import studio_preparation_candidate
    from sciplot_core.studio_core.preparation_original_sources import capture_original_input, verify_original_ledger

    root = tmp_path / 'project'
    root.mkdir()
    (root / 'plot_request.json').write_bytes(b'{}')
    cap = tmp_path / 'finite-inputs'
    cap.mkdir()
    (cap / 'known.csv').write_bytes(b'x,y\n1,2\n')
    (cap / 'ungranted.csv').write_bytes(b'No parent permission.')
    store = FileProjectStore(root, locations={'inputs': ResourceRoot(cap, ('known.csv',))} if kind == 'finite_parent' else None)
    before = store.snapshot(import_legacy=True)
    if kind == 'produced_directory':
        data = b'x,y\n1,2\n'
        import hashlib
        command = ProjectCommand.create('figure_set', 'derived-output', project_id=before['project_id'],
            expected_generation=before['generation'], read_set={'studio/processed/data.csv': None},
            write_set=['studio/processed/data.csv'], request={})
        ProjectCommands(store).execute(command, lambda: ProjectMutation({'studio/processed/data.csv': PreparedFile(data, 0o644)}, {},
            prepared_sources=(PreparedSource('d' * 32, str(root / 'studio/processed/data.csv'),
                hashlib.sha256(data).hexdigest(), data, mode=0o644, produced_resource='studio/processed/data.csv'),)))
        before = store.snapshot()
    with studio_preparation_candidate(store, snapshot=before) as candidate:
        if kind == 'new_private':
            candidate.write_member('source/new/unregistered.csv', b'x,y\n1,2\n')
            target = root / 'source/new'
        elif kind == 'foreign_store':
            target = tmp_path / 'foreign/.sciplot_store'
        elif kind == 'finite_parent':
            target = cap
        else:
            target = root / 'studio/processed'
        monkeypatch.setattr(source_tree_io, 'read_file', lambda *_a, **_k: pytest.fail('An unproven directory reached content IO.'))
        if kind == 'new_private':
            assert capture_original_input({'input': str(target)}, base_dir=candidate.project_dir, snapshot=before) is None
            with pytest.raises(ValueError, match='not selected'):
                verify_original_ledger({'transform_ledger': {'steps': [{'input_artifacts': [
                    {'kind': 'directory', 'path': str(target), 'sha256': 'a' * 64}]}]}}, (), prepared_sources=())
        else:
            with pytest.raises(ValueError):
                capture_original_input({'input': str(target)}, base_dir=candidate.project_dir, snapshot=before)
    assert store.snapshot()['generation'] == before['generation']


def test_membership_race_cannot_read_an_unregistered_neighbour(tmp_path, monkeypatch):
    from sciplot_core.project_store import FileProjectStore, source_tree_io
    from sciplot_core.studio_core.preparation_candidate import studio_preparation_candidate
    from sciplot_core.studio_core import preparation_original_sources as inputs

    root = tmp_path / 'project'
    (root / 'source').mkdir(parents=True)
    (root / 'source/data.csv').write_bytes(b'x,y\n1,2\n')
    (root / 'plot_request.json').write_bytes(b'{}')
    store = FileProjectStore(root)
    before = store.snapshot(import_legacy=True)
    with studio_preparation_candidate(store, snapshot=before) as candidate:
        census = inputs._require_registered_members
        def race(*args, **kwargs):
            census(*args, **kwargs)
            (candidate.project_dir / 'source/unregistered.csv').write_bytes(b'Outside the captured namespace.')
        read_file = source_tree_io.read_file
        def confined(fd, name, **kwargs):
            assert name != 'unregistered.csv', 'A metadata race must not grant contents of the new neighbour.'
            return read_file(fd, name, **kwargs)
        monkeypatch.setattr(inputs, '_require_registered_members', race)
        monkeypatch.setattr(source_tree_io, 'read_file', confined)
        with pytest.raises(ValueError, match='exact registered file capability'):
            inputs.capture_original_input({'input': str(root / 'source')}, base_dir=candidate.project_dir, snapshot=before)
    assert store.snapshot()['generation'] == before['generation']


@pytest.mark.parametrize('change', ['bytes', 'mode', 'unknown_member'])
def test_registered_original_change_after_private_audit_cannot_publish(prepared_request, monkeypatch, change):
    from sciplot_core.studio_core import preparation_commands as commands

    project, source, request_path = prepared_request
    directory = project / 'source'
    directory.mkdir()
    original = directory / source.name
    original.write_bytes(source.read_bytes())
    payload = json.loads(request_path.read_bytes())
    payload['input'] = str(directory)
    request_path.write_text(json.dumps(payload))
    store = project_store(project)
    before = store.snapshot(import_legacy=True)
    audit = commands.audit_studio_candidate
    def drift(*args, **kwargs):
        result = audit(*args, **kwargs)
        if change == 'bytes':
            original.write_bytes(b'An outside change after the private audit.')
        elif change == 'mode':
            original.chmod(0o600 if original.stat().st_mode & 0o777 != 0o600 else 0o644)
        else:
            (directory / 'unknown.csv').write_bytes(b'An unadmitted namespace member.')
        return result
    monkeypatch.setattr(commands, 'audit_studio_candidate', drift)
    with pytest.raises(ValueError):
        prepare_studio_document(request_path)
    assert store.snapshot()['generation'] == before['generation']
    assert not (project / 'studio/document.vsz').exists()
    if change == 'bytes':
        assert original.read_bytes() == b'An outside change after the private audit.'
    elif change == 'mode':
        assert original.stat().st_mode & 0o777 != before['files']['source/' + source.name]['mode']
    else:
        assert (directory / 'unknown.csv').read_bytes() == b'An unadmitted namespace member.'


def multifile_mapping_request(tmp_path, project, rule=None):
    """Real confirmation/execution only; rendering and audit remain the caller's."""
    from sciplot_core.data_mapping import create_data_mapping_confirmation, execute_data_mapping_proposal
    from sciplot_core.foundation.file_hashing import file_sha256
    from sciplot_core.mapping_contract import DataColumnMapping, DataMappingProposal, DataSourceReference

    request_path = project / 'plot_request.json'
    raw = tmp_path / 'frequency'
    raw.mkdir()
    for name, value in [('one', 100), ('two', 200)]:
        (raw / f'{name}.csv').write_text(f'Angular Frequency (rad/s),Storage Modulus (Pa)\n1,{value}\n10,{value + 20}\n')
    base = tmp_path / 'mapping-base.json'
    patch = {'template': 'point_line', 'rule_id': rule} if rule else {'template': 'curve'}
    base.write_text(json.dumps({'input': str(raw), **patch}))
    proposal = DataMappingProposal(proposal_id='frequency_sources', provider='external_task',
        base_request_sha256=file_sha256(base),
        sources=tuple(DataSourceReference(name, f'{name}.csv', file_sha256(raw / f'{name}.csv')) for name in ['one', 'two']),
        columns=tuple(column for name in ['one', 'two'] for column in [
            DataColumnMapping(name, 0, 'Angular Frequency (rad/s)', 'x', expected_header='Angular Frequency (rad/s)'),
            DataColumnMapping(name, 1, 'Storage Modulus (Pa)', 'y', expected_header='Storage Modulus (Pa)')]),
        sample_labels={'one': 'one', 'two': 'two'},
        request_patch=patch)
    confirmation = create_data_mapping_confirmation(proposal, source_root=raw, request_path=base,
        output_root=tmp_path / 'mapping', confirmed_by='Explicit generated frequency mapping')
    execution = execute_data_mapping_proposal(proposal, confirmation, source_root=raw, request_path=base,
        output_root=tmp_path / 'mapping')
    request = json.loads(Path(execution['request_seed']).read_bytes())
    request.update(output=str(project / 'runs/run_001'), delivery_output=str(tmp_path / 'visible'))
    request_path.write_text(json.dumps(request))
    ledger = json.loads(Path(execution['transform_ledger']).read_bytes())
    return raw, execution, ledger, request_path


@pytest.mark.parametrize('rule', [None, 'rheology_frequency_sweep'])
def test_multifile_mapping_public_owner_preserves_supported_and_refused_science(prepared_request, tmp_path, rule):
    project, _unused, _request_path = prepared_request
    raw, execution, ledger, request_path = multifile_mapping_request(tmp_path, project, rule)
    if rule is not None:
        # Confirmed generic-XY mapping into this specialized frequency
        # comparison adapter is outside the current table-mapping contract.
        # Preserve that exact-inventory guard; do not relax science for admission.
        from sciplot_core.studio_render.models import StudioPreparationBlocked
        with pytest.raises(StudioPreparationBlocked, match='outside the confirmed mapped output inventory'):
            prepare_studio_document(request_path)
        assert not (project / 'studio/document.vsz').exists()
        return
    prepared = prepare_studio_document(request_path)
    store = project_store(project)
    record = store.query(prepared['project_command']['command_id'])
    assert record['phase'] == 'complete'
    assert str(raw) not in record['source_tree_origins']
    assert execution['data_dir'] in record['source_tree_origins']
    current_request = json.loads(store.read_bytes('plot_request.json'))
    assert ledger['steps'][0] in current_request['transform_ledger']['steps']
    spec = json.loads(store.read_bytes('studio/spec.json'))
    assert sorted(series['y_values'] for series in spec['series']) == [[100., 120.], [200., 220.]]
    assert all(series['x_values'] == [1., 10.] for series in spec['series'])
