"""One fresh default engine namespace per real primary pytest item."""
from __future__ import annotations

import atexit
import inspect
import os
from pathlib import Path
import signal
import socket
import stat
import subprocess
import sys
import tempfile
from typing import Any
import weakref
from uuid import uuid4

from sciplot_core.foundation.file_hashing import file_sha256
from sciplot_core.verification.private_process_boundaries import owned_caller, owner_identity

SOCKET = "SCIPLOT_ENGINE_SOCKET"
ACTOR = "SCIPLOT_AUDIT_ACTOR_SOCKET"
_held: list[tuple[Any, subprocess.Popen[Any], Path, str]] = []
_actor_installed = False
_fixture_observer: Any = None


def _endpoint(address: Any) -> tuple[Path, dict[str, int]]:
    path = Path(os.fsdecode(address)).absolute().resolve(strict=True)
    row = path.lstat()
    if not stat.S_ISSOCK(row.st_mode):
        raise ValueError("Connected AF_UNIX endpoint is not a socket.")
    return path, {"device": row.st_dev, "inode": row.st_ino, "ctime_ns": row.st_ctime_ns, "uid": row.st_uid}


def install_socket_ports(observer: Any) -> None:
    original_bind, original_connect = socket.socket.bind, socket.socket.connect
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
            observer.record(facts, sync=True)

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
                             "local_binding_token": token, "socket_owner": owner}, sync=True)

    for name, operation in (("bind", bind), ("connect", connect)):
        setattr(socket.socket, name, operation)


def _directory(path: Path) -> dict[str, int]:
    info = path.lstat()
    if not stat.S_ISDIR(info.st_mode) or info.st_uid != os.getuid() or stat.S_IMODE(info.st_mode) != 0o700:
        raise ValueError("Audit engine namespace is not a private owned directory.")
    return {"device": info.st_dev, "inode": info.st_ino, "uid": info.st_uid, "mode": stat.S_IMODE(info.st_mode)}


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


def hold_server(observer: Any, process: subprocess.Popen[Any], token: str, actor: dict[str, Any] | None) -> None:
    if actor is None:
        return
    if observer is not None:
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

    def spawn(process: subprocess.Popen[Any], *args: Any, **kwargs: Any) -> None:
        bound = signature.bind(process, *args, **kwargs)
        environment = bound.arguments.get("env")
        actor = server_call(bound.arguments.get("args"), dict(os.environ if environment is None else environment))
        original(process, *args, **kwargs)
        hold_server(None, process, "unobserved", actor)

    for name, operation in {"__init__": spawn}.items():
        setattr(subprocess.Popen, name, operation)
    _actor_installed = True


def _item_generation(frame: dict[str, Any], frames: list[dict[str, Any]], entries: list[dict[str, Any]], primary: int) -> str | None:
    """Trace actual source launches to the primary's one live item interval."""
    seen = set()
    while frame["pid"] != primary:
        if frame["epoch"] in seen:
            return None
        seen.add(frame["epoch"])
        starts = [row for row in frames if row["event"] == "process_start" and row["epoch"] == frame["epoch"]]
        if len(starts) != 1:
            return None
        start = starts[0]
        continuation = start.get("continuation")
        if isinstance(continuation, dict):
            parents = [row for row in frames if row["event"] == "exec_seal" and row["pid"] == frame["pid"]
                       and row["epoch"] == continuation.get("epoch") and row["sha256"] == continuation.get("sha256")]
        else:
            parents = [row for row in frames if row["event"] == "child_spawn" and row["epoch"] == start.get("parent_epoch")
                       and row.get("child_token") == start.get("child_token") and row.get("child_pid") == frame["pid"]]
        if len(parents) != 1:
            return None
        frame = parents[0]
    owners = [row for row in entries if row["epoch"] == frame["epoch"] and row["sequence"] < frame["sequence"]
              and any(end["event"] == "audit_socket_exit" and end["pid"] == primary and end["epoch"] == row["epoch"]
                      and end.get("socket") == row["socket"] and end.get("test_nodeid") == row["test_nodeid"]
                      and frame["sequence"] < end["sequence"] for end in frames)]
    return owners[0]["sha256"] if len(owners) == 1 else None


def review_sockets(frames: list[dict[str, Any]], *, primary: int, scope: dict[str, Any] | None,
                   records: dict[str, Any], native_exits: dict[str, dict[str, Any]]) -> list[str]:
    """Recheck the finite namespace facts; never trust an environment approval."""
    issues = []
    entries = [row for row in frames if row["event"] == "audit_socket_enter" and row["pid"] == primary]
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

        exits = [row for row in frames if row["event"] == "audit_socket_exit" and row["pid"] == primary
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
        for spawned in [row for row in frames if row["event"] == "audit_server_spawn" and row.get("socket") == str(path)]:
            closed = [row for row in frames if row["event"] == "audit_server_close" and row["pid"] == spawned["pid"]
                      and row.get("child_token") == spawned["child_token"] and row.get("child_pid") == spawned["child_pid"]]
            native = native_exits.get(spawned["epoch"] + ":" + spawned["child_token"])
            if (spawned.get("owner") != owner_identity("socket_client.py", "ensure_server")
                    or not ((len(closed) == 1 and closed[0].get("actual_wait_returncode") == 0)
                            or (native is not None and native["returncode"] == 0))):
                issues.append("observed default engine has no source-owned normal actual child wait")
    for connected in [row for row in frames if row["event"] == "audit_socket_connect"]:
        generation = _item_generation(connected, frames, entries, primary)
        bound = [row for row in frames if row["event"] == "audit_socket_bind" and row.get("initial_absent") is True
                 and row.get("socket") == connected["socket"] and row.get("endpoint") == connected.get("endpoint")
                 and generation is not None and _item_generation(row, frames, entries, primary) == generation
                 and row["monotonic_ns"] < connected["monotonic_ns"]
                 and ((row["pid"] == connected["pid"] and row["binding_token"] == connected.get("local_binding_token"))
                      or (isinstance(connected.get("socket_owner"), dict) and connected["socket_owner"].get("pid") == row["pid"]
                          and connected["socket_owner"].get("device") == row["endpoint"]["device"]
                          and connected["socket_owner"].get("inode") == row["endpoint"]["inode"]))]
        if not bound:
            issues.append("AF_UNIX connection has no observed fresh actor binding")
    if any(row["event"] == "untracked_socket_connect" for row in frames):
        issues.append("AF_UNIX connection bypassed its successful endpoint owner")
    if any(row["event"] in {"audit_socket_failed", "audit_server_failed"} for row in frames):
        issues.append("default engine actor cleanup failed")
    return issues
