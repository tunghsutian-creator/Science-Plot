"""Managed authority survives artifact deletion through the public thin clients."""

import json
import os
from pathlib import Path
import shutil
import signal
import subprocess
import tempfile
from time import perf_counter

import anyio
from mcp import Client
from mcp.client.stdio import StdioServerParameters
import pytest

from sciplot_core._paths import REPO_ROOT
from sciplot_core.foundation.file_hashing import file_sha256
from sciplot_core.plot_engine.storage import load_head
from sciplot_core.plot_protocol.client import _ping, call
from sciplot_core.plot_protocol.paths import read_owner
from managed_plot_helpers import request_for_source


@pytest.mark.comprehensive
@pytest.mark.parametrize("figure", [False, True], ids=["cartesian-v1", "figure-v2"])
def test_public_cli_create_and_mcp_rebuild_from_canonical_document(tmp_path, figure):
    from test_figure_document import request_for_figure

    request = request_for_figure(tmp_path) if figure else request_for_source(tmp_path)
    source = Path(request["data_binding"]["data_sources"][0]["path"])
    source_hash = file_sha256(source)
    request_file = tmp_path / "managed-create.json"
    request_file.write_text(json.dumps(request))
    timings = []
    with tempfile.TemporaryDirectory(prefix="spmanaged-", dir="/tmp") as temporary:
        socket = Path(temporary) / "engine.sock"
        environment = {**os.environ, "SCIPLOT_ENGINE_SOCKET": str(socket)}
        engine_pid = None
        try:
            started = perf_counter()
            process = subprocess.run([str(REPO_ROOT / "skill/scripts/sciplot"), "plot", "create",
                "--request", str(request_file), "--json"], cwd=REPO_ROOT, env=environment,
                capture_output=True, text=True, timeout=180)
            timings.append({"case": "cli_managed_create_cold", "seconds": round(perf_counter() - started, 6)})
            assert process.returncode == 0, process.stdout + process.stderr
            created = json.loads(process.stdout)
            assert created["ready_to_use"] and created["plot_type"] == "ManagedPlot", created
            engine_pid = read_owner(socket)["pid"]
            root = Path(created["plot"])
            opened = call("project.open", {"target": str(root)}, socket_path=socket)
            described = call("plot.describe", {"plot": str(root)}, socket_path=socket)
            assert opened["plot_id"] == described["plot_id"] == created["plot_id"]
            assert described["authority"]["source_of_truth"] == "sciplot_document"
            assert described["authority"]["rebuild_from_document"] is True
            if figure:
                assert described["plot_ir_version"] == 2 and created["publication_qa"]["native_text_checked"]
            head = load_head(root)
            binding = head["binding"]
            native = Path(binding["document"])
            ir_path = Path(binding["ir_path"])
            ir = json.loads(ir_path.read_text())
            pixels = (native.parent / "preview.png").read_bytes()
            native_state = json.loads((native.parent / "build.json").read_text())["native_state_hash"]
            authority_paths = [root / "head.json", root / "managed-creation.json", Path(binding["canonical_document"])]
            authority_paths.extend(root.glob("revisions/*.json"))
            authority_before = {str(path): file_sha256(path) for path in authority_paths}
            shutil.rmtree(Path(binding["output"]))
            shutil.rmtree(root / "ir")
            dirty = call("plot.describe", {"plot": str(root)}, socket_path=socket)
            assert dirty["artifact_status"] == "missing" and dirty["next_step"]["action"] == "plot.export"

            async def rebuild_and_replay():
                parameters = StdioServerParameters(command=str(REPO_ROOT / "skill/scripts/sciplot"),
                    args=["mcp"], cwd=REPO_ROOT, env=environment)
                async with Client(parameters, read_timeout_seconds=180) as mcp:
                    started = perf_counter()
                    result = await mcp.call_tool("sciplot_plot_export", {"plot": str(root)})
                    timings.append({"case": "mcp_managed_rebuild_warm", "seconds": round(perf_counter() - started, 6)})
                    assert not result.is_error, result.content
                    rebuilt = result.structured_content
                    started = perf_counter()
                    replay = await mcp.call_tool("sciplot_plot_create", {"request": request})
                    timings.append({"case": "mcp_managed_create_same_key", "seconds": round(perf_counter() - started, 6)})
                    assert not replay.is_error, replay.content
                    return rebuilt, replay.structured_content

            rebuilt, replay = anyio.run(rebuild_and_replay)
            for receipt in (rebuilt, replay):
                assert receipt["ready_to_use"] and receipt["revision"] == 0, receipt
                assert receipt["plot_id"] == created["plot_id"]
                assert receipt["scientific_hash"] == created["scientific_hash"]
                assert receipt["presentation_hash"] == created["presentation_hash"]
            assert json.loads(ir_path.read_text()) == ir
            assert (native.parent / "preview.png").read_bytes() == pixels
            assert json.loads((native.parent / "build.json").read_text())["native_state_hash"] == native_state
            assert {str(path): file_sha256(path) for path in authority_paths} == authority_before
            assert len(list((root / "revisions").glob("*.json"))) == 1
            current = call("plot.describe", {"plot": str(root)}, socket_path=socket)
            assert current["status"] == "current" and current["dependencies"]["invalidated"] == []
            assert _ping(socket, 3)["pid"] == engine_pid and file_sha256(source) == source_hash
            evidence = REPO_ROOT / (".tmp_verify/figure_grammar_20261008/protocol_acceptance.json" if figure else
                                    ".tmp_verify/managed_architecture_20261008/protocol_acceptance.json")
            evidence.parent.mkdir(parents=True, exist_ok=True)
            evidence.write_text(json.dumps({"status": "passed", "transport": "CLI + official MCP -> persistent UNIX engine",
                "plot": str(root), "plot_type": "ManagedPlot", "server_pid": engine_pid, "server_pid_stable": True,
                "source_unchanged": True, "canonical_authority_unchanged": True, "scientific_hash_unchanged": True,
                "generated_native_ir_preview_exports_deleted": True, "rebuilt_from_canonical": True,
                "ir_equal": True, "pixels_equal": True, "native_state_equal": True, "revision": 0,
                "same_key_creation_reuses_document": True, "measurements": timings,
                "measurement_scope": "Local calls only; CLI includes startup, MCP excludes initialization. No AI latency measured."}, indent=2))
        finally:
            if engine_pid is None and socket.exists():
                engine_pid = read_owner(socket)["pid"]
            if engine_pid is not None:
                os.kill(engine_pid, signal.SIGTERM)
