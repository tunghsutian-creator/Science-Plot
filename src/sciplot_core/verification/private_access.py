"""Producer open facts and one lossless private-access receipt projection.

An audit event describes an attempted operation, not a returned descriptor.
Directory-open facts grant no directory enumeration or descendant content access.
"""
from __future__ import annotations

import os
import errno
from functools import wraps
import operator
from pathlib import Path
import re
import stat
import sys
import threading
from typing import Any

_open_context = threading.local()
_port_installed = False


def _primitive_path(value: Any) -> str | bytes:
    path = os.fspath(value)
    # CPython's path converter uses the primitive contents, not subclass
    # equality/decode callbacks. Do the same before activating any context.
    return str.__str__(path) if isinstance(path, str) else bytes.__bytes__(path)


def _fd_identity(info: os.stat_result) -> tuple[int, int, int]:
    return info.st_dev, info.st_ino, info.st_mode


def install_open_port() -> None:
    """Retain the real dir_fd for its synchronous CPython audit hook only."""
    global _port_installed
    if _port_installed:
        return
    original = os.open

    @wraps(original)
    def opened(path: Any, flags: int, mode: int = 0o777, *, dir_fd: int | None = None) -> int:
        previous = getattr(_open_context, "request", None)
        # Execute argument protocols once, before this call's context exists.
        # A __fspath__/__index__ callback must not borrow the outer dir_fd.
        _open_context.request = None
        try:
            actual_path = _primitive_path(path)
            actual_flags, actual_mode = operator.index(flags), operator.index(mode)
            actual_fd = None if dir_fd is None else operator.index(dir_fd)
            _open_context.request = (actual_path, actual_flags, actual_fd)
            return original(actual_path, actual_flags, actual_mode, dir_fd=actual_fd)
        finally:
            _open_context.request = previous

    os.open = opened
    _port_installed = True


def _fd_path(descriptor: int) -> tuple[Path | None, str | None]:
    """Resolve this live FD, never a cached path or descriptor number grant."""
    try:
        before = os.fstat(descriptor)
    except OSError as exc:
        return None, "invalid_descriptor" if exc.errno == errno.EBADF else "unknown_descriptor"
    try:
        nonfilesystem = "pipe" if stat.S_ISFIFO(before.st_mode) else "socket" if stat.S_ISSOCK(before.st_mode) else None
        if sys.platform == "darwin":
            import fcntl
            name = os.fsdecode(fcntl.fcntl(descriptor, fcntl.F_GETPATH, b"\0" * 1024).split(b"\0", 1)[0])
        elif sys.platform.startswith("linux"):
            name = os.readlink(f"/proc/self/fd/{descriptor}")
            if nonfilesystem and name.startswith(nonfilesystem + ":[") and name.endswith("]"):
                return (None, "nonfilesystem_" + nonfilesystem) if _fd_identity(before) == _fd_identity(os.fstat(descriptor)) else (None, "unknown_descriptor")
        else:
            return None, "unknown_descriptor"
        path = Path(name)
        if not path.is_absolute() or name.endswith(" (deleted)") or path.resolve() != path:
            return None, "unknown_descriptor"
        current, after = path.lstat(), os.fstat(descriptor)
        if _fd_identity(before) != _fd_identity(current) or _fd_identity(current) != _fd_identity(after):
            return None, "unknown_descriptor"
        return path, None
    except OSError as exc:
        if sys.platform == "darwin" and exc.errno == errno.EBADF and nonfilesystem:
            try:
                if _fd_identity(before) == _fd_identity(os.fstat(descriptor)):
                    return None, "nonfilesystem_" + nonfilesystem
            except OSError:
                pass
        return None, "unknown_descriptor"
    except (ValueError, RuntimeError):
        return None, "unknown_descriptor"


