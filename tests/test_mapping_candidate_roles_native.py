"""The smoke mapping sub-lifecycle uses real native preparation and publication."""
import json
from pathlib import Path
import subprocess

import pytest

from sciplot_core.native_process.session import _close_workers
from sciplot_core.project_host_factory import project_store
from sciplot_core.smoke.data_mapping import _write_synthetic_ftir, _data_mapping_studio_lifecycle_probe
from sciplot_core.studio import prepare_studio_document


@pytest.mark.comprehensive
def test_mapping_studio_lifecycle_keeps_destination_separate_from_immutable_seed(tmp_path, monkeypatch):
    root = tmp_path / 'scenario'
    source = root / 'fixture/ftir_runtime_smoke.csv'
    _write_synthetic_ftir(source)
    raw = source.read_bytes()
    starts, popen = [], subprocess.Popen
    def observe(*args, **kwargs):
        child = popen(*args, **kwargs)
        starts.append(child)
        return child
    monkeypatch.setattr(subprocess, 'Popen', observe)
    try:
        initial = prepare_studio_document(source, output_root=root / 'projects',
            project_name='Synthetic FTIR runtime smoke')
        result = _data_mapping_studio_lifecycle_probe(run_root=root, source_path=source,
            base_request_path=Path(initial['request']))
        assert result['passed'] is True, result
        assert result['raw_hash_before'] == result['raw_hash_after']
        assert result['series_count'] == 1 and result['coverage']['status'] == 'passed'
        assert result['ready_to_use'] is True and result['delivery_complete'] is True
        project = Path(result['request_candidate']).parent
        store = project_store(project)
        current = store.snapshot()
        assert 'plot_request.json' not in current.get('input_resources', [])
        assert not any(entry.get('locator') == str(project / 'plot_request.json')
            for versions in current['sources'].values() for entry in versions.values())
        execution = json.loads((project / 'execution.json').read_bytes())
        assert any(entry.get('locator') == execution['request_seed']
            for versions in current['sources'].values() for entry in versions.values())
        assert source.read_bytes() == raw
    finally:
        _close_workers()
        assert all(child.poll() is not None for child in starts)
        (tmp_path / 'mapping-role-native-workers.json').write_text(json.dumps(
            [{'pid': child.pid, 'returncode': child.returncode} for child in starts], indent=2))
