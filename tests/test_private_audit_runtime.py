"""Fresh engine scopes follow real item/source context, never ambient labels."""
from contextlib import contextmanager, nullcontext
import errno
import inspect
import os
import threading
from types import SimpleNamespace

import pytest

from sciplot_core.verification.input_scope import load_manifest
from sciplot_core.verification import private_audit_runtime as runtime
from sciplot_core.verification import private_socket_ports as socket_ports
from sciplot_core.verification import private_exclusion_boundary as boundary
from sciplot_core.verification import private_observer as observation


class Observer:
    def __init__(self, scope):
        self._exclusion_collection = scope
        self.frames = []

    def record(self, value, **kwargs):
        self.frames.append(value)


@pytest.mark.parametrize("peer_errno,error_class", [(errno.ENOTCONN, "OSError"), (errno.EACCES, "PermissionError")])
def test_successful_connect_is_not_changed_by_peer_observation_failure(monkeypatch, peer_errno, error_class):
    from pathlib import Path
    import socket
    from sciplot_core.plot_protocol import paths

    calls, frames = [], []
    path = Path("/generated/observed/engine.sock")
    identity = {"device": 1, "inode": 2, "ctime_ns": 3}
    owner = {"pid": 401, "device": 1, "inode": 2}

    class Socket:
        family = socket.AF_UNIX

        def bind(self, address):
            pytest.fail("The generated connect contract must not bind a socket")

        def listen(self, *args, **kwargs):
            pytest.fail("The generated connect contract must not listen")

        def connect(self, address):
            calls.append(address)

    def unavailable(connection):
        assert isinstance(connection, Socket)
        raise OSError(peer_errno, "generated peer lookup failure")

    observer = SimpleNamespace(guard=threading.local(), record=lambda value, **_: frames.append(value))
    with monkeypatch.context() as control:
        control.setattr(socket_ports, "socket", SimpleNamespace(socket=Socket, AF_UNIX=socket.AF_UNIX))
        control.setattr(socket_ports, "_endpoint", lambda address: (path, identity))
        control.setattr(socket_ports, "kernel_peer_pid", unavailable)
        control.setattr(paths, "read_owner", lambda _: owner)
        runtime.install_socket_ports(observer)
        assert Socket().connect(str(path)) is None
        assert observer.guard.socket_port is False

    assert calls == [str(path)]
    assert len(frames) == 1
    assert type(frames[0].pop("connected_monotonic_ns")) is int
    assert frames[0] == {"event": "audit_socket_connect", "socket": str(path), "endpoint": identity,
                         "local_binding_token": None, "socket_owner": owner, "peer_pid": None,
                         "peer_lookup_error": {"error_class": error_class, "errno": peer_errno}}


def _closed_peer_facts():
    endpoint = {"device": 1, "inode": 2, "ctime_ns": 3}
    owner = {"pid": 401, "device": 1, "inode": 2, "instance_id": "first-instance"}
    identity = {"pid": 401, "start_sec": 10, "start_usec": 1}
    connected = {"socket": "/generated/engine.sock", "endpoint": endpoint,
                 "socket_owner": owner, "peer_pid": None, "connected_monotonic_ns": 30,
                 "peer_lookup_error": {"error_class": "OSError", "errno": errno.ENOTCONN}}
    actor = {"socket": connected["socket"], "identity": identity, "default_owned": False,
             "ready": {"endpoint": endpoint, "socket_owner": owner, "peer_pid": 401},
             "item_generation": "first-item", "ready_monotonic_ns": 20}
    actual = {"identity": identity, "generation": "first-launch", "status": "OBSERVED",
              "returncode": -15, "observed_monotonic_ns": 40}
    return connected, actor, {"first-launch": actual}


def test_closed_binding_retains_unknown_peer_and_original_exit_policy():
    from copy import deepcopy

    connected, actor, exits = _closed_peer_facts()
    before = deepcopy((connected, actor, exits))
    assert runtime._closed_native_binding(connected, actor, "first-launch", "first-item", exits)
    assert (connected, actor, exits) == before and connected["peer_pid"] is None
    actor["default_owned"] = True
    assert not runtime._closed_native_binding(connected, actor, "first-launch", "first-item", exits)
    exits["first-launch"]["returncode"] = 0
    assert runtime._closed_native_binding(connected, actor, "first-launch", "first-item", exits)


