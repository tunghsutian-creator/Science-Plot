"""Mapping status observes its confirmed finite raw set, never a namespace tree."""
from dataclasses import replace
import hashlib
import json
from pathlib import Path
import stat

import pytest

from sciplot_core.data_mapping import create_data_mapping_confirmation, execute_data_mapping_proposal, load_data_mapping_execution
from sciplot_core.data_mapping.execution_inputs import MappingInputReadSet, mapping_input_reads
from sciplot_core.foundation.file_hashing import file_sha256
from sciplot_core.mapping_contract import DataColumnMapping, DataMappingProposal, DataSourceReference
from sciplot_core.project_commands import ProjectCommand, ProjectCommands, ProjectMutation
from sciplot_core.project_store import FileProjectStore
from sciplot_core.studio import observe_studio_source_content, resolve_studio_mapping_application
from test_gui_source_currentness import Document
from test_project_query_readonly_sources import inventory


def mapped_project(tmp_path, count=1):
    canonical = tmp_path / 'canonical-original'
    canonical.mkdir()
    (canonical / 'not-a-mapping-source.txt').write_text('Original prepared input is a different role.')
    raw = tmp_path / 'confirmed-raw'
    raw.mkdir()
    names = [f'measurement{i}' for i in range(count)]
    for name in names:
        (raw / f'{name}.csv').write_text('Wavelength (nm),Absorbance (a.u.)\n400,3\n500,1\n')
    base = tmp_path / 'base.json'
    base.write_text(json.dumps({'input': str(canonical), 'rule_id': 'uvvis_spectrum', 'template': 'curve'}))
    proposal = DataMappingProposal(proposal_id='finite-source-status', provider='external_task',
        base_request_sha256=file_sha256(base),
        sources=tuple(DataSourceReference(name, f'{name}.csv', file_sha256(raw / f'{name}.csv')) for name in names),
        columns=tuple(column for name in names for column in (
            DataColumnMapping(name, 0, 'Wavelength (nm)', 'x', expected_header='Wavelength (nm)'),
            DataColumnMapping(name, 1, 'Absorbance (a.u.)', 'y', expected_header='Absorbance (a.u.)'))),
        sample_labels={name: name for name in names}, request_patch={'rule_id': 'uvvis_spectrum', 'template': 'curve'})
    confirmation = create_data_mapping_confirmation(proposal, source_root=raw, request_path=base,
        output_root=tmp_path / 'executions', confirmed_by='Explicit finite GUI source test')
    execution = execute_data_mapping_proposal(proposal, confirmation, source_root=raw,
        request_path=base, output_root=tmp_path / 'executions')
    project = Path(execution['output_root'])
    request = json.loads((project / 'plot_request.json').read_bytes())
    with mapping_input_reads(request['data_mapping_execution']) as readset:
        load_data_mapping_execution(readset.execution)
    store = FileProjectStore(project)
    before = store.snapshot(import_legacy=True)
    # A scientific source version's normalized stored mode is distinct from
    # the live physical mode captured by the current numeric invocation.
    sources = tuple(replace(item, mode=0o600) if Path(item.locator).parent == raw else item
                    for item in readset.prepared_sources(before))
    command = ProjectCommand.create('figure_set', 'register-exact-mapping-inputs', project_id=before['project_id'],
        expected_generation=before['generation'], read_set={name: item['sha256'] for name, item in before['files'].items()},
        write_set=[], request={},
        source_trees=tuple(readset.trees.values()))
    ProjectCommands(store).execute(command, lambda: ProjectMutation({}, {}, prepared_sources=sources,
        input_reads=readset.input_reads(before)))
    return store, request, execution, raw, canonical


def verified(store, request):
    observed = []
    effective, application = resolve_studio_mapping_application(request, project_dir=store.root,
        request_path=store.root / 'plot_request.json', on_verified_mapping=observed.append)
    assert len(observed) == 1 and observed[0].numeric_inputs_sha256
    return effective, application, observed[0]


def observe(store, path, readset=None, *, audit=True, revision=None):
    return observe_studio_source_content(path, project_dir=store.root, request_path=store.root / 'plot_request.json',
        audit_source=audit, mapping_inputs=readset, expected_revision=revision)


