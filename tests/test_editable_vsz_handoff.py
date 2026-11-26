"""An explicitly delivered editable figure is independent even as a lone file."""

import json
import os
from pathlib import Path
import shutil
import signal
import subprocess
import sys

import pytest

from sciplot_core._paths import REPO_ROOT
from sciplot_core.delivery import native_snapshot
from sciplot_core.foundation.file_hashing import file_sha256
from sciplot_core.plot_protocol.paths import read_owner
from sciplot_core.veusz_runtime import veusz_worker_environment


def test_standalone_save_does_not_admit_a_linked_dataset(tmp_path, monkeypatch):
    source = tmp_path / "original.vsz"
    source.write_bytes(b"native source")
    stage = tmp_path / "isolated"
    stage.mkdir()

    def linked_save(_action, _source, target, *_opts):
        Path(target).parent.mkdir()
        Path(target).write_bytes(b"saved but still linked")
        return {"status": "passed", "original_sha256": file_sha256(source),
                "portable_sha256": file_sha256(Path(target)), "imports": [
                    {"source": "linked.csv", "sha256": "unadmitted"}],
                "native_state_sha256": "same", "reopened_native_state_sha256": "same"}

    monkeypatch.setattr(native_snapshot, "_native", linked_save)
    with pytest.raises(native_snapshot.SnapshotImportUnselected):
        native_snapshot.stage_standalone_native(
            source, stage / "figure.vsz", tmp_path / "private", original_sha256=file_sha256(source))
    assert list(stage.iterdir()) == []


_COLD_VEUSZ = """
import json, sys
from pathlib import Path
from sciplot_core.plot_backends.managed_audit import native_state
from sciplot_core.studio_core.export_execution import export_studio_document
from sciplot_core.studio_core.persistence import atomic_save_veusz_document
from sciplot_core.veusz_worker.document_edit import loaded_native_document

target, output = map(Path, sys.argv[1:3])
expected = json.loads(sys.argv[3])
assert set(target.parent.iterdir()) == {target}
with loaded_native_document(target) as doc:
    before = native_state(doc)
    assert {name: record['data'] for name, record in before['datasets'].items()} == expected
    assert not any(record['linked'] for record in before['datasets'].values())
    xy = {name: node['settings'] for name, node in before['widgets'].items() if node['type'] == 'xy'}
    labels = {name: record['key'] for name, record in xy.items() if record['key']}
    assert sorted(labels.values()) == ['Blue label', 'Red label']
    curve = next(name for name, record in xy.items()
                 if isinstance(record['xData'], str) and record['xData'] in expected and not record['PlotLine/hide'])
    path = curve + '/PlotLine/color'
    doc.resolveSettingPath(None, path).set('#A34455')
    assert atomic_save_veusz_document(doc, target)['ready_for_export']
with loaded_native_document(target) as doc:
    after = native_state(doc)
    assert after['datasets'] == before['datasets']
    assert {name: after['widgets'][name]['settings']['key'] for name in labels} == labels
    assert doc.resolveSettingPath(None, path).get() == '#A34455'
exports = export_studio_document(target, formats=['pdf'], output_dir=output)['exports']
assert len(exports) == 1 and exports[0]['format'] == 'pdf' and exports[0]['exists']
print(json.dumps(exports[0]))
"""