@pytest.mark.parametrize("change", [
    "known_different_peer", "known_same_peer_with_error", "missing_lookup_error", "other_errno", "unknown_error_class",
    "endpoint_changed", "endpoint_unobserved", "owner_instance_changed", "owner_missing", "peer_ready_mismatch",
    "wrong_item", "unknown_item", "missing_exit", "other_exit_generation", "other_exit_identity", "unknown_exit",
    "late_ready", "exit_observed_before_connection", "missing_connection_time", "boolean_connection_time",
])
def test_closed_binding_refuses_incomplete_or_borrowed_facts(change):
    from copy import deepcopy

    connected, actor, exits = deepcopy(_closed_peer_facts())
    item = "first-item"
    if change == "known_different_peer":
        connected["peer_pid"] = 999
    elif change == "known_same_peer_with_error":
        connected["peer_pid"] = 401
    elif change == "missing_lookup_error":
        connected.pop("peer_lookup_error")
    elif change == "other_errno":
        connected["peer_lookup_error"]["errno"] = errno.EACCES
    elif change == "unknown_error_class":
        connected["peer_lookup_error"]["error_class"] = "ValueError"
    elif change == "endpoint_changed":
        connected["endpoint"] = {**connected["endpoint"], "inode": 999}
    elif change == "endpoint_unobserved":
        connected["endpoint_observation_error"] = {"error_class": "FileNotFoundError", "errno": errno.ENOENT}
    elif change == "owner_instance_changed":
        connected["socket_owner"] = {**connected["socket_owner"], "instance_id": "second-instance"}
    elif change == "owner_missing":
        connected["socket_owner"] = None
    elif change == "peer_ready_mismatch":
        actor["ready"]["peer_pid"] = 999
    elif change == "wrong_item":
        item = "second-item"
    elif change == "unknown_item":
        item = None
    elif change == "missing_exit":
        exits.clear()
    elif change == "other_exit_generation":
        exits["first-launch"]["generation"] = "second-launch"
    elif change == "other_exit_identity":
        exits["first-launch"]["identity"] = {**actor["identity"], "start_usec": 999}
    elif change == "unknown_exit":
        exits["first-launch"]["status"] = "UNKNOWN"
    elif change == "late_ready":
        actor["ready_monotonic_ns"] = 30
    elif change == "exit_observed_before_connection":
        exits["first-launch"]["observed_monotonic_ns"] = 29
    elif change == "missing_connection_time":
        connected.pop("connected_monotonic_ns")
    elif change == "boolean_connection_time":
        connected["connected_monotonic_ns"] = True
    else:
        pytest.fail("Unknown generated contract mutation")
    assert not runtime._closed_native_binding(connected, actor, "first-launch", item, exits)


@pytest.mark.parametrize("mode", ["closed", "different_peer", "missing_native", "competing_generation",
                                  "unclosed_registration", "unknown_exit_registration", "duplicate_exit_registration"])