def access_path(event: str, args: tuple[Any, ...]) -> tuple[Path | None, str | None]:
    """Resolve the actual supported Python request, including FD arguments.

    Invalid descriptors keep the original operation's exception. Live descriptors
    with unknown paths fail closed at each sensor, never falling back to cwd.
    This observes requests; it does not assert successful reads or kernel-wide IO.
    """
    if not args:
        return None, None
    value = args[0]
    if isinstance(value, int):
        # CPython's directory path converter uses -1 for its cwd/default,
        # including an explicit -1 argument. It is not a failed FD request.
        if value == -1 and event in {"os.listdir", "os.scandir"}:
            return Path.cwd(), None
        return _fd_path(value)
    if value is None and event in {"os.listdir", "os.scandir"}:
        value = os.curdir
    if not isinstance(value, (str, bytes, os.PathLike)):
        return None, None
    value = _primitive_path(value)
    path = Path(os.fsdecode(value))
    if event == "open" and len(args) == 3 and args[1] is None and not path.is_absolute():
        request = getattr(_open_context, "request", None)
        if (request is not None and os.fsdecode(request[0]) == os.fsdecode(value)
                and type(args[2]) is int and args[2] & ~getattr(os, "O_CLOEXEC", 0) == request[1] & ~getattr(os, "O_CLOEXEC", 0)):
            descriptor = request[2]
            if descriptor is not None:
                # Explicit openat cwd sentinels are valid requests despite
                # fstat(sentinel) == EBADF. These are this producer's OS ABI.
                cwd_fd = -2 if sys.platform == "darwin" else -100 if sys.platform.startswith("linux") else None
                if descriptor == cwd_fd:
                    return Path(os.path.abspath(path)), None
                base, issue = _fd_path(descriptor)
                if base is None:
                    return None, issue
                if not stat.S_ISDIR(base.lstat().st_mode):
                    return None, "invalid_descriptor"  # The real open will raise ENOTDIR.
                path = base / path
        else:
            return None, "unknown_open_context"
    return Path(os.path.abspath(path)), None


def observed_access(event: str, args: tuple[Any, ...], roots: tuple[Path, ...]) -> dict[str, Any] | None:
    """Turn a resolved Python request into one observer fact, without data."""
    path, issue = access_path(event, args)
    if issue in {"nonfilesystem_pipe", "nonfilesystem_socket"}:
        return {"event": "nonfilesystem_descriptor", "descriptor_kind": issue.removeprefix("nonfilesystem_"), "access_event": event}
    if issue is not None and issue != "invalid_descriptor":
        return {"event": "sensor_failure", "operation": issue, "access_event": event}
    if path is not None:
        resolved = path.resolve()
        if any(path.is_relative_to(root) or resolved.is_relative_to(root) for root in roots):
            return {"event": event, "path": str(path), "resolved_path": str(resolved),
                    **(open_facts(args) if event == "open" else {})}
    return None


def open_constants() -> dict[str, Any]:
    """Snapshot constants in the producer; consumers never use their own masks."""
    return {"platform": sys.platform, **{name: getattr(os, name, None) for name in (
        "O_RDONLY", "O_ACCMODE", "O_DIRECTORY", "O_NOFOLLOW", "O_CLOEXEC",
    )}}


def open_facts(args: tuple[Any, ...]) -> dict[str, Any]:
    """Retain CPython's mode/flags, without recording data or arbitrary args."""
    if (len(args) != 3 or (args[1] is not None and not isinstance(args[1], str))
            or type(args[2]) is not int):
        return {}  # Unknown facts can never derive directory-open permission.
    return {"open_mode": args[1], "open_flags": args[2]}


