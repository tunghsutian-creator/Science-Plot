"""Host delivery addresses survive private cleanup; audit observations stay true."""

from copy import deepcopy
import errno
from pathlib import Path
import shutil

import pytest

from sciplot_core.figure_plan import FigureOutcome, FigureTask, ResolvedFigurePlan
from sciplot_core.figure_plan.artifact_locations import artifact_is_file
from sciplot_core.figure_plan.execution import (
    finalize_figure_plan_result, merge_figure_outcomes, outcomes_for_artifact_map,
)
from sciplot_core.figure_plan.manifest_gate import figure_plan_manifest_gate
from sciplot_core.foundation.file_hashing import file_sha256
from sciplot_core.project_store import FileProjectStore
from sciplot_core.project_store.runtime import project_candidate_runtime
from sciplot_core.study_model.run_artifacts import attach_run_artifacts_to_study_model
from sciplot_core.terminal_request import project_terminal_render_request
from sciplot_core.workflow.request_rendering import RequestRenderResult
from sciplot_core.workflow.route_intent import resolve_workflow_route_intent


def seed(tmp_path):
    project = tmp_path / 'project'
    project.mkdir()
    source = project / 'data.csv'
    source.write_bytes(b'Time,Signal\ns,V\n0,1\n1,2\n')
    store = FileProjectStore(project)
    snapshot = store.snapshot(import_legacy=True)
    private = tmp_path / 'private'
    private.mkdir(mode=0o700)
    (private / source.name).write_bytes(source.read_bytes())
    (private / source.name).chmod(source.stat().st_mode & 0o777)
    output = private / 'runs/run_001'
    figures = output / 'figures'
    figures.mkdir(parents=True)
    artifacts = [figures / name for name in ('signal.vsz', 'signal.pdf', 'signal_300dpi.tiff')]
    for path in artifacts:
        path.write_bytes(b'generated exact ' + path.suffix.encode())
    task = FigureTask(figure_id='signal', order=1, title='Signal', x_metric='Time', y_metric='Signal',
                      template='curve', artifact_stem='signal', document_stem='signal')
    plan = ResolvedFigurePlan.planned(rule_id='dsc_curve', selection_policy='fixture_single',
        primary_figure_id=task.figure_id, tasks=(task,), source_sha256=file_sha256(source))
    model = {'kind': 'sciplot_study_model', 'version': 2,
        'experiment': {'rule_id': 'dsc_curve'},
        'samples': [{'id': 'sample_A', 'replicates': [{'id': 'raw_1', 'source_file': {
            'source_path': str(source), 'raw_path': str(source), 'sha256': file_sha256(source),
            'unit': 'V', 'original_name': source.name}}]}],
        'figure_queue': [{'id': 'signal', 'metric': 'Signal', 'x_metric': 'Time', 'y_metric': 'Signal'}],
        'scientific_extension': {'values': [1.0, 2.0], 'units': ['s', 'V'], 'source_uuid': 'raw_1'}}
    return project, source, store, snapshot, private, output, artifacts, plan, model


def publish_generated_outputs(store, snapshot, private, artifacts):
    writes = {path.relative_to(private).as_posix(): path.read_bytes() for path in artifacts}
    store.reserve('publish', 'publish-digest', expected_generation=snapshot['generation'],
                  read_set={name: None for name in writes}, write_set=list(writes))
    store.publish('publish', 'publish-digest', writes=writes, result={})