def test_socket_review_requires_unique_closed_native_binding_and_never_rescues_wrong_peer(mode, monkeypatch):
    from copy import deepcopy
    from pathlib import Path
    from sciplot_core.foundation.json_hashing import canonical_json_sha256

    # These are already-validated actor/exit model inputs, not kernel evidence.
    primary, child, token, node = 100, 401, "first-child", "tests/test_private_audit_runtime.py::generated_item"
    path = str(Path("/tmp").resolve() / "sp-audit-generated-closed-peer" / "engine.sock")
    directory = {"device": 1, "inode": 2, "uid": 501, "mode": 0o700}
    scope = dict(manifest_sha256="generated-manifest", collection_sha256="generated-collection",
                 suite_root_sha256="generated-suite", nodes={node})
    source = Path(runtime.__file__).resolve().parents[3] / node.split("::")[0]
    source_sha = runtime.file_sha256(source)
    records = {canonical_json_sha256(str(source)): {"sha256": source_sha}}
    monkeypatch.setattr(runtime, "_directory", lambda _: directory)
    connected, actor, exits = _closed_peer_facts()
    connected.update(socket=path, event="audit_socket_connect", pid=primary, epoch="primary",
                     sequence=6, monotonic_ns=31)
    actor.update(socket=path, default_owned=True, launch_epoch="primary", launch_token=token)
    actor.pop("item_generation")  # review derives this from real item lineage.
    actual = exits.pop("first-launch")
    actual.update(generation="primary:first-child", returncode=0)
    exits["primary:first-child"] = actual
    actors = {"primary:first-child": actor}
    common = {"pid": primary, "epoch": "primary", "socket": path, "test_nodeid": node}
    frames = [
        {**common, "event": "audit_socket_enter", "sequence": 1, "sha256": "first-item",
         "owner": runtime.owner_identity("private_audit_runtime.py", "start_node"), "initial_absent": True,
         **{key: value for key, value in scope.items() if key != "nodes"},
         "test_source_sha256": source_sha, "directory": directory},
        {**common, "event": "spawn_attempt", "sequence": 2, "child_token": token},
        {**common, "event": "child_spawn", "sequence": 3, "child_pid": child, "child_token": token},
        {"event": "process_start", "pid": child, "epoch": "server", "sequence": 0,
         "parent_epoch": "primary", "child_token": token},
        {"event": "audit_socket_bind", "pid": child, "epoch": "server", "sequence": 1,
         "socket": path, "endpoint": connected["endpoint"], "binding_token": token,
         "initial_absent": True, "monotonic_ns": 10},
        {**common, "event": "native_registration_request", "sequence": 4,
         "request": {"generation": "primary:first-child", "actor": deepcopy(actor)}},
        {**common, "event": "audit_server_spawn", "sequence": 5, "child_pid": child, "child_token": token,
         "owner": runtime.owner_identity("socket_client.py", "ensure_server")},
        connected,
        {**common, "event": "audit_server_close", "sequence": 7, "child_pid": child,
         "child_token": token, "actual_wait_returncode": 0},
        {**common, "event": "audit_socket_exit", "sequence": 9, "directory": directory},
    ]
    if mode == "different_peer":
        connected.pop("peer_lookup_error")
        connected["peer_pid"] = 999
    elif mode == "missing_native":
        actors.clear()
        exits.clear()
    elif mode == "competing_generation":
        other = deepcopy(actor)
        other.update(launch_token="second-child", identity={"pid": 999})
        actors["primary:second-child"] = other
        frames.append({**common, "event": "spawn_attempt", "sequence": 4, "child_token": "second-child"})
        frames.append({**common, "event": "native_registration_request", "sequence": 5,
                       "request": {"generation": "primary:second-child", "actor": deepcopy(other)}})
    elif mode in {"unclosed_registration", "unknown_exit_registration", "duplicate_exit_registration"}:
        # validated_exits omits B from actors/exits in all three cases. Its raw
        # registration still prevents A from authorizing the ambiguous socket.
        frames.append({**common, "event": "native_registration_request", "sequence": 5,
                       "request": {"generation": "primary:second-child", "actor": deepcopy(actor)}})
        if mode != "unclosed_registration":
            status = {**common, "event": "native_exit_status", "sequence": 8,
                      "fact": {"generation": "primary:second-child",
                               "status": "UNKNOWN" if mode == "unknown_exit_registration" else "OBSERVED"}}
            frames.extend([status] * (2 if mode == "duplicate_exit_registration" else 1))
    result = runtime.review_sockets(frames, primary=primary, scope=scope, records=records,
                                   native_exits=exits, native_actors=actors)
    assert result == ([] if mode == "closed" else ["AF_UNIX connection has no observed fresh actor binding"])
    assert connected["peer_pid"] == (999 if mode == "different_peer" else None)


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


def test_confirmed_registration_preserves_the_persistent_spawn(tmp_path, monkeypatch):
    from sciplot_core.verification import private_native_exit_port as port

    observer = Observer(None)
    monkeypatch.setattr(port, "register_server", lambda *args: True)
    monkeypatch.setattr(runtime, "_held", [])
    process = SimpleNamespace(pid=401)  # Any poll/signal/wait is a test failure.
    runtime.hold_server(observer, process, "actual-token", {"socket": str(tmp_path / "engine.sock"), "default_owned": True})
    assert [r["event"] for r in observer.frames] == ["audit_server_spawn"]
    assert runtime._held == []


