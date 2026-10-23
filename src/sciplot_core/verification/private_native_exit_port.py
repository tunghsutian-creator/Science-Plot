"""One live native registration port for the actual primary audit process."""
from __future__ import annotations

import json
import os
from pathlib import Path
import re
import signal
import socket
import sys
import threading
import time
from typing import Any

from sciplot_core.plot_protocol.paths import kernel_peer_pid
from sciplot_core.verification.native_exit_boundary import (
    NativeExitSensor, ProcessIdentity, read_identity, endpoint_identity, validate_exit_fact, validate_registration,
)
from sciplot_core.verification.private_process_boundaries import ZERO, executable_hash, frame_digest, source_hashes, owner_identity, owned_caller, live_native_request

def _image(identity: ProcessIdentity) -> tuple[str, str]:
    return identity.executable, identity.executable_sha256

def _server_identity(pid: int, socket_path: str, deadline: float) -> ProcessIdentity:
    """Resolve this one launch before registering; an UNKNOWN is never retried."""
    producer = read_identity(os.getpid())
    first = read_identity(pid)
    entry = str(Path(sys.executable).resolve(strict=True)), executable_hash(sys.executable)
    fields = ("pid", "ppid", "uid", "start_sec", "start_usec", "cwd")
    generation = tuple(getattr(first, key) for key in fields)
    if (first.ppid != producer.pid or first.uid != producer.uid
            or first.cwd != str(Path(socket_path).parent.resolve(strict=True)) or entry[1] is None):
        raise ValueError("Native server is not this source launch generation.")
    current = first
    while True:
        if tuple(getattr(current, key) for key in fields) != generation or _image(current) not in {entry, _image(producer)}:
            raise ValueError("Native server generation or launch image changed.")
        if time.monotonic() >= deadline:
            raise ValueError("Native server did not settle before registration.")
        if _image(current) == _image(producer):
            return current
        time.sleep(.01)
        current = read_identity(pid)

def _startup_bound(frames: list[dict[str, Any]], request: dict[str, Any], attempt: dict[str, Any],
                   binding: dict[str, Any]) -> bool:
    """Keep the requested entrypoint and actual kernel executable independent."""
    try:
        identity, watcher = request["identity"], binding["watcher_identity"]
        producer = [r for r in frames if r["event"] == "process_start" and r["epoch"] == request["epoch"]]
        child = [r for r in frames if r["event"] == "process_start" and r["pid"] == identity["pid"]
                 and r.get("parent_epoch") == request["epoch"] and r.get("child_token") == request["token"]
                 and r.get("continuation") is None]
        primary = [r for r in frames if r["event"] == "process_start" and r["pid"] == watcher["pid"]]
        if len(producer) != 1 or len(child) != 1 or len(primary) != 1:
            return False
        runtime = primary[0]["python_runtime"]
        entry = attempt.get("expected_executable_sha256")
        if not isinstance(entry, str) or re.fullmatch("[0-9a-f]{64}", entry) is None:
            return False
        return bool(identity["ppid"] == producer[0]["pid"] and identity["uid"] == watcher["uid"]
            and (identity["executable"], identity["executable_sha256"]) == (watcher["executable"], watcher["executable_sha256"])
            and attempt["expected_executable_sha256"] == producer[0]["executable_sha256"] == child[0]["executable_sha256"]
            and producer[0]["python_runtime"] == child[0]["python_runtime"] == runtime
            and identity["executable_sha256"] in runtime["loaded_core_sha256"]
            and binding["native_images"]["python_core"]["sha256"] in runtime["loaded_core_sha256"])
    except (KeyError, TypeError, ValueError):
        return False

def _epoch_rows(directory: Path, epoch: str) -> list[dict[str, Any]]:
    if not isinstance(epoch, str) or not re.fullmatch("[0-9a-f]{32}", epoch):
        raise ValueError("Native request generation is not a source epoch/token.")
    rows: list[dict[str, Any]] = []
    head = ZERO
    for raw in (directory / (epoch + ".jsonl")).read_bytes().splitlines(keepends=True):
        if not raw.endswith(b"\n"):
            break
        row = json.loads(raw)
        if (row["sequence"] != len(rows) or row["previous_sha256"] != head
                or row["sha256"] != frame_digest({key: value for key, value in row.items() if key != "sha256"})):
            raise ValueError("Native request producer chain is invalid.")
        head = row["sha256"]
        rows.append(row)
    if not rows or rows[0].get("observer_sources_sha256") != source_hashes():
        raise ValueError("Native request producer source is not bound.")
    return rows