@pytest.mark.parametrize('count', [1, 2])
def test_confirmed_originals_differ_from_canonical_input_without_granting_the_parent(tmp_path, monkeypatch, count):
    from sciplot_core.project_store import source_tree_io
    from sciplot_core.data_mapping import execution_inputs
    store, request, execution, raw, canonical = mapped_project(tmp_path, count)
    sibling = raw / 'unselected.csv'
    sibling.write_text('No source permission, never hashed.')
    empty = raw / 'unselected-empty'
    empty.mkdir()
    read = execution_inputs._read
    def finite(path, *args, **kwargs):
        assert path != sibling and path != raw and path != canonical
        return read(path, *args, **kwargs)
    monkeypatch.setattr(execution_inputs, '_read', finite)
    tree = source_tree_io.observe
    def no_namespace(path, **kwargs):
        assert Path(path) not in {raw, canonical}, 'Namespace-only directories are not current tree evidence.'
        return tree(path, **kwargs)
    monkeypatch.setattr(source_tree_io, 'observe', no_namespace)
    before = inventory(tmp_path)
    _effective, application, inputs = verified(store, request)
    result = observe(store, canonical, inputs)
    assert application['raw_inputs_preserved'] is True
    assert result['scope'] == 'mapping_selected_files'
    assert result['audit_status'] == 'matches_confirmed_mapping_sources'
    assert result['selected_files_current'] is True and result['path'] is None
    assert result['content']['kind'] == 'selected_files' and result['content']['member_count'] == count
    assert 'sha256' not in result['content']  # no historical whole-directory certification
    assert set(result['observation_revision']) == {'project_id', 'generation', 'request_sha256'}
    assert result['mapping_execution'] == request['data_mapping_execution']
    assert result['confirmation_id'] == execution['confirmation_id']
    assert result['proposal_sha256'] == execution['proposal_sha256']
    assert {item['identity_path'] for item in result['selected_files']} == {
        str(raw / name) for name in execution['source_hashes']}
    for literal, item in inputs.files.items():
        if Path(literal).parent == raw:
            assert item.mode == 0o600 and item.actual_mode == stat.S_IMODE(Path(literal).stat().st_mode)
    assert inventory(tmp_path) == before


def test_single_original_keeps_legacy_file_digest_and_physical_open_target(tmp_path):
    from sciplot_gui.studio_project_status.source_status import _source_status
    store, request, execution, raw, _canonical = mapped_project(tmp_path)
    _effective, _application, inputs = verified(store, request)
    source = raw / next(iter(execution['source_hashes']))
    result = _source_status(source, transform_ledger=execution['transform_steps'] and {'steps': execution['transform_steps']},
        audit_source=True, _content_observer=lambda path, **kwargs: observe(store, path, inputs, audit=kwargs['audit_source']))
    assert result['scope'] == 'mapping_source_file'
    assert result['kind'] == 'file' and result['sha256'] == hashlib.sha256(source.read_bytes()).hexdigest()
    assert result['audit_status'] == 'matches_last_run_lineage'
    assert result['path'] == result['identity_path'] == str(source)


@pytest.mark.parametrize('audit', [False, True])
def test_unobserved_mapping_does_not_read_old_namespace_or_claim_current(tmp_path, monkeypatch, audit):
    from sciplot_core.studio_core import source_content_observation as core
    store, request, _execution, _raw, canonical = mapped_project(tmp_path)
    monkeypatch.setattr(core, '_external_tree', lambda *_a, **_k: pytest.fail('Namespace is not a full original tree.'))
    monkeypatch.setattr(core, '_mapped_source', lambda *_a, **_k: pytest.fail('No numeric source observation exists.'))
    before = inventory(tmp_path)
    result = observe(store, canonical, audit=audit)
    assert result['audit_status'] == ('not_currently_observed' if audit else 'not_computed')
    assert result['exists'] is False and result['path'] is None and 'content' not in result
    assert inventory(tmp_path) == before


