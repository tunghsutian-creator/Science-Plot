"""One live native registration port for the actual primary audit process."""
from __future__ import annotations

import json
import os
from pathlib import Path
import re
import signal
import sys
import threading
import time
from typing import Any

from sciplot_core.verification.native_exit_boundary import (
    NativeExitSensor, ProcessIdentity, read_identity, validate_exit_fact, validate_registration,
)
from sciplot_core.verification.private_process_boundaries import ZERO, executable_hash, frame_digest, source_hashes, owner_identity


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
    if rows[0]["pid"] != identity.ppid:
        raise ValueError("Native registration target is not this actual source producer's child.")
    spawned = [row for row in rows if row["event"] == "audit_server_spawn" and row.get("child_token") == request["token"]
               and row.get("child_pid") == identity.pid
               and all(row.get(key) == value for key, value in request["actor"].items())]
    sent = [row for row in rows if row["event"] == "native_registration_request" and row.get("request") == request]
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
                self.stopping.wait(.01)

    def register(self, request: dict[str, Any]) -> None:
        keys = {"generation", "epoch", "token", "identity", "actor"}
        if set(request) != keys or request["generation"] != request["epoch"] + ":" + request["token"]:
            raise ValueError("Native registration request is not closed.")
        scope = getattr(self.observer, "_audit_socket_scope", None)
        if (scope is None or request["actor"].get("owner") != owner_identity("socket_client.py", "ensure_server")
                or request["actor"]["socket"] not in scope[0]["sockets"]):
            raise ValueError("Native registration is outside the real item endpoint scope.")
        identity = ProcessIdentity.from_dict(request["identity"])
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


def register_server(observer: Any, process: Any, token: str, actor: dict[str, Any]) -> bool | None:
    if getattr(observer, "_exclusion_phase", None) is not None:
        return None
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


def validated_exits(frames: list[dict[str, Any]], *, primary: int) -> dict[str, dict[str, Any]]:
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
        if (len(sender) != 1 or len(spawned) != 1 or len(attempts) != 1 or len(terminal) != 1
                or spawned[0].get("owner") != owner_identity("socket_client.py", "ensure_server")
                or spawned[0].get("socket") != request["actor"]["socket"]
                or not _startup_bound(frames, request, attempts[0], binding)
                or request["generation"] != epoch + ":" + token
                or not validate_registration(registration, expected_identity=ProcessIdentity.from_dict(request["identity"]),
                    generation=request["generation"], watcher_binding=binding)):
            continue
        statuses = [item["fact"] for item in frames if item["event"] == "native_exit_status" and item["pid"] == primary
                    and item["fact"].get("generation") == request["generation"]]
        if len(statuses) == 1 and validate_exit_fact(statuses[0], registration):
            result[request["generation"]] = statuses[0]
    return result