@pytest.mark.parametrize('with_plan', [False, True])
def test_study_host_artifacts_keep_original_locations_and_observed_qa_after_cleanup(tmp_path, with_plan):
    project, source, store, snapshot, private, output, artifacts, plan, model = seed(tmp_path)
    original = deepcopy(model)
    qa = {'kind': 'sciplot_artifact_qa', 'status': 'passed',
          'pdfs': [{'path': str(artifacts[1]), 'content_sha256': file_sha256(artifacts[1])}],
          'publication': {'veusz_document_audit': {'path': str(artifacts[0]),
              'observed_bytes_sha256': file_sha256(artifacts[0]), 'actual_worker': 'synthetic-test-double'}}}
    qa_before = deepcopy(qa)
    completed = merge_figure_outcomes(plan, (FigureOutcome(figure_id='signal', status='ready',
        artifacts=tuple(map(str, artifacts))),))
    logical_paths = [str(project / path.relative_to(private)) for path in artifacts]
    baseline_plan = merge_figure_outcomes(plan, (FigureOutcome(figure_id='signal', status='ready',
        artifacts=tuple(logical_paths)),))
    baseline = attach_run_artifacts_to_study_model(model, output_dir=project / 'runs/run_001',
        figures=logical_paths[1:], qa=qa, analysis_metrics=[{'name': 'Signal', 'value': 2.0, 'unit': 'V'}],
        resolved_figure_plan=baseline_plan.to_payload() if with_plan else None)
    with project_candidate_runtime(store, private):
        actual = attach_run_artifacts_to_study_model(model, output_dir=output,
            figures=list(map(str, artifacts[1:])), qa=qa,
            analysis_metrics=[{'name': 'Signal', 'value': 2.0, 'unit': 'V'}],
            resolved_figure_plan=completed.to_payload() if with_plan else None)
        assert all(artifact_is_file(row['path']) for row in actual['run']['figure_artifacts'])
    assert actual == baseline
    assert model == original and qa == qa_before
    assert actual['run']['qa'] == qa_before
    assert actual['samples'] == original['samples']
    assert actual['scientific_extension'] == original['scientific_extension']
    assert actual['run']['output'] == str(project / 'runs/run_001')
    assert actual['run']['unbound_figure_artifacts'] == []
    publish_generated_outputs(store, snapshot, private, artifacts)
    shutil.rmtree(private)
    assert all(Path(row['path']).is_file() for row in actual['run']['figure_artifacts'])
    assert all(Path(row['path']).is_file() for row in actual['figure_queue'][0]['artifacts'])
    assert actual['run']['qa']['pdfs'][0]['path'] == str(artifacts[1])  # Original observed IO fact.
    assert file_sha256(project / artifacts[1].relative_to(private)) == qa['pdfs'][0]['content_sha256']
    assert store.snapshot()['sources'] == snapshot['sources'] and file_sha256(source) == plan.source_sha256


@pytest.mark.parametrize('reported_plan', [False, True])
def test_terminal_outcome_producers_share_one_literal_plan_and_strict_artifact_gate(tmp_path, reported_plan):
    project, source, store, snapshot, private, output, artifacts, plan, model = seed(tmp_path)
    raw_outcome = FigureOutcome(figure_id='signal', status='ready', artifacts=tuple(map(str, artifacts)))
    original_result = {'terminal_render_requests': [project_terminal_render_request(template='curve',
        render_options={}, request_context={'rule_id': plan.rule_id, 'resolved_figure_task': plan.tasks[0].to_payload()})]}
    if reported_plan:
        original_result['resolved_figure_plan'] = merge_figure_outcomes(plan, (raw_outcome,)).to_payload()
    else:
        original_result['figure_outcomes'] = [raw_outcome.to_payload()]
    before = deepcopy(original_result)
    with project_candidate_runtime(store, private):
        mapped = outcomes_for_artifact_map(plan, {'signal': list(map(str, artifacts))})
        assert mapped[0].delivery_artifacts_complete
        assert mapped[0].artifacts == tuple(str(project / path.relative_to(private)) for path in artifacts)
        rendered = RequestRenderResult(route_intent=resolve_workflow_route_intent({'template': 'curve'}),
            final_recipe=None, result=original_result, plotted_data_source=source, selected_figure_plan=plan)
        completed = rendered.completed_figure_plan
        assert completed is not None and completed.plan_sha256 == plan.plan_sha256
        assert completed.tasks == plan.tasks and completed.source_sha256 == plan.source_sha256
        assert completed.outcomes == tuple(mapped)
        study = attach_run_artifacts_to_study_model(model, output_dir=output,
            figures=list(map(str, artifacts[1:])), resolved_figure_plan=completed.to_payload())
        manifest = {'resolved_figure_plan': completed.to_payload(), 'result': rendered.result, 'study_model': study}
        gate = figure_plan_manifest_gate(manifest)
        assert gate is not None and gate['complete'] and all(gate['projection_consistency'].values())
        assert original_result == before
        artifacts[1].unlink()
        missing = figure_plan_manifest_gate(manifest)
        assert missing is not None and not missing['complete']
        assert not missing['projection_consistency']['outcome_artifacts_exist']


def test_artifact_scope_refuses_alias_and_missing_output_without_rewriting_science(tmp_path):
    _project, _source, store, _snapshot, private, output, artifacts, plan, model = seed(tmp_path)
    alias = output / 'figures/alias.pdf'
    with project_candidate_runtime(store, private):
        alias.symlink_to(artifacts[1])
        assert not artifact_is_file(alias)
        with pytest.raises(OSError) as refused:
            attach_run_artifacts_to_study_model(model, output_dir=output, figures=[str(alias)])
        assert refused.value.errno == errno.ELOOP
        missing = finalize_figure_plan_result(plan, {'outputs': [str(output / 'missing.pdf')]})
        assert missing is not None and not missing.complete
        assert missing.outcomes[0].artifacts == ()