@pytest.mark.parametrize('change', ['bytes', 'missing', 'alias', 'raw_mode', 'metadata_mode', 'proof', 'foreign', 'header', 'verify_false'])
def test_mapping_source_observation_requires_same_numeric_closure_and_live_versions(tmp_path, change):
    store, request, execution, raw, canonical = mapped_project(tmp_path)
    _effective, _application, inputs = verified(store, request)
    source = raw / next(iter(execution['source_hashes']))
    if change == 'bytes':
        source.write_bytes(source.read_bytes() + b' ')
    elif change == 'missing':
        source.unlink()
    elif change == 'alias':
        other = tmp_path / 'same-bytes.csv'
        other.write_bytes(source.read_bytes())
        source.unlink()
        source.symlink_to(other)
    elif change in {'raw_mode', 'metadata_mode'}:
        target = source if change == 'raw_mode' else Path(execution['request_seed'])
        target.chmod(0o600 if stat.S_IMODE(target.stat().st_mode) != 0o600 else 0o644)
    elif change == 'proof':
        inputs.numeric_inputs_sha256 = 'f' * 64
    elif change == 'foreign':
        canonical = raw / 'unselected.csv'
        canonical.write_text('Not confirmed.')
    elif change == 'verify_false':
        with mapping_input_reads(request['data_mapping_execution']) as inputs:
            load_data_mapping_execution(inputs.execution, verify=False)
    else:
        inputs = MappingInputReadSet(inputs.execution, files=inputs.files.copy())
        inputs.seal()  # public header-only seal is not proof of numeric verification
    before = inventory(tmp_path)
    with pytest.raises((OSError, ValueError)):
        observe(store, canonical, inputs)
    assert inventory(tmp_path) == before


def test_verified_source_stays_bound_to_the_prechecked_revision(tmp_path):
    store, request, _execution, _raw, canonical = mapped_project(tmp_path)
    revision = observe_studio_source_content(None, project_dir=store.root,
        request_path=store.root / 'plot_request.json', audit_source=False)
    _effective, _application, inputs = verified(store, request)
    before = store.snapshot()
    command = ProjectCommand.create('figure_set', 'next-legitimate-generation', project_id=before['project_id'],
        expected_generation=before['generation'], read_set={'note.txt': None}, write_set=['note.txt'], request={})
    ProjectCommands(store).execute(command, lambda: ProjectMutation({'note.txt': b'new metadata'}, {}))
    with pytest.raises(ValueError, match='revision changed'):
        observe(store, canonical, inputs, revision=revision)


def test_official_cold_mapping_stays_unknown_without_reading_old_raw_or_creating_views(tmp_path, monkeypatch):
    from sciplot_core.data_mapping import execution_inputs
    from sciplot_core.studio import CurrentMappingObservationUnavailable
    store, request, _execution, _raw, canonical = mapped_project(tmp_path)
    cold = FileProjectStore.import_bundle(store.export_bundle(tmp_path / 'official-bundle'), tmp_path / 'cold')
    read, read_file = execution_inputs._read, execution_inputs.read_file
    def confined(path, *args, **kwargs):
        result = read(path, *args, **kwargs)
        assert result[1].is_relative_to(cold.root), 'Cold mapping retried old-origin metadata or raw bytes.'
        return result
    def no_raw(fd, name, **kwargs):
        assert name not in {Path(item).name for item in _execution['source_hashes']}, 'Cold status read old raw bytes.'
        return read_file(fd, name, **kwargs)
    monkeypatch.setattr(execution_inputs, '_read', confined)
    monkeypatch.setattr(execution_inputs, 'read_file', no_raw)
    before = inventory(tmp_path)
    with pytest.raises(CurrentMappingObservationUnavailable):
        verified(cold, request)
    result = observe(cold, canonical)
    assert result['audit_status'] == 'not_currently_observed' and result['path'] is None
    assert inventory(tmp_path) == before


@pytest.mark.parametrize('count', [1, 2])
def test_public_status_adapter_shares_one_mapping_observation_without_claiming_missing_qa(tmp_path, count):
    from sciplot_gui.studio_project.status_adapter import build_studio_project_status
    store, _request, execution, _raw, _canonical = mapped_project(tmp_path, count)
    before = inventory(tmp_path)
    result = build_studio_project_status(document_path=store.root / 'studio/document.vsz', document=Document(),
        project_dir=store.root, request_path=store.root / 'plot_request.json', audit_source=True,
        _figure_set_scope_resolver=lambda **_kw: (None, 'not_applicable'))
    source, mapping = result['source'], result['mapping']
    assert source['audit_status'] == 'matches_confirmed_mapping_sources'
    assert source['scope'] == 'mapping_selected_files' and source['member_count'] == count
    assert source['observation_revision'] == mapping['observation_revision']
    assert set(source['observation_revision']) == {'project_id', 'generation', 'request_sha256'}
    assert source['confirmation_id'] == mapping['confirmation_id'] == execution['confirmation_id']
    assert mapping['status'] == 'unverified'  # no published native QA was manufactured by this fixture
    assert result['provenance']['source_current'] is False and result['provenance']['complete'] is False
    assert inventory(tmp_path) == before
