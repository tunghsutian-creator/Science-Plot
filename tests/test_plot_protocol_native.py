"""Real CLI creation and official MCP replay through one persistent native engine."""

from socket_fixture_helpers import socket_directory

import json
import os
import signal
import socket as socket_module
import subprocess
import time
from pathlib import Path
from time import perf_counter

import anyio
import pytest
from mcp import Client
from mcp.client.stdio import StdioServerParameters

from sciplot_core._paths import REPO_ROOT
from sciplot_core.foundation.file_hashing import file_sha256
from sciplot_core.foundation.source_tree import source_tree_sha256
from sciplot_core.plot_engine.storage import load_head
from sciplot_core.plot_protocol import rpc
from sciplot_core.plot_protocol.client import _ping, call
from sciplot_core.plot_protocol.paths import read_owner


def _decoded_json_bytes(value):
    """Measure a decoded result, not a transport frame or client-visible text."""
    return len(json.dumps(value, ensure_ascii=False, separators=(",", ":")).encode("utf-8"))


@pytest.mark.focused
def test_decoded_result_size_is_compact_utf8_not_an_envelope():
    assert _decoded_json_bytes({"label": "α"}) == len('{"label":"α"}'.encode())


@pytest.mark.comprehensive
def test_native_cli_create_socket_patch_and_official_mcp_replay(tmp_path):
    source = tmp_path / "UVvis.csv"
    source.write_text("Wavelength,Absorbance,Wavelength,Absorbance\nnm,a.u.,nm,a.u.\n"
                      "E2,E2,E4,E4\n400,1,400,2\n450,2,450,3\n500,3,500,4\n")
    source_hash = file_sha256(source)
    measurements = []
    with socket_directory(prefix="spnative-", dir="/tmp") as temporary:
        socket = Path(temporary) / "engine.sock"
        environment = {**os.environ, "SCIPLOT_ENGINE_SOCKET": str(socket)}
        engine_pid = None

        def cli(label, arguments, *, success=True):
            started = perf_counter()
            process = subprocess.run([str(REPO_ROOT / "skill/scripts/sciplot"), "plot", *arguments, "--json"],
                                     env=environment, cwd=REPO_ROOT, capture_output=True, text=True, timeout=180,
                                     check=False)
            measurements.append({"case": label, "seconds": round(perf_counter() - started, 6),
                                 "cli_stdout_utf8_bytes": len(process.stdout.encode("utf-8")),
                                 "exit_code": process.returncode})
            assert process.returncode == (0 if success else 1), process.stdout + process.stderr
            return json.loads(process.stdout)

        try:
            request_file = tmp_path / "create.json"
            request_file.write_text(json.dumps({"source": str(source), "rule_id": "uvvis_spectrum",
                                                "idempotency_key": "native-create"}))
            created = cli("cli_create_cold_engine", ["create", "--request", str(request_file)])
            assert created["status"] == "complete" and created["ready_to_use"] is True, created
            engine_pid = read_owner(socket)["pid"]
            plot = Path(created["plot"])
            opened = cli("cli_open_warm_engine", ["open", str(plot)])
            described = cli("cli_describe_warm_engine", ["describe", str(plot)])
            assert opened["plot_id"] == described["plot_id"] == created["plot_id"]
            assert described["status"] == "current" and described["revision"] == 0
            scientific_hash = described["scientific_hash"]
            for identifier in ("series:E2", "series:E4"):
                assert identifier in described["objects"]
            request = {"plot_id": created["plot_id"], "base_revision": 0,
                       "idempotency_key": "native-width", "intent_class": "presentation", "changes": [
                           {"op": "set", "target": ["series:E2", "series:E4"], "property": "style.line.width", "value": "0.7pt"}]}
            patch_file = tmp_path / "patch.json"
            patch_file.write_text(json.dumps(request))
            patched = cli("cli_patch_warm_engine", ["patch", str(plot), "--request", str(patch_file)])
            assert patched["status"] == "complete" and patched["revision"] == 1 and patched["ready_to_use"] is True
            assert patched["scientific_hash"] == scientific_hash and patched["scientific_hash_changed"] is False
            transaction = json.loads(Path(patched["evidence"]).read_text())
            assert transaction["review"]["scientific_audit"]["status"] == "passed"
            before_replay = {str(path): file_sha256(path) for path in plot.glob("revisions/*.json")}

            async def replay_via_mcp():
                parameters = StdioServerParameters(command=str(REPO_ROOT / "skill/scripts/sciplot"),
                    args=["mcp"], cwd=REPO_ROOT, env=environment)
                async with Client(parameters, read_timeout_seconds=180) as mcp:
                    started = perf_counter()
                    result = await mcp.call_tool("sciplot_plot_patch", {"plot": str(plot), "request": request})
                    measurements.append({"case": "mcp_same_key_replay", "seconds": round(perf_counter() - started, 6),
                        "decoded_result_compact_json_utf8_bytes": _decoded_json_bytes(result.structured_content)})
                    assert not result.is_error, result.content
                    return result.structured_content

            replay = anyio.run(replay_via_mcp)
            assert replay["replayed"] is True and replay["revision"] == 1 and replay["ready_to_use"] is True
            assert {str(path): file_sha256(path) for path in plot.glob("revisions/*.json")} == before_replay
            assert _ping(socket, 3)["pid"] == engine_pid
            warm_descriptions = []
            for index in range(3):
                started = perf_counter()
                current = call("plot.describe", {"plot": str(plot)}, socket_path=socket)
                measurements.append({"case": f"rpc_describe_{index + 1}", "seconds": round(perf_counter() - started, 6),
                    "decoded_result_compact_json_utf8_bytes": _decoded_json_bytes(current)})
                assert current["scientific_hash"] == scientific_hash and current["revision"] == 1
                warm_descriptions.append(current)
            assert warm_descriptions[1:] == warm_descriptions[:-1]
            unknown = tmp_path / "unclassified.csv"
            unknown.write_text("X,Y\nunit,unit\nE2,E2\n0,1\n1,2\n")
            unknown_request = tmp_path / "unknown.json"
            unknown_request.write_text(json.dumps({"source": str(unknown), "profile": str(tmp_path / "missing-profile.json"),
                                                   "idempotency_key": "scientific-choice"}))
            question = cli("cli_unresolved_scientific_input", ["create", "--request", str(unknown_request)])
            assert question["status"] == "needs_input" and question["question"]
            state = json.loads((Path(question["plot"]) / "task/task.json").read_text())
            assert state["source_sha256"] == source_tree_sha256(unknown)
            unknown.write_text(unknown.read_text() + "2,3\n")
            response = tmp_path / "changed-source-answer.json"
            response.write_text(json.dumps({"response": {"rule_id": "uvvis_spectrum"}}))
            rejected = cli("cli_changed_source_answer", ["decide", question["plot"], "--request", str(response)], success=False)
            assert (rejected.get("reason_code") or (rejected.get("blocker") or {}).get("reason_code")) == "source_changed", rejected
            assert file_sha256(source) == source_hash
            assert _ping(socket, 3)["pid"] == engine_pid
            report = {"status": "passed", "transport": "CLI + official MCP stdio -> same persistent UNIX engine",
                      "server_pid": engine_pid, "server_pid_stable": True, "plot": str(plot),
                      "creation_ready": True, "revision": 1, "idempotent_replay": True,
                      "source_unchanged": True, "scientific_hash_unchanged": True, "native_scientific_audit": "passed",
                      "unresolved_science_source_bound": True, "changed_source_answer": "rejected",
                      "question_trigger": "Missing explicit profile requires a source-bound rule choice.",
                      "measurements": measurements,
                      "measurement_scope": "Local adapter observations only. CLI time includes interpreter startup and bytes are actual stdout. MCP time excludes stdio initialization; MCP and RPC byte counts are compact JSON re-encodings of decoded result objects, not wire bytes or client-visible text. The three warm RPC describe samples alone are same-operation repeats. External-client tokens, billed cost, and end-to-end latency are unknown."}
            output = REPO_ROOT / ".tmp_verify/document_migration_20261007/transport_native_acceptance.json"
            output.parent.mkdir(parents=True, exist_ok=True)
            output.write_text(json.dumps(report, ensure_ascii=False, indent=2))
        finally:
            if engine_pid is None and socket.exists():
                engine_pid = read_owner(socket)["pid"]
            if engine_pid is not None:
                os.kill(engine_pid, signal.SIGTERM)