def _live_request(directory: Path, request: dict[str, Any], identity: ProcessIdentity) -> None:
    if not isinstance(request["token"], str) or not re.fullmatch("[0-9a-f]{32}", request["token"]):
        raise ValueError("Native request generation is not a source epoch/token.")
    rows = _epoch_rows(directory, request["epoch"])
    if "launch" not in request["actor"] and rows[0]["pid"] != identity.ppid:
        raise ValueError("Native registration target is not this actual source producer's child.")
    sent = [row for row in rows if row["event"] == "native_registration_request" and row.get("request") == request]
    if len(sent) != 1:
        raise ValueError("Native registration has no actual source-owned server launch or unique request.")
    launch = request["actor"].get("launch")
    if launch is not None:
        from sciplot_core.verification.native_exit_boundary import validate_actor_launch
        if not validate_actor_launch(request, rows, rows[0]["pid"], {request["epoch"] + ":" + launch["token"]}):
            raise ValueError("Native peer has no exact actual fenced parent generation.")
        return
    spawned = [row for row in rows if row["event"] == "audit_server_spawn" and row.get("child_token") == request["token"]
               and row.get("child_pid") == identity.pid
               and all(row.get(key) == value for key, value in request["actor"].items())]
    if len(spawned) != 1 or len(sent) != 1 or spawned[0]["sequence"] >= sent[0]["sequence"]:
        raise ValueError("Native registration has no actual source-owned server launch.")

def _parent_exit(directory: Path, epoch: str, parent_pid: int) -> dict[str, str]:
    rows = _epoch_rows(directory, epoch)
    first, last = rows[0], rows[-1]
    if (first["pid"] != parent_pid or last["event"] != "process_finish"
            or last.get("recorded_events") != len(rows) - 1 or last.get("lost_events") != 0
            or not first.get("parent_epoch")):
        raise ValueError("Actor parent reparenting has no genuine finished producer.")
    ancestor = _epoch_rows(directory, first["parent_epoch"])
    exits = [row for row in ancestor if row["event"] == "child_exit" and row.get("child_pid") == parent_pid
             and row.get("child_token") == first.get("child_token") and row.get("returncode") == 0]
    if len(exits) != 1:
        raise ValueError("Actor parent reparenting has no actual normal parent exit.")
    return {"producer_epoch": epoch, "producer_finish_sha256": last["sha256"],
            "ancestor_epoch": first["parent_epoch"], "actual_parent_exit_sha256": exits[0]["sha256"]}

def _write(path: Path, value: dict[str, Any]) -> None:
    temporary = path.with_suffix(".pending")
    with temporary.open("x", encoding="utf-8") as stream:
        json.dump(value, stream, sort_keys=True)
        stream.flush()
        os.fsync(stream.fileno())
    temporary.replace(path)


