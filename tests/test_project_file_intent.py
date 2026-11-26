"""A relocation-safe typed text edit publishes once through public transports."""

from contextlib import closing
import json
import os
from pathlib import Path
import shutil
import signal
import subprocess
import sys

import pytest

from sciplot_core._paths import REPO_ROOT
from sciplot_core.foundation.file_hashing import file_sha256
from sciplot_core.plot_engine.errors import EngineError
from sciplot_core.plot_engine.service import PlotService
from sciplot_core.plot_protocol.paths import read_owner
from sciplot_core.project_lifecycle import project_file
from sciplot_core.project_lifecycle.project_file import ProjectFileSaveUnconfirmed, create_project_file, open_project_file
from sciplot_core.project_store.repository import FileProjectStore


@pytest.mark.comprehensive
def test_relocated_project_file_axis_edit_is_saved_once_through_cli_and_daily_mcp(tmp_path, monkeypatch):
    import anyio
    from mcp import Client
    from socket_fixture_helpers import socket_directory
    from test_figure_document import request_for_figure
    from test_mcp_stdio import _parameters

    root = tmp_path.resolve()
    original = root / "original"
    original.mkdir()
    project = original / "project"
    project.mkdir()
    store = FileProjectStore(project)
    store.snapshot(import_legacy=True)
    request = request_for_figure(original)
    raw = (original / "figure.csv").read_bytes()
    with closing(PlotService()) as service:
        saved = service.create(request, project=project)
        assert saved["ready_to_use"], saved
    snapshot = store.snapshot()
    archive = original / "模量数据.sciplot"
    initial = create_project_file(archive, store, expected_generation=snapshot["generation"])
    folder = root / "移入 (测试)"
    folder.mkdir()
    moved = archive.rename(folder / "新料.sciplot")
    shutil.rmtree(original)
    scratch = root / "scratch"
    scratch.mkdir()
    env = {**os.environ, "TMPDIR": str(scratch), "SCIPLOT_PYTHON": sys.executable,
           "MPLCONFIGDIR": str(root / "mpl")}
    intent = {"mode": "apply", "plot_id": saved["plot_id"], "base_revision": 0,
              "idempotency_key": "test-axis", "property": "axis.label",
              "target_id": "axis:xb", "value": "Frequency, Hz"}
    request_json = root / "intent.json"

    def cli(operation, *args, code=0):
        run = subprocess.run(
            [str(REPO_ROOT / "skill/scripts/sciplot"), "plot", operation, *map(str, args), "--direct", "--json"],
            env=env, cwd=root, capture_output=True, text=True, timeout=90, check=False,
        )
        assert run.returncode == code, run.stdout + run.stderr
        assert not list(scratch.iterdir())
        assert str(scratch) not in run.stdout
        return json.loads(run.stdout)

    request_json.write_text(json.dumps({**intent, "mode": "plan"}))
    plan = cli("intent", moved.relative_to(root), "--request", request_json)
    assert not plan["saved"] and plan["project_file"] == str(moved) and plan["status"] == "ready"
    assert plan["before"] == "Frequency (Hz)" and plan["after"] == intent["value"]
    assert file_sha256(moved) == initial.sha256

    with socket_directory(prefix="sp-file-edit-", dir="/tmp") as directory:
        socket = Path(directory) / "engine.sock"
        parameters = _parameters(cli=True, profile="daily")
        parameters.env = {**(parameters.env or {}), **env, "SCIPLOT_ENGINE_SOCKET": str(socket)}

        async def check_mcp():
            async with Client(parameters, read_timeout_seconds=90) as client:
                reply = await client.call_tool("sciplot_plot_intent", {"plot": str(moved), "request": intent})
                assert not reply.is_error, reply.content
                assert str(scratch) not in str(reply.structured_content)
                return reply.structured_content

        try:
            result = anyio.run(check_mcp)
        finally:
            if socket.exists():
                os.kill(read_owner(socket)["pid"], signal.SIGTERM)

    assert result == {"kind": "sciplot_project_file_intent", "version": 1, "status": "saved", "saved": True,
                      "project_file": str(moved), "project_id": initial.project_id, "plot_id": saved["plot_id"],
                      "idempotency_key": "test-axis", "revision": 1, "current_revision": 1,
                      "scientific_hash": saved["scientific_hash"], "presentation_hash": result["presentation_hash"]}
    assert result["presentation_hash"] != saved["presentation_hash"]
    published = file_sha256(moved)
    assert published != initial.sha256

    request_json.write_text(json.dumps(intent))
    assert cli("intent", moved, "--request", request_json) == {**result, "status": "already_saved"}
    request_json.write_text(json.dumps({**intent, "value": "Wrong edit"}))
    assert cli("intent", moved, "--request", request_json, code=1)["reason_code"] == "document_idempotency_conflict"
    request_json.write_text(json.dumps({**intent, "idempotency_key": "new-stale-key"}))
    assert cli("intent", moved, "--request", request_json, code=1)["reason_code"] == "document_revision_conflict"
    opened = cli("open", moved, "--figure", saved["plot_id"])
    assert opened["revision"] == 1 and opened["scientific_hash"] == saved["scientific_hash"]
    assert opened["presentation_hash"] == result["presentation_hash"]

    with open_project_file(moved, workspace_parent=scratch) as session:
        [(source_id, versions)] = session.store.snapshot()["sources"].items()
        [version] = versions
        assert session.store.resolve_source(source_id, version).read_bytes() == raw
    assert not original.exists() and not list(scratch.iterdir())
    assert list(folder.iterdir()) == [moved] and file_sha256(moved) == published

    next_intent = {**intent, "base_revision": 1, "idempotency_key": "second-axis", "value": "Frequency / Hz"}
    true_publish = project_file._publish

    def refuse_replace(*args):
        raise OSError("publication stopped before replace")

    def lose_ack(path, stage, candidate, baseline):
        true_publish(path, stage, candidate, baseline)
        raise ProjectFileSaveUnconfirmed(candidate.receipt)

    with closing(PlotService()) as service, monkeypatch.context() as fault:
        fault.setattr(project_file, "_publish", refuse_replace)
        with pytest.raises(EngineError) as refused:
            service.intent(moved, next_intent)
        assert refused.value.reason_code == "project_file_save_failed"
        assert file_sha256(moved) == published and cli("open", moved)["revision"] == 1

        fault.setattr(project_file, "_publish", lose_ack)
        with pytest.raises(EngineError) as unconfirmed:
            service.intent(moved, next_intent)
        assert unconfirmed.value.reason_code == "project_file_save_unconfirmed"
        assert unconfirmed.value.repair["idempotency_key"] == next_intent["idempotency_key"]
        assert unconfirmed.value.repair["revision"] == 2
        observed = file_sha256(moved)
        assert observed != published
        request_json.write_text(json.dumps(next_intent))
        retry = cli("intent", moved, "--request", request_json)
        assert retry["status"] == "already_saved" and retry["revision"] == 2
        assert file_sha256(moved) == observed
    assert cli("open", moved)["revision"] == 2
    assert list(folder.iterdir()) == [moved]
