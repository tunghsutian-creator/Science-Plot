"""Mac process input exclusion facts; callers own node scope and actual waits.

This leaf does not activate an observer, grant an auxiliary classification or
claim a child's sensor completed. It never opens protected data for reading.
"""
from __future__ import annotations

from dataclasses import dataclass, field
import hashlib
import json
import os
from pathlib import Path
import shutil
import stat
import subprocess
import sys
from typing import Any, Mapping, Sequence

from sciplot_core.foundation.json_hashing import canonical_json_sha256
from sciplot_core.verification.evidence_runtime import runtime_loader_environment
from sciplot_core.verification.public_input_guard import forbidden_roots

SANDBOX = Path("/usr/bin/sandbox-exec")
ENV = Path("/usr/bin/env")
SYSTEM = Path("/System/Library/CoreServices/SystemVersion.plist")
KIND = "sciplot_private_input_excluded_invocation"


def _digest(value: object) -> str:
    return canonical_json_sha256(value, allow_nan=False)


def _metadata(path: Path) -> dict[str, int] | None:
    try:
        value = path.lstat()
    except FileNotFoundError:
        return None
    if stat.S_ISLNK(value.st_mode):
        raise ValueError(f"Private exclusion rejects a symlink: {path}")
    return {name: getattr(value, name) for name in
            ("st_dev", "st_ino", "st_mode", "st_nlink", "st_size", "st_mtime_ns", "st_ctime_ns")}


def _members(roots: Sequence[str]) -> dict[str, dict[str, int] | None]:
    result: dict[str, dict[str, int] | None] = {}
    def visit(path: Path) -> None:
        row = _metadata(path)
        result[str(path)] = row
        if row is None:
            return
        if stat.S_ISDIR(row["st_mode"]):
            with os.scandir(path) as entries:
                children = sorted(entry.name for entry in entries)
            for name in children:
                visit(path / name)
        elif not stat.S_ISREG(row["st_mode"]) or row["st_nlink"] != 1:
            raise ValueError(f"Private exclusion requires single-link regular files: {path}")
    for root in roots:
        visit(Path(root))
    return result


def _ancestors(paths: Sequence[str]) -> dict[str, dict[str, int] | None]:
    result = {}
    for name in paths:
        for path in Path(name).parents:
            row = _metadata(path)
            if row is not None and not stat.S_ISDIR(row["st_mode"]):
                raise ValueError("Private exclusion requires ordinary directory ancestors.")
            result[str(path)] = None if row is None else {key: row[key] for key in ("st_dev", "st_ino", "st_mode")}
    return result


def _tool(path: Path) -> dict[str, Any]:
    actual = path.resolve(strict=True)
    before = _metadata(actual)
    if before is None or not stat.S_ISREG(before["st_mode"]):
        raise ValueError("Private exclusion capability/source is not an actual regular file.")
    hashed = hashlib.sha256(actual.read_bytes()).hexdigest()
    if _metadata(actual) != before:
        raise ValueError("Private exclusion capability changed during hashing.")
    return {"path": str(actual), "sha256": hashed, "metadata": before}


def _identity() -> dict[str, Any]:
    if sys.platform != "darwin":
        raise ValueError("Private process exclusion requires the actual Mac capability.")
    uname = os.uname()
    return {"sandbox": _tool(SANDBOX), "env": _tool(ENV), "system": _tool(SYSTEM),
            "interpreter": _tool(Path(sys.executable)),
            "os": {"release": uname.release, "version": uname.version, "machine": uname.machine},
            "sources": [_tool(Path(__file__)), _tool(Path(__file__).with_name("public_input_guard.py")),
                        _tool(Path(__file__).with_name("evidence_runtime.py"))]}


@dataclass(frozen=True)
class ExclusionSnapshot:
    payload_json: str

    def to_dict(self) -> dict[str, Any]:
        return dict(json.loads(self.payload_json))