class _Port:
    def __init__(self, observer: Any) -> None:
        self.observer = observer
        self.directory = observer.directory / "native-exits"
        self.directory.mkdir(mode=0o700)
        self.queue = self.directory / "requests"
        self.queue.touch(mode=0o600, exist_ok=False)
        self.sensor = NativeExitSensor()
        self.requests: dict[str, dict[str, Any]] = {}
        self.exits: dict[str, dict[str, Any]] = {}
        self.launches: dict[str, tuple[Any, dict[str, Any], ProcessIdentity, bool]] = {}
        self.discovered: set[tuple[str, int, int, int]] = set()
        self.lock = threading.RLock()
        self.stopping = threading.Event()
        observer.record({"event": "native_exit_sensor_start", "binding": self.sensor.binding}, sync=True)
        self.thread = threading.Thread(target=self.run, name="sciplot-native-exit-observer", daemon=True)
        self.thread.start()

    def run(self) -> None:
        with self.queue.open(encoding="utf-8") as stream:
            while not self.stopping.is_set():
                line = stream.readline()
                if line:
                    try:
                        request = json.loads(line)
                        self.register(request)
                    except (OSError, KeyError, TypeError, ValueError) as exc:
                        self.observer.record({"event": "native_exit_port_failed", "error_class": type(exc).__name__}, sync=True)
                with self.lock:
                    for fact in self.sensor.drain():
                        self.exits[fact["generation"]] = fact
                        self.observer.record({"event": "native_exit_status", "fact": fact}, sync=True)
                self.discover()
                self.stopping.wait(.01)

    def discover(self) -> None:
        """Observe only descendants of actual fenced launches in this live item."""
        from sciplot_core.plot_protocol.paths import read_owner
        from uuid import uuid4

        active = getattr(self.observer, "_audit_socket_scope", None)
        if active is None:
            return
        for name in active[0]["sockets"]:
            try:
                endpoint, owner = endpoint_identity(name, ready=True)[1], read_owner(Path(name))
                identity = read_identity(owner["pid"])
                generation = (name, identity.pid, identity.start_sec, identity.start_usec)
                if generation in self.discovered or owner["pid"] != identity.pid or endpoint_identity(name, ready=True)[1] != endpoint:
                    continue
                for token, (process, attempt, initial, managed) in list(self.launches.items()):
                    if attempt["nodeid"] != active[0]["test_nodeid"]:
                        continue
                    parent = identity if identity.pid == process.pid else read_identity(identity.ppid)
                    fields = ("pid", "ppid", "uid", "start_sec", "start_usec")
                    if tuple(getattr(parent, k) for k in fields) != tuple(getattr(initial, k) for k in fields):
                        continue
                    self.observer.guard.active = True
                    try:
                        with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as connection:
                            connection.settimeout(.1)
                            connection.connect(name)
                            peer_pid = kernel_peer_pid(connection)
                            if peer_pid != identity.pid or read_identity(identity.pid) != identity:
                                continue
                    finally:
                        self.observer.guard.active = False
                    if endpoint_identity(name, ready=True)[1] != endpoint:
                        continue
                    launch = {"token": token, "attempt_sha256": attempt["sha256"],
                              "initial": initial.to_dict(), "parent": parent.to_dict()}
                    actor = {"socket": name, "default_owned": managed,
                             "owner": owned_caller("private_native_exit_port.py", "_Port.discover"),
                             "launch": launch, "ready": {"endpoint": endpoint, "socket_owner": owner, "peer_pid": peer_pid}}
                    request = {"epoch": self.observer.epoch, "token": token if identity.pid == process.pid else uuid4().hex,
                               "identity": identity.to_dict(), "actor": actor}
                    request["generation"] = request["epoch"] + ":" + request["token"]
                    recorded = self.observer.record({"event": "native_registration_request", "request": request,
                        "test_nodeid": active[0]["test_nodeid"]}, sync=True)
                    if recorded is None:
                        raise ValueError("Native request was not recorded.")
                    self.register(request, recorded=recorded)
                    self.discovered.add(generation)
                    break
            except (OSError, ValueError, KeyError, TypeError):
                continue  # No real peer/ancestry/registration: never invent binding.

    def register(self, request: dict[str, Any], *, recorded: dict[str, Any] | None = None) -> None:
        keys = {"generation", "epoch", "token", "identity", "actor"}
        if set(request) != keys or request["generation"] != request["epoch"] + ":" + request["token"]:
            raise ValueError("Native registration request is not closed.")
        scope = getattr(self.observer, "_audit_socket_scope", None)
        expected = owner_identity("private_native_exit_port.py", "_Port.discover") if "launch" in request["actor"] else owner_identity("socket_client.py", "ensure_server")
        if (scope is None or request["actor"].get("owner") != expected
                or request["actor"]["socket"] not in scope[0]["sockets"]):
            raise ValueError("Native registration is outside the real item endpoint scope.")
        identity = ProcessIdentity.from_dict(request["identity"])
        if "launch" in request["actor"]:
            launch = request["actor"]["launch"]
            held = self.launches.get(launch["token"])
            if (held is None or held[1]["sha256"] != launch["attempt_sha256"]
                    or held[2].to_dict() != launch["initial"]
                    or request["actor"].get("default_owned") is not held[3]
                    or identity.uid != held[2].uid or not (identity.pid == held[0].pid or identity.ppid == held[0].pid)
                    or read_identity(held[0].pid).to_dict() != launch["parent"]):
                raise ValueError("Native request lost its actual held launch generation.")
        if not live_native_request(self.observer, request, recorded,
                primary=self.sensor.binding["watcher_identity"]["pid"], node=scope[0]["test_nodeid"]):
            _live_request(self.observer.directory, request, identity)
        watcher = ProcessIdentity.from_dict(self.sensor.binding["watcher_identity"])
        if _image(identity) != _image(watcher):
            raise ValueError("Native server executable differs from the actual audit runtime.")
        with self.lock:
            fact = self.sensor.register(request["generation"], identity)
            bound = {"request": request, "registration": fact, "test_nodeid": scope[0]["test_nodeid"]}
            self.requests[request["generation"]] = bound
        self.observer.record({"event": "native_exit_registration", **bound}, sync=True)
        _write(self.directory / (request["token"] + ".ack"), fact)

    def finish_node(self, facts: dict[str, Any]) -> None:
        from sciplot_core.plot_protocol.paths import read_owner

        for generation, bound in list(self.requests.items()):
            request, registration = bound["request"], bound["registration"]
            if bound["test_nodeid"] != facts["test_nodeid"] or not request["actor"].get("default_owned"):
                continue
            if generation not in self.exits and registration.get("status") == "REGISTERED":
                original = ProcessIdentity.from_dict(request["identity"])
                current = read_identity(original.pid)
                expected, actual = original.to_dict(), current.to_dict()
                lineage = None
                if current.ppid != original.ppid:
                    if current.ppid != 1:
                        raise ValueError("Actor parent changed to an unproved process.")
                    lineage = _parent_exit(self.observer.directory, request["epoch"], original.ppid)
                expected.pop("ppid")
                actual.pop("ppid")
                owner = read_owner(Path(request["actor"]["socket"]))
                if actual != expected or owner["pid"] != original.pid or original.pid <= 0:
                    raise ValueError("Native actor generation changed; no signal was sent.")
                os.kill(original.pid, signal.SIGTERM)
                self.observer.record({"event": "native_actor_stop", "generation": generation,
                    "registration_sha256": registration["registration_sha256"], "socket_owner": owner,
                    "current_identity": current.to_dict(), "parent_lineage": lineage}, sync=True)
            deadline = time.monotonic() + 20
            while generation not in self.exits and time.monotonic() < deadline:
                self.stopping.wait(.01)
            if self.exits.get(generation, {}).get("returncode") != 0:
                raise ValueError("Owned default actor has no normal genuine kernel exit.")

    def close(self) -> None:
        self.stopping.set()
        self.thread.join(timeout=5)
        with self.lock:
            for fact in self.sensor.drain():
                self.observer.record({"event": "native_exit_status", "fact": fact}, sync=True)
            for fact in self.sensor.close():
                self.observer.record({"event": "native_exit_status", "fact": fact}, sync=True)
        self.observer.record({"event": "native_exit_sensor_close", "thread_stopped": not self.thread.is_alive()}, sync=True)

