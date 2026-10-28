"""Initial JSON originals join the real native generation and cold export."""
import json
from pathlib import Path
import subprocess

import pytest

from sciplot_core.foundation.file_hashing import file_sha256
from sciplot_core.native_process.session import _close_workers
from sciplot_core.plot_backends import VeuszBackend
from sciplot_core.project_host_factory import project_store
from sciplot_core.project_store import FileProjectStore
from sciplot_core.studio import export_native_document_artifacts, prepare_studio_document
from test_project_source_update_native import _native


@pytest.mark.comprehensive
def test_public_initial_json_original_survives_native_import_and_cold_export(tmp_path, monkeypatch):
    source = tmp_path / 'UVvis.csv'
    source.write_text('Wavelength,Absorbance,Wavelength,Absorbance\nnm,a.u.,nm,a.u.\n'
                      'E2,E2,E4,E4\n400,1,400,2\n450,2,450,3\n500,3,500,4\n')
    original, digest = source.read_bytes(), file_sha256(source)
    project = tmp_path / 'project'
    project.mkdir()
    request = {'input': str(source), 'rule_id': 'uvvis_spectrum', 'template': 'curve',
               'output': str(project / 'runs/run_001'), 'delivery_output': str(tmp_path / 'delivery'),
               'render_options': {'reverse_x': True}}
    (project / 'plot_request.json').write_text(json.dumps(request))
    starts, popen = [], subprocess.Popen
    def observe(*args, **kwargs):
        process = popen(*args, **kwargs)
        starts.append(process)
        return process
    monkeypatch.setattr(subprocess, 'Popen', observe)
    backend = VeuszBackend()
    try:
        prepared = prepare_studio_document(project / 'plot_request.json')
        store = project_store(project)
        current = store.snapshot()
        assert prepared['project_command']['generation'] == current['generation']
        owners = [identity for identity, versions in current['sources'].items()
                  if versions.get(digest, {}).get('locator') == str(source)]
        assert len(owners) == 1
        assert 'produced_resource' not in current['sources'][owners[0]][digest]
        semantic, _binding = backend.import_project(project, plot_id='initial-json')
        assert semantic['scientific_hash']
        native = _native(Path(prepared['document']))
        for sample, values in {'E2': [1, 2, 3], 'E4': [2, 3, 4]}.items():
            assert native['series'][sample]['x'] == [400, 450, 500]
            assert native['series'][sample]['y'] == values
        backend.close()
        _close_workers()
        cold = FileProjectStore.import_bundle(store.export_bundle(tmp_path / 'bundle'), tmp_path / 'cold')
        source.rename(tmp_path / 'original-offline.csv')
        project.rename(tmp_path / 'project-offline')
        regenerated = prepare_studio_document(cold.root, regenerate_generated=True)
        cold_native = _native(Path(regenerated['document']))
        assert cold_native['series'] == native['series']
        assert json.loads(cold.read_bytes('plot_request.json'))['input'] == str(source)
        assert cold.snapshot()['sources'][owners[0]][digest] == current['sources'][owners[0]][digest]
        exported = export_native_document_artifacts(Path(regenerated['document']), formats=['pdf'])
        assert exported['document_audit']['status'] == 'passed', exported
        assert exported['standalone_export']['export_ready'] is True, exported
        assert any(item['format'] == 'pdf' and Path(item['path']).is_file() for item in exported['exports'])
        assert not source.exists() and not project.exists()
        assert (tmp_path / 'original-offline.csv').read_bytes() == original
    finally:
        backend.close()
        _close_workers()
        assert all(process.poll() is not None for process in starts)
        (tmp_path / 'initial-json-native-workers.json').write_text(json.dumps(
            [{'pid': process.pid, 'returncode': process.returncode} for process in starts], indent=2))
