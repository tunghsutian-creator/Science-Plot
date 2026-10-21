"""Held endpoint and closed launch facts for the single process boundary."""
from __future__ import annotations

import os
import json
from contextvars import ContextVar, Token
from dataclasses import dataclass, field
from pathlib import Path
import subprocess
import stat
from typing import Any, Mapping, Sequence

from sciplot_core.foundation.json_hashing import canonical_json_sha256
from sciplot_core.verification.evidence_runtime import runtime_loader_environment

_active: ContextVar[ExcludedInvocation | None] = ContextVar("sciplot_private_launch", default=None)


@dataclass
class ExcludedInvocation:
    argv: tuple[str, ...]
    environment: dict[str, str]
    stdio: tuple[int, int, int]
    proof: dict[str, Any]
    _duplicates: list[int] = field(repr=False)
    _target_argv: tuple[str, ...] = field(default=(), repr=False)
    _snapshot_json: str = field(default="", repr=False)
    _drop_environment: tuple[str, ...] = field(default=(), repr=False)
    _token: Token[ExcludedInvocation | None] | None = field(default=None, repr=False)

    def __enter__(self) -> ExcludedInvocation:
        if self._token is not None:
            raise ValueError("Private launch context cannot be entered twice.")
        self._token = _active.set(self)
        return self

    def __exit__(self, *_arguments: object) -> None:
        if self._token is not None:
            _active.reset(self._token)
            self._token = None
        for descriptor in self._duplicates:
            os.close(descriptor)
        self._duplicates.clear()


def current_invocation() -> ExcludedInvocation | None:
    return _active.get()


def bound_source_invocation(argv: Sequence[str], environment: Mapping[str, str], stdio: tuple[Any, Any, Any],
                            cwd: Path | None, dropped: Sequence[str]) -> ExcludedInvocation | None:
    current = current_invocation()
    if current is None or tuple(argv) != current.argv:
        return None
    payload = json.loads(current._snapshot_json)
    prefix = launch_prefix(payload, runtime_loader_environment(current.environment), current._drop_environment)
    retained = {key: item for key, item in environment.items() if key not in set(dropped)}
    expected = {key: item for key, item in current.environment.items() if key not in set(dropped)}
    if (stdio != current.stdio or str(Path.cwd() if cwd is None else cwd.absolute()) != current.proof["actual"]["cwd"]
            or retained != expected or current.argv != (*prefix, *current._target_argv)):
        raise ValueError("Source-owned exclusion invocation no longer matches its held launch.")
    return current


def socket_scope_facts(scope: Mapping[str, Any] | None) -> dict[str, Any] | None:
    """Check live endpoint namespace; the primary owner attests initial newness."""
    if scope is None:
        return None
    if set(scope) != {"sockets", "directory", "initial_absent"} or scope["initial_absent"] is not True:
        raise ValueError("Socket scope needs the exact fresh primary namespace fact.")
    names = scope["sockets"]
    if not isinstance(names, list) or not names or any(not isinstance(name, str) for name in names) or names != sorted(set(names)):
        raise ValueError("Socket scope requires finite distinct literal endpoints.")
    paths = [Path(name) for name in names]
    path = paths[0]
    if any(not item.is_absolute() or item.resolve() != item or item.parent != path.parent for item in paths):
        raise ValueError("Socket scope requires a canonical literal endpoint.")
    row = path.parent.lstat()
    identity = {"device": row.st_dev, "inode": row.st_ino, "uid": row.st_uid, "mode": stat.S_IMODE(row.st_mode)}
    if not stat.S_ISDIR(row.st_mode) or row.st_uid != os.getuid() or identity["mode"] != 0o700 or scope["directory"] != identity:
        raise ValueError("Socket namespace identity or private permissions changed.")
    for item in paths:
        try:
            endpoint = item.lstat()
        except FileNotFoundError:
            continue
        if not stat.S_ISSOCK(endpoint.st_mode) or endpoint.st_uid != os.getuid() or endpoint.st_nlink != 1:
            raise ValueError("Socket endpoint is not the ordinary owned socket.")
    return {"sockets": names, "directory": identity, "initial_absent": True}


def original_stdio_facts(stdin: Any = None, stdout: Any = None, stderr: Any = None) -> list[dict[str, Any]]:
    result = []
    for index, value in enumerate((stdin, stdout, stderr)):
        if type(value) is int and value < 0:
            if value not in {subprocess.PIPE, subprocess.DEVNULL, *({subprocess.STDOUT} if index == 2 else set())}:
                raise ValueError("Unsupported private exclusion stdio sentinel.")
            result.append({"kind": "sentinel", "value": value})
        else:
            descriptor = index if value is None else value if type(value) is int else value.fileno()
            if type(descriptor) is not int or descriptor < 0:
                raise ValueError("Invalid original stdio descriptor.")
            result.append({"kind": "inherit" if value is None else "fd" if type(value) is int else "stream", "fd": descriptor})
    return result