def _directory_request(facts: dict[str, Any]) -> bool:
    constants = facts.get("constants")
    flags = facts.get("flags")
    if (set(facts) != {"mode", "flags", "constants", "raw"}
            or facts.get("mode") is not None or type(flags) is not int or flags < 0
            or not isinstance(constants, dict)
            or set(constants) != {"platform", "O_RDONLY", "O_ACCMODE", "O_DIRECTORY", "O_NOFOLLOW", "O_CLOEXEC"}
            or not isinstance(constants["platform"], str) or not constants["platform"]):
        return False
    names = ("O_RDONLY", "O_ACCMODE", "O_DIRECTORY", "O_NOFOLLOW", "O_CLOEXEC")
    if not all(type(constants[name]) is int and constants[name] >= 0 for name in names):
        return False
    readonly, access, directory, nofollow, cloexec = (constants[name] for name in names)
    if (not access or not directory or not nofollow or not cloexec or readonly & ~access
            or any(left & right for left, right in (
                (access, directory), (access, nofollow), (access, cloexec),
                (directory, nofollow), (directory, cloexec), (nofollow, cloexec),
            ))):
        return False
    required = readonly | directory | nofollow
    return flags in {required, required | cloexec} and flags & access == readonly


def file_parent_open(event: dict[str, Any], dependencies: list[tuple[str, str]]) -> bool:
    """Derive only an exact file's direct-parent metadata-open request."""
    facts = event.get("open")
    if event.get("event") != "open" or not isinstance(facts, dict) or not _directory_request(facts):
        return False
    raw = facts.get("raw")
    if (not isinstance(raw, dict)
            or set(raw) != {"epoch", "sequence", "sha256", "path", "resolved_path"}
            or not isinstance(raw.get("epoch"), str) or not re.fullmatch(r"[0-9a-f]{32}", raw["epoch"])
            or type(raw.get("sequence")) is not int or raw["sequence"] < 1
            or not isinstance(raw.get("sha256"), str) or not re.fullmatch(r"[0-9a-f]{64}", raw["sha256"])
            or not isinstance(raw.get("path"), str) or not Path(raw["path"]).is_absolute()
            or raw["path"] != raw.get("resolved_path")):
        return False  # Even an in-namespace alias cannot acquire this permission.
    path = Path(event["path"])
    return any(kind == "file" and path == Path(identifier).parent for identifier, kind in dependencies)


def access_events(capture: dict[str, Any], aliases: list[tuple[Path, Path]]) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Project verified raw frames identically for the exporter and verifier.

    Callers must first obtain a complete source/runtime/wait-bound review_capture.
    Original facts and their stream identity remain in each normalized open row.
    Missing old facts stay missing; no role is reconstructed from a path or caller.
    """
    starts = {frame["epoch"]: frame for frame in capture["frames"] if frame["event"] == "process_start"}
    diagnostics = {(row["epoch"], row["sequence"]) for row in capture["diagnostic_observations"]}
    events: list[dict[str, Any]] = []
    collection: list[dict[str, Any]] = []
    for frame in capture["frames"]:
        if frame["event"] not in {"open", "os.scandir", "os.listdir"}:
            continue
        actual, resolved = Path(frame["path"]), Path(frame["resolved_path"])
        if actual.resolve() != resolved:
            raise ValueError("observed private path alias changed")
        identifier = next((prefix / resolved.relative_to(root) for root, prefix in aliases
                           if resolved.is_relative_to(root)), None)
        if identifier is None or (frame["epoch"], frame["sequence"]) in diagnostics:
            continue
        nodeid = re.sub(r" \((setup|call|teardown)\)$", "", frame["nodeid"])
        row: dict[str, Any] = {"event": frame["event"], "path": identifier.as_posix(), "nodeid": nodeid}
        if frame["event"] == "open" and ("open_mode" in frame or "open_flags" in frame):
            if ("open_mode" not in frame or "open_flags" not in frame
                    or (frame["open_mode"] is not None and not isinstance(frame["open_mode"], str))
                    or type(frame["open_flags"]) is not int):
                raise ValueError("malformed original open facts")
            row["open"] = {"mode": frame["open_mode"], "flags": frame["open_flags"],
                           "constants": starts[frame["epoch"]].get("open_constants"),
                           "raw": {key: frame[key] for key in ("epoch", "sequence", "sha256", "path", "resolved_path")}}
        if not nodeid and row["event"] in {"os.scandir", "os.listdir"}:
            collection.append({**row, "classification": "collector-directory-enumeration"})
        else:
            events.append(row)
    return events, collection