def test_failed_registration_closes_only_the_held_spawn_and_retains_unknown(tmp_path, monkeypatch):
    from sciplot_core.verification import private_native_exit_port as port
    import subprocess

    monkeypatch.setattr(port, "register_server", lambda *args: False)
    monkeypatch.setattr(runtime, "_held", [])
    class Process:
        pid = 401
        def __init__(self, polled, failure, calls):
            self.polled, self.failure, self.calls = polled, failure, calls
        def poll(self):
            self.calls.append("poll")
            return self.polled
        def terminate(self):
            self.calls.append("terminate")
        def wait(self, *, timeout):
            self.calls.append(("wait", timeout))
            if self.failure:
                raise subprocess.TimeoutExpired("modeled-child", timeout)
            return 0
    for polled, timeout in ((None, False), (0, False), (None, True)):
        observer, calls = Observer(None), []
        with pytest.raises(ValueError, match="registration failed"):
            runtime.hold_server(observer, Process(polled, timeout, calls), "actual-token", {"socket": str(tmp_path / "engine.sock"), "default_owned": True})
        assert calls == (["poll", "terminate", ("wait", 20)] if polled is None else ["poll", ("wait", 20)])
        last = observer.frames[-1]
        assert last["event"] == "audit_server_failed" and last["child_pid"] == 401 and last["child_token"] == "actual-token"
        assert last["actual_wait_returncode"] == (None if timeout else 0)
        if timeout:
            assert last["error_class"] == "TimeoutExpired"
        assert runtime._held == []


@contextmanager
def _composed_process_ports(tmp_path, monkeypatch, order):
    calls, admissions, held, frames = [], [], [], []

    class Process:
        def __init__(self, args, *, env=None, cwd=None, stdin=None, stdout=None, stderr=None,
                     close_fds=True, start_new_session=False, bufsize=-1, encoding=None):
            calls.append(dict(args=args, env=env, cwd=cwd, stdin=stdin, stdout=stdout, stderr=stderr,
                              close_fds=close_fds, start_new_session=start_new_session,
                              bufsize=bufsize, encoding=encoding))
            self.pid, self.returncode = 401, None

        def wait(self, *args, **kwargs):
            pytest.fail("Generated composition contract must not wait for a real process")

        def poll(self, *args, **kwargs):
            pytest.fail("Generated composition contract must not poll a real process")

    original_signature = inspect.signature(Process.__init__)
    observer = SimpleNamespace(directory=tmp_path, run="generated-run", epoch="generated-epoch", reserved={},
        guard=threading.local(), wrapper_environment={}, record=lambda value, **_: frames.append(value))

    def admit(port):
        def recognize(command, environment):
            admissions.append((port, command, environment))
            return {"port": port}
        return recognize

    with monkeypatch.context() as control:
        process_module = SimpleNamespace(Popen=Process)
        for owner, port in ((runtime, "cleanup"), (observation, "observer")):
            control.setattr(owner, "subprocess", process_module)
            control.setattr(owner, "server_call", admit(port))
            control.setattr(owner, "hold_server", lambda *args: held.append(args))
        control.setenv(runtime.ACTOR, "/generated/owned-engine.sock")
        control.setattr(runtime, "_actor_installed", False)
        control.setattr(observation, "install_socket_ports", lambda _: None)
        control.setattr(observation, "executable_hash", lambda *_, **__: None)
        control.setattr(observation, "owned_caller", lambda *_: None)
        control.setattr(observation, "excluded_launch", lambda *_: nullcontext(None))
        for name in ("uname_call", "wrapper_call", "native_probe_call"):
            control.setattr(observation, name, lambda *_: None)
        for name in ("waitpid", "execve", "execvpe"):
            control.setattr(observation.os, name, getattr(observation.os, name))
        installers = (runtime.install_actor_cleanup, lambda: observation._install_process_ports(observer))
        for install in installers if order == "cleanup_first" else reversed(installers):
            install()
        yield Process, original_signature, observer, calls, admissions, held, frames


@pytest.mark.parametrize("order", ["cleanup_first", "observer_first"])
@pytest.mark.parametrize("invocation", ["positional", "keyword"])
def test_composed_process_ports_preserve_signature_and_forward_exact_arguments(tmp_path, monkeypatch, order, invocation):
    with _composed_process_ports(tmp_path, monkeypatch, order) as state:
        Process, signature, observer, calls, admissions, held, frames = state
        arguments = ["generated-python", "-c", "generated command"]
        options = dict(env={"GENERATED_TARGET": "retained"}, cwd=tmp_path / "generated-cwd",
                       stdin=-3, stdout=-1, stderr=-2, close_fds=False, start_new_session=True,
                       bufsize=17, encoding="utf8")
        child = Process(arguments, **options) if invocation == "positional" else Process(args=arguments, **options)
        assert calls == [{"args": arguments, **options}]
        assert calls[0]["args"] is arguments
        assert sorted(port for port, _, _ in admissions) == ["cleanup", "observer"]
        assert all(command is arguments and environment == options["env"] for _, command, environment in admissions)
        assert len(held) == 2 and all(row[1] is child for row in held)
        assert sum(row[0] is observer for row in held) == 1 and sum(row[0] is None for row in held) == 1
        attempt = next(frame for frame in frames if frame["event"] == "spawn_attempt")
        assert attempt["argv_sha256"] == observation.frame_digest({"argv": arguments})
        assert [frame["event"] for frame in frames] == ["spawn_attempt", "child_spawn"]
        assert inspect.signature(Process.__init__) == signature