def hold_stdio(value: Any, index: int, forbidden: set[tuple[int, int]], duplicates: list[int]) -> tuple[int, dict[str, Any], dict[str, Any]]:
    original = original_stdio_facts(*([None] * index + [value] + [None] * (2 - index)))[index]
    if type(value) is int and value < 0:
        return value, original, dict(original)
    source = index if value is None else value if type(value) is int else value.fileno()
    if type(source) is not int or source < 0:
        raise ValueError("Private exclusion requires actual bound stdio descriptors.")
    descriptor = os.dup(source)
    duplicates.append(descriptor)
    row = os.fstat(descriptor)
    if (row.st_dev, row.st_ino) in forbidden:
        raise ValueError("Private exclusion refuses protected input/evidence stdio.")
    actual = {"kind": "bound_fd", "device": row.st_dev, "inode": row.st_ino, "mode": row.st_mode}
    return descriptor, original, actual


def launch_prefix(payload: Mapping[str, Any], loader: Mapping[str, str], dropped: Sequence[str]) -> tuple[str, ...]:
    return (payload["identity"]["sandbox"]["path"], "-p", payload["profile"], payload["identity"]["env"]["path"],
            *(part for key in dropped for part in ("-u", key)), "--", *(f"{key}={loader[key]}" for key in sorted(loader)))


def launch_facts(payload: Mapping[str, Any], argv: tuple[str, ...], environment: Mapping[str, str], *,
                        stdio: tuple[int, int, int], cwd: Path | None = None, close_fds: bool = True,
                        pass_fds: Sequence[int] = (), preexec_fn: Any = None, shell: bool = False,
                        executable: str | None = None, drop_environment: Sequence[str] = ()) -> dict[str, Any]:
    """Call independently on the immutable final original_init arguments."""
    if type(argv) is not tuple or shell is not False or executable is not None or close_fds is not True or pass_fds or preexec_fn is not None:
        raise ValueError("Unsafe actual private exclusion launch flags.")
    loader, dropped = runtime_loader_environment(environment), sorted(set(drop_environment))
    if (set(loader) & set(dropped) or any(key.startswith(("DYLD_", "LD_")) and key not in loader for key in environment)):
        raise ValueError("Unreviewed loader projection.")
    prefix = launch_prefix(payload, loader, dropped)
    target = {key: value for key, value in environment.items() if key not in dropped}
    rows = []
    for index, descriptor in enumerate(stdio):
        if type(descriptor) is not int:
            raise ValueError("Actual stdio must use the held descriptor or sentinel.")
        if descriptor < 0:
            rows.append(original_stdio_facts(*([None] * index + [descriptor] + [None] * (2 - index)))[index])
        else:
            row = os.fstat(descriptor)
            rows.append({"kind": "bound_fd", "device": row.st_dev, "inode": row.st_ino, "mode": row.st_mode})
    return {"argv_sha256": canonical_json_sha256(list(argv), allow_nan=False), "prefix_sha256": canonical_json_sha256(list(argv[:len(prefix)]), allow_nan=False),
            "suffix_sha256": canonical_json_sha256(list(argv[len(prefix):]), allow_nan=False), "launch_environment_sha256": canonical_json_sha256(dict(environment), allow_nan=False),
            "target_environment_sha256": canonical_json_sha256(target, allow_nan=False), "loader_environment": loader, "stdio": rows,
            "cwd": str(Path.cwd() if cwd is None else cwd.absolute()),
            "flags": {"close_fds": close_fds, "pass_fds": [], "preexec_fn": None, "shell": shell, "executable": executable}}


def validate_stdio(rows: list[Any], old: list[Any], excluded: set[tuple[int, int]]) -> None:
    for index, (row, prior) in enumerate(zip(rows, old, strict=True)):
        if not isinstance(row, dict) or not isinstance(prior, dict):
            raise ValueError("Invalid private exclusion stdio.")
        if row.get("kind") == "sentinel":
            allowed = {subprocess.PIPE, subprocess.DEVNULL, *({subprocess.STDOUT} if index == 2 else set())}
            if set(row) != {"kind", "value"} or row.get("value") not in allowed or row != prior:
                raise ValueError("Invalid private exclusion stdio sentinel.")
        elif (set(row) != {"kind", "device", "inode", "mode"} or row.get("kind") != "bound_fd"
                or set(prior) != {"kind", "fd"} or prior["kind"] not in {"inherit", "fd", "stream"}
                or type(prior["fd"]) is not int or prior["fd"] < 0
                or (prior["kind"] == "inherit" and prior["fd"] != index)
                or any(type(row[key]) is not int for key in ("device", "inode", "mode"))
                or (row["device"], row["inode"]) in excluded):
            raise ValueError("Unsafe private exclusion bound endpoint.")
