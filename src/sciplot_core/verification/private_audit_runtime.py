"""One fresh default engine namespace per real primary pytest item."""
from __future__ import annotations

import atexit
from functools import wraps
import inspect
import os
from pathlib import Path
import signal
import socket
import subprocess
import sys
import tempfile
from typing import Any
import weakref
from uuid import uuid4

from sciplot_core.foundation.file_hashing import file_sha256
from sciplot_core.plot_protocol.paths import kernel_peer_pid
from sciplot_core.verification.native_exit_boundary import endpoint_identity as _endpoint, namespace_identity as _directory, settled_binding, explicit_exit_bound
from sciplot_core.verification.private_process_boundaries import owned_caller, owner_identity

SOCKET = "SCIPLOT_ENGINE_SOCKET"
ACTOR = "SCIPLOT_AUDIT_ACTOR_SOCKET"
_held: list[tuple[Any, subprocess.Popen[Any], Path, str]] = []
_actor_installed = False
_fixture_observer: Any = None

def install_socket_ports(observer: Any) -> None:
    original_bind, original_connect, original_listen = socket.socket.bind, socket.socket.connect, socket.socket.listen
    bindings: dict[str, tuple[Any, dict[str, Any]]] = {}

    def bind(endpoint: socket.socket, address: Any) -> None:
        absent = endpoint.family == socket.AF_UNIX and not Path(os.fsdecode(address)).exists()
        observer.guard.socket_port = True
        try:
            original_bind(endpoint, address)
        finally:
            observer.guard.socket_port = False
        if endpoint.family == socket.AF_UNIX:
            path, identity = _endpoint(address)
            facts = {"event": "audit_socket_bind", "socket": str(path), "endpoint": identity,
                     "binding_token": uuid4().hex, "initial_absent": absent}
            bindings[str(path)] = weakref.ref(endpoint), facts
            recorded = observer.record(facts, sync=True)
            if recorded is not None:
                facts["sha256"] = recorded["sha256"]

    def listen(endpoint: socket.socket, *args: Any, **kwargs: Any) -> None:
        original_listen(endpoint, *args, **kwargs)
        for name, (held, creation) in list(bindings.items()):
            if held() is endpoint:
                _, identity = _endpoint(name)
                ready = {**creation, "event": "audit_socket_listen", "endpoint": identity,
                         "creation_sha256": creation.get("sha256"),
                         "owner": owned_caller("server.py", "serve")}
                ready.pop("sha256", None)
                observer.record(ready, sync=True)
                bindings[name] = held, ready

    def connect(endpoint: socket.socket, address: Any) -> None:
        before = _endpoint(address) if endpoint.family == socket.AF_UNIX else None
        observer.guard.socket_port = True
        try:
            original_connect(endpoint, address)
        finally:
            observer.guard.socket_port = False
        if before is not None:
            path, identity = before
            if _endpoint(address) != before:
                raise ValueError("AF_UNIX endpoint changed during connect.")
            local = bindings.get(str(path))
            token = None
            if local is not None and (owned := local[0]()) is not None and owned.fileno() >= 0 and local[1]["endpoint"] == identity:
                token = local[1]["binding_token"]
            from sciplot_core.plot_protocol.paths import read_owner
            try:
                owner = read_owner(path)
            except (OSError, ValueError):
                owner = None
            observer.record({"event": "audit_socket_connect", "socket": str(path), "endpoint": identity,
                             "local_binding_token": token, "socket_owner": owner,
                             "peer_pid": kernel_peer_pid(endpoint)}, sync=True)

    for name, operation in (("bind", bind), ("listen", listen), ("connect", connect)):
        setattr(socket.socket, name, operation)

