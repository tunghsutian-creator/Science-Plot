"""Owned synthetic create/style/undo/restart/export through actual public clients."""
import json
import os
from pathlib import Path
import shutil
import signal
import socket
import subprocess
import time

import anyio
from mcp import Client
from mcp.client.stdio import StdioServerParameters
import pytest
from socket_fixture_helpers import socket_directory
from managed_plot_helpers import request_for_source, patch

from sciplot_core._paths import REPO_ROOT
from sciplot_core.foundation.file_hashing import file_sha256
from sciplot_core.plot_engine.storage import load_head, read
from sciplot_core.plot_protocol.client import call
from sciplot_core.plot_protocol.paths import read_owner


@pytest.mark.comprehensive
def test_semantic_lifecycle_cli_rpc_mcp_undo_restart_and_cold_export(tmp_path):
    wire = request_for_source(tmp_path)
    source = Path(wire["data_binding"]["data_sources"][0]["path"])
    original_source = source.read_bytes()
    with socket_directory(prefix="splife-", dir="/tmp") as temporary:
        endpoint = Path(temporary) / "engine.sock"
        environment = {**os.environ, "SCIPLOT_ENGINE_SOCKET": str(endpoint)}
        owned_pid = None

        def cli(action, root=None, request=None):
            arguments = [str(REPO_ROOT / "skill/scripts/sciplot"), "plot", action]
            if root is not None:
                arguments.append(str(root))
            if request is not None:
                payload = tmp_path / (action + ".json")
                payload.write_text(json.dumps(request))
                arguments.extend(["--request", str(payload)])
            process = subprocess.run([*arguments, "--json"], cwd=REPO_ROOT, env=environment,
                                     capture_output=True, text=True, timeout=180, check=False)
            assert process.returncode == 0, process.stdout + process.stderr
            return json.loads(process.stdout)

        try:
            created = cli("create", request=wire)
            owned_pid = read_owner(endpoint)["pid"]
            assert created["ready_to_use"] and created["revision"] == 0
            root = Path(created["plot"])
            baseline = load_head(root)
            baseline_native = Path(baseline["binding"]["document"])
            baseline_state = read(baseline_native.parent / "build.json")["native_state_hash"]
            edited = call("plot.patch", {"plot": str(root), "request": patch(
                created, "lifecycle-style", "style.line.width", "1.2pt", "series:A")}, socket_path=endpoint)
            assert edited["revision"] == 1 and edited["ready_to_use"]

            async def undo():
                params = StdioServerParameters(command=str(REPO_ROOT / "skill/scripts/sciplot"), args=["mcp"],
                                               cwd=REPO_ROOT, env=environment)
                async with Client(params, read_timeout_seconds=180) as client:
                    result = await client.call_tool("sciplot_plot_rollback", {"plot": str(root), "request": {
                        "base_revision": 1, "target_revision": 0, "idempotency_key": "lifecycle-undo"}})
                    assert not result.is_error, result.content
                    reviewed = result.structured_content
                    assert reviewed["status"] == "needs_review"
                    result = await client.call_tool("sciplot_plot_decide", {
                        "plot": str(root), "request": reviewed["next_step"]["request"]})
                    assert not result.is_error, result.content
                    return result.structured_content

            undone = anyio.run(undo)
            assert undone["revision"] == 2 and undone["ready_to_use"]
            before_restart = load_head(root)
            assert before_restart["document"]["presentation"] == baseline["document"]["presentation"]
            assert before_restart["document"]["scientific_hash"] == baseline["document"]["scientific_hash"]
            history = {str(path): file_sha256(path) for path in root.glob("revisions/*.json")}
            assert len(history) == 3
            # Pre-migration journals have no additive normalized-command field.
            # A completed read must preserve their bytes; cold export may advance
            # export stages, while their original request/scientific evidence stays frozen.
            journal = Path(undone["evidence"])
            old = read(journal)
            old.pop("normalized_command")
            journal.write_text(json.dumps(old))
            old_bytes = journal.read_bytes()
            assert cli("export", root)["ready_to_use"]
            assert journal.read_bytes() == old_bytes
            original_command = {key: old[key] for key in ("request", "request_hash", "before", "document")}
            # Delete only disposable products; the immutable head/science/history survive.
            shutil.rmtree(Path(before_restart["binding"]["output"]))
            shutil.rmtree(root / "ir")
            old_pid = owned_pid
            os.kill(old_pid, signal.SIGTERM)
            deadline = time.monotonic() + 5
            while time.monotonic() < deadline:
                with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as connection:
                    try:
                        connection.connect(str(endpoint))
                    except (ConnectionRefusedError, FileNotFoundError):
                        break
                time.sleep(0.01)
            else:
                pytest.fail("The owned test daemon did not stop.")
            rebuilt = cli("export", root)
            owned_pid = read_owner(endpoint)["pid"]
            assert owned_pid != old_pid and rebuilt["ready_to_use"] and rebuilt["revision"] == 2
            assert rebuilt["scientific_hash"] == created["scientific_hash"]
            native = Path(load_head(root)["binding"]["document"])
            assert read(native.parent / "build.json")["native_state_hash"] == baseline_state
            assert {str(path): file_sha256(path) for path in root.glob("revisions/*.json")} == history
            recovered = read(journal)
            assert "normalized_command" not in recovered
            assert {key: recovered[key] for key in original_command} == original_command
            assert source.read_bytes() == original_source
            report = REPO_ROOT / ".tmp_verify/core-lifecycle/public-native-lifecycle.json"
            report.parent.mkdir(parents=True, exist_ok=True)
            report.write_text(json.dumps({"status": "passed", "plot": str(root), "revision": 2,
                "clients": ["CLI create", "RPC patch", "official MCP rollback/decide", "CLI export after daemon restart"],
                "scientific_hash": rebuilt["scientific_hash"], "native_state_equal": True,
                "raw_bytes_unchanged": True, "immutable_revisions_unchanged": True, "old_journal_readonly_bytes_unchanged": True,
                "old_journal_cold_replay_original_command_unchanged": True}, indent=2))
        finally:
            log = endpoint.with_suffix(endpoint.suffix + ".log")
            if log.is_file():
                destination = REPO_ROOT / ".tmp_verify/core-lifecycle/native-engine.log"
                destination.parent.mkdir(parents=True, exist_ok=True)
                destination.write_bytes(log.read_bytes())
            if owned_pid is None and endpoint.exists():
                owned_pid = read_owner(endpoint)["pid"]
            if owned_pid is not None:
                try:
                    os.kill(owned_pid, signal.SIGTERM)
                except ProcessLookupError:
                    pass