def start_port(observer: Any) -> None:
    if (sys.platform == "darwin" and getattr(observer, "_exclusion_collection", None) is not None
            and not hasattr(observer, "_native_exit_port")):
        observer._native_exit_port = _Port(observer)

def observe_launch(observer: Any, process: Any, token: str, attempt: dict[str, Any] | None,
                   actor: dict[str, Any] | None) -> None:
    port = getattr(observer, "_native_exit_port", None)
    if port is None or attempt is None or (attempt.get("input_boundary") or {}).get("kind") != "sciplot_private_input_excluded_invocation":
        return
    try:
        identity = read_identity(process.pid)
        if identity.ppid != os.getpid() or identity.uid != os.getuid():
            raise ValueError("Fenced launch changed before native observation.")
        port.launches[token] = process, attempt, identity, bool(actor and actor["default_owned"])
        if actor is not None:
            deadline = time.monotonic() + 5
            while time.monotonic() < deadline:
                if any(r["request"]["actor"].get("launch", {}).get("token") == token for r in list(port.requests.values())):
                    return
                time.sleep(.01)
            raise ValueError("Source-owned actor has no registered native readiness.")
    except (OSError, ValueError):
        observer.record({"event": "native_exit_port_failed", "error_class": "launch_identity_unavailable"}, sync=True)