def start_node(observer: Any, item: Any) -> None:
    global _fixture_observer
    scope = getattr(observer, "_exclusion_collection", None)
    repo = Path(__file__).resolve().parents[3]
    source = repo / item.nodeid.split("::", 1)[0]
    if (scope is None or item.nodeid not in scope["nodes"] or Path(item.path).resolve() != source
            or getattr(observer, "_audit_socket_scope", None) is not None):
        return
    directory = Path(tempfile.mkdtemp(prefix="sp-audit-", dir="/tmp")).resolve()
    path = directory / "engine.sock"
    facts = {"socket": str(path), "directory": _directory(directory), "initial_absent": not any(directory.iterdir()),
             "sockets": [str(path)],
             "test_nodeid": item.nodeid, "manifest_sha256": scope["manifest_sha256"],
             "collection_sha256": scope["collection_sha256"], "suite_root_sha256": scope["suite_root_sha256"],
             "test_source_sha256": file_sha256(source),
             "owner": owner_identity("private_audit_runtime.py", "start_node")}
    observer._audit_socket_scope = (facts, {key: os.environ.get(key) for key in (SOCKET, ACTOR)})
    _fixture_observer = observer
    os.environ[SOCKET] = str(path)
    os.environ[ACTOR] = str(path)
    observer.record({"event": "audit_socket_enter", **facts}, sync=True)

def reserve_socket_fixture(names: tuple[str, ...]) -> Path | None:
    """Reserve only fresh exact endpoints in the current primary item scope."""
    observer = _fixture_observer
    if observer is None:
        return None
    active = getattr(observer, "_audit_socket_scope", None)
    if active is None:
        return None
    facts, _ = active
    directory = Path(facts["socket"]).parent
    if (not names or len(names) != len(set(names)) or any(Path(name).name != name or name in {"", ".", ".."} for name in names)
            or _directory(directory) != facts["directory"] or facts["test_nodeid"] != observer.nodeid
            or any((directory / name).exists() or (directory / name).is_symlink() for name in names)):
        raise ValueError("Generated socket fixtures require fresh endpoints in the real item scope.")
    facts["sockets"] = sorted(set(facts["sockets"]) | {str(directory / name) for name in names})
    observer.record({"event": "audit_socket_reserve", "test_nodeid": observer.nodeid,
                     "socket": facts["socket"], "sockets": facts["sockets"], "directory": facts["directory"],
                     "initial_absent": True, "owner": owner_identity("private_audit_runtime.py", "reserve_socket_fixture")}, sync=True)
    return directory

def active_socket_scope(observer: Any) -> dict[str, Any] | None:
    active = getattr(observer, "_audit_socket_scope", None)
    if active is None:
        return None
    facts, _ = active
    return {key: facts[key] for key in ("sockets", "directory", "initial_absent")}

def saved_socket_scope(records: list[dict[str, Any]], attempt: dict[str, Any]) -> dict[str, Any] | None:
    enters = [row for row in records if row["event"] == "audit_socket_enter"
              and row.get("test_nodeid") == attempt["nodeid"] and row["sequence"] < attempt["sequence"]]
    if len(enters) != 1 or enters[0].get("owner") != owner_identity("private_audit_runtime.py", "start_node"):
        return None
    facts = enters[0]
    for reserved in [row for row in records if row["event"] == "audit_socket_reserve"
                     and row.get("test_nodeid") == attempt["nodeid"] and facts["sequence"] < row["sequence"] < attempt["sequence"]]:
        if (reserved.get("owner") != owner_identity("private_audit_runtime.py", "reserve_socket_fixture")
                or reserved.get("initial_absent") is not True or reserved["directory"] != facts["directory"]
                or not set(facts["sockets"]).issubset(reserved["sockets"])):
            return None
        facts = reserved
    return {key: facts[key] for key in ("sockets", "directory", "initial_absent")}

def _stop_owned(path: Path, process: subprocess.Popen[Any]) -> dict[str, Any]:
    from sciplot_core.plot_protocol.paths import read_owner

    owner = read_owner(path)
    if type(owner["pid"]) is not int or owner["pid"] <= 0 or owner["pid"] != process.pid:
        raise ValueError("Audit cleanup refused a different server PID.")
    process.send_signal(signal.SIGTERM)
    code = process.wait(timeout=20)
    if code != 0:
        raise ValueError("Audit-owned server did not terminate normally.")
    if path.exists() or path.with_name(path.name + ".owner.json").exists():
        raise ValueError("Audit-owned server did not release its socket.")
    return {"server": owner, "actual_wait_returncode": code}

