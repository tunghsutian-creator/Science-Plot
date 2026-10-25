"""New artifact producers retain scientific literals across private build cleanup."""
from copy import deepcopy
from dataclasses import replace
from io import StringIO
import json
from pathlib import Path
import shutil

import pandas as pd
import pytest

from sciplot_core.foundation.file_hashing import file_sha256
from sciplot_core.project_store import FileProjectStore, ProjectConflict
from sciplot_core.project_store.runtime import project_candidate_runtime
from sciplot_core.studio_render.frame_series import _series_from_frame_records
from sciplot_core.studio_render.models import StudioSourceFrame
from sciplot_core.studio_render.source_artifacts import literal_source_artifact
from sciplot_core.studio_render.terminal_contract import derive_terminal_render_data_contract

CASES = {
    'curve': ('curve', 'Time,Signal\ns,V\nA,A\n0,2\n1,4\n2,8\n'),
    'scalar': ('heatmap', 'x,y,z\n0,0,1\n0,1,2\n1,0,3\n1,1,4\n'),
    'replicate': ('box_strip', 'Strength,Strength\nMPa,MPa\nA,B\n1,3\n2,4\n3,5\n'),
    'components': ('bar', 'Sample,Component,Value\nA,X,1\nA,Y,2\nB,X,3\nB,Y,4\n'),
    'grouped': ('bar', 'Sample,Condition,Value\nA,wet,1\nA,wet,2\nA,dry,3\nA,dry,4\nB,wet,5\nB,wet,6\nB,dry,7\nB,dry,8\n'),
}


def project_frame(tmp_path, text):
    project = tmp_path / 'project'
    project.mkdir()
    source = project / 'source.csv'
    source.write_text(text)
    store = FileProjectStore(project)
    snapshot = store.snapshot(import_legacy=True)
    private = tmp_path / 'private'
    private.mkdir(mode=0o700)
    target = private / source.name
    target.write_bytes(source.read_bytes())
    target.chmod(source.stat().st_mode & 0o777)
    frame = StudioSourceFrame('A', source, file_sha256(source), pd.read_csv(StringIO(text), dtype=object))
    return store, snapshot, private, frame


@pytest.mark.parametrize('family', list(CASES))
def test_curve_scalar_and_categorical_artifact_writers_keep_literal_arrays_and_hashes_after_cleanup(tmp_path, family):
    template, text = CASES[family]
    store, snapshot, private, frame = project_frame(tmp_path, text)
    request = {'template': template, 'render_options': {'summary_statistic': 'raw_only'}}
    original = _series_from_frame_records(deepcopy(request), frames=[frame])
    physical = replace(frame, path=private / frame.path.name)
    with project_candidate_runtime(store, private):
        produced = _series_from_frame_records(deepcopy(request), frames=[physical])
        assert physical.path.is_file() and physical.path != frame.path  # Model remains physical and pure.
        assert produced == original
        assert produced[0] and all(item.source_artifacts for item in produced[0])
        for item in produced[0]:
            assert item.source_artifacts == ((str(frame.path), frame.sha256),)
        if family == 'scalar':
            assert produced[1]['scalar_field']['source_artifacts'] == [{'path': str(frame.path), 'sha256': frame.sha256}]
    shutil.rmtree(private)
    for item in produced[0]:
        for path, digest in item.source_artifacts:
            assert Path(path).is_file() and file_sha256(Path(path)) == digest
    assert store.snapshot()['generation'] == snapshot['generation']
    assert frame.path.read_text() == text


def test_terminal_contract_top_level_and_per_unit_artifacts_use_one_literal_projection(tmp_path):
    store, snapshot, private, frame = project_frame(tmp_path, CASES['curve'][1])
    request = {'template': 'curve', 'input': str(frame.path)}
    baseline = derive_terminal_render_data_contract(request=deepcopy(request), terminal_sources=[frame.path])
    with project_candidate_runtime(store, private):
        projected = derive_terminal_render_data_contract(request=deepcopy(request), terminal_sources=[private / frame.path.name])
    assert projected == baseline and str(private) not in json.dumps(projected)
    shutil.rmtree(private)
    assert all(file_sha256(Path(record['path'])) == record['sha256'] for record in projected['source_artifacts'])
    assert store.snapshot()['generation'] == snapshot['generation']


