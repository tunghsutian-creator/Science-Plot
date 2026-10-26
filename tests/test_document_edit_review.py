"""One historical sealed native review reader for task consumers."""

from __future__ import annotations

import copy
import json
from pathlib import Path
import pytest

from test_native_project_commands import edit as edit
from test_project_query import project as project
from sciplot_core.project_commands import ProjectCommand, ProjectCommands, ProjectMutation
from sciplot_core.project_store.state import command_path
from sciplot_core.studio_core.document_edit_review import verified_document_edit_review
from sciplot_core.studio_core.project_command_scope import project_store


def test_sealed_review_is_historical_evidence_without_native_apply_or_repair(edit):
    project, document, review, calls = edit
    before = document.read_bytes()
    verified, record = verified_document_edit_review(project, review)
    assert verified == {key: value for key, value in review.items() if key != 'review_path'}
    assert record['phase'] == 'needs_review' and document.read_bytes() == before and len(calls) == 1
    app = ProjectCommands(project_store(project))
    command = ProjectCommand.from_payload(record['metadata'])
    app.decide(command, decision_id=review['decision_id'], accept=True)
    store = project_store(project)
    current = store.snapshot()
    relative = store.logical_path(document)
    later = ProjectCommand.create('save', 'later-native-save', project_id=current['project_id'],
        expected_generation=current['generation'], read_set={relative: current['files'][relative]['sha256']},
        write_set=[relative], request={})
    app.execute(later, lambda: ProjectMutation({relative: b'later native bytes'}, {}))
    historical, completed = verified_document_edit_review(project, review)
    assert historical == verified and completed['phase'] == 'complete'
    assert document.read_bytes() == b'later native bytes' and len(calls) == 1


def test_rejected_sealed_review_is_readable_history_and_cannot_be_accepted(edit):
    project, document, review, calls = edit
    before = document.read_bytes()
    app = ProjectCommands(project_store(project))
    record = app.query(review['operation_id'])
    command = ProjectCommand.from_payload(record['metadata'])
    app.decide(command, decision_id=review['decision_id'], accept=False)
    verified, rejected = verified_document_edit_review(project, review)
    assert verified['decision_id'] == review['decision_id'] and rejected['phase'] == 'rejected'
    with pytest.raises(ValueError):
        app.decide(command, decision_id=review['decision_id'], accept=True)
    assert document.read_bytes() == before and len(calls) == 1


def test_additional_typed_read_witness_is_retained_beyond_selected_base_files(edit):
    project, document, review, calls = edit
    store = project_store(project)
    app = ProjectCommands(store)
    prior = app.query(review['operation_id'])
    extra = 'studio/figures/second.vsz'
    snapshot = store.snapshot()
    original = ProjectCommand.from_payload(prior['metadata'])
    command = ProjectCommand.create('document_edit', 'review-with-extra-read', project_id=original.project_id,
        expected_generation=original.expected_generation,
        read_set={**dict(original.read_set), extra: snapshot['files'][extra]['sha256']},
        write_set=original.write_set, request=json.loads(original.request_json),
        projected_reads=original.projected_reads)
    recorded = app.preview(command, lambda: ProjectMutation(
        {name: Path(value) for name, value in prior['staged_paths'].items()}, prior['result'],
        review=prior['review'], artifacts={name: Path(value) for name, value in prior['artifact_paths'].items()}))
    supplied = {**review, 'operation_id': command.key, 'decision_id': recorded['decision_id']}
    verified, retained = verified_document_edit_review(project, supplied)
    assert verified['document_sha256'] == review['document_sha256']
    assert retained['read_set'][extra] == snapshot['files'][extra]['sha256']
    assert extra not in retained['result']['base_files'] and len(calls) == 1


@pytest.mark.parametrize('changed', ['decision', 'version_type', 'intent', 'receipt_review', 'metadata'])
def test_sealed_reader_refuses_changed_identity_or_mutable_review_hints(edit, changed):
    project, document, original, calls = edit
    supplied = copy.deepcopy(original)
    before = document.read_bytes()
    if changed == 'decision':
        supplied['decision_id'] = 'f' * 64
    elif changed == 'version_type':
        supplied['version'] = 3.0
    elif changed == 'intent':
        supplied['actual_changes'][0]['value'] = '99pt'
    else:
        path = project / '.sciplot_store' / command_path(original['operation_id'])
        record = json.loads(path.read_text())
        if changed == 'receipt_review':
            record['review']['scientific_audit']['status'] = 'failed'
        else:
            record['metadata']['request']['figure_id'] = 'second'
        path.write_text(json.dumps(record))
    with pytest.raises(ValueError):
        verified_document_edit_review(project, supplied)
    assert document.read_bytes() == before and len(calls) == 1



def test_sealed_scoped_review_refuses_a_foreign_key_even_with_self_consistent_metadata(edit):
    project, document, review, calls = edit
    store = project_store(project)
    app = ProjectCommands(store)
    prior = app.query(review['operation_id'])
    original = ProjectCommand.from_payload(prior['metadata'])
    intent = {**json.loads(original.request_json), 'request_id': 'a' * 64}
    command = ProjectCommand.create('document_edit', 'foreign-scoped-key', project_id=original.project_id,
        expected_generation=original.expected_generation, read_set=dict(original.read_set),
        write_set=original.write_set, request=intent, projected_reads=original.projected_reads)
    record = app.preview(command, lambda: ProjectMutation(
        {name: Path(value) for name, value in prior['staged_paths'].items()}, prior['result'],
        review=prior['review'], artifacts={name: Path(value) for name, value in prior['artifact_paths'].items()}))
    supplied = {**review, 'operation_id': command.key, 'decision_id': record['decision_id']}
    with pytest.raises(ValueError, match='host-assigned operation identity'):
        verified_document_edit_review(project, supplied)
    assert record['phase'] == 'needs_review' and len(calls) == 1
