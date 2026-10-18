"""Bound native figures continue through CLI, official MCP and the UNIX engine."""

import json
import os
from pathlib import Path
import signal
import subprocess
import tempfile

import anyio
from mcp import Client
from mcp.client.stdio import StdioServerParameters
import pytest

from sciplot_core._paths import REPO_ROOT
from sciplot_core.foundation.file_hashing import file_sha256
from sciplot_core.plot_protocol.paths import read_owner
from test_native_suite_operations import suite as suite


@pytest.mark.comprehensive
def test_native_object_delta_and_selected_export_share_public_transports(suite, tmp_path):
    _workspace, _delivery, source, prepared, manifest = suite
    main, optional = [Path(item["path"]) for item in manifest["documents"]]
    optional.rename(tmp_path / "parked_optional.vsz")
    Path(manifest["native_result"]["figures"][1]["spec_path"]).rename(tmp_path / "parked_optional.spec.json")
    protected = {name: file_sha256(Path(name)) for name in [str(source), str(prepared),
        *manifest["documents"][1]["exports"], str(tmp_path / "parked_optional.vsz"),
        str(tmp_path / "parked_optional.spec.json")]}
    with tempfile.TemporaryDirectory(prefix="sp-native-", dir="/tmp") as temporary:
        socket = Path(temporary) / "engine.sock"
        environment = {**os.environ, "SCIPLOT_ENGINE_SOCKET": str(socket)}
        engine_pid = None
        try:
            process = subprocess.run([str(REPO_ROOT / "skill/scripts/sciplot"), "plot", "open", str(main),
                "--scope", "summary", "--json"], cwd=REPO_ROOT, env=environment,
                capture_output=True, text=True, timeout=180)
            assert process.returncode == 0, process.stdout + process.stderr
            opened = json.loads(process.stdout)
            engine_pid = read_owner(socket)["pid"]
            assert opened["plot_type"] == "LegacyPlot"
            assert opened["object_operations"]["revision_semantics"] == "content_bound"
            assert opened["object_operations"]["patch"]["available"] is True
            request = {"plot_id": opened["plot_id"], "base_revision": opened["revision"],
                "idempotency_key": "public-native-note", "intent_class": "presentation", "changes": [
                {"op": "set", "target": ["annotation:graph1:note_0"],
                 "property": "annotation.y", "value": .82}]}

            async def scenario():
                parameters = StdioServerParameters(command=str(REPO_ROOT / "skill/scripts/sciplot"),
                    args=["mcp"], cwd=REPO_ROOT, env=environment)
                async with Client(parameters, read_timeout_seconds=180) as client:
                    described = await client.call_tool("sciplot_plot_describe", {"plot": str(main),
                        "description": {"scope": "edit", "target": "annotation:graph1:note_0", "property": "annotation.y"}})
                    assert not described.is_error, described.content
                    assert described.structured_content["current_value"] == .94
                    preview = await client.call_tool("sciplot_plot_patch", {"plot": str(main), "request": request})
                    assert not preview.is_error, preview.content
                    payload = preview.structured_content
                    assert payload["status"] == "needs_review"
                    committed = await client.call_tool("sciplot_plot_decide", {"plot": str(main),
                        "request": payload["next_step"]["request"]})
                    assert not committed.is_error, committed.content
                    result = committed.structured_content
                    assert result["status"] == "complete" and result["ready_to_use"] is True
                    assert result["scientific_hash_changed"] is False
                    assert result["transform_execution"]["executed"] == []
                    exported = await client.call_tool("sciplot_plot_export", {"plot": str(main)})
                    assert not exported.is_error, exported.content
                    assert exported.structured_content["selected_figures"] == ["Main"]
                    return result

            committed = anyio.run(scenario)
            recovery = {key: request[key] for key in ("plot_id", "base_revision", "idempotency_key")}
            recovery_path = tmp_path / "resume.json"
            recovery_path.write_text(json.dumps(recovery))
            replay = subprocess.run([str(REPO_ROOT / "skill/scripts/sciplot"), "plot", "resume", str(main),
                "--request", str(recovery_path), "--json"], cwd=REPO_ROOT, env=environment,
                capture_output=True, text=True, timeout=180)
            assert replay.returncode == 0, replay.stdout + replay.stderr
            resumed = json.loads(replay.stdout)
            assert resumed["replayed"] is True and resumed["revision"] == committed["revision"]
            assert resumed["ready_to_use"] is True
            assert {name: file_sha256(Path(name)) for name in protected} == protected
        finally:
            if engine_pid is None and socket.exists():
                engine_pid = read_owner(socket)["pid"]
            if engine_pid is not None:
                os.kill(engine_pid, signal.SIGTERM)
