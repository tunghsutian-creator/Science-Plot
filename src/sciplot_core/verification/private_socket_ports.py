"""Source-bound socket observations; unknown facts never change connect results."""
from __future__ import annotations

import errno
import os
from pathlib import Path
import socket
import time
from typing import Any
import weakref
from uuid import uuid4

from sciplot_core.plot_protocol.paths import kernel_peer_pid
from sciplot_core.verification.native_exit_boundary import endpoint_identity as _endpoint
from sciplot_core.verification.private_process_boundaries import owned_caller

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
            connected_ns = time.monotonic_ns()
            facts: dict[str, Any] = {"event": "audit_socket_connect", "socket": str(path),
                                     "endpoint": identity, "connected_monotonic_ns": connected_ns}
            try:
                if _endpoint(address) != before:
                    facts["endpoint_observation_error"] = {"error_class": "ValueError", "errno": None}
            except (OSError, ValueError) as exc:
                facts["endpoint_observation_error"] = {"error_class": type(exc).__name__, "errno": getattr(exc, "errno", None)}
            local = bindings.get(str(path))
            token = None
            if local is not None and (owned := local[0]()) is not None and owned.fileno() >= 0 and local[1]["endpoint"] == identity:
                token = local[1]["binding_token"]
            from sciplot_core.plot_protocol.paths import read_owner
            try:
                owner = read_owner(path)
            except (OSError, ValueError):
                owner = None
            facts.update(local_binding_token=token, socket_owner=owner, peer_pid=None)
            try:
                facts["peer_pid"] = kernel_peer_pid(endpoint)
            except (OSError, ValueError) as exc:
                # Observation cannot change an already successful business call.
                # Missing peer facts remain explicit and are rechecked at review.
                facts["peer_lookup_error"] = {"error_class": type(exc).__name__, "errno": getattr(exc, "errno", None)}
            observer.record(facts, sync=True)

    for name, operation in (("bind", bind), ("listen", listen), ("connect", connect)):
        setattr(socket.socket, name, operation)


def _closed_native_binding(connected: dict[str, Any], actor: dict[str, Any], generation_key: str,
                           item_generation: str | None, native_exits: dict[str, dict[str, Any]]) -> bool:
    """Attribute a closed endpoint, never invent a kernel peer for this call.

    Actors/exits are already source-sealed and registration/exit validated by
    validated_exits. This finite case is not authorization for arbitrary sockets,
    descriptor handoffs, a Python bind alone or a merely claimed owner PID.
    """
    actual = native_exits.get(generation_key)
    connected_ns = connected.get("connected_monotonic_ns")
    return (connected.get("peer_pid") is None
        and connected.get("peer_lookup_error") == {"error_class": "OSError", "errno": errno.ENOTCONN}
        and connected.get("endpoint_observation_error") is None
        and item_generation is not None and actor["item_generation"] == item_generation
        and actor["socket"] == connected["socket"] and actor["ready"]["endpoint"] == connected.get("endpoint")
        and connected.get("socket_owner") == actor["ready"]["socket_owner"]
        and actor["ready"]["peer_pid"] == actor["identity"]["pid"]
        and actual is not None and actual["identity"] == actor["identity"]
        and actual["generation"] == generation_key and actual["status"] == "OBSERVED"
        and (actor["default_owned"] is False or actual["returncode"] == 0)
        and type(connected_ns) is int and actor["ready_monotonic_ns"] < connected_ns
        # This orders observations, not the exact kernel exit instant.
        and connected_ns <= actual["observed_monotonic_ns"])