def finish_node(observer: Any, item: Any) -> None:
    global _fixture_observer
    active = getattr(observer, "_audit_socket_scope", None)
    if active is None:
        return
    facts, previous = active
    path = Path(facts["socket"])
    try:
        if facts["test_nodeid"] != item.nodeid or _directory(path.parent) != facts["directory"]:
            raise ValueError("Audit engine scope changed before item exit.")
        from sciplot_core.verification.private_native_exit_port import finish_node as finish_native_node
        finish_native_node(observer, facts)
        close_servers(path)
        if path.exists() or path.with_name(path.name + ".owner.json").exists():
            raise ValueError("An unowned or unclosed default actor remains; no PID was signalled.")
        observer.record({"event": "audit_socket_exit", "test_nodeid": item.nodeid,
                         "socket": str(path), "directory": _directory(path.parent)}, sync=True)
    except (OSError, ValueError, subprocess.TimeoutExpired) as exc:
        observer.record({"event": "audit_socket_failed", "test_nodeid": item.nodeid,
                         "socket": str(path), "error_class": type(exc).__name__}, sync=True)
        raise
    finally:
        for key, value in previous.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value
        observer._audit_socket_scope = None
        if _fixture_observer is observer:
            _fixture_observer = None

def server_call(command: Any, environment: dict[str, str]) -> dict[str, Any] | None:
    owner = owned_caller("socket_client.py", "ensure_server")
    if (owner is None or not isinstance(command, (list, tuple)) or len(command) != 7
            or list(command[:4]) != [sys.executable, "-m", "sciplot_core.plot_protocol.server", "--socket"]
            or not isinstance(command[4], str) or command[5] != "--request-timeout"):
        return None
    return {"socket": command[4], "owner": owner, "default_owned": environment.get(ACTOR) == command[4]}

def hold_server(observer: Any, process: subprocess.Popen[Any], token: str, actor: dict[str, Any] | None, attempt: dict[str, Any] | None = None) -> None:
    from sciplot_core.verification.private_native_exit_port import observe_launch
    observe_launch(observer, process, token, attempt, actor)
    if actor is None:
        return
    # The observer's child marker coordinates cleanup; it is no native proof.
    if observer is None and getattr(process, "_sciplot_audit_child", None):
        return
    if observer is not None:
        # Transfer only this actual held object, preserving earlier children.
        for entry in list(_held):
            if entry[0] is None and entry[1] is process:
                try:
                    _held.remove(entry)
                except ValueError:
                    pass  # The existing holder already closed this entry.
        observer.record({"event": "audit_server_spawn", "child_token": token, "child_pid": process.pid, **actor}, sync=True)
        from sciplot_core.verification.private_native_exit_port import register_server
        registered = register_server(observer, process, token, actor)
        if registered is False:
            cleanup: dict[str, Any] = {"actual_wait_returncode": None, "wait_called": False}
            try:
                cleanup["poll_returncode"] = process.poll()
                if cleanup["poll_returncode"] is None:
                    process.terminate()
                cleanup["wait_called"] = True
                cleanup["actual_wait_returncode"] = process.wait(timeout=20)
            except (OSError, subprocess.TimeoutExpired) as exc:
                cleanup["error_class"] = type(exc).__name__
            observer.record({"event": "audit_server_failed", "child_token": token,
                "child_pid": process.pid, "socket": actor["socket"], **cleanup}, sync=True)
            raise ValueError("Audit server registration failed; started child cleanup is recorded.")
        if registered is True:
            return
    if not actor["default_owned"]:
        return
    _held.append((observer, process, Path(actor["socket"]), token))
    if len(_held) == 1:
        atexit.register(close_servers)

def close_servers(socket: Path | None = None) -> None:
    for observer, process, path, token in list(_held):
        if socket is not None and path != socket:
            continue
        _held.remove((observer, process, path, token))
        try:
            if process.poll() is None:
                cleanup = _stop_owned(path, process)
            else:
                cleanup = {"actual_wait_returncode": process.wait(), "server": None}
            if observer is not None:
                observer.record({"event": "audit_server_close", "child_token": token, "child_pid": process.pid,
                                 "socket": str(path), **cleanup}, sync=True)
        except (OSError, ValueError, subprocess.TimeoutExpired) as exc:
            if observer is not None:
                observer.record({"event": "audit_server_failed", "child_token": token, "child_pid": process.pid,
                                 "socket": str(path), "error_class": type(exc).__name__}, sync=True)