def prepare_private_exclusion(repo_root: Path, environment: Mapping[str, str], *, stage_root: Path | None = None,
                              audit_directory: Path | None = None, evidence_paths: Sequence[Path] = ()) -> ExclusionSnapshot:
    """Freeze actual membership/stat facts, without reading protected bytes."""
    parameters = {"repo_root": str(repo_root.absolute()), "reference_data": environment.get("SCIPLOT_REFERENCE_DATA"),
                  "stage_root": str(stage_root.absolute()) if stage_root is not None else None,
                  "audit_directory": str(audit_directory.absolute()) if audit_directory is not None else None,
                  "evidence_paths": sorted(str(path.absolute()) for path in evidence_paths)}
    roots = forbidden_roots(repo_root.absolute(), dict(environment))
    if stage_root is not None:
        roots.extend(forbidden_roots(stage_root.absolute(), {}))
    names = sorted({str(path.absolute()) for path in roots})
    writes = sorted({*(str(path.absolute()) for path in evidence_paths),
                     *([str(audit_directory.absolute())] if audit_directory is not None else [])})
    ancestors = _ancestors([*names, *writes])
    evidence_anchors = {}
    for name in writes:
        row = _metadata(Path(name))
        if row is not None and stat.S_ISDIR(row["st_mode"]):
            evidence_anchors[name] = {key: row[key] for key in ("st_dev", "st_ino", "st_mode")}
    members = _members(names)
    profile = "(version 1)\n(allow default)\n"
    profile += "(deny file* " + " ".join("(subpath " + json.dumps(name) + ")" for name in names) + ")\n"
    if writes:
        profile += "(deny file-write* " + " ".join("(subpath " + json.dumps(name) + ")" for name in writes) + ")\n"
    profile += "(deny file-write* " + " ".join("(literal " + json.dumps(name) + ")" for name in sorted(ancestors)) + ")\n"
    payload = {"version": 1, "parameters": parameters, "roots": names, "members": members,
               "ancestors": ancestors, "write_protected_paths": writes, "evidence_anchors": evidence_anchors,
               "profile": profile, "identity": _identity()}
    if _members(names) != members or _ancestors([*names, *writes]) != ancestors:
        raise ValueError("Private exclusion namespace changed during preparation.")
    return ExclusionSnapshot(json.dumps(payload, sort_keys=True, separators=(",", ":"), allow_nan=False))


def validate_private_exclusion(snapshot: ExclusionSnapshot | Mapping[str, Any]) -> None:
    """Recompute a serialized snapshot; a caller must bind its trusted parameters."""
    value = snapshot.to_dict() if isinstance(snapshot, ExclusionSnapshot) else dict(snapshot)
    if set(value) != {"version", "parameters", "roots", "members", "ancestors", "write_protected_paths", "evidence_anchors", "profile", "identity"}:
        raise ValueError("Unknown private exclusion snapshot shape.")
    parameters = value.get("parameters")
    if not isinstance(parameters, dict) or set(parameters) != {"repo_root", "reference_data", "stage_root", "audit_directory", "evidence_paths"}:
        raise ValueError("Unknown private exclusion parameters.")
    try:
        reference = parameters["reference_data"]
        environment = {} if reference is None else {"SCIPLOT_REFERENCE_DATA": reference}
        expected = prepare_private_exclusion(Path(parameters["repo_root"]), environment,
            stage_root=Path(parameters["stage_root"]) if parameters["stage_root"] is not None else None,
            audit_directory=Path(parameters["audit_directory"]) if parameters["audit_directory"] is not None else None,
            evidence_paths=tuple(Path(path) for path in parameters["evidence_paths"]))
    except (OSError, TypeError, KeyError) as error:
        raise ValueError("Invalid or unavailable private exclusion facts.") from error
    if value != expected.to_dict():
        raise ValueError("Private exclusion membership, resource, ancestor or capability drift.")


def _inode_set(rows: Mapping[str, Any]) -> set[tuple[int, int]]:
    return {(row["st_dev"], row["st_ino"]) for row in rows.values() if row is not None}


def _evidence_inodes(paths: Sequence[str]) -> set[tuple[int, int]]:
    result: set[tuple[int, int]] = set()
    for name in paths:
        path = Path(name)
        row = _metadata(path)
        if row is None:
            continue
        result.add((row["st_dev"], row["st_ino"]))
        if not stat.S_ISDIR(row["st_mode"]) and (not stat.S_ISREG(row["st_mode"]) or row["st_nlink"] != 1):
            raise ValueError("Private exclusion requires ordinary single-link evidence.")
        if stat.S_ISDIR(row["st_mode"]):
            for parent, directories, files in os.walk(path, followlinks=False):
                for part in [*directories, *files]:
                    current = _metadata(Path(parent) / part)
                    if current is not None:
                        if not stat.S_ISDIR(current["st_mode"]) and (not stat.S_ISREG(current["st_mode"]) or current["st_nlink"] != 1):
                            raise ValueError("Private exclusion requires ordinary single-link evidence.")
                        result.add((current["st_dev"], current["st_ino"]))
    return result


@dataclass
class ExcludedInvocation:
    argv: tuple[str, ...]
    environment: dict[str, str]
    stdio: tuple[int, int, int]
    proof: dict[str, Any]
    _duplicates: list[int] = field(repr=False)

    def __enter__(self) -> ExcludedInvocation:
        return self

    def __exit__(self, *_arguments: object) -> None:
        for descriptor in self._duplicates:
            os.close(descriptor)
        self._duplicates.clear()