def test_artifact_projection_preserves_existing_hash_and_refuses_private_source_alias(tmp_path):
    store, _snapshot, private, frame = project_frame(tmp_path, CASES['curve'][1])
    assert literal_source_artifact('unbound-relative.csv', frame.sha256) == ('unbound-relative.csv', frame.sha256)
    with project_candidate_runtime(store, private):
        assert literal_source_artifact(private / frame.path.name, frame.sha256) == (str(frame.path), frame.sha256)
        (private / 'alias.csv').symlink_to(frame.path)
        with pytest.raises((ProjectConflict, OSError)):
            literal_source_artifact(private / 'alias.csv', frame.sha256)


def test_verified_source_group_writer_projects_artifact_without_changing_group_identity(tmp_path):
    from sciplot_core.studio_render.source_group_series import source_group_series
    store, snapshot, private, frame = project_frame(tmp_path, 'Impact strength\n1\n2\n3\n')
    frame.frame.attrs['sciplot_source_group'] = {'version': 1, 'source_id': 'group-A',
        'source_namespace': str(frame.path), 'sample': 'A', 'category': 'A', 'condition': None,
        'display_label': 'display A'}
    baseline = source_group_series([frame])
    with project_candidate_runtime(store, private):
        actual = source_group_series([replace(frame, path=private / frame.path.name)])
    assert actual == baseline and actual[0][0].source_artifacts == ((str(frame.path), frame.sha256),)
    assert actual[1]['source_bindings'][actual[0][0].x_name]['source_namespace'] == str(frame.path)
    assert store.snapshot()['generation'] == snapshot['generation']


@pytest.mark.parametrize('mode', ['given_values', 'mean_sample_sd'])
def test_explicit_categorical_writers_keep_declared_identity_and_read_path_separate(tmp_path, mode):
    from sciplot_core.studio_render.categorical_bindings import read_categorical_frame
    from sciplot_core.studio_render.categorical_bound_series import bound_categorical_series
    from test_task_ordinary_categorical import _binding
    text = 'Sample,Condition,Strength (MPa)\nA,dry,1\nB,dry,3\n'
    if mode != 'given_values':
        text += 'A,dry,2\nB,dry,4\n'
    store, snapshot, private, frame = project_frame(tmp_path, text)
    binding = {**_binding(frame.path, mode), 'source_identity_version': 1, 'source_namespace': str(frame.path)}
    bound = read_categorical_frame(frame.path, binding)
    baseline = bound_categorical_series([bound])
    with project_candidate_runtime(store, private):
        actual = bound_categorical_series([replace(bound, path=private / frame.path.name)])
    assert actual == baseline
    assert all(item.source_artifacts == ((str(frame.path), frame.sha256),) for item in actual[0])
    assert all(item['source_namespace'] == str(frame.path) for item in actual[1]['source_bindings'].values())
    assert store.snapshot()['generation'] == snapshot['generation']


@pytest.mark.parametrize('family', ['performance', 'impact'])
def test_special_performance_and_impact_artifact_producers_keep_original_tuple(tmp_path, family):
    from sciplot_core.studio_core.series_request import _series_from_request
    from sciplot_core.studio_core.impact_series import _impact_point_line_series_from_source
    project = tmp_path / 'project'
    project.mkdir()
    if family == 'performance':
        source = project / 'performance.csv'
        fixture = Path(__file__).parent / 'fixtures/performance_comparison/material_performance_long.csv'
        source.write_bytes(fixture.read_bytes())  # Existing tracked public generated fixture only.
        request = {'input': str(source), 'rule_id': 'performance_comparison', 'template': 'scatter'}
        def build(path):
            return _series_from_request({**request, 'input': str(path)}, base_dir=path.parent)[0]
    else:
        from test_impact_condition_figure_set import _write_two_condition_impact_source
        source = project / 'impact.xlsx'
        _write_two_condition_impact_source(source)
        request = {'input': str(source), 'rule_id': 'impact_metric', 'template': 'point_line'}
        def build(path):
            return _impact_point_line_series_from_source(path, request={**request, 'input': str(path)})[0]
    digest = file_sha256(source)
    baseline = build(source)
    store = FileProjectStore(project)
    snapshot = store.snapshot(import_legacy=True)
    private = tmp_path / 'private'
    private.mkdir(mode=0o700)
    actual_source = private / source.name
    actual_source.write_bytes(source.read_bytes())
    actual_source.chmod(source.stat().st_mode & 0o777)
    with project_candidate_runtime(store, private):
        actual = build(actual_source)
    assert actual == baseline
    assert all(item.source_artifacts == ((str(source), digest),) for item in actual)
    shutil.rmtree(private)
    assert file_sha256(source) == digest and store.snapshot()['generation'] == snapshot['generation']