@pytest.mark.parametrize("order", ["cleanup_first", "observer_first"])
def test_composed_process_ports_still_refuse_nested_argv_before_original_call(tmp_path, monkeypatch, order):
    with _composed_process_ports(tmp_path, monkeypatch, order) as state:
        Process, _, _, calls, _, held, frames = state
        with pytest.raises(TypeError, match="str, bytes or os.PathLike"):
            Process([["generated-invalid-nested-argv"]])
        assert calls == [] and held == [] and frames == []


@pytest.mark.parametrize("order", ["cleanup_first", "observer_first"])
@pytest.mark.parametrize("registration", [True, None, False])
def test_observer_takes_only_same_process_fallback_and_preserves_actual_cleanup(tmp_path, monkeypatch, order, registration):
    from sciplot_core.verification import private_native_exit_port as port

    class Process:
        pid = 401

        def __init__(self):
            self.returncode, self.calls = None, []

        def poll(self):
            self.calls.append("poll")
            return self.returncode

        def terminate(self):
            self.calls.append("terminate")

        def wait(self, *, timeout=None):
            self.calls.append(("wait", timeout))
            self.returncode = 0
            return 0

    observer, process, old_process = Observer(None), Process(), Process()
    socket = tmp_path / "current-owned.sock"
    old = (None, old_process, tmp_path / "previous-owned.sock", "previous-token")
    actor = {"socket": str(socket), "default_owned": True}
    registrations = []

    def register(*args):
        registrations.append(args)
        return registration

    with monkeypatch.context() as control:
        control.setattr(runtime, "_held", [old])
        control.setattr(port, "register_server", register)
        control.setattr(runtime.atexit, "register", lambda *_: None)
        with pytest.raises(ValueError, match="registration failed") if registration is False else nullcontext():
            if order == "cleanup_first":
                runtime.hold_server(None, process, "unobserved", actor)
            process._sciplot_audit_child = "current-audit-token"
            runtime.hold_server(observer, process, "current-audit-token", actor)
            if order == "observer_first":
                runtime.hold_server(None, process, "unobserved", actor)
        assert registrations == [(observer, process, "current-audit-token", actor)]
        assert [row for row in runtime._held if row[1] is old_process] == [old]
        current = [row for row in runtime._held if row[1] is process]
        assert len(current) == (1 if registration is None else 0)
        assert all(row[0] is observer and row[3] == "current-audit-token" for row in current)
        if registration is None:
            assert process.calls == []
            process.returncode = 0
        runtime.close_servers(socket)
        assert runtime._held == [old] and old_process.calls == []
        assert process.calls == (["poll", "terminate", ("wait", 20)] if registration is False else
                                 ["poll", ("wait", None)] if registration is None else [])
        if registration is False:
            failed = observer.frames[-1]
            assert failed["event"] == "audit_server_failed" and failed["actual_wait_returncode"] == 0
        elif registration is None:
            closed = observer.frames[-1]
            assert closed["event"] == "audit_server_close" and closed["actual_wait_returncode"] == 0


@pytest.mark.parametrize("mutation", ["neighbor_only", "target_also_closed"])
def test_observer_handoff_preserves_adjacent_holder_creation_and_cleanup(tmp_path, monkeypatch, mutation):
    from sciplot_core.verification import private_native_exit_port as port

    observer = Observer(None)
    process = SimpleNamespace(pid=401, _sciplot_audit_child="current-audit-token")
    fallback = (None, process, tmp_path / "current.sock", "unobserved")
    old_neighbor = (None, SimpleNamespace(pid=402), tmp_path / "old.sock", "old-token")
    new_neighbor = (None, SimpleNamespace(pid=403), tmp_path / "new.sock", "new-token")

    class Registry(list):
        changed = False

        def __iter__(self):
            yield from list(list.__iter__(self))
            if not self.changed:
                self.changed = True
                self.append(new_neighbor)
                self.remove(old_neighbor)
                if mutation == "target_also_closed":
                    self.remove(fallback)

    registry, registrations = Registry([fallback, old_neighbor]), []

    def register(*args):
        registrations.append(args)
        return True

    actor = {"socket": str(tmp_path / "current.sock"), "default_owned": True}
    with monkeypatch.context() as control:
        control.setattr(runtime, "_held", registry)
        control.setattr(port, "register_server", register)
        runtime.hold_server(observer, process, "current-audit-token", actor)
        assert runtime._held is registry and registry == [new_neighbor]
        assert registrations == [(observer, process, "current-audit-token", actor)]