@pytest.mark.comprehensive
def test_exact_editable_vsz_handoff_cli_daily_mcp_and_cold_single_file_edit(tmp_path):
    import anyio
    from mcp import Client
    from socket_fixture_helpers import socket_directory
    from test_mcp_stdio import _parameters
    from test_task_control_native import _cli
    from test_task_semantic_creation import _single_table_spectral_control

    from sciplot_core.plot_backends.native_primitives import native_datasets
    from sciplot_core.plot_engine.service import PlotService
    from sciplot_core.project_lifecycle.context import load_head, project_query, read, repository_scope
    from sciplot_core.project_store import FileProjectStore

    origin = (tmp_path / "original").resolve()
    origin.mkdir()
    source, intent = _single_table_spectral_control(origin)
    request = origin / "request.json"
    request.write_text(json.dumps({"version": 1, "action": "create", "sources": [str(source)], "intent": intent,
                                   "formats": ["pdf"], "out": str(origin / "initial PDF")}))
    first = _cli("task", "start", "--request", request, "--task-dir", origin / "task")
    assert first["ready_to_use"] and first["result"]["revision"] == 0
    assert {path.suffix for path in (origin / "initial PDF").iterdir()} == {".pdf"}
    saved = first["result"]
    plot = Path(saved["plot"])
    store = FileProjectStore(plot.parent.parent)
    generation = store.snapshot()["generation"]

    def publication():
        service = PlotService(read_only_legacy=True)
        try:
            with repository_scope(service.repository, capabilities=service.capabilities), project_query(plot):
                return read(plot / "export-cache.json"), load_head(plot)["binding"]["ir_path"]
        finally:
            service.close()

    cache, ir_path = publication()
    artifact_files = {Path(path): sha for path, sha in cache["artifact_files"].items()}
    original = {source.resolve(): file_sha256(source), **artifact_files}
    assert all(path.is_relative_to(origin) and file_sha256(path) == sha for path, sha in original.items())
    assert Path(ir_path) in artifact_files
    expected = native_datasets(json.loads(Path(ir_path).read_text()))

    def cli(directory, revision=0, returncode=0, *extra):
        completed = subprocess.run([str(REPO_ROOT / "skill/scripts/sciplot"), "plot", "export", str(plot), "--direct",
            "--editable-vsz", "--output-dir", str(directory), "--plot-id", saved["plot_id"], "--revision", str(revision),
            "--json", *extra], cwd=REPO_ROOT, capture_output=True, text=True, timeout=90, check=False)
        assert completed.returncode == returncode, completed.stdout + completed.stderr
        return json.loads(completed.stdout)

    def verify(result, directory):
        assert result["status"] == "exported" and result["mode"] == "independent_native_snapshot"
        assert result["managed_project_included"] is False and len(result["native_state_sha256"]) == 64
        assert all(result[key] == saved[key] for key in ("plot_id", "revision", "scientific_hash", "presentation_hash"))
        record, = result["exports"]
        target, = directory.resolve().iterdir()
        assert target.name == "figure.vsz" and record == {
            "format": "editable_vsz", "path": str(target), "sha256": file_sha256(target)}
        return target

    cli_out = origin / "editable CLI"
    exported = cli(cli_out)
    original_vsz = verify(exported, cli_out)
    assert cli(cli_out, 0, 1)["reason_code"] == "figure_handoff_destination_exists"
    refused = origin / "refused"
    assert cli(refused, 1, 1)["reason_code"] == "figure_handoff_revision_conflict"
    assert cli(refused, 0, 2, "--tiff")["status"] == "failed" and not refused.exists()

    mcp_out = origin / "editable MCP"
    with socket_directory(prefix="sp-vsz-", dir="/tmp") as runtime:
        socket = Path(runtime) / "engine.sock"
        parameters = _parameters(cli=True, profile="daily")
        parameters.env = {**(parameters.env or {}), "SCIPLOT_ENGINE_SOCKET": str(socket)}

        async def run_mcp():
            async with Client(parameters, read_timeout_seconds=90) as client:
                handoff = {"output_dir": str(mcp_out), "plot_id": saved["plot_id"], "revision": 0,
                           "formats": ["editable_vsz"]}
                result = await client.call_tool("sciplot_plot_export", {"plot": str(plot), "handoff": handoff})
                assert not result.is_error, result.content
                verify(result.structured_content, mcp_out)
                assert result.structured_content["native_state_sha256"] == exported["native_state_sha256"]
                bad = await client.call_tool("sciplot_plot_export", {"plot": str(plot), "handoff": {
                    **handoff, "output_dir": str(refused), "formats": ["plotted_csv", "editable_vsz"]}})
                assert bad.is_error and not refused.exists()

        try:
            anyio.run(run_mcp)
        finally:
            if socket.exists():
                os.kill(read_owner(socket)["pid"], signal.SIGTERM)

    isolated = (tmp_path / "only the VSZ").resolve()
    isolated.mkdir()
    copied = isolated / original_vsz.name
    shutil.copy2(original_vsz, copied)
    assert file_sha256(copied) == exported["exports"][0]["sha256"]
    unavailable = tmp_path / "offline originals"
    origin.rename(unavailable)
    try:
        assert not any(path.exists() for path in [*original, plot, original_vsz, mcp_out])
        native = subprocess.run([sys.executable, "-c", _COLD_VEUSZ, str(copied), str(tmp_path / "re-export"),
                                 json.dumps(expected)], cwd=isolated, env=veusz_worker_environment(),
                                capture_output=True, text=True, timeout=60, check=False)
        assert native.returncode == 0, native.stdout + native.stderr
        pdf = json.loads(native.stdout)
        assert file_sha256(Path(pdf["path"])) == pdf["sha256"]
        assert file_sha256(copied) != exported["exports"][0]["sha256"]
    finally:
        unavailable.rename(origin)
    assert file_sha256(original_vsz) == exported["exports"][0]["sha256"]
    assert all(file_sha256(path) == sha for path, sha in original.items())
    assert publication() == (cache, ir_path) and store.snapshot()["generation"] == generation