@pytest.mark.comprehensive
def test_native_mutation_lost_reply_and_daemon_restart_replay_once(tmp_path):
    from managed_plot_helpers import patch, request_for_source

    create_request = request_for_source(tmp_path)
    source = Path(create_request["data_binding"]["data_sources"][0]["path"])
    source_hash = file_sha256(source)
    with socket_directory(prefix="sprecovery-", dir="/tmp") as temporary:
        socket_path = Path(temporary) / "engine.sock"
        engine_pid = None
        try:
            created = call("plot.create", {"request": create_request}, socket_path=socket_path)
            assert created["ready_to_use"], created
            engine_pid = read_owner(socket_path)["pid"]
            root = Path(created["plot"])
            described = call("plot.describe", {"plot": str(root)}, socket_path=socket_path)
            edit = patch(described, "lost-reply-width", "style.line.width", "1.2pt", "series:A")
            params = {"plot": str(root), "request": edit}
            request_id = "lost-mutation-reply"
            # Send the real mutation, then lose the caller's reply channel.
            # A later explicit retry must recover its durable outcome once.
            with socket_module.socket(socket_module.AF_UNIX, socket_module.SOCK_STREAM) as connection:
                connection.connect(str(socket_path))
                connection.sendall(rpc.encode({"jsonrpc": "2.0", "id": request_id,
                                               "method": "plot.patch", "params": params}))
            replayed = call("plot.patch", params, socket_path=socket_path, request_id=request_id)
            assert replayed["ready_to_use"] and replayed["replayed"] and replayed["revision"] == 1, replayed
            assert replayed["scientific_hash"] == created["scientific_hash"]
            head = load_head(root)
            native = Path(head["binding"]["document"])
            native_hash = file_sha256(native)
            canonical_paths = [root / "head.json", *root.glob("revisions/*.json")]
            assert len(canonical_paths) == 3  # Head plus revisions zero and one.
            canonical_before = {str(path): file_sha256(path) for path in canonical_paths}
            first_pid = engine_pid
            # Replay must survive abrupt death as well as a lost response.
            os.kill(first_pid, signal.SIGKILL)
            deadline = time.monotonic() + 5
            while True:
                with socket_module.socket(socket_module.AF_UNIX, socket_module.SOCK_STREAM) as connection:
                    try:
                        connection.connect(str(socket_path))
                    except (ConnectionRefusedError, FileNotFoundError):
                        break
                assert time.monotonic() < deadline, "The terminated daemon still accepts connections."
                time.sleep(0.01)
            restarted = call("plot.patch", params, socket_path=socket_path, request_id=request_id)
            engine_pid = read_owner(socket_path)["pid"]
            assert engine_pid != first_pid and _ping(socket_path, 3)["pid"] == engine_pid
            assert restarted["ready_to_use"] and restarted["replayed"] and restarted["revision"] == 1, restarted
            assert restarted["scientific_hash"] == created["scientific_hash"]
            assert {str(path): file_sha256(path) for path in canonical_paths} == canonical_before
            assert len(list(root.glob("revisions/*.json"))) == 2
            assert file_sha256(native) == native_hash and file_sha256(source) == source_hash
            evidence = REPO_ROOT / ".tmp_verify/protocol_mac_20261013/native_lost_reply_recovery.json"
            evidence.parent.mkdir(parents=True, exist_ok=True)
            evidence.write_text(json.dumps({"status": "passed", "plot": str(root),
                "transport": "Actual AF_UNIX with native managed compilation",
                "lost_reply_explicit_same_request_replay": True, "daemon_restart_same_request_replay": True,
                "request_id": request_id, "revision": 1, "revision_count": 2,
                "first_server_pid": first_pid, "restarted_server_pid": engine_pid,
                "native_unchanged_on_restart_replay": True, "canonical_history_unchanged_on_restart_replay": True,
                "scientific_hash_unchanged": True, "source_unchanged": True}, indent=2))
        finally:
            if engine_pid is not None:
                try:
                    os.kill(engine_pid, signal.SIGTERM)
                except ProcessLookupError:
                    pass


