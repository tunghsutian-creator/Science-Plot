"""Fresh engine scopes follow real item/source context, never ambient labels."""
import os
from types import SimpleNamespace

import pytest

from sciplot_core.verification.input_scope import load_manifest
from sciplot_core.verification import private_audit_runtime as runtime
from sciplot_core.verification import private_exclusion_boundary as boundary


class Observer:
    def __init__(self, scope):
        self._exclusion_collection = scope
        self.frames = []

    def record(self, value, **kwargs):
        self.frames.append(value)


@pytest.mark.parametrize("scope_name", ["public", "private"])
def test_item_socket_is_fresh_private_same_across_phases_and_restores_previous(scope_name, monkeypatch):
    node = load_manifest()["scopes"][scope_name][0]
    scope = {**boundary._scope([node]), "suite_root_sha256": "generated-unit-root"}
    observer = Observer(scope)
    item = SimpleNamespace(nodeid=node, path=boundary.REPO / node.split("::")[0])
    monkeypatch.setenv(runtime.SOCKET, "/generated/previous-user-server.sock")
    runtime.start_node(observer, item)
    socket = os.environ[runtime.SOCKET]
    assert socket != "/generated/previous-user-server.sock"
    assert observer.frames[0]["directory"]["mode"] == 0o700
    assert observer.frames[0]["initial_absent"] is True
    assert observer.frames[0]["test_nodeid"] == node
    runtime.start_node(observer, item)
    assert os.environ[runtime.SOCKET] == socket and len(observer.frames) == 1
    runtime.finish_node(observer, item)
    assert os.environ[runtime.SOCKET] == "/generated/previous-user-server.sock"
    assert observer.frames[-1]["event"] == "audit_socket_exit"


def test_unknown_context_cannot_replace_default_actor(monkeypatch):
    monkeypatch.setenv(runtime.SOCKET, "/generated/user.sock")
    monkeypatch.setenv("PYTEST_CURRENT_TEST", load_manifest()["scopes"]["public"][0])
    observer = Observer(None)
    runtime.start_node(observer, SimpleNamespace(nodeid="tests/fake.py::test_fake", path="/generated/fake.py"))
    assert not observer.frames and os.environ[runtime.SOCKET] == "/generated/user.sock"
    assert runtime.server_call(["python", "-m", "sciplot_core.plot_protocol.server", "--socket", "/generated/user.sock",
                                "--request-timeout", "600"], dict(os.environ)) is None


@pytest.mark.parametrize("owner_pid", [-1, 0, 402])
def test_cleanup_never_signals_an_owner_json_pid_without_the_held_child(owner_pid, tmp_path, monkeypatch):
    from sciplot_core.plot_protocol import paths

    calls = []
    process = SimpleNamespace(pid=401, send_signal=lambda value: calls.append(value))
    monkeypatch.setattr(paths, "read_owner", lambda path: {"pid": owner_pid})
    with pytest.raises(ValueError, match="different server PID"):
        runtime._stop_owned(tmp_path / "engine.sock", process)
    assert not calls


def test_unowned_remaining_endpoint_is_preserved_and_blocked_without_signal(monkeypatch):
    node = load_manifest()["scopes"]["public"][0]
    observer = Observer({**boundary._scope([node]), "suite_root_sha256": "generated-unit-root"})
    item = SimpleNamespace(nodeid=node, path=boundary.REPO / node.split("::")[0])
    monkeypatch.setattr(runtime, "_held", [])
    monkeypatch.setattr(runtime.os, "kill", lambda *args: pytest.fail("Unknown PID must not be signalled"))
    runtime.start_node(observer, item)
    from pathlib import Path
    endpoint = Path(os.environ[runtime.SOCKET])
    endpoint.write_text("generated unknown endpoint; preserve it")
    with pytest.raises(ValueError, match="unowned or unclosed"):
        runtime.finish_node(observer, item)
    assert endpoint.read_text() == "generated unknown endpoint; preserve it"
    assert observer.frames[-1]["event"] == "audit_socket_failed"


def test_live_endpoint_parent_lineage_cannot_move_to_next_item_via_an_ambient_label():
    entered = [{"event": "audit_socket_enter", "pid": 100, "epoch": "primary", "sequence": sequence,
                "socket": name + "/engine.sock", "test_nodeid": name, "sha256": name + "-generation"}
               for sequence, name in [(1, "first"), (5, "second")]]
    frames = [*entered,
              {"event": "child_spawn", "pid": 100, "epoch": "primary", "sequence": 2,
               "child_pid": 200, "child_token": "actual-first-child"},
              {"event": "process_start", "pid": 200, "epoch": "server", "sequence": 0,
               "parent_epoch": "primary", "child_token": "actual-first-child", "nodeid": "second"},
              *[{"event": "audit_socket_exit", "pid": 100, "epoch": "primary", "sequence": sequence,
                 "socket": name + "/engine.sock", "test_nodeid": name} for sequence, name in [(4, "first"), (8, "second")]]]
    endpoint = {"socket": "first/engine.sock", "endpoint": {"device": 1, "inode": 2, "ctime_ns": 3},
                "local_binding_token": "same-live-endpoint", "nodeid": "second"}
    bound = {**endpoint, "event": "audit_socket_bind", "pid": 200, "epoch": "server", "sequence": 1}
    same_item = {**endpoint, "event": "audit_socket_connect", "pid": 100, "epoch": "primary", "sequence": 3}
    borrowed = {**same_item, "sequence": 6}
    assert runtime._item_generation(bound, frames, entered, 100) == "first-generation"
    assert runtime._item_generation(same_item, frames, entered, 100) == "first-generation"
    assert runtime._item_generation(borrowed, frames, entered, 100) == "second-generation"
    assert runtime._item_generation({**bound, "epoch": "unobserved"}, frames, entered, 100) is None