def register_server(observer: Any, process: Any, token: str, actor: dict[str, Any]) -> bool | None:
    if getattr(observer, "_exclusion_phase", None) is not None:
        port = getattr(observer, "_native_exit_port", None)
        return True if port and any(r["request"]["actor"].get("launch", {}).get("token") == token
                                   for r in list(port.requests.values())) else None
    directory = observer.directory / "native-exits"
    if not (directory / "requests").is_file():
        return None
    try:
        deadline = time.monotonic() + 5
        identity = _server_identity(process.pid, actor["socket"], deadline)
        request = {"generation": observer.epoch + ":" + token, "epoch": observer.epoch,
                   "token": token, "identity": identity.to_dict(), "actor": actor}
        observer.record({"event": "native_registration_request", "request": request}, sync=True)
        if time.monotonic() >= deadline:
            return False
        content = (json.dumps(request, sort_keys=True) + "\n").encode()
        descriptor = os.open(directory / "requests", os.O_WRONLY | os.O_APPEND | os.O_NOFOLLOW)
        try:
            if os.write(descriptor, content) != len(content):
                raise OSError("Native request append was incomplete.")
        finally:
            os.close(descriptor)
        ack = directory / (token + ".ack")
        while not ack.exists() and time.monotonic() < deadline:
            time.sleep(.01)
        if not ack.exists():
            return False
        value = json.loads(ack.read_bytes())
        return bool(time.monotonic() < deadline and value.get("status") == "REGISTERED" and value.get("generation") == request["generation"] and value.get("identity") == request["identity"])
    except (OSError, TypeError, ValueError):
        return False

def finish_node(observer: Any, facts: dict[str, Any]) -> None:
    port = getattr(observer, "_native_exit_port", None)
    if port is not None:
        port.finish_node(facts)

def close_port(observer: Any) -> None:
    port = getattr(observer, "_native_exit_port", None)
    if port is not None:
        port.close()

def validated_exits(frames: list[dict[str, Any]], *, primary: int, source_exclusions: set[str] | None = None,
                    actors: dict[str, dict[str, Any]] | None = None) -> dict[str, dict[str, Any]]:
    starts = [row for row in frames if row["event"] == "native_exit_sensor_start" and row["pid"] == primary]
    closes = [row for row in frames if row["event"] == "native_exit_sensor_close" and row["pid"] == primary]
    if (len(starts) != 1 or starts[0]["binding"]["watcher_identity"]["pid"] != primary
            or len(closes) != 1 or closes[0].get("thread_stopped") is not True):
        return {}
    binding = starts[0]["binding"]
    result = {}
    for row in [item for item in frames if item["event"] == "native_exit_registration" and item["pid"] == primary]:
        request, registration = row["request"], row["registration"]
        epoch, token = request["epoch"], request["token"]
        sender = [item for item in frames if item["event"] == "native_registration_request" and item["epoch"] == epoch
                  and item.get("request") == request]
        spawned = [item for item in frames if item["event"] == "audit_server_spawn" and item["epoch"] == epoch
                   and item.get("child_token") == token and item.get("child_pid") == request["identity"]["pid"]]
        attempts = [item for item in frames if item["event"] == "spawn_attempt" and item["epoch"] == epoch and item.get("child_token") == token]
        terminal = [item for item in frames if item["event"] == "process_finish" and item["pid"] == request["identity"]["pid"]]
        launch = request["actor"].get("launch")
        if launch is not None:
            from sciplot_core.verification.native_exit_boundary import validate_actor_launch
            source_bound = validate_actor_launch(request, frames, primary, source_exclusions or set())
        else:
            source_bound = (len(spawned) == len(attempts) == len(terminal) == 1
                and spawned[0].get("owner") == owner_identity("socket_client.py", "ensure_server")
                and spawned[0].get("socket") == request["actor"]["socket"]
                and _startup_bound(frames, request, attempts[0], binding))
        if (len(sender) != 1 or not source_bound or request["generation"] != epoch + ":" + token
                or not validate_registration(registration, expected_identity=ProcessIdentity.from_dict(request["identity"]),
                    generation=request["generation"], watcher_binding=binding)):
            continue
        statuses = [item["fact"] for item in frames if item["event"] == "native_exit_status" and item["pid"] == primary
                    and item["fact"].get("generation") == request["generation"]]
        if len(statuses) == 1 and validate_exit_fact(statuses[0], registration):
            result[request["generation"]] = statuses[0]
            if actors is not None and launch is not None:
                actors[request["generation"]] = {**request["actor"], "identity": request["identity"],
                    "ready_monotonic_ns": sender[0]["monotonic_ns"], "launch_epoch": epoch,
                    "launch_token": launch["token"]}
    return result