def _stdio(value: Any, index: int, forbidden: set[tuple[int, int]], duplicates: list[int]) -> tuple[int, dict[str, Any], dict[str, Any]]:
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


def _prefix(payload: Mapping[str, Any], loader: Mapping[str, str], dropped: Sequence[str]) -> tuple[str, ...]:
    return (payload["identity"]["sandbox"]["path"], "-p", payload["profile"], payload["identity"]["env"]["path"],
            *(part for key in dropped for part in ("-u", key)), "--", *(f"{key}={loader[key]}" for key in sorted(loader)))


def actual_launch_facts(snapshot: ExclusionSnapshot, argv: tuple[str, ...], environment: Mapping[str, str], *,
                        stdio: tuple[int, int, int], cwd: Path | None = None, close_fds: bool = True,
                        pass_fds: Sequence[int] = (), preexec_fn: Any = None, shell: bool = False,
                        executable: str | None = None, drop_environment: Sequence[str] = ()) -> dict[str, Any]:
    """Call independently on the immutable final original_init arguments."""
    if type(argv) is not tuple or shell is not False or executable is not None or close_fds is not True or pass_fds or preexec_fn is not None:
        raise ValueError("Unsafe actual private exclusion launch flags.")
    loader, dropped = runtime_loader_environment(environment), sorted(set(drop_environment))
    if (set(loader) & set(dropped) or any(key.startswith(("DYLD_", "LD_")) and key not in loader for key in environment)):
        raise ValueError("Unreviewed loader projection.")
    prefix = _prefix(snapshot.to_dict(), loader, dropped)
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
    return {"argv_sha256": _digest(list(argv)), "prefix_sha256": _digest(list(argv[:len(prefix)])),
            "suffix_sha256": _digest(list(argv[len(prefix):])), "launch_environment_sha256": _digest(dict(environment)),
            "target_environment_sha256": _digest(target), "loader_environment": loader, "stdio": rows,
            "cwd": str(Path.cwd() if cwd is None else cwd.absolute()),
            "flags": {"close_fds": close_fds, "pass_fds": [], "preexec_fn": None, "shell": shell, "executable": executable}}


def _target(command: str, cwd: Path, environment: Mapping[str, str]) -> Path:
    if os.sep in command:
        return (cwd / command).resolve(strict=True)
    search = os.pathsep.join(str((cwd / part).absolute()) for part in environment.get("PATH", os.defpath).split(os.pathsep))
    found = shutil.which(command, path=search)
    if found is None:
        raise ValueError("Private exclusion cannot resolve the original executable.")
    return Path(found).resolve(strict=True)


def wrap_private_exclusion(snapshot: ExclusionSnapshot, argv: Sequence[str], *, environment: Mapping[str, str],
                           cwd: Path | None = None, stdin: Any = None, stdout: Any = None, stderr: Any = None,
                           close_fds: bool = True, pass_fds: Sequence[int] = (), preexec_fn: Any = None,
                           shell: bool = False, executable: str | None = None,
                           drop_environment: Sequence[str] = ()) -> ExcludedInvocation:
    """Hold duplicated endpoints through Popen; no sensor/lifecycle waiver here."""
    if (shell is not False or executable is not None or close_fds is not True or pass_fds or preexec_fn is not None
            or isinstance(argv, (str, bytes)) or not argv
            or any(not isinstance(arg, str) or "\0" in arg for arg in argv) or not argv[0] or "=" in argv[0]):
        raise ValueError("Unsupported or unsafe private exclusion invocation.")
    if any(not isinstance(key, str) or not key or "=" in key or "\0" in key for key in drop_environment):
        raise ValueError("Invalid post-boundary environment projection.")
    validate_private_exclusion(snapshot)
    payload = snapshot.to_dict()
    current = Path.cwd() if cwd is None else cwd.absolute()
    _ancestors([str(current / "scope-child")])
    target = _target(argv[0], current, environment)
    if any(current.is_relative_to(Path(root)) or target.is_relative_to(Path(root)) for root in payload["roots"]):
        raise ValueError("Private exclusion refuses a protected cwd or executable before reading it.")
    original_target = _tool(target)
    forbidden = _inode_set(payload["members"]) | _evidence_inodes(payload["write_protected_paths"])
    duplicates: list[int] = []
    try:
        stdio = [_stdio(value, index, forbidden, duplicates) for index, value in enumerate((stdin, stdout, stderr))]
        dropped = sorted(set(drop_environment))
        actual = (*_prefix(payload, runtime_loader_environment(environment), dropped), *argv)
        original = {"argv_sha256": _digest(list(argv)), "environment_sha256": _digest(dict(environment)),
                    "cwd": str(current), "executable": original_target, "stdio": [row[1] for row in stdio]}
        endpoints = (stdio[0][0], stdio[1][0], stdio[2][0])
        effective = actual_launch_facts(snapshot, actual, environment, stdio=endpoints, cwd=current, drop_environment=dropped)
        proof = {"kind": KIND, "version": 1, "snapshot": payload, "snapshot_sha256": _digest(payload),
                 "profile_sha256": hashlib.sha256(payload["profile"].encode()).hexdigest(),
                 "original": original, "actual": effective, "drop_environment": dropped,
                 "evidence_inodes": sorted([list(pair) for pair in forbidden])}
        return ExcludedInvocation(actual, dict(environment), endpoints, proof, duplicates)
    except BaseException:
        for descriptor in duplicates:
            os.close(descriptor)
        raise