@pytest.mark.comprehensive
def test_native_frozen_recovery_survives_lost_reply_and_restart_via_cli_mcp(tmp_path, monkeypatch):
    """Only three original binding fields cross the recovery transports."""
    from managed_plot_helpers import patch, request_for_source
    from sciplot_core.plot_protocol import client
    from sciplot_core.plot_protocol.paths import TransportError

    create_request = request_for_source(tmp_path)
    source = Path(create_request["data_binding"]["data_sources"][0]["path"])
    source_hash = file_sha256(source)
    with socket_directory(prefix="spr2-", dir="/tmp") as temporary:
        socket_path = Path(temporary) / "engine.sock"
        environment = {**os.environ, "SCIPLOT_ENGINE_SOCKET": str(socket_path)}
        engine_pid = None
        discarded = []
        real_socket = socket_module.socket

        class DropReplySocket:
            def __init__(self, *args):
                self.connection = real_socket(*args)

            def __enter__(self):
                return self

            def __exit__(self, *_args):
                self.connection.close()

            def connect(self, path):
                self.connection.connect(path)

            def settimeout(self, value):
                self.connection.settimeout(value)

            def sendall(self, payload):
                self.connection.sendall(payload)

            def recv(self, limit):
                # The real daemon finished its request. Discard its actual
                # response bytes and close the caller channel before delivery.
                discarded.append(self.connection.recv(limit))
                self.connection.close()
                return b""

        def lose_reply(params):
            with monkeypatch.context() as controlled:
                controlled.setattr(client.socket, "socket", DropReplySocket)
                with pytest.raises(TransportError) as failed:
                    client._exchange(socket_path, {"jsonrpc": "2.0", "id": "controlled-loss",
                        "method": "plot.patch", "params": params}, 180)
            assert failed.value.reason_code == "transport_outcome_unknown"
            assert failed.value.repair["automatic_retry"] is False
            assert failed.value.repair["idempotency_key"] == params["request"]["idempotency_key"]
            assert discarded[-1], "No real daemon response was available to lose."
            return failed.value.repair

        def cli_resume(root, request):
            path = tmp_path / "resume.json"
            path.write_text(json.dumps(request))
            result = subprocess.run([str(REPO_ROOT / "skill/scripts/sciplot"), "plot", "resume", str(root),
                "--request", str(path), "--json"], env=environment, cwd=REPO_ROOT,
                capture_output=True, text=True, timeout=180, check=False)
            assert result.returncode == 0, result.stdout + result.stderr
            return json.loads(result.stdout)

        def stop_abruptly(pid):
            os.kill(pid, signal.SIGKILL)
            deadline = time.monotonic() + 5
            while time.monotonic() < deadline:
                with real_socket(socket_module.AF_UNIX, socket_module.SOCK_STREAM) as probe:
                    try:
                        probe.connect(str(socket_path))
                    except (ConnectionRefusedError, FileNotFoundError):
                        return
                time.sleep(.01)
            pytest.fail("The owned terminated daemon still accepts connections.")

        try:
            created = call("plot.create", {"request": create_request}, socket_path=socket_path)
            assert created["ready_to_use"] and created["revision"] == 0
            engine_pid = read_owner(socket_path)["pid"]
            root = Path(created["plot"])
            described = call("plot.describe", {"plot": str(root)}, socket_path=socket_path)
            native = Path(load_head(root)["binding"]["document"])
            initial_native_hash = file_sha256(native)
            review = patch(described, "lost-review", "axis.limits", [0, 4], "axis:x")
            lose_reply({"plot": str(root), "request": review})
            frozen = call("plot.describe", {"plot": str(root), "description": {"scope": "summary"}}, socket_path=socket_path)
            assert frozen["revision"] == 0 and frozen["pending"]["phase"] == "needs_review"
            assert frozen["next_step"]["action"] == "plot.decide"
            assert frozen["recovery"]["preview"]["path"]
            recovery = {"plot_id": created["plot_id"], "base_revision": 0, "idempotency_key": "lost-review"}
            assert file_sha256(native) == initial_native_hash and len(list(root.glob("revisions/*.json"))) == 1
            first_pid = engine_pid
            stop_abruptly(engine_pid)
            resumed = cli_resume(root, recovery)
            engine_pid = read_owner(socket_path)["pid"]
            assert engine_pid != first_pid
            assert resumed["status"] == "needs_review" and resumed["preview"] == frozen["recovery"]["preview"]
            assert file_sha256(native) == initial_native_hash and load_head(root)["document"]["revision"] == 0
            accepted = call("plot.decide", {"plot": str(root), "request": frozen["next_step"]["request"]}, socket_path=socket_path)
            assert accepted["ready_to_use"] and accepted["revision"] == 1
            assert accepted["scientific_hash"] == created["scientific_hash"]
            described = call("plot.describe", {"plot": str(root)}, socket_path=socket_path)
            edit = patch(described, "lost-width", "style.line.width", "1.2pt", "series:A")
            repair = lose_reply({"plot": str(root), "request": edit})
            summary = call("plot.describe", {"plot": str(root), "description": {"scope": "summary"}}, socket_path=socket_path)
            assert summary["revision"] == 2 and summary["recovery"]["phase"] == "complete"
            assert repair["base_revision"] == 1
            recovery = summary["recovery"]["next_step"]["request"]
            assert recovery == {"plot_id": created["plot_id"], "base_revision": 1, "idempotency_key": "lost-width"}
            canonical = [root / "head.json", *root.glob("revisions/*.json")]
            canonical_hashes = {str(path): file_sha256(path) for path in canonical}
            native = Path(load_head(root)["binding"]["document"])
            native_hash = file_sha256(native)

            async def mcp_resume():
                parameters = StdioServerParameters(command=str(REPO_ROOT / "skill/scripts/sciplot"),
                    args=["mcp"], cwd=REPO_ROOT, env=environment)
                async with Client(parameters, read_timeout_seconds=180) as mcp:
                    result = await mcp.call_tool("sciplot_plot_resume", {"plot": str(root), "request": recovery})
                    assert not result.is_error, result.content
                    return result.structured_content

            replayed = anyio.run(mcp_resume)
            assert replayed["ready_to_use"] and replayed["replayed"] and replayed["revision"] == 2
            stop_abruptly(engine_pid)
            restarted = cli_resume(root, recovery)
            engine_pid = read_owner(socket_path)["pid"]
            assert restarted["ready_to_use"] and restarted["replayed"] and restarted["revision"] == 2
            assert len(list(root.glob("revisions/*.json"))) == 3
            assert {str(path): file_sha256(path) for path in canonical} == canonical_hashes
            assert file_sha256(native) == native_hash and file_sha256(source) == source_hash
            evidence = REPO_ROOT / ".tmp_verify/round2-recovery/native-transport.json"
            evidence.parent.mkdir(parents=True, exist_ok=True)
            evidence.write_text(json.dumps({"status": "passed", "plot": str(root),
                "transport": "Actual AF_UNIX cold daemon + CLI resume + official MCP resume",
                "lost_reply_count": len(discarded), "review_not_auto_accepted": True,
                "frozen_preview_recovered_after_restart": True, "revision": 2, "revision_count": 3,
                "semantic_history_unchanged_on_replays": True, "native_unchanged_on_replays": True,
                "scientific_hash_unchanged": True, "source_unchanged": True,
                "first_daemon_pid": first_pid, "last_daemon_pid": engine_pid}, indent=2))
        finally:
            if engine_pid is not None:
                try:
                    os.kill(engine_pid, signal.SIGTERM)
                except ProcessLookupError:
                    pass
