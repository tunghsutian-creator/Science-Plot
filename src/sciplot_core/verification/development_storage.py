"""Bound disposable development pytest files, never verification evidence."""
from __future__ import annotations

from collections.abc import Iterator, Mapping, Sequence
from contextlib import contextmanager
from dataclasses import dataclass, field
import fcntl
import json
import os
from pathlib import Path
import re
import shutil
import stat
import sys
from typing import Any
from uuid import uuid4

DEVELOPMENT_ROOT_KEY = "SCIPLOT_DEV_PYTEST_ROOT"
SPACE_WARNING_BYTES = 5 * 1024**3
_KIND = "sciplot_disposable_pytest"
_NAME = re.compile(r"run-[0-9a-f]{32}\Z")
_EVIDENCE_KEYS = ("SCIPLOT_VERIFY_FINISH", "SCIPLOT_PRIVATE_AUDIT_DIR",
                  "SCIPLOT_PRIVATE_AUDIT_ROOTS", "SCIPLOT_PRIVATE_AUDIT_RUN",
                  "SCIPLOT_PRIVATE_AUDIT_PARENT", "SCIPLOT_PRIVATE_AUDIT_CHILD",
                  "SCIPLOT_PRIVATE_AUDIT_CONTINUATION", "SCIPLOT_AUDIT_ACTOR_SOCKET")


def without_development_storage(environment: Mapping[str, str]) -> dict[str, str]:
    """Drop only our inherited temp override before a recorded execution."""
    result = dict(environment)
    owned = result.pop(DEVELOPMENT_ROOT_KEY, None)
    if owned is not None and result.get("PYTEST_DEBUG_TEMPROOT") == owned:
        result.pop("PYTEST_DEBUG_TEMPROOT")
    return result


def space_observation(root: Path) -> dict[str, Any]:
    """Report current capacity; this is neither a quota nor a predicted peak."""
    try:
        free = shutil.disk_usage(root).free
    except OSError as exc:
        return {"free_bytes": None, "warning_threshold_bytes": SPACE_WARNING_BYTES,
                "low_space": None, "warning": f"Development free space is unavailable: {exc}"}
    low = free < SPACE_WARNING_BYTES
    return {"free_bytes": free, "warning_threshold_bytes": SPACE_WARNING_BYTES,
            "low_space": low, "warning": (
                "Less than 5 GiB is available; inspect disposable development files "
                "before a write-intensive run. Evidence and unknown runs are not auto-deleted."
                if low else None)}


def _observer_active() -> bool:
    module = sys.modules.get("sciplot_core.verification.private_observer")
    if module is None:
        return False
    current = getattr(module, "current_observer", None)
    return current is None or current() is not None


def _write_state(directory_fd: int, payload: dict[str, Any]) -> None:
    fd = os.open(".run.tmp", os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW,
                 0o600, dir_fd=directory_fd)
    with os.fdopen(fd, "w", encoding="utf-8") as stream:
        json.dump(payload, stream)
        stream.write("\n")
    os.replace(".run.tmp", "run.json", src_dir_fd=directory_fd, dst_dir_fd=directory_fd)


@dataclass
class DevelopmentPytestRun:
    command: list[str]
    environment: dict[str, str]
    managed: bool = False
    directory: Path | None = None
    cleanup: dict[str, Any] = field(default_factory=dict)
    _directory_fd: int = -1
    _finished: bool = False

    def finish(self, returncode: int) -> None:
        """Call only after the original child has returned its actual exit code."""
        if not self.managed:
            return
        if self._finished:
            raise RuntimeError("The development pytest child was already completed.")
        if type(returncode) is not int:
            raise TypeError("The child exit code must be an integer.")
        current = os.fstat(self._directory_fd)
        _write_state(self._directory_fd, {
            "kind": _KIND, "version": 1, "state": "completed",
            "inode": [current.st_dev, current.st_ino], "returncode": returncode,
        })
        self._finished = True


def _completed(directory_fd: int) -> tuple[dict[str, Any], int] | None:
    fd = os.open("run.json", os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=directory_fd)
    try:
        info = os.fstat(fd)
        if not stat.S_ISREG(info.st_mode) or info.st_size > 8192:
            return None
        value = json.loads(os.read(fd, 8193))
        own = os.fstat(directory_fd)
        if (not isinstance(value, dict) or value.get("kind") != _KIND
                or value.get("version") != 1 or value.get("state") != "completed"
                or value.get("inode") != [own.st_dev, own.st_ino]
                or type(value.get("returncode")) is not int):
            return None
        return value, info.st_mtime_ns
    finally:
        os.close(fd)


def _remove_contents(directory_fd: int) -> None:
    """Delete inside the held owned inode, never a replacement of its old name."""
    for name in os.listdir(directory_fd):
        info = os.stat(name, dir_fd=directory_fd, follow_symlinks=False)
        if stat.S_ISDIR(info.st_mode):
            shutil.rmtree(name, dir_fd=directory_fd)
        else:
            os.unlink(name, dir_fd=directory_fd)