def install_actor_cleanup() -> None:
    """Only own newly launched source servers; this grants no audit exemption."""
    global _actor_installed
    if _actor_installed or not os.environ.get(ACTOR):
        return
    original = subprocess.Popen.__init__
    signature = inspect.signature(original)

    @wraps(original)
    def spawn(process: subprocess.Popen[Any], *args: Any, **kwargs: Any) -> None:
        bound = signature.bind(process, *args, **kwargs)
        environment = bound.arguments.get("env")
        actor = server_call(bound.arguments.get("args"), dict(os.environ if environment is None else environment))
        original(process, *args, **kwargs)
        hold_server(None, process, "unobserved", actor)

    for name, operation in {"__init__": spawn}.items():
        setattr(subprocess.Popen, name, operation)
    _actor_installed = True


_FrameIndex = tuple[dict[str, list[dict[str, Any]]], dict[str, list[dict[str, Any]]]]

def _socket_review_index(frames: list[dict[str, Any]]) -> _FrameIndex:
    events: dict[str, list[dict[str, Any]]] = {}
    exits: dict[str, list[dict[str, Any]]] = {}
    for row in frames:
        events.setdefault(row["event"], []).append(row)
        socket = row.get("socket")
        if row["event"] == "audit_socket_exit" and isinstance(socket, str):
            exits.setdefault(socket, []).append(row)
    return events, exits

def _item_generation(frame: dict[str, Any], frames: list[dict[str, Any]], entries: list[dict[str, Any]], primary: int,
                     index: _FrameIndex | None = None) -> str | None:
    """Trace actual source launches to the primary's one live item interval."""
    events, exits = _socket_review_index(frames) if index is None else index
    seen = set()
    while frame["pid"] != primary:
        if frame["epoch"] in seen:
            return None
        seen.add(frame["epoch"])
        starts = [row for row in events.get("process_start", []) if row["epoch"] == frame["epoch"]]
        if len(starts) != 1:
            return None
        start = starts[0]
        continuation = start.get("continuation")
        if isinstance(continuation, dict):
            parents = [row for row in events.get("exec_seal", []) if row["pid"] == frame["pid"]
                       and row["epoch"] == continuation.get("epoch") and row["sha256"] == continuation.get("sha256")]
        else:
            parents = [row for row in events.get("child_spawn", []) if row["epoch"] == start.get("parent_epoch")
                       and row.get("child_token") == start.get("child_token") and row.get("child_pid") == frame["pid"]]
        if len(parents) != 1:
            return None
        frame = parents[0]
    owners = [row for row in entries if row["epoch"] == frame["epoch"] and row["sequence"] < frame["sequence"]
              and any(end["pid"] == primary and end["epoch"] == row["epoch"]
                      and end.get("socket") == row["socket"] and end.get("test_nodeid") == row["test_nodeid"]
                      and frame["sequence"] < end["sequence"] for end in exits.get(row["socket"], []))]
    return owners[0]["sha256"] if len(owners) == 1 else None

