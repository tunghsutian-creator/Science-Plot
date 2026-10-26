"""Domain reasons keep exact input-version refusals without masking other guards."""
import json

import pytest

from test_performance_metric_selection import selection_for
from test_project_query_source_versions import generation
from sciplot_core.foundation.file_hashing import file_sha256
from sciplot_core.foundation.source_errors import SourceVersionMismatch
from sciplot_core.performance_comparison.models import PerformanceComparisonError
from sciplot_core.project_commands import ProjectCommand, ProjectCommands, ProjectMutation
from sciplot_core.project_store import ProjectConflict
from sciplot_core.project_store.source_inspection import physical_file
from sciplot_core.studio_core.preparation_source_runtime import current_preparation_runtime


@pytest.mark.parametrize('case', ['selected', 'other-version-selection', 'unselected', 'alias', 'missing'])
def test_current_preparation_keeps_selected_performance_source_reason_exact(tmp_path, case):
    store, request, source, _paths = generation(tmp_path, directory=False)
    if case != 'unselected':
        request['performance_selection'] = selection_for(source)
        if case == 'other-version-selection':
            request['performance_selection']['source_sha256'] = 'a' * 64
        before = store.snapshot()
        command = ProjectCommand.create('save', 'add-exact-selection', project_id=before['project_id'],
            expected_generation=before['generation'], read_set={'plot_request.json': before['files']['plot_request.json']['sha256']},
            write_set=['plot_request.json'], request={})
        ProjectCommands(store).execute(command, lambda: ProjectMutation({'plot_request.json': json.dumps(request).encode()}, {}))
    before = store.snapshot()
    if case == 'alias':
        original = tmp_path / 'aliased-original.csv'
        source.rename(original)
        source.symlink_to(original)
    elif case == 'missing':
        source.unlink()
    else:
        source.write_bytes(source.read_bytes() + b'\n')
    error = (PerformanceComparisonError if case == 'selected' else FileNotFoundError
             if case == 'missing' else OSError if case == 'alias' else ValueError)
    with pytest.raises(error) as caught:
        with current_preparation_runtime(store, before):
            pytest.fail('Changed, missing or aliased sources must be rejected before rendering.')
    if case == 'selected':
        assert caught.value.reason_code == 'performance_selection_source_changed'
        assert isinstance(caught.value.__cause__, SourceVersionMismatch)
    else:
        assert not isinstance(caught.value, PerformanceComparisonError)
        if case in {'other-version-selection', 'unselected'}:
            assert isinstance(caught.value, SourceVersionMismatch)
    assert store.snapshot()['generation'] == before['generation']


def test_physical_source_inspection_emits_typed_mismatch_only_after_actual_hash(tmp_path):
    source = tmp_path / 'original.csv'
    source.write_bytes(b'original bytes')
    expected = file_sha256(source)
    source.write_bytes(b'observed changed bytes')
    with pytest.raises(SourceVersionMismatch) as caught:
        physical_file(source, expected)
    assert isinstance(caught.value, ProjectConflict)
    assert (caught.value.literal, caught.value.expected_sha256, caught.value.observed_sha256) == (
        str(source), expected, file_sha256(source))
    source.unlink()
    with pytest.raises(FileNotFoundError):
        physical_file(source, expected)