def _prune(base_fd: int) -> dict[str, Any]:
    result: dict[str, Any] = {"deleted": [], "kept_failed": [], "protected": []}
    candidates = []
    try:
        for name in os.listdir(base_fd):
            if not _NAME.fullmatch(name):
                continue
            directory_fd = lease = -1
            try:
                directory_fd = os.open(name, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW,
                                       dir_fd=base_fd)
                lease = os.open("lease", os.O_RDWR | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=directory_fd)
                if not stat.S_ISREG(os.fstat(lease).st_mode):
                    result["protected"].append(name)
                    continue
                fcntl.flock(lease, fcntl.LOCK_EX | fcntl.LOCK_NB)
                completed = _completed(directory_fd)
                if completed is None:
                    result["protected"].append(name)
                    continue
                value, modified = completed
                candidates.append((modified, name, value["returncode"], directory_fd, lease))
                directory_fd = lease = -1
            except (OSError, ValueError, UnicodeError, RecursionError):
                result["protected"].append(name)
            finally:
                for fd in (lease, directory_fd):
                    if fd >= 0:
                        os.close(fd)
        failed = 0
        for _modified, name, returncode, directory_fd, _lease in sorted(candidates, reverse=True):
            if returncode != 0:
                failed += 1
                if failed <= 2:
                    result["kept_failed"].append(name)
                    continue
            current = os.stat(name, dir_fd=base_fd, follow_symlinks=False)
            held = os.fstat(directory_fd)
            if ((current.st_dev, current.st_ino) != (held.st_dev, held.st_ino)
                    or not shutil.rmtree.avoids_symlink_attacks):
                result["protected"].append(name)
                continue
            _remove_contents(directory_fd)
            current = os.stat(name, dir_fd=base_fd, follow_symlinks=False)
            if (current.st_dev, current.st_ino) != (held.st_dev, held.st_ino):
                result["protected"].append(name)
                continue
            os.rmdir(name, dir_fd=base_fd)
            result["deleted"].append(name)
    except OSError as exc:
        result["warning"] = str(exc)
    finally:
        for _modified, _name, _returncode, directory_fd, lease in candidates:
            os.close(lease)
            os.close(directory_fd)
    return result


@contextmanager
def development_pytest_run(
    command: Sequence[str], root: Path, *, environment: Mapping[str, str] | None = None,
) -> Iterator[DevelopmentPytestRun]:
    """Own one ordinary pytest's scratch lifespan; unfinished runs stay protected.

    Pytest only cleans inside this run's separate container. A kernel lease, not
    pytest's time-limited lock file, protects concurrent and long-running tasks.
    No recorded output, worktree or unknown directory is a cleanup candidate.
    """
    inherited = dict(os.environ if environment is None else environment)
    argv = list(command)
    if argv[1:3] != ["-m", "pytest"]:
        yield DevelopmentPytestRun(argv, inherited)
        return
    clean = without_development_storage(inherited)
    explicit = any(item == "--basetemp" or item.startswith("--basetemp=")
                   or item.startswith("-o") or item.startswith("--override-ini") for item in argv[3:])
    observed = (_observer_active() or any(clean.get(key) for key in _EVIDENCE_KEYS)
                or "sciplot_closure_audit" in clean.get("PYTEST_PLUGINS", ""))
    run = DevelopmentPytestRun(argv, clean)
    if (explicit or observed or clean.get("PYTEST_ADDOPTS", "").strip()
            or clean.get("PYTEST_DEBUG_TEMPROOT")):
        yield run
        return
    root = root.resolve()
    base = root / ".tmp_verify" / "pytest-development"
    if base.parent.is_symlink() or base.is_symlink():
        raise ValueError("Development scratch directories cannot follow symlinks.")
    base.mkdir(parents=True, exist_ok=True, mode=0o700)
    base_fd = os.open(base, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    lease = directory_fd = -1
    try:
        name = "run-" + uuid4().hex
        os.mkdir(name, mode=0o700, dir_fd=base_fd)
        directory_fd = os.open(name, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=base_fd)
        lease = os.open("lease", os.O_RDWR | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW,
                        0o600, dir_fd=directory_fd)
        fcntl.flock(lease, fcntl.LOCK_EX | fcntl.LOCK_NB)
        current = os.fstat(directory_fd)
        _write_state(directory_fd, {"kind": _KIND, "version": 1, "state": "running",
                                   "inode": [current.st_dev, current.st_ino], "returncode": None})
        run.directory = base / name
        run.managed = True
        run._directory_fd = directory_fd
        run.command.extend(["-o", "tmp_path_retention_count=2", "-o", "tmp_path_retention_policy=failed"])
        run.environment.update({"PYTEST_DEBUG_TEMPROOT": str(run.directory),
                                DEVELOPMENT_ROOT_KEY: str(run.directory)})
        yield run
    finally:
        if lease >= 0:
            os.close(lease)
        if directory_fd >= 0:
            os.close(directory_fd)
        try:
            run.cleanup = _prune(base_fd)
        finally:
            os.close(base_fd)