def review_sockets(frames: list[dict[str, Any]], *, primary: int, scope: dict[str, Any] | None,
                   records: dict[str, Any], native_exits: dict[str, dict[str, Any]],
                   source_exclusions: set[str] | None = None, native_actors: dict[str, dict[str, Any]] | None = None) -> list[str]:
    """Recheck the finite namespace facts; never trust an environment approval."""
    issues = []
    index = events, socket_exits = _socket_review_index(frames)
    entries = [row for row in events.get("audit_socket_enter", []) if row["pid"] == primary]
    if scope is None:
        return ["engine actor scope has no frozen primary collection"] if entries else []
    if len(entries) != len(scope["nodes"]) or {row["test_nodeid"] for row in entries} != scope["nodes"]:
        issues.append("fresh default engine namespace is absent for a primary item")
    sockets = {row["socket"] for row in entries}
    if len(sockets) != len(entries):
        issues.append("default engine namespace was reused between items")
    for entered in entries:
        path = Path(entered["socket"])
        source = Path(__file__).resolve().parents[3] / entered["test_nodeid"].split("::", 1)[0]
        from sciplot_core.foundation.json_hashing import canonical_json_sha256

        exits = [row for row in socket_exits.get(str(path), []) if row["pid"] == primary
                 and row.get("socket") == str(path)]
        if (entered.get("owner") != owner_identity("private_audit_runtime.py", "start_node")
                or entered.get("initial_absent") is not True or path.name != "engine.sock"
                or path.parent.parent != Path("/tmp").resolve() or not path.parent.name.startswith("sp-audit-")
                or entered.get("manifest_sha256") != scope["manifest_sha256"]
                or entered.get("collection_sha256") != scope["collection_sha256"]
                or entered.get("suite_root_sha256") != scope["suite_root_sha256"]
                or entered.get("test_source_sha256") != file_sha256(source)
                or records.get(canonical_json_sha256(str(source)), {}).get("sha256") != file_sha256(source)
                or len(exits) != 1 or exits[0]["sequence"] <= entered["sequence"]
                or entered["directory"] != _directory(path.parent) or exits[0]["directory"] != entered["directory"]
                or path.exists() or path.with_name(path.name + ".owner.json").exists()):
            issues.append("default engine namespace identity or normal closure differs")
        for spawned in [row for row in events.get("audit_server_spawn", []) if row.get("socket") == str(path)]:
            closed = [row for row in events.get("audit_server_close", []) if row["pid"] == spawned["pid"]
                      and row.get("child_token") == spawned["child_token"] and row.get("child_pid") == spawned["child_pid"]]
            native = native_exits.get(spawned["epoch"] + ":" + spawned["child_token"])
            matches = [native_exits[g] for g, actor in (native_actors or {}).items() if g in native_exits
                       and actor["launch_epoch"] == spawned["epoch"] and actor["launch_token"] == spawned["child_token"]
                       and actor["identity"]["pid"] == spawned["child_pid"]]
            native = native if native is not None else matches[0] if len(matches) == 1 else None
            if spawned.get("default_owned") is False:
                if not explicit_exit_bound(spawned, events.get("child_exit", []), source_exclusions or set()):
                    issues.append("observed explicit engine has no closed actual exit")
                continue
            if (spawned.get("owner") != owner_identity("socket_client.py", "ensure_server")
                    or not ((len(closed) == 1 and closed[0].get("actual_wait_returncode") == 0)
                            or (native is not None and native["returncode"] == 0))):
                issues.append("observed default engine has no source-owned normal actual child wait")
    for actor in (native_actors or {}).values():
        launches = [r for r in events.get("spawn_attempt", []) if r["epoch"] == actor["launch_epoch"] and r.get("child_token") == actor["launch_token"]]
        actor["item_generation"] = _item_generation(launches[0], frames, entries, primary, index) if len(launches) == 1 else None
    for connected in events.get("audit_socket_connect", []):
        generation = _item_generation(connected, frames, entries, primary, index)
        ready = [row for row in events.get("audit_socket_listen", []) if settled_binding(row, events.get("audit_socket_bind", []))]
        bound = [row for row in [*events.get("audit_socket_bind", []), *ready] if row.get("initial_absent") is True
                 and row.get("socket") == connected["socket"] and row.get("endpoint") == connected.get("endpoint")
                 and generation is not None and _item_generation(row, frames, entries, primary, index) == generation
                 and row["monotonic_ns"] < connected["monotonic_ns"]
                 and ((row["pid"] == connected["pid"] and row["binding_token"] == connected.get("local_binding_token"))
                      or (isinstance(connected.get("socket_owner"), dict) and connected["socket_owner"].get("pid") == row["pid"]
                          and connected["socket_owner"].get("device") == row["endpoint"]["device"]
                          and connected["socket_owner"].get("inode") == row["endpoint"]["inode"]))]
        native_bound = [actor for actor in (native_actors or {}).values() if actor["socket"] == connected["socket"]
                  and actor["ready"]["endpoint"] == connected.get("endpoint")
                  and actor["identity"]["pid"] == connected.get("peer_pid")
                  and actor["item_generation"] == generation
                  and actor["ready_monotonic_ns"] < connected["monotonic_ns"]]
        if not bound and not native_bound:
            issues.append("AF_UNIX connection has no observed fresh actor binding")
    if events.get("untracked_socket_connect"):
        issues.append("AF_UNIX connection bypassed its successful endpoint owner")
    if events.get("audit_socket_failed") or events.get("audit_server_failed"):
        issues.append("default engine actor cleanup failed")
    return issues
