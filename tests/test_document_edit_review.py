"""One historical sealed native review reader for task consumers."""

from __future__ import annotations

import copy
import json
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
