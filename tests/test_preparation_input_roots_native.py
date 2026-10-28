"""Real generic-XY mapped inputs keep source and namespace authority separate."""
import json
from pathlib import Path
import subprocess

import pytest

from sciplot_core.native_process.session import _close_workers
from sciplot_core.project_host_factory import project_store
from sciplot_core.studio import prepare_studio_document, export_native_document_artifacts
from test_preparation_input_roots import multifile_mapping_request
from test_project_source_update_native import _native


@pytest.mark.comprehensive
def test_generic_multifile_mapping_prepares_real_native_and_publishes_exact_sources(tmp_path, monkeypatch):
    project = tmp_path / 'project'
    project.mkdir()
    raw, execution, ledger, request_path = multifile_mapping_request(tmp_path, project)
    originals = {name: (raw / name).read_bytes() for name in ['one.csv', 'two.csv']}
    starts, popen = [], subprocess.Popen
    def observe(*args, **kwargs):
        child = popen(*args, **kwargs)
        starts.append(child)
        return child
    monkeypatch.setattr(subprocess, 'Popen', observe)
    try:
        result = prepare_studio_document(request_path)
        store = project_store(project)
        current = store.snapshot()
        record = store.query(result['project_command']['command_id'])
        assert record['phase'] == 'complete' and record['generation'] == current['generation']
        assert str(raw) not in record['source_tree_origins']
        assert execution['data_dir'] in record['source_tree_origins']
        saved = json.loads(store.read_bytes('plot_request.json'))
        assert ledger['steps'][0] in saved['transform_ledger']['steps']
        audits = json.loads(Path(record['artifact_paths']['native-audits.json']).read_bytes())
        assert audits and all(item['status'] == 'passed' and not item.get('native_port_double') for item in audits)
        document = Path(result['document'])
        native = _native(document)
        assert sorted(values['y'] for values in native['series'].values()) == [[100., 120.], [200., 220.]]
        assert all(values['x'] == [1., 10.] for values in native['series'].values())
        spec = json.loads(store.read_bytes('studio/spec.json'))
        assert spec['axes']['x']['label'] == r'\omega (rad s⁻¹)'
        assert spec['axes']['y']['label'] == r'\italic{G}′ (Pa)'
        for name, data in originals.items():
            assert (raw / name).read_bytes() == data
            assert any(entry.get('locator') == str(raw / name) for versions in current['sources'].values() for entry in versions.values())
        exported = export_native_document_artifacts(document, formats=['pdf'])
        assert exported['document_audit']['status'] == 'passed', exported
        assert exported['standalone_export']['export_ready'] is True, exported
        assert all((raw / name).read_bytes() == data for name, data in originals.items())
    finally:
        _close_workers()
        assert all(child.poll() is not None for child in starts)
        (tmp_path / 'mapping-native-workers.json').write_text(json.dumps(
            [{'pid': child.pid, 'returncode': child.returncode} for child in starts], indent=2))
