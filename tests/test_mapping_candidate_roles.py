"""Editable request destinations are not immutable mapping science inputs."""
import json
from pathlib import Path

import pytest

from sciplot_core.data_mapping import load_data_mapping_execution
from sciplot_core.data_mapping.execution_inputs import mapping_input_reads
from sciplot_core.project_store import FileProjectStore, ProjectConflict
from sciplot_core.studio_core.preparation_candidate import studio_preparation_candidate
from test_mapping_execution_directories import directory_execution


def test_private_request_completion_preserves_seed_without_minting_input_role(tmp_path):
    _origin, request, execution = directory_execution(tmp_path)
    root = Path(execution['output_root'])
    store = FileProjectStore(root)
    before = store.snapshot(import_legacy=True)
    seed = Path(execution['request_seed']).read_bytes()
    with studio_preparation_candidate(store, snapshot=before) as candidate:
        with mapping_input_reads(request['data_mapping_execution']) as inputs:
            load_data_mapping_execution(inputs.execution)
            candidate.write_request({**request, 'review_notes': ['Current request metadata may evolve.']})
        assert str(root / 'plot_request.json') not in inputs.files
        assert str(root / 'plot_request.json') not in inputs.metadata
        assert str(root / 'plot_request.json') not in inputs.trees
        assert all(source.locator != str(root / 'plot_request.json') for source in inputs.prepared_sources(before))
        assert all(item.resource != 'plot_request.json' for item in inputs.input_reads(before))
    assert Path(execution['request_seed']).read_bytes() == seed
    assert store.snapshot()['generation'] == before['generation']


@pytest.mark.parametrize('change', ['seed', 'candidate_alias', 'candidate_missing', 'foreign_candidate'])
def test_candidate_role_separation_does_not_relax_seeds_or_destinations(tmp_path, change):
    _origin, request, execution = directory_execution(tmp_path)
    candidate = Path(execution['request_candidate'])
    if change == 'seed':
        seed = Path(execution['request_seed'])
        seed.write_bytes(seed.read_bytes() + b' ')
    elif change == 'candidate_alias':
        saved = candidate.with_name('same-bytes.json')
        saved.write_bytes(candidate.read_bytes())
        candidate.unlink()
        candidate.symlink_to(saved)
    elif change == 'candidate_missing':
        candidate.unlink()
    else:
        path = Path(request['data_mapping_execution'])
        payload = json.loads(path.read_bytes())
        payload['request_candidate'] = str(tmp_path / 'foreign/plot_request.json')
        path.write_text(json.dumps(payload))
    with pytest.raises((ValueError, OSError)):
        load_data_mapping_execution(request['data_mapping_execution'])


def test_destination_notes_may_evolve_between_numeric_replays(tmp_path):
    _origin, request, execution = directory_execution(tmp_path)
    candidate = Path(execution['request_candidate'])
    seed = Path(execution['request_seed']).read_bytes()
    for note in ['first review', 'another review']:
        candidate.write_text(json.dumps({**request, 'review_notes': [note]}))
        with mapping_input_reads(request['data_mapping_execution']) as inputs:
            assert load_data_mapping_execution(inputs.execution)['status'] == 'passed'
        assert str(candidate) not in inputs.files
        assert str(candidate) not in inputs.metadata
    assert Path(execution['request_seed']).read_bytes() == seed


@pytest.mark.parametrize('outside_change', [False, True])
def test_request_destination_updates_use_real_outer_preimage_cas(tmp_path, monkeypatch, outside_change):
    from sciplot_core.project_commands import PreparedFile, ProjectCommand, ProjectCommands, ProjectMutation
    from sciplot_core.project_store import state
    from sciplot_core.project_store.runtime import project_runtime

    _origin, request, execution = directory_execution(tmp_path)
    root = Path(execution['output_root'])
    store = FileProjectStore(root)
    before = store.snapshot(import_legacy=True)
    with project_runtime(store), mapping_input_reads(request['data_mapping_execution']) as inputs:
        load_data_mapping_execution(inputs.execution)
        sources = inputs.prepared_sources(before)
    updated = json.dumps({**request, 'review_notes': ['An explicit destination update.']}).encode()
    command = ProjectCommand.create('figure_set', 'complete-request', project_id=before['project_id'],
        expected_generation=before['generation'], read_set={name: item['sha256'] for name, item in before['files'].items()},
        write_set=['plot_request.json'], request={'review_notes': ['An explicit destination update.']})
    boundary = state.boundary
    def drift(name):
        if outside_change and name == 'before_head':
            (root / 'plot_request.json').write_bytes((root / 'plot_request.json').read_bytes() + b' ')
        boundary(name)
    monkeypatch.setattr(state, 'boundary', drift)
    def publish():
        return ProjectCommands(store).execute(command, lambda: ProjectMutation(
            {'plot_request.json': PreparedFile(updated, before['files']['plot_request.json']['mode'])}, {},
            prepared_sources=sources, input_reads=inputs.input_reads(before)))
    if outside_change:
        with pytest.raises(ProjectConflict):
            publish()
        assert store.snapshot()['generation'] == before['generation']
        assert (root / 'plot_request.json').read_bytes() != updated
    else:
        assert publish()['phase'] == 'complete'
        assert store.read_bytes('plot_request.json') == updated
        assert 'plot_request.json' not in store.snapshot().get('input_resources', [])
        assert not any(entry.get('locator') == str(root / 'plot_request.json')
            for versions in store.snapshot()['sources'].values() for entry in versions.values())


def test_unpublished_wrong_role_artifact_stays_protected_without_rewriting_history(tmp_path):
    from sciplot_core.project_commands import InputRead, PreparedSource, ProjectCommand, ProjectCommands, ProjectMutation

    _origin, _request, execution = directory_execution(tmp_path)
    root = Path(execution['output_root'])
    store = FileProjectStore(root)
    before = store.snapshot(import_legacy=True)
    entry = before['files']['plot_request.json']
    identity = 'e' * 32
    old = ProjectCommand.create('figure_set', 'retained-internal-role-error', project_id=before['project_id'],
        expected_generation=before['generation'], read_set={'plot_request.json': entry['sha256']}, write_set=[], request={})
    ProjectCommands(store).execute(old, lambda: ProjectMutation({}, {}, prepared_sources=(
        PreparedSource(identity, str(root / 'plot_request.json'), entry['sha256'], (root / 'plot_request.json').read_bytes(), mode=entry['mode']),),
        input_reads=(InputRead('plot_request.json', identity, entry['sha256']),)))
    protected = store.snapshot()
    assert 'plot_request.json' in protected['input_resources']
    command = ProjectCommand.create('figure_set', 'do-not-silently-repair-old-role', project_id=before['project_id'],
        expected_generation=protected['generation'], read_set={'plot_request.json': entry['sha256']},
        write_set=['plot_request.json'], request={})
    with pytest.raises(ProjectConflict, match='original input'):
        ProjectCommands(store).execute(command, lambda: ProjectMutation({'plot_request.json': b'{}'}, {}))
    assert store.snapshot() == protected
    assert store.read_bytes('plot_request.json', generation=before['generation']) == (root / 'plot_request.json').read_bytes()