def test_socket_review_scans_whole_stream_once_and_retains_duplicate_exit_refusal(monkeypatch):
    from pathlib import Path
    from sciplot_core.foundation.json_hashing import canonical_json_sha256

    class CountedFrames(list):
        visits = 0

        def __iter__(self):
            for row in super().__iter__():
                self.visits += 1
                yield row

    primary, frames, nodes = 100, [], set()
    directory = {"device": 1, "inode": 2, "uid": 501, "mode": 0o700}
    scope = dict(manifest_sha256="generated-manifest", collection_sha256="generated-collection",
                 suite_root_sha256="generated-suite", nodes=nodes)
    source = Path(runtime.__file__).resolve().parents[3] / "tests/test_private_audit_runtime.py"
    source_sha = runtime.file_sha256(source)
    records = {canonical_json_sha256(str(source)): {"sha256": source_sha}}
    monkeypatch.setattr(runtime, "_directory", lambda _: directory)
    for index in range(4):
        node = f"tests/test_private_audit_runtime.py::generated_item_{index}"
        nodes.add(node)
        socket = str(Path("/tmp").resolve() / f"sp-audit-generated-review-{index}" / "engine.sock")
        token, child, epoch = f"generated-child-{index}", 200 + index, f"child-epoch-{index}"
        endpoint = {"device": 10, "inode": 20 + index, "ctime_ns": 30}
        owner = {"pid": child, "device": endpoint["device"], "inode": endpoint["inode"]}
        common = {"pid": primary, "epoch": "primary", "socket": socket, "test_nodeid": node}
        frames.extend([
            {**common, "event": "audit_socket_enter", "sequence": index * 10 + 1, "sha256": f"generation-{index}",
             "owner": runtime.owner_identity("private_audit_runtime.py", "start_node"), "initial_absent": True,
             **{key: value for key, value in scope.items() if key != "nodes"},
             "test_source_sha256": source_sha, "directory": directory},
            {**common, "event": "child_spawn", "sequence": index * 10 + 2, "child_pid": child, "child_token": token},
            {"event": "process_start", "pid": child, "epoch": epoch, "sequence": 0,
             "parent_epoch": "primary", "child_token": token},
            {"event": "audit_socket_bind", "pid": child, "epoch": epoch, "sequence": 1,
             "socket": socket, "endpoint": endpoint, "binding_token": token, "initial_absent": True,
             "monotonic_ns": index * 10 + 4},
            {**common, "event": "audit_server_spawn", "sequence": index * 10 + 5,
             "child_pid": child, "child_token": token, "owner": runtime.owner_identity("socket_client.py", "ensure_server")},
            {**common, "event": "audit_socket_connect", "sequence": index * 10 + 6,
             "endpoint": endpoint, "socket_owner": owner, "monotonic_ns": index * 10 + 6},
            {**common, "event": "audit_server_close", "sequence": index * 10 + 7,
             "child_pid": child, "child_token": token, "actual_wait_returncode": 0},
            {**common, "event": "audit_socket_exit", "sequence": index * 10 + 9, "directory": directory},
        ])
    frames.extend({"event": "open", "pid": 999, "epoch": "unrelated", "sequence": index,
                   "path": "/generated/unrelated-input"} for index in range(4096))
    results, visits, lengths = [], [], []
    for duplicate in (False, True):
        stream = CountedFrames(frames + ([dict(frames[7])] if duplicate else []))
        results.append(runtime.review_sockets(stream, primary=primary, scope=scope, records=records, native_exits={}))
        visits.append(stream.visits)
        lengths.append(len(stream))
    assert results == [[], ["default engine namespace identity or normal closure differs"]]
    assert visits == lengths
