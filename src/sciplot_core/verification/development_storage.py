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
import subprocess
import sys
import time
from typing import Any
from uuid import uuid4

from platformdirs import user_cache_path

DEVELOPMENT_ROOT_KEY = "SCIPLOT_DEV_PYTEST_ROOT"
SPACE_WARNING_BYTES = 5 * 1024**3
_KIND = "sciplot_development_cache"
RETAINED_BYTES = 512 * 1024**2
RETAINED_SECONDS = 7 * 86400
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
class DevelopmentCheckRun:
    command: list[str]
    environment: dict[str, str]
    managed: bool = False
    directory: Path | None = None
    cleanup: dict[str, Any] = field(default_factory=dict)
    _directory_fd: int = -1
    _finished: bool = False
    purpose: str = "pytest"

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
            "purpose": self.purpose,
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
        purpose = value.get("purpose", "pytest") if isinstance(value, dict) else None
        if (not isinstance(value, dict) or value.get("kind") != _KIND
                or value.get("version") != 1 or value.get("state") != "completed"
                or not isinstance(purpose, str) or purpose not in {"pytest", "mypy", "swift", "ruff"}
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


def _retained_size(directory_fd: int, limit: int) -> int:
    """Bound the accounting walk; aliases count only their own directory entry."""
    total = 0
    for name in os.listdir(directory_fd):
        info = os.stat(name, dir_fd=directory_fd, follow_symlinks=False)
        if stat.S_ISDIR(info.st_mode):
            child = os.open(name, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=directory_fd)
            try:
                total += _retained_size(child, limit - total)
            finally:
                os.close(child)
        else:
            total += info.st_size
        if total > limit:
            break
    return total


def _prune(base_fd: int) -> dict[str, Any]:
    result: dict[str, Any] = {"deleted": [], "kept_failed": [], "kept_cache": [], "protected": []}
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
                candidates.append((modified, name, value, directory_fd, lease))
                directory_fd = lease = -1
            except (OSError, ValueError, UnicodeError, RecursionError):
                result["protected"].append(name)
            finally:
                for fd in (lease, directory_fd):
                    if fd >= 0:
                        os.close(fd)
        failed = retained = 0
        tools: set[str] = set()
        for _modified, name, value, directory_fd, _lease in sorted(candidates, reverse=True):
            returncode = value["returncode"]
            purpose = value.get("purpose", "pytest")
            fresh = time.time_ns() - _modified <= RETAINED_SECONDS * 10**9
            keep = (returncode != 0 and failed < 2) or (returncode == 0 and purpose != "pytest" and purpose not in tools)
            if fresh and keep:
                try:
                    size = _retained_size(directory_fd, RETAINED_BYTES - retained)
                except (OSError, RecursionError):
                    result["protected"].append(name)
                    continue
                if size + retained <= RETAINED_BYTES:
                    retained += size
                    if returncode:
                        failed += 1
                    else:
                        tools.add(purpose)
                    result["kept_failed" if returncode else "kept_cache"].append(name)
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
        result["retained_bytes"] = retained
    except OSError as exc:
        result["warning"] = str(exc)
    finally:
        for _modified, _name, _returncode, directory_fd, lease in candidates:
            os.close(lease)
            os.close(directory_fd)
    return result


def _reuse_tool_cache(base_fd: int, purpose: str) -> tuple[str, int, int] | None:
    for name in os.listdir(base_fd):
        if not _NAME.fullmatch(name):
            continue
        directory_fd = lease = -1
        try:
            directory_fd = os.open(name, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=base_fd)
            lease = os.open("lease", os.O_RDWR | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=directory_fd)
            if not stat.S_ISREG(os.fstat(lease).st_mode):
                continue
            fcntl.flock(lease, fcntl.LOCK_EX | fcntl.LOCK_NB)
            completed = _completed(directory_fd)
            if completed is not None and completed[0].get("purpose") == purpose and completed[0]["returncode"] == 0:
                cache_fd = os.open("cache", os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=directory_fd)
                os.close(cache_fd)
                held = os.fstat(directory_fd)
                current = os.stat(name, dir_fd=base_fd, follow_symlinks=False)
                if (held.st_dev, held.st_ino) == (current.st_dev, current.st_ino):
                    result = name, directory_fd, lease
                    directory_fd = lease = -1
                    return result
        except (OSError, ValueError, UnicodeError, RecursionError):
            pass  # Unknown/busy caches are not reused or deleted.
        finally:
            for fd in (lease, directory_fd):
                if fd >= 0:
                    os.close(fd)
    return None


def _purpose(argv: list[str]) -> str | None:
    return argv[2] if len(argv) >= 3 and argv[1] == "-m" and argv[2] in {"pytest", "mypy", "ruff"} else (
        "swift" if argv and (Path(argv[0]).name == "swiftc" or
                           (Path(argv[0]).name == "xcrun" and argv[1:2] == ["swiftc"])) else None)


@contextmanager
def development_check_run(
    command: Sequence[str], root: Path, *, environment: Mapping[str, str] | None = None,
) -> Iterator[DevelopmentCheckRun]:
    """Own ordinary check scratch; compiler caches are revalidated by their tool.

    Pytest only cleans inside this run's separate container. A kernel lease, not
    pytest's time-limited lock file, protects concurrent and long-running tasks.
    No recorded output, worktree or unknown directory is a cleanup candidate.
    """
    inherited = dict(os.environ if environment is None else environment)
    argv = list(command)
    purpose = _purpose(argv)
    if purpose is None:
        yield DevelopmentCheckRun(argv, inherited)
        return
    clean = without_development_storage(inherited)
    cache_keys = {"mypy": ("MYPY_CACHE_DIR",), "ruff": ("RUFF_CACHE_DIR",),
                  "swift": ("CLANG_MODULE_CACHE_PATH", "SWIFT_MODULECACHE_PATH")}
    explicit = any(item.startswith(("--basetemp", "-o", "--override-ini", "--lf", "--last-failed",
                                   "--ff", "--failed-first", "--cache-", "--stepwise", "--sw", "--input-scope"))
                   for item in argv[3:]) if purpose == "pytest" else (
        any(item.startswith(("--cache-dir", "-module-cache-path")) for item in argv)
        or "--no-cache" in argv or any(clean.get(key) for key in cache_keys[purpose]))
    observed = (_observer_active() or any(clean.get(key) for key in _EVIDENCE_KEYS)
                or "sciplot_closure_audit" in clean.get("PYTEST_PLUGINS", ""))
    run = DevelopmentCheckRun(argv, clean, purpose=purpose)
    if (explicit or observed or clean.get("PYTEST_ADDOPTS", "").strip()
            or clean.get("PYTEST_DEBUG_TEMPROOT")):
        yield run
        return
    root = root.resolve()
    base = user_cache_path("SciPlot") / "development"
    resolved = base.resolve()
    if (resolved == root or resolved.is_relative_to(root) or root.is_relative_to(resolved)
            or any((path / ".git").exists() for path in (resolved, *resolved.parents))):
        raise ValueError("Disposable pytest storage must be outside source checkouts and projects.")
    if base.parent.is_symlink() or base.is_symlink():
        raise ValueError("Development scratch directories cannot follow symlinks.")
    base.mkdir(parents=True, exist_ok=True, mode=0o700)
    base_fd = os.open(base, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    lease = directory_fd = -1
    try:
        reused = _reuse_tool_cache(base_fd, purpose) if purpose != "pytest" else None
        if reused is None:
            name = "run-" + uuid4().hex
            os.mkdir(name, mode=0o700, dir_fd=base_fd)
            directory_fd = os.open(name, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=base_fd)
            lease = os.open("lease", os.O_RDWR | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW,
                            0o600, dir_fd=directory_fd)
            fcntl.flock(lease, fcntl.LOCK_EX | fcntl.LOCK_NB)
        else:
            name, directory_fd, lease = reused
        current = os.fstat(directory_fd)
        _write_state(directory_fd, {"kind": _KIND, "version": 1, "state": "running",
                                   "inode": [current.st_dev, current.st_ino], "returncode": None,
                                   "purpose": purpose})
        run.directory = base / name
        run.managed = True
        run._directory_fd = directory_fd
        if purpose != "pytest" and reused is None:
            os.mkdir("cache", mode=0o700, dir_fd=directory_fd)
        if purpose == "pytest":
            run.command.extend(["-o", "tmp_path_retention_count=2", "-o", "tmp_path_retention_policy=failed",
                                "-o", "cache_dir=" + str(run.directory / "pytest-cache")])
            run.environment.update({"PYTEST_DEBUG_TEMPROOT": str(run.directory),
                                    DEVELOPMENT_ROOT_KEY: str(run.directory)})
        elif purpose in {"mypy", "ruff"}:
            run.command.extend(["--cache-dir", str(run.directory / "cache")])
        else:
            run.command.extend(["-module-cache-path", str(run.directory / "cache")])
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


def main() -> int:
    command = sys.argv[1:]
    if command[:1] == ["--"]:
        command = command[1:]
    if _purpose(command) is None:
        raise ValueError("Expected python -m pytest/mypy/ruff, swiftc or xcrun swiftc.")
    code = None
    try:
        with development_check_run(command, Path.cwd()) as run:
            if run.managed:
                print(f"Development tool cache: {run.directory}", file=sys.stderr)
            code = subprocess.call(run.command, env=run.environment)
            run.finish(code)
    except OSError as exc:
        if code is None:
            raise
        print(f"Development cache finalization failed: {exc}", file=sys.stderr)
        return code
    if run.cleanup.get("warning"):
        print(run.cleanup["warning"], file=sys.stderr)
    return code


if __name__ == "__main__":
    raise SystemExit(main())