def validate_excluded_proof(proof: Mapping[str, Any], *, expected_snapshot: ExclusionSnapshot | Mapping[str, Any],
                            original_argv_sha256: str, original_environment_sha256: str,
                            original_executable_sha256: str, original_cwd: str,
                            original_stdio: Sequence[Mapping[str, Any]], actual_launch: Mapping[str, Any],
                            drop_environment: Sequence[str] = ()) -> None:
    """Validate closed facts against trusted parent launch-frame bindings."""
    validate_private_exclusion(expected_snapshot)
    value = dict(proof)
    expected_keys = {"kind", "version", "snapshot", "snapshot_sha256", "profile_sha256", "original", "actual", "drop_environment", "evidence_inodes"}
    payload = expected_snapshot.to_dict() if isinstance(expected_snapshot, ExclusionSnapshot) else dict(expected_snapshot)
    if (set(value) != expected_keys or value.get("kind") != KIND or value.get("version") != 1
            or value.get("snapshot") != payload or value.get("snapshot_sha256") != _digest(payload)
            or value.get("profile_sha256") != hashlib.sha256(payload["profile"].encode()).hexdigest()
            or value.get("drop_environment") != sorted(set(drop_environment))):
        raise ValueError("Unknown, stale or mismatched private exclusion proof.")
    original, actual = value["original"], value["actual"]
    if (not isinstance(original, dict) or set(original) != {"argv_sha256", "environment_sha256", "cwd", "executable", "stdio"}
            or not isinstance(actual, dict) or set(actual) != {"argv_sha256", "prefix_sha256", "suffix_sha256", "launch_environment_sha256",
                "target_environment_sha256", "loader_environment", "stdio", "cwd", "flags"} or actual != dict(actual_launch)
            or original["argv_sha256"] != original_argv_sha256 or original["environment_sha256"] != original_environment_sha256
            or actual["launch_environment_sha256"] != original_environment_sha256 or actual["suffix_sha256"] != original_argv_sha256
            or actual["cwd"] != original_cwd or original["stdio"] != list(original_stdio)
            or actual["flags"] != {"close_fds": True, "pass_fds": [], "preexec_fn": None, "shell": False, "executable": None}
            or original["cwd"] != original_cwd or not isinstance(original["executable"], dict)
            or set(original["executable"]) != {"path", "sha256", "metadata"}
            or original["executable"]["sha256"] != original_executable_sha256):
        raise ValueError("Private exclusion original/actual launch bindings differ.")
    loader = actual["loader_environment"]
    if (not isinstance(loader, dict) or set(loader) - {"DYLD_FRAMEWORK_PATH"}
            or any(not isinstance(key, str) or not isinstance(item, str) for key, item in loader.items())
            or set(loader) & set(drop_environment)
            or actual["prefix_sha256"] != _digest(list(_prefix(payload, loader, sorted(set(drop_environment)))))):
        raise ValueError("Actual launch does not carry the exact exclusion prefix.")
    rows, old = actual["stdio"], original["stdio"]
    if not isinstance(rows, list) or not isinstance(old, list) or len(rows) != 3 or len(old) != 3:
        raise ValueError("Incomplete private exclusion stdio binding.")
    inode_rows = value["evidence_inodes"]
    if (not isinstance(inode_rows, list) or any(not isinstance(pair, list) or len(pair) != 2
            or any(type(number) is not int or number < 0 for number in pair) for pair in inode_rows)
            or inode_rows != sorted([list(pair) for pair in {tuple(pair) for pair in inode_rows}])):
        raise ValueError("Malformed private exclusion evidence inode facts.")
    excluded = _inode_set(payload["members"]) | {tuple(pair) for pair in inode_rows} | _evidence_inodes(payload["write_protected_paths"])
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
